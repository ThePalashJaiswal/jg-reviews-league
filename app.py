"""JG Reviews League — Streamlit app.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import auth
import db
import engine as E

st.set_page_config(page_title="JG Reviews League", page_icon="🏆", layout="wide")

st.markdown("""
<style>
:root { --jg-gold: #B07D1F; --jg-navy: #13223F; }
.jg-brand { font-family: Georgia, 'Times New Roman', serif; font-size: 1.6rem; font-weight: 700; color: var(--jg-gold); }
.jg-pill { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: .8rem; font-weight: 600; }
.jg-approved { background: #E1F2E8; color: #1F7A4D; } .jg-pending, .jg-flagged { background: #FBF0D9; color: #9A6200; }
.jg-rejected, .jg-missed, .jg-invalidated { background: #F8E3E1; color: #B23A3A; }
.jg-weekend, .jg-holiday, .jg-off { background: #ECEEF3; color: #6F7891; } .jg-open { border: 1px dashed #9AA3B5; color: #6F7891; }
.jg-cal { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.jg-cal div { border-radius: 6px; padding: 4px 6px; min-height: 48px; font-size: .8rem; }
.jg-cal .h { min-height: 0; text-align: center; font-weight: 600; color: #6F7891; text-transform: uppercase; font-size: .7rem; }
.jg-cal .today { outline: 2px solid var(--jg-gold); outline-offset: -2px; }
.jg-cal small { display: block; font-weight: 600; }
.jg-demo { background: #FBF0D9; color: #9A6200; padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

LABEL = {"approved": "Approved", "pending": "Pending verification", "flagged": "Flagged", "rejected": "Rejected",
         "invalidated": "Invalidated", "missed": "Missed", "holiday": "Holiday", "weekend": "Non-working day",
         "open": "Not yet submitted", "off": "Non-working day"}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def pill(status: str, text: str | None = None) -> str:
    return f"<span class='jg-pill jg-{status}'>{text or LABEL.get(status, status)}</span>"


def nice(s: str) -> str:
    return f"{DOW[E.weekday(s)]} {int(s[8:])} {MONTHS[int(s[5:7]) - 1]}"


def nice_month(ym: str) -> str:
    return f"{MONTHS[int(ym[5:]) - 1]} {ym[:4]}"


# ---------------- auth gate ----------------
auth.bootstrap_admin()
user = auth.current_user()
if not user:
    auth.login_screen()
    st.stop()
if user["must_change"]:
    st.markdown("<div class='jg-brand'>JG Reviews League</div>", unsafe_allow_html=True)
    auth.change_password_form(user, forced=True)
    st.stop()

IS_ADMIN = user["role"] == "admin"
TODAY = E.today_ist()
DATA = db.load_all()
SET = DATA["settings"]
START = SET.get("start_date") or TODAY
HOL = set(DATA["holidays"])
SUBS, STATUS = DATA["subs"], DATA["statuses"]


def months_since_start() -> list[str]:
    out, m = [], START[:7]
    while m <= TODAY[:7]:
        out.append(m)
        y, mo = int(m[:4]), int(m[5:]) + 1
        m = f"{y + (mo > 12)}-{(mo - 1) % 12 + 1:02d}"
    return out or [TODAY[:7]]


_league_cache: dict[str, dict] = {}


def league(ym: str) -> dict:
    if ym not in _league_cache:
        _league_cache[ym] = E.league(ym, TODAY, START, SUBS, STATUS, HOL)
    return _league_cache[ym]


def row_for(ym: str, code: str) -> dict:
    return next(r for r in league(ym)["rows"] if r["centre"] == code)


def today_score(code: str) -> tuple[E.CentreScore, E.LedgerRow | None]:
    sc = E.score_centre(code, SUBS, STATUS, HOL, START, TODAY)
    last = sc.ledger[-1] if sc.ledger and sc.ledger[-1].date == TODAY else None
    return sc, last


# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown("<div class='jg-brand'>JG Reviews League</div>", unsafe_allow_html=True)
    who = "Admin" if IS_ADMIN else f"{E.CENTRE_NAME[user['centre']]} centre"
    st.caption(f"Signed in as **{user['username']}** · {who}")
    if SET.get("demo") == "1":
        st.markdown("<div class='jg-demo'>Demo database: sample records, not real Google reviews.</div>", unsafe_allow_html=True)
    months = months_since_start()
    MONTH = st.selectbox("Month", months, index=len(months) - 1, format_func=nice_month)
    if IS_ADMIN:
        pages = ["Overview", "Verification queue", "All centres", "Leaderboard", "Analytics", "Monthly rewards",
                 "Working-day calendar", "User management", "Reports & exports", "Audit log", "Settings", "My password"]
        pending_n = sum(1 for s in SUBS if STATUS[s["id"]] in ("pending", "flagged"))
        if pending_n:
            st.caption(f"🔔 {pending_n} submission{'s' if pending_n > 1 else ''} awaiting verification")
    else:
        pages = ["Dashboard", "Submit review", "Submission history", "Streaks & points", "Leaderboard", "My password"]
    PAGE = st.radio("Go to", pages, label_visibility="collapsed")
    if st.button("Sign out", width="stretch"):
        st.session_state.pop("user", None)
        st.rerun()

if not SET.get("start_date") and IS_ADMIN:
    st.warning("League start date isn't set, so scoring starts from today. Set it under Settings.")


# ---------------- shared pieces ----------------
def leaderboard_table(ym: str, highlight: str | None = None) -> None:
    lg = league(ym)
    win = {w["centre"]: w["position"] for w in lg["winners"]}
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    rows = []
    for r in lg["rows"]:
        rows.append({
            "Rank": f"{medal.get(r['rank'], '')} {r['rank']}{' (tie)' if r['tied'] else ''}".strip(),
            "Centre": ("▶ " if r["centre"] == highlight else "") + r["name"],
            "Points": r["points"], "Approved days": r["approved"], "Current streak": r["current_streak"],
            "Longest streak": r["longest"],
            "Reward": f"Reward #{win[r['centre']]}" if r["centre"] in win else ("Eligible" if r["eligible"] else f"{E.THRESHOLD - r['points']} to go"),
            "Gap to next": "—" if r["rank"] == 1 else r["gap"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Ranked by points, then approved days, then current streak. Ties are shown, not broken. "
               "Reward needs 15 points; the top three eligible centres win.")


def calendar_html(code: str, ym: str) -> str:
    sc = E.score_centre(code, SUBS, STATUS, HOL, START, TODAY)
    m = {r.date: r for r in sc.ledger}
    first = ym + "-01"
    cells = [f"<div class='h'>{d}</div>" for d in DOW] + ["<div></div>"] * E.weekday(first)
    cur = first
    while cur[:7] == ym:
        r = m.get(cur)
        if r:
            st_ = r.status
            lab = (f"+{r.points}" + (" ×2" if r.mult == 2 else "")) if st_ == "approved" else \
                {"holiday": "Holiday", "missed": "Missed", "pending": "Pending", "rejected": "Rejected", "open": "Today"}.get(st_, "")
        else:
            st_, lab = ("open", "") if cur > TODAY else ("off", "")
        cells.append(f"<div class='jg-{st_}{' today' if cur == TODAY else ''}' title='{nice(cur)}: {LABEL.get(st_, st_)}'>"
                     f"{int(cur[8:])}<small>{lab}</small></div>")
        cur = E.add_days(cur, 1)
    legend = " ".join(pill(s) for s in ["approved", "pending", "rejected", "missed", "holiday", "weekend"])
    return f"<div class='jg-cal'>{''.join(cells)}</div><p style='margin-top:8px'>{legend}</p>"


def ledger_df(code: str, ym: str) -> pd.DataFrame:
    rows = [r for r in row_for(ym, code)["score"].ledger if r.working and E.month_of(r.date) == ym]
    return pd.DataFrame([{
        "Date": nice(r.date), "Status": LABEL.get(r.status, r.status), "Base": r.base,
        "Multiplier": f"×{r.mult}" if r.mult else "—", "Points": r.points, "Streak": r.streak,
        "Extra reviews": r.extra, "Why": r.note, "Rule": r.rule,
    } for r in reversed(rows)])


def subs_df(rows: list[dict], with_centre: bool = False) -> pd.DataFrame:
    out = []
    for s in sorted(rows, key=lambda x: (x["review_date"], x["created_at"]), reverse=True):
        d = DATA["latest"].get(s["id"], {})
        rec = {"Review date": s["review_date"]}
        if with_centre:
            rec["Centre"] = E.CENTRE_NAME[s["centre"]]
        rec.update({"Status": LABEL[STATUS[s["id"]]], "Reason": d.get("reason") or "", "Logged by": s["staff"],
                    "Reviewer": s["reviewer"] or "", "Review link": s["review_url"], "Logged at": s["created_at"][:16]})
        out.append(rec)
    return pd.DataFrame(out)


def show_subs(rows, with_centre=False):
    if not rows:
        st.info("Nothing logged yet. Submissions appear here as soon as they're made.")
        return
    st.dataframe(subs_df(rows, with_centre), hide_index=True, width="stretch",
                 column_config={"Review link": st.column_config.LinkColumn("Review link", display_text="Open")})


# ---------------- centre pages ----------------
def page_dashboard(code: str) -> None:
    r = row_for(MONTH, code)
    sc, t = today_score(code)
    status = t.status if t and t.working else "off"
    st.caption(f"{date.fromisoformat(TODAY):%A · %d %b %Y}")
    st.title(f"{E.CENTRE_NAME[code]} centre")
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(pill(status, "Today: " + LABEL[status]), unsafe_allow_html=True)
        if status == "approved":
            st.write("Today's review is approved. Keep the streak alive.")
        elif status == "pending":
            st.write("Your submission is awaiting verification.")
        elif status == "off":
            st.write("Non-working day. Streaks are safe over weekends and holidays.")
        elif sc.current_streak:
            st.write("One more working day toward your next milestone. Log today's review to keep the streak alive.")
        else:
            st.write("Start a new streak today: log one genuine review.")
    with c2:
        nxt = next((m for m in (5, 10, 20, 40) if m > sc.current_streak), sc.current_streak + 10)
        st.metric("🔥 Working-day streak", sc.current_streak, help=f"Next milestone: {nxt}")

    st.subheader(nice_month(MONTH))
    above = E.CENTRE_NAME.get(r["above"]) if r["above"] else None
    k = st.columns(4)
    k[0].metric("Monthly points", r["points"])
    k[1].metric("Rank", f"#{r['rank']}" + (" (tie)" if r["tied"] else ""),
                help=f"{r['gap']} behind {above}" if above else "Top of the table")
    k[2].metric("Approved days", r["approved"])
    k[3].metric("Missed working days", r["missed"])
    k = st.columns(4)
    pend = sum(1 for s in SUBS if s["centre"] == code and E.month_of(s["review_date"]) == MONTH and STATUS[s["id"]] in ("pending", "flagged"))
    k[0].metric("Pending", pend)
    k[1].metric("Longest streak this month", r["longest"])
    k[2].metric("Gap to centre above", r["gap"] if above else "—")
    winners = {w["centre"] for w in league(MONTH)["winners"]}
    k[3].metric("Reward", "In top 3" if code in winners else "Eligible" if r["eligible"] else "Not yet")
    st.progress(min(1.0, r["points"] / E.THRESHOLD),
                text="15-point reward eligibility achieved" if r["eligible"] else f"{r['points']} / 15 points toward reward eligibility")

    a, b = st.columns(2)
    with a:
        st.markdown("**Calendar**")
        st.markdown(calendar_html(code, MONTH), unsafe_allow_html=True)
    with b:
        st.markdown("**Rejected submissions this month**")
        rej = [s for s in SUBS if s["centre"] == code and E.month_of(s["review_date"]) == MONTH and STATUS[s["id"]] in E.NON_SCORING]
        if rej:
            st.dataframe(pd.DataFrame([{"Date": nice(s["review_date"]), "Reason": DATA["latest"][s["id"]].get("reason") or "—"} for s in rej]),
                         hide_index=True, width="stretch")
        else:
            st.caption("None this month.")


def page_submit(code: str) -> None:
    st.title("Log a Google review")
    if st.session_state.get("just_submitted"):
        s = st.session_state["just_submitted"]
        st.success(f"Submission logged for {nice(s['date'])}. Your submission is awaiting verification; points count once the admin approves it.")
        if st.button("Log another review"):
            st.session_state.pop("just_submitted")
            st.rerun()
        return
    todays = [s for s in SUBS if s["centre"] == code and s["review_date"] == TODAY]
    if todays:
        st.info(f"Today already has {len(todays)} logged review(s). Extra reviews are recorded, but the day still earns one score.")
    if not E.is_working_day(TODAY, HOL):
        st.info("Today is a non-working day. You can log a review, but only working days earn points.")
    with st.form("submit", clear_on_submit=False):
        st.text_input("Centre", value=f"{E.CENTRE_NAME[code]} (from your login)", disabled=True)
        rd = st.date_input("Review date", value=date.fromisoformat(TODAY), max_value=date.fromisoformat(TODAY),
                           min_value=date.fromisoformat(START) if START <= TODAY else None, format="DD/MM/YYYY")
        url = st.text_input("Link to the public Google review", placeholder="https://maps.app.goo.gl/…",
                            help="Open the review on Google Maps, tap Share, and paste the link.")
        reviewer = st.text_input("Reviewer name on Google (optional)")
        staff = st.text_input("Logged by", placeholder="Your name")
        ev = st.file_uploader("Screenshot (optional, up to 2 MB)", type=["png", "jpg", "jpeg", "webp"])
        notes = st.text_area("Notes (optional)")
        go = st.form_submit_button("Submit for verification", type="primary")
    if go:
        rd_s = rd.isoformat()
        errs = []
        if rd_s > TODAY:
            errs.append("Pick a review date up to today.")
        if rd_s < START:
            errs.append(f"The league starts on {nice(START)}.")
        if not url.strip().lower().startswith(("http://", "https://")) or "." not in url:
            errs.append("Paste the full review link, starting with https://")
        if not staff.strip():
            errs.append("Add the name of the person logging this review.")
        if ev and ev.size > 2 * 1024 * 1024:
            errs.append("The screenshot is over 2 MB. Crop it or send a smaller image.")
        for e in errs:
            st.error(e)
        if errs:
            return
        try:
            db.add_submission(user, rd_s, url, reviewer.strip(), staff.strip(), notes.strip(),
                              ev.getvalue() if ev else None, ev.type if ev else None)
        except db.DuplicateLink:
            st.error("This review link has already been logged. Each review counts once.")
            return
        st.session_state["just_submitted"] = {"date": rd_s}
        st.rerun()


def page_history(code: str) -> None:
    st.title("Submission history")
    show_subs([s for s in SUBS if s["centre"] == code])


def page_points(code: str) -> None:
    st.title("Streaks & points")
    st.caption(f"How every point in {nice_month(MONTH)} was earned · scoring rule {E.RULE_VERSION}")
    df = ledger_df(code, MONTH)
    if df.empty:
        st.info(f"No working days in this month since the league started on {nice(START)}.")
    else:
        st.dataframe(df, hide_index=True, width="stretch")


# ---------------- admin pages ----------------
def page_overview() -> None:
    st.title(f"{nice_month(MONTH)} at a glance")
    lg = league(MONTH)
    working = E.is_working_day(TODAY, HOL)
    today = {c: today_score(c) for c, _ in E.CENTRES}
    compliant = sum(1 for sc, t in today.values() if t and t.status == "approved")
    k = st.columns(6)
    k[0].metric("Approved days", sum(r["approved"] for r in lg["rows"]))
    k[1].metric("Compliant today", f"{compliant} / 7" if working else "—")
    k[2].metric("Pending today", 7 - compliant if working else "—")
    k[3].metric("On a streak", sum(1 for sc, _ in today.values() if sc.current_streak > 0))
    k[4].metric("Points awarded", sum(r["points"] for r in lg["rows"]))
    k[5].metric("Reward-eligible", sum(1 for r in lg["rows"] if r["eligible"]))
    rows = []
    for r in sorted(lg["rows"], key=lambda x: x["name"]):
        sc, t = today[r["centre"]]
        rows.append({"Centre": r["name"], "Today": LABEL[t.status if t and t.working else "off"],
                     "Monthly reviews": sum(1 for s in SUBS if s["centre"] == r["centre"] and E.month_of(s["review_date"]) == MONTH),
                     "Current streak": r["current_streak"], "Monthly points": r["points"],
                     "Rank": f"{r['rank']}{'=' if r['tied'] else ''}", "Reward eligibility": "Eligible" if r["eligible"] else f"{E.THRESHOLD - r['points']} to go"})
    st.subheader("Centres")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    missed_today = [r["Centre"] for r in rows if r["Today"] in ("Not yet submitted", "Rejected")]
    if working and missed_today:
        st.warning("No approved review yet today: " + ", ".join(missed_today))
    st.subheader("Leaderboard")
    leaderboard_table(MONTH)


def page_queue() -> None:
    st.title("Verification queue")
    f = st.columns(5)
    status_f = f[0].selectbox("Status", ["Pending + flagged", "All", "Approved", "Rejected", "Invalidated"])
    centre_f = f[1].selectbox("Centre", ["All"] + [n for _, n in E.CENTRES])
    from_f = f[2].date_input("From", value=None, format="DD/MM/YYYY")
    to_f = f[3].date_input("To", value=None, format="DD/MM/YYYY")
    staff_f = f[4].text_input("Staff")
    url_count: dict[str, int] = {}
    for s in SUBS:
        url_count[db.norm_url(s["review_url"])] = url_count.get(db.norm_url(s["review_url"]), 0) + 1

    def keep(s):
        stt = STATUS[s["id"]]
        if status_f == "Pending + flagged" and stt not in ("pending", "flagged"):
            return False
        if status_f not in ("Pending + flagged", "All") and stt != status_f.lower():
            return False
        if centre_f != "All" and E.CENTRE_NAME[s["centre"]] != centre_f:
            return False
        if from_f and s["review_date"] < from_f.isoformat():
            return False
        if to_f and s["review_date"] > to_f.isoformat():
            return False
        return not staff_f or staff_f.lower() in (s["staff"] or "").lower()

    rows = sorted([s for s in SUBS if keep(s)], key=lambda s: (s["review_date"], s["created_at"]))
    st.caption(f"{len(rows)} match{'es' if len(rows) != 1 else ''}" + (" · showing first 50" if len(rows) > 50 else ""))
    if not rows:
        st.success("Queue is clear.")
    for s in rows[:50]:
        stt = STATUS[s["id"]]
        with st.container(border=True):
            top = st.columns([3, 2])
            top[0].markdown(f"**{E.CENTRE_NAME[s['centre']]}** · {nice(s['review_date'])} &nbsp; {pill(stt)}", unsafe_allow_html=True)
            top[1].caption(f"Logged {s['created_at'][:16].replace('T', ' ')} IST by {s['staff']}")
            st.markdown(f"[{s['review_url']}]({s['review_url']})")
            meta = []
            if s["reviewer"]:
                meta.append(f"Reviewer: {s['reviewer']}")
            if s["notes"]:
                meta.append(f"Note: {s['notes']}")
            if meta:
                st.caption(" · ".join(meta))
            same_day = any(o["id"] != s["id"] and o["centre"] == s["centre"] and o["review_date"] == s["review_date"]
                           and STATUS[o["id"]] == "approved" for o in SUBS)
            if url_count[db.norm_url(s["review_url"])] > 1:
                st.warning("Same review link appears more than once.")
            if same_day:
                st.caption("⚠ This day already has an approved review: this one earns no extra point.")
            if not E.is_working_day(s["review_date"], HOL):
                st.caption("⚠ Non-working day: earns no points.")
            if s["has_evidence"]:
                with st.expander("Screenshot"):
                    b, _t = db.evidence(s["id"])
                    if b:
                        st.image(b)
            txt = st.text_input("Reason (needed to reject or invalidate) or note", key=f"r_{s['id']}")
            bcols = st.columns(5)
            act = None
            if stt != "approved" and bcols[0].button("Approve", key=f"a_{s['id']}", type="primary"):
                act = ("approved", "", txt)
            if stt in ("pending", "flagged") and bcols[1].button("Reject", key=f"x_{s['id']}"):
                act = ("rejected", txt, "")
            if stt == "pending" and bcols[2].button("Flag", key=f"f_{s['id']}"):
                act = ("flagged", "", txt)
            if stt == "approved" and bcols[1].button("Invalidate", key=f"i_{s['id']}"):
                act = ("invalidated", txt, "")
            if bcols[3].button("Save note", key=f"n_{s['id']}"):
                act = (stt, "", txt) if txt else None
                if not txt:
                    st.error("Type a note first.")
            if act:
                status, reason, note = act
                if status in ("rejected", "invalidated") and not reason.strip():
                    st.error("Add a reason before rejecting or invalidating.")
                else:
                    db.decide(user, s["id"], status, reason.strip(), note.strip())
                    st.toast({"approved": "Approved · leaderboard updated", "rejected": "Rejected",
                              "flagged": "Flagged", "invalidated": "Invalidated · scores recalculated"}.get(status, "Note saved"))
                    st.rerun()
            hist = DATA["history"].get(s["id"], [])
            if hist:
                with st.expander(f"History ({len(hist)})"):
                    for h in reversed(hist):
                        st.caption(f"{h['decided_at'][:16].replace('T', ' ')} · {LABEL.get(h['status'], h['status'])}"
                                   + (f" · {h['reason']}" if h["reason"] else "") + (f" · note: {h['note']}" if h["note"] else ""))


def page_centres() -> None:
    st.title("All centres")
    code = st.selectbox("Centre", [c for c, _ in E.CENTRES], format_func=lambda c: E.CENTRE_NAME[c])
    tabs = st.tabs(["Dashboard", "Score ledger", "Submissions"])
    with tabs[0]:
        page_dashboard(code)
    with tabs[1]:
        df = ledger_df(code, MONTH)
        if df.empty:
            st.info("No working days yet this month.")
        else:
            st.dataframe(df, hide_index=True, width="stretch")
    with tabs[2]:
        show_subs([s for s in SUBS if s["centre"] == code and E.month_of(s["review_date"]) == MONTH])


def page_analytics() -> None:
    st.title(f"Analytics · {nice_month(MONTH)}")
    lg = league(MONTH)
    days, cur = [], MONTH + "-01"
    while cur[:7] == MONTH and cur <= TODAY:
        if E.is_working_day(cur, HOL) and cur >= START:
            n = sum(1 for r in lg["rows"] if any(x.date == cur and x.status == "approved" for x in r["score"].ledger))
            days.append({"Date": cur, "Centres approved": n, "Compliance %": round(n / 7 * 100),
                         "Logged": sum(1 for s in SUBS if s["review_date"] == cur)})
        cur = E.add_days(cur, 1)
    gold, blue = "#B07D1F", "#2F5BA8"
    a, b = st.columns(2)
    with a:
        st.markdown("**Daily compliance** · centres with an approved review")
        if days:
            df = pd.DataFrame(days)
            st.altair_chart(alt.Chart(df).mark_bar(color=gold, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("Date:T", title=None), y=alt.Y("Centres approved:Q", scale=alt.Scale(domain=[0, 7])),
                tooltip=["Date:T", "Centres approved", "Compliance %", "Logged"]), width="stretch")
            st.caption(f"Average compliance: {round(df['Compliance %'].mean())}%")
        else:
            st.info("No working days yet this month.")
    with b:
        st.markdown("**Points by centre** · dashed line = 15-point threshold")
        pdf = pd.DataFrame([{"Centre": r["name"], "Points": r["points"]} for r in lg["rows"]])
        bars = alt.Chart(pdf).mark_bar(color=gold).encode(x="Points:Q", y=alt.Y("Centre:N", sort="-x", title=None), tooltip=["Centre", "Points"])
        rule = alt.Chart(pd.DataFrame({"x": [E.THRESHOLD]})).mark_rule(strokeDash=[4, 4]).encode(x="x:Q")
        st.altair_chart(bars + rule, width="stretch")
    a, b = st.columns(2)
    with a:
        st.markdown("**Streaks** · current vs longest this month")
        sdf = pd.DataFrame([{"Centre": r["name"], "Streak": "Current", "Days": r["current_streak"]} for r in lg["rows"]]
                           + [{"Centre": r["name"], "Streak": "Longest this month", "Days": r["longest"]} for r in lg["rows"]])
        st.altair_chart(alt.Chart(sdf).mark_bar().encode(
            y=alt.Y("Centre:N", title=None), x="Days:Q", yOffset="Streak:N",
            color=alt.Color("Streak:N", scale=alt.Scale(range=[gold, blue]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["Centre", "Streak", "Days"]), width="stretch")
    with b:
        st.markdown("**Missed working days**")
        st.dataframe(pd.DataFrame([{"Centre": r["name"], "Missed": r["missed"], "Of which pending": r["pending_days"],
                                    "Of which rejected": r["rejected_days"], "Working days": r["working_days"]}
                                   for r in sorted(lg["rows"], key=lambda x: -x["missed"])]), hide_index=True, width="stretch")
    st.markdown("**Month by month** · points per centre (★ = reached 15)")
    hist = []
    for code, name in E.CENTRES:
        rec = {"Centre": name}
        for m in months_since_start():
            r = row_for(m, code)
            rec[nice_month(m)] = f"{r['points']}{' ★' if r['eligible'] else ''}"
        hist.append(rec)
    st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")
    st.markdown("**Pending verification**")
    show_subs([s for s in SUBS if STATUS[s["id"]] in ("pending", "flagged")], with_centre=True)


def reward_status(month: str, code: str) -> dict:
    return next((r for r in DATA["rewards"] if r["month"] == month and r["centre"] == code), {})


def page_rewards() -> None:
    st.title(f"Monthly rewards · {nice_month(MONTH)}")
    st.caption("Provisional: month in progress" if MONTH >= TODAY[:7] else "Final for the month")
    lg = league(MONTH)
    cols = st.columns(3)
    for i, pos in enumerate((1, 2, 3)):
        ws = [w for w in lg["winners"] if w["position"] == pos]
        with cols[i].container(border=True):
            st.markdown(f"**Position {pos}** · {SET.get(f'reward_{pos}') or 'Reward not set (Settings)'}")
            if not ws:
                st.caption("No centre has qualified for this position yet.")
            for w in ws:
                cur = reward_status(MONTH, w["centre"])
                st.markdown(f"### {E.CENTRE_NAME[w['centre']]}")
                st.caption(f"{w['points']} points" + (" · tie" if w["tied"] else ""))
                opts = ["pending", "announced", "fulfilled"]
                new = st.selectbox("Status", opts, index=opts.index(cur.get("status", "pending")), key=f"rs_{w['centre']}")
                note = st.text_input("Note", value=cur.get("note") or "", key=f"rn_{w['centre']}")
                if st.button("Save", key=f"rb_{w['centre']}"):
                    db.set_reward(user, MONTH, w["centre"], pos, new, note)
                    st.toast(f"Reward marked {new}")
                    st.rerun()
    st.subheader("Eligibility")
    win = {w["centre"]: w["position"] for w in lg["winners"]}
    st.dataframe(pd.DataFrame([{"Centre": r["name"], "Points": r["points"], "Approved days": r["approved"],
                                "Eligible": "Yes" if r["eligible"] else "No",
                                "Position": f"Reward #{win[r['centre']]}" if r["centre"] in win else "—"} for r in lg["rows"]]),
                 hide_index=True, width="stretch")
    past = [m for m in months_since_start() if m < TODAY[:7]]
    if past:
        st.subheader("Past winners")
        rows = []
        for m in reversed(past):
            w = league(m)["winners"]
            rec = {"Month": nice_month(m)}
            for p in (1, 2, 3):
                rec[f"#{p}"] = ", ".join(f"{E.CENTRE_NAME[x['centre']]} ({x['points']})" for x in w if x["position"] == p) or "—"
            rows.append(rec)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def page_calendar() -> None:
    st.title("Working-day calendar")
    st.caption("Mon–Fri count. Weekends and the holidays below never break a streak. Changes recalculate every score instantly.")
    with st.form("hol", clear_on_submit=True):
        c = st.columns([1, 2, 1])
        d = c[0].date_input("Date", format="DD/MM/YYYY")
        lab = c[1].text_input("Holiday", placeholder="e.g. Diwali")
        if c[2].form_submit_button("Add holiday"):
            db.add_holiday(user, d.isoformat(), lab.strip() or "Holiday")
            st.rerun()
    if not DATA["holidays"]:
        st.info("No holidays set yet.")
    for hd in sorted(DATA["holidays"]):
        c = st.columns([2, 3, 1])
        c[0].write(nice(hd) + " " + hd[:4])
        c[1].write(DATA["holidays"][hd])
        if c[2].button("Remove", key=f"h_{hd}"):
            db.remove_holiday(user, hd)
            st.rerun()


def page_users() -> None:
    st.title("User management")
    st.caption("There is no public sign-up. Create one login per centre here; each new password is shown once.")
    if st.session_state.get("shown_pw"):
        u, p = st.session_state.pop("shown_pw")
        st.success(f"Password for **{u}**: `{p}` — copy it now and send it privately. They'll be asked to change it at first sign-in.")
    us = db.list_users()
    st.dataframe(pd.DataFrame([{"Username": u["username"], "Role": u["role"], "Centre": E.CENTRE_NAME.get(u["centre"] or "", "—"),
                                "Active": "Yes" if u["active"] else "No", "Created": u["created_at"][:10]} for u in us]),
                 hide_index=True, width="stretch")
    covered = {u["centre"] for u in us if u["role"] == "centre" and u["active"]}
    missing = [n for c, n in E.CENTRES if c not in covered]
    if missing:
        st.warning("No active login yet for: " + ", ".join(missing))
    a, b = st.columns(2)
    with a, st.form("newuser", clear_on_submit=True):
        st.markdown("**Create account**")
        role = st.selectbox("Role", ["centre", "admin"])
        centre = st.selectbox("Centre (centre accounts)", [c for c, _ in E.CENTRES], format_func=lambda c: E.CENTRE_NAME[c])
        uname = st.text_input("Username", placeholder="e.g. bhopal")
        if st.form_submit_button("Create", type="primary"):
            if not uname.strip() or db.get_user(uname):
                st.error("Pick a username that isn't taken.")
            else:
                pw = auth.new_password()
                db.create_user(user["username"], uname, auth.hash_pw(pw), role, centre if role == "centre" else None)
                st.session_state["shown_pw"] = (uname.strip().lower(), pw)
                st.rerun()
    with b:
        st.markdown("**Reset or disable**")
        others = [u for u in us if u["id"] != user["id"]]
        if others:
            sel = st.selectbox("Account", others, format_func=lambda u: f"{u['username']} ({u['role']})")
            c = st.columns(2)
            if c[0].button("Reset password"):
                pw = auth.new_password()
                db.update_user(user["username"], sel["id"], password_hash=auth.hash_pw(pw), must_change=True)
                st.session_state["shown_pw"] = (sel["username"], pw)
                st.rerun()
            if c[1].button("Enable" if not sel["active"] else "Disable"):
                db.update_user(user["username"], sel["id"], active=not sel["active"])
                st.rerun()


REPORTS = {
    "Daily compliance": "One row per centre per working day",
    "Submission register": "Every logged review with status and decision",
    "Monthly scorecard": "One row per centre: counts, points, streaks, rank, reward",
    "Leaderboard": "Ranked table for the month",
    "Reward eligibility": "Eligibility, positions and reward status",
    "Streak records": "Daily scoring ledger since the league started",
}


def report_df(kind: str, centre: str | None, d_from: str | None, d_to: str | None) -> pd.DataFrame:
    lg = league(MONTH)
    ok = lambda c: not centre or c == centre  # noqa: E731
    rng = lambda s: (not d_from or s >= d_from) and (not d_to or s <= d_to)  # noqa: E731
    win = {w["centre"]: w["position"] for w in lg["winners"]}
    if kind == "Daily compliance":
        return pd.DataFrame([{"Date": x.date, "Centre": r["name"], "Working day": "Yes" if x.working else "No",
                              "Status": LABEL.get(x.status, x.status), "Points": x.points, "Streak": x.streak, "Extra reviews": x.extra}
                             for r in lg["rows"] if ok(r["centre"]) for x in r["score"].ledger
                             if E.month_of(x.date) == MONTH and rng(x.date)])
    if kind == "Submission register":
        rows = [s for s in SUBS if ok(s["centre"]) and ((rng(s["review_date"]) if (d_from or d_to) else E.month_of(s["review_date"]) == MONTH))]
        out = []
        for s in sorted(rows, key=lambda x: x["review_date"]):
            d = DATA["latest"].get(s["id"], {})
            out.append({"Submission ID": s["id"], "Review date": s["review_date"], "Centre": E.CENTRE_NAME[s["centre"]],
                        "Review link": s["review_url"], "Reviewer": s["reviewer"] or "", "Logged by": s["staff"],
                        "Notes": s["notes"] or "", "Logged at": s["created_at"], "Status": LABEL[STATUS[s["id"]]],
                        "Reason": d.get("reason") or "", "Admin note": d.get("note") or "", "Decided at": d.get("decided_at") or ""})
        return pd.DataFrame(out)
    if kind in ("Monthly scorecard", "Leaderboard"):
        out = []
        for r in lg["rows"]:
            if not ok(r["centre"]):
                continue
            rec = {"Rank": f"{r['rank']}{' (tie)' if r['tied'] else ''}", "Centre": r["name"], "Points": r["points"],
                   "Approved days": r["approved"], "Current streak": r["current_streak"], "Longest streak": r["longest"]}
            if kind == "Leaderboard":
                rec.update({"Eligible": "Yes" if r["eligible"] else "No", "Gap to next rank": r["gap"]})
            else:
                rec.update({"Logged reviews": sum(1 for s in SUBS if s["centre"] == r["centre"] and E.month_of(s["review_date"]) == MONTH),
                            "Missed working days": r["missed"], "Eligible": "Yes" if r["eligible"] else "No",
                            "Reward position": win.get(r["centre"], ""),
                            "Reward status": reward_status(MONTH, r["centre"]).get("status", "pending") if r["centre"] in win else ""})
            out.append(rec)
        return pd.DataFrame(out)
    if kind == "Reward eligibility":
        return pd.DataFrame([{"Month": MONTH, "Centre": r["name"], "Points": r["points"], "Eligible": "Yes" if r["eligible"] else "No",
                              "Position": win.get(r["centre"], ""), "Reward": SET.get(f"reward_{win[r['centre']]}", "") if r["centre"] in win else "",
                              "Status": reward_status(MONTH, r["centre"]).get("status", "pending") if r["centre"] in win else ""}
                             for r in lg["rows"]])
    if kind == "Streak records":
        out = []
        for code, name in E.CENTRES:
            if not ok(code):
                continue
            sc, _ = today_score(code)
            out += [{"Centre": name, "Date": x.date, "Status": LABEL.get(x.status, x.status), "Base": x.base, "Multiplier": x.mult or "",
                     "Points": x.points, "Streak": x.streak, "Rule": x.rule, "Qualifying submission": x.sub_id or ""}
                    for x in sc.ledger if x.working and rng(x.date)]
        return pd.DataFrame(out)
    return pd.DataFrame()


def page_reports() -> None:
    st.title("Reports & exports")
    st.caption(f"Uses the month in the sidebar ({nice_month(MONTH)}) plus these filters.")
    c = st.columns(3)
    centre = c[0].selectbox("Centre", [None] + [x for x, _ in E.CENTRES], format_func=lambda x: "All centres" if x is None else E.CENTRE_NAME[x])
    d_from = c[1].date_input("From", value=None, format="DD/MM/YYYY")
    d_to = c[2].date_input("To", value=None, format="DD/MM/YYYY")
    f, t = (d_from.isoformat() if d_from else None), (d_to.isoformat() if d_to else None)
    frames = {}
    for kind, desc in REPORTS.items():
        df = report_df(kind, centre, f, t)
        frames[kind] = df
        r = st.columns([4, 1, 1])
        r[0].markdown(f"**{kind}** · {len(df)} rows  \n<span style='opacity:.7'>{desc}</span>", unsafe_allow_html=True)
        slug = kind.lower().replace(" ", "-")
        r[1].download_button("CSV", df.to_csv(index=False).encode("utf-8-sig"), f"jg-{slug}-{MONTH}.csv", "text/csv", key=f"c_{slug}")
        r[2].download_button("XLSX", to_xlsx({kind: df}), f"jg-{slug}-{MONTH}.xlsx", key=f"x_{slug}")
    st.download_button("Download all reports (XLSX workbook)", to_xlsx(frames), f"jg-reviews-all-{MONTH}.xlsx", type="primary")


def to_xlsx(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in frames.items():
            (df if not df.empty else pd.DataFrame({"Note": ["No rows for these filters"]})).to_excel(w, sheet_name=name[:31], index=False)
    return buf.getvalue()


def page_audit() -> None:
    st.title("Audit log")
    rows = db.audit_rows()
    if not rows:
        st.info("No activity yet. Submissions, decisions, settings and account changes are recorded here.")
        return
    st.dataframe(pd.DataFrame([{"When (IST)": r["at"][:19].replace("T", " "), "Who": r["actor"], "Action": r["action"], "Detail": r["detail"]}
                               for r in rows]), hide_index=True, width="stretch")
    st.caption("Newest 500 events. Decisions are never overwritten: each change adds a new row.")


def page_settings() -> None:
    st.title("Settings")
    with st.form("settings"):
        sd = st.date_input("League start date", value=date.fromisoformat(START), format="DD/MM/YYYY",
                           help="Working days before this date are ignored.")
        r = [st.text_input(f"Reward for position {p}", value=SET.get(f"reward_{p}", ""), placeholder="Describe the reward") for p in (1, 2, 3)]
        if st.form_submit_button("Save settings", type="primary"):
            if sd.isoformat() != SET.get("start_date"):
                db.set_setting(user, "start_date", sd.isoformat())
            for p, v in zip((1, 2, 3), r):
                if v != SET.get(f"reward_{p}", ""):
                    db.set_setting(user, f"reward_{p}", v)
            st.toast("Settings saved")
            st.rerun()
    st.caption(f"Scoring rule {E.RULE_VERSION}: 1 point per working day with an approved review; Monday earns 2 when the previous "
               "working day also qualified; one score per centre per day; 15 points to qualify; the top three eligible centres win.")


# ---------------- router ----------------
if IS_ADMIN:
    _ = {"Overview": page_overview, "Verification queue": page_queue, "All centres": page_centres,
     "Leaderboard": lambda: (st.title(f"Leaderboard · {nice_month(MONTH)}"), leaderboard_table(MONTH)),
     "Analytics": page_analytics, "Monthly rewards": page_rewards, "Working-day calendar": page_calendar,
     "User management": page_users, "Reports & exports": page_reports, "Audit log": page_audit,
     "Settings": page_settings, "My password": lambda: (st.title("My password"), auth.change_password_form(user))}[PAGE]()
else:
    code = user["centre"]
    _ = {"Dashboard": lambda: page_dashboard(code), "Submit review": lambda: page_submit(code),
     "Submission history": lambda: page_history(code), "Streaks & points": lambda: page_points(code),
     "Leaderboard": lambda: (st.title(f"Leaderboard · {nice_month(MONTH)}"), leaderboard_table(MONTH, code)),
     "My password": lambda: (st.title("My password"), auth.change_password_form(user))}[PAGE]()
