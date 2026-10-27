"""Database layer. SQLite locally, Postgres (Supabase) in production.

Every write goes through a function here, and every write adds an audit row.
Decisions are append-only: the latest decision for a submission is its status,
and earlier ones stay as history. Nothing is edited silently.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import sqlalchemy as sa
import streamlit as st

import engine as E

md = sa.MetaData()

users = sa.Table(
    "users", md,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("username", sa.String(64), nullable=False, unique=True),
    sa.Column("password_hash", sa.String(200), nullable=False),
    sa.Column("role", sa.String(10), nullable=False),  # admin | centre
    sa.Column("centre", sa.String(8)),
    sa.Column("active", sa.Boolean, nullable=False, default=True),
    sa.Column("must_change", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.String(32), nullable=False),
)

submissions = sa.Table(
    "submissions", md,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("centre", sa.String(8), nullable=False, index=True),
    sa.Column("review_date", sa.String(10), nullable=False, index=True),
    sa.Column("review_url", sa.Text, nullable=False),
    sa.Column("url_norm", sa.Text, nullable=False, unique=True),  # duplicate links blocked by the database
    sa.Column("reviewer", sa.String(120)),
    sa.Column("staff", sa.String(120), nullable=False),
    sa.Column("notes", sa.Text),
    sa.Column("evidence", sa.LargeBinary),
    sa.Column("evidence_type", sa.String(40)),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("created_by", sa.Integer, nullable=False),
)

decisions = sa.Table(
    "decisions", md,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("submission_id", sa.String(36), nullable=False, index=True),
    sa.Column("status", sa.String(16), nullable=False),  # approved | rejected | flagged | invalidated | pending
    sa.Column("reason", sa.Text),
    sa.Column("note", sa.Text),
    sa.Column("decided_by", sa.Integer, nullable=False),
    sa.Column("decided_at", sa.String(32), nullable=False),
    sa.Column("rule", sa.String(8)),
)

holidays = sa.Table(
    "holidays", md,
    sa.Column("date", sa.String(10), primary_key=True),
    sa.Column("label", sa.String(120), nullable=False),
)

settings = sa.Table(
    "settings", md,
    sa.Column("key", sa.String(40), primary_key=True),
    sa.Column("value", sa.Text),
)

rewards = sa.Table(
    "rewards", md,
    sa.Column("month", sa.String(7), primary_key=True),
    sa.Column("centre", sa.String(8), primary_key=True),
    sa.Column("position", sa.Integer),
    sa.Column("status", sa.String(16), nullable=False),  # pending | announced | fulfilled
    sa.Column("note", sa.Text),
    sa.Column("updated_at", sa.String(32), nullable=False),
)

audit = sa.Table(
    "audit_log", md,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("at", sa.String(32), nullable=False),
    sa.Column("actor", sa.String(64), nullable=False),
    sa.Column("action", sa.String(40), nullable=False),
    sa.Column("detail", sa.Text),
)


def now() -> str:
    return datetime.now(tz=E.IST).isoformat(timespec="seconds")


@st.cache_resource
def get_engine() -> sa.Engine:
    try:
        url = st.secrets.get("DATABASE_URL", "")
    except Exception:  # no secrets.toml locally
        url = ""
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///jg_reviews.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    eng = sa.create_engine(url, pool_pre_ping=True)
    md.create_all(eng)
    return eng


def _audit(conn, actor: str, action: str, detail: str) -> None:
    conn.execute(audit.insert().values(at=now(), actor=actor, action=action, detail=detail))


def norm_url(u: str) -> str:
    u = (u or "").strip().lower()
    for p in ("https://", "http://"):
        if u.startswith(p):
            u = u[len(p):]
    return u.rstrip("/")


# ---------- reads ----------

def load_all() -> dict:
    """Everything the scoring engine needs, in one round trip per table."""
    eng = get_engine()
    with eng.connect() as c:
        subs = [dict(r._mapping) for r in c.execute(sa.select(
            submissions.c.id, submissions.c.centre, submissions.c.review_date, submissions.c.review_url,
            submissions.c.reviewer, submissions.c.staff, submissions.c.notes, submissions.c.created_at,
            submissions.c.created_by, (submissions.c.evidence.isnot(None)).label("has_evidence")))]
        decs = [dict(r._mapping) for r in c.execute(sa.select(decisions).order_by(decisions.c.id))]
        hols = {r.date: r.label for r in c.execute(sa.select(holidays))}
        sets = {r.key: r.value for r in c.execute(sa.select(settings))}
        rews = [dict(r._mapping) for r in c.execute(sa.select(rewards))]
    latest: dict[str, dict] = {}
    history: dict[str, list] = {}
    for d in decs:
        latest[d["submission_id"]] = d
        history.setdefault(d["submission_id"], []).append(d)
    statuses = {s["id"]: latest[s["id"]]["status"] if s["id"] in latest else "pending" for s in subs}
    return {"subs": subs, "latest": latest, "history": history, "statuses": statuses,
            "holidays": hols, "settings": sets, "rewards": rews}


def evidence(sub_id: str):
    with get_engine().connect() as c:
        r = c.execute(sa.select(submissions.c.evidence, submissions.c.evidence_type)
                      .where(submissions.c.id == sub_id)).first()
    return (r.evidence, r.evidence_type) if r else (None, None)


def list_users() -> list[dict]:
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(
            sa.select(users.c.id, users.c.username, users.c.role, users.c.centre, users.c.active,
                      users.c.created_at).order_by(users.c.role, users.c.centre))]


def get_user(username: str):
    with get_engine().connect() as c:
        r = c.execute(sa.select(users).where(users.c.username == username.strip().lower())).first()
    return dict(r._mapping) if r else None


def audit_rows(limit: int = 500) -> list[dict]:
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(sa.select(audit).order_by(audit.c.id.desc()).limit(limit))]


def count_admins() -> int:
    with get_engine().connect() as c:
        return c.execute(sa.select(sa.func.count()).select_from(users).where(users.c.role == "admin")).scalar_one()


# ---------- writes ----------

class DuplicateLink(Exception):
    pass


def _admin(user: dict) -> None:
    """Server-side guard: admin-only writes refuse anyone else, whatever the UI shows."""
    if not user or user.get("role") != "admin" or not user.get("active"):
        raise PermissionError("Admin only")


def add_submission(user: dict, review_date: str, url: str, reviewer: str, staff: str, notes: str,
                   ev_bytes: bytes | None, ev_type: str | None) -> str:
    if not user or user.get("role") != "centre" or not user.get("centre"):
        raise PermissionError("Only centre accounts log reviews")
    sid = str(uuid.uuid4())
    try:
        with get_engine().begin() as c:
            c.execute(submissions.insert().values(
                id=sid, centre=user["centre"], review_date=review_date, review_url=url.strip(),
                url_norm=norm_url(url), reviewer=reviewer or None, staff=staff, notes=notes or None,
                evidence=ev_bytes, evidence_type=ev_type, created_at=now(), created_by=user["id"]))
            _audit(c, user["username"], "submit", f"{E.CENTRE_NAME[user['centre']]} review for {review_date} ({sid[:8]})")
    except sa.exc.IntegrityError as e:
        raise DuplicateLink() from e
    return sid


def decide(user: dict, sub_id: str, status: str, reason: str = "", note: str = "") -> None:
    _admin(user)
    with get_engine().begin() as c:
        c.execute(decisions.insert().values(submission_id=sub_id, status=status, reason=reason or None,
                                            note=note or None, decided_by=user["id"], decided_at=now(),
                                            rule=E.RULE_VERSION))
        _audit(c, user["username"], status, f"submission {sub_id[:8]}" + (f": {reason}" if reason else "")
               + (f" (note: {note})" if note else ""))


def set_setting(user: dict, key: str, value: str) -> None:
    _admin(user)
    with get_engine().begin() as c:
        c.execute(settings.delete().where(settings.c.key == key))
        c.execute(settings.insert().values(key=key, value=value))
        _audit(c, user["username"], "setting", f"{key} = {value}")


def add_holiday(user: dict, date: str, label: str) -> None:
    _admin(user)
    with get_engine().begin() as c:
        c.execute(holidays.delete().where(holidays.c.date == date))
        c.execute(holidays.insert().values(date=date, label=label))
        _audit(c, user["username"], "holiday_add", f"{date} {label}")


def remove_holiday(user: dict, date: str) -> None:
    _admin(user)
    with get_engine().begin() as c:
        c.execute(holidays.delete().where(holidays.c.date == date))
        _audit(c, user["username"], "holiday_remove", date)


def set_reward(user: dict, month: str, centre: str, position: int, status: str, note: str) -> None:
    _admin(user)
    with get_engine().begin() as c:
        c.execute(rewards.delete().where((rewards.c.month == month) & (rewards.c.centre == centre)))
        c.execute(rewards.insert().values(month=month, centre=centre, position=position, status=status,
                                          note=note or None, updated_at=now()))
        _audit(c, user["username"], "reward", f"{month} {E.CENTRE_NAME[centre]} #{position} -> {status}")


def create_user(actor: str, username: str, password_hash: str, role: str, centre: str | None,
                must_change: bool = True) -> None:
    with get_engine().begin() as c:
        c.execute(users.insert().values(username=username.strip().lower(), password_hash=password_hash, role=role,
                                        centre=centre, active=True, must_change=must_change, created_at=now()))
        _audit(c, actor, "user_create", f"{username} ({role}{' ' + centre if centre else ''})")


def update_user(actor: str, user_id: int, **values) -> None:
    with get_engine().begin() as c:
        c.execute(users.update().where(users.c.id == user_id).values(**values))
        shown = {k: v for k, v in values.items() if k != "password_hash"}
        if "password_hash" in values:
            shown["password"] = "reset"
        _audit(c, actor, "user_update", f"user {user_id}: {shown}")
