"""JG Reviews League scoring engine (rule version v1).

Pure functions only: no database, no Streamlit. Every page and every report
calls these, so the rules live in exactly one place.

Dates are 'YYYY-MM-DD' strings in IST calendar terms.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

RULE_VERSION = "v1"
THRESHOLD = 15
IST = ZoneInfo("Asia/Kolkata")

CENTRES = [
    ("BPL", "Bhopal"),
    ("JPR", "Jaipur"),
    ("DEL", "Delhi"),
    ("IDR", "Indore"),
    ("PRY", "Prayagraj"),
    ("JBP", "Jabalpur"),
    ("LKO", "Lucknow"),
]
CENTRE_NAME = dict(CENTRES)

# Submission statuses that never earn points
NON_SCORING = {"rejected", "invalidated"}
PENDING_LIKE = {"pending", "flagged"}


def today_ist(now: datetime | None = None) -> str:
    now = now or datetime.now(tz=IST)
    return now.astimezone(IST).date().isoformat()


def d(s: str) -> date:
    return date.fromisoformat(s)


def add_days(s: str, n: int) -> str:
    return (d(s) + timedelta(days=n)).isoformat()


def weekday(s: str) -> int:
    """0 = Monday .. 6 = Sunday."""
    return d(s).weekday()


def is_working_day(s: str, holidays: set[str] | None = None) -> bool:
    return weekday(s) < 5 and s not in (holidays or set())


def month_of(s: str) -> str:
    return s[:7]


def month_end(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


@dataclass
class LedgerRow:
    date: str
    working: bool
    status: str  # approved | pending | rejected | missed | open | weekend | holiday
    points: int = 0
    base: int = 0
    mult: int = 0
    streak: int = 0
    sub_id: str | None = None
    extra: int = 0
    note: str = ""
    rule: str = ""


@dataclass
class CentreScore:
    centre: str
    ledger: list[LedgerRow] = field(default_factory=list)
    current_streak: int = 0


def _group(subs: list[dict], statuses: dict[str, str], centre: str) -> dict[str, dict]:
    days: dict[str, dict] = {}
    for s in subs:
        if s["centre"] != centre:
            continue
        st = statuses.get(s["id"], "pending")
        day = days.setdefault(s["review_date"], {"approved": [], "pending": [], "rejected": [], "all": []})
        day["all"].append(s)
        if st == "approved":
            day["approved"].append(s)
        elif st in PENDING_LIKE:
            day["pending"].append(s)
        else:
            day["rejected"].append(s)
    for day in days.values():
        day["approved"].sort(key=lambda x: x.get("created_at") or "")
    return days


def score_centre(centre: str, subs: list[dict], statuses: dict[str, str], holidays: set[str],
                 start: str, today: str) -> CentreScore:
    """Walk every day from `start` to `today` and build the scoring ledger.

    Rules:
      1. An approved submission on a working day earns 1 base point.
      2. Consecutive working days extend the streak; weekends and holidays are skipped.
      3. Monday earns x2 when the previous working day also qualified.
      4. A working day with no approved submission resets the streak.
      5. Only approved submissions count; pending earns nothing.
      7. At most one score per centre per working day.
    """
    days = _group(subs, statuses, centre)
    out = CentreScore(centre=centre)
    streak, prev_ok = 0, False
    cur = start
    while cur <= today:
        info = days.get(cur)
        extra = len(info["all"]) if info else 0
        if not is_working_day(cur, holidays):
            out.ledger.append(LedgerRow(cur, False, "holiday" if cur in holidays else "weekend", extra=extra))
        elif info and info["approved"]:
            streak = streak + 1 if prev_ok else 1
            mult = 2 if (weekday(cur) == 0 and prev_ok) else 1
            note = ("Monday bonus: previous working day qualified" if mult == 2
                    else "Streak starts" if streak == 1 else "Streak continues")
            out.ledger.append(LedgerRow(cur, True, "approved", points=mult, base=1, mult=mult, streak=streak,
                                        sub_id=info["approved"][0]["id"], extra=extra - 1, note=note,
                                        rule=RULE_VERSION))
            prev_ok = True
        elif cur == today:
            st = "pending" if info and info["pending"] else "rejected" if info and info["rejected"] else "open"
            out.ledger.append(LedgerRow(cur, True, st, extra=extra, note="Day still open"))
        else:
            st = "pending" if info and info["pending"] else "rejected" if info and info["rejected"] else "missed"
            out.ledger.append(LedgerRow(cur, True, st, extra=extra,
                                        note="Waiting for approval" if st == "pending" else "No approved review: streak resets"))
            streak, prev_ok = 0, False
        cur = add_days(cur, 1)
    out.current_streak = streak if prev_ok else 0
    return out


def month_summary(score: CentreScore, ym: str, today: str) -> dict:
    s = {"points": 0, "approved": 0, "missed": 0, "pending_days": 0, "rejected_days": 0,
         "longest": 0, "working_days": 0}
    for r in score.ledger:
        if month_of(r.date) != ym or not r.working:
            continue
        s["working_days"] += 1
        if r.status == "approved":
            s["points"] += r.points
            s["approved"] += 1
            s["longest"] = max(s["longest"], r.streak)
        elif r.date < today:
            s["missed"] += 1
            if r.status == "pending":
                s["pending_days"] += 1
            if r.status == "rejected":
                s["rejected_days"] += 1
    s["current_streak"] = score.current_streak
    s["eligible"] = s["points"] >= THRESHOLD
    return s


def _key(r: dict) -> tuple:
    return (r["points"], r["approved"], r["current_streak"])


def rank(rows: list[dict]) -> list[dict]:
    """Competition ranking: points, then approved days, then current streak. Ties stay ties."""
    out = [dict(r) for r in rows]
    for r in out:
        r["rank"] = 1 + sum(1 for o in out if _key(o) > _key(r))
        r["tied"] = any(o is not r and _key(o) == _key(r) for o in out)
    out.sort(key=lambda r: (r["rank"], r["centre"]))
    for r in out:
        above = [o for o in out if o["rank"] < r["rank"]]
        nxt = above[-1] if above else None
        r["gap"] = (nxt["points"] - r["points"]) if nxt else 0
        r["above"] = nxt["centre"] if nxt else None
    return out


def rewards(ranked: list[dict]) -> list[dict]:
    """Top three positions among centres with at least THRESHOLD points."""
    eligible = [r for r in ranked if r["points"] >= THRESHOLD]
    res = []
    for r in eligible:
        pos = 1 + sum(1 for o in eligible if _key(o) > _key(r))
        if pos <= 3:
            res.append({"centre": r["centre"], "position": pos, "points": r["points"], "approved": r["approved"],
                        "tied": any(o is not r and _key(o) == _key(r) for o in eligible)})
    return res


def league(month: str, today: str, start: str, subs: list[dict], statuses: dict[str, str],
           holidays: set[str], centres: list[tuple[str, str]] = CENTRES) -> dict:
    end = min(today, month_end(month))
    rows = []
    for code, name in centres:
        sc = score_centre(code, subs, statuses, holidays, start, max(end, start) if end >= start else start)
        rows.append({"centre": code, "name": name, "score": sc, **month_summary(sc, month, today)})
    ranked = rank(rows)
    return {"rows": ranked, "winners": rewards(ranked)}
