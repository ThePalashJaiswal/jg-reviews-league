"""Create a local DEMO database with sample records for all seven centres.

    python seed_demo.py            # writes demo.db
    DATABASE_URL=sqlite:///demo.db streamlit run app.py

Demo logins (local only, never use in production):
    admin / demo-admin-2026        bhopal, jaipur, delhi, indore, prayagraj, jabalpur, lucknow / demo-centre-2026

The records are invented samples, not real Google reviews. The app shows a
"Demo database" banner whenever this data is loaded.
"""
import os
import random
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///demo.db")
if Path("demo.db").exists() and os.environ["DATABASE_URL"] == "sqlite:///demo.db":
    Path("demo.db").unlink()

import auth  # noqa: E402
import db  # noqa: E402
import engine as E  # noqa: E402

rnd = random.Random(20261027)
eng = db.get_engine()
today = E.today_ist()
start = E.add_days(today, -60)[:8] + "01"
hols = {f"{today[:4]}-10-02": "Gandhi Jayanti"}

with eng.begin() as c:
    admin_hash = auth.hash_pw("demo-admin-2026")
    centre_hash = auth.hash_pw("demo-centre-2026")
    c.execute(db.users.insert().values(username="admin", password_hash=admin_hash, role="admin", centre=None,
                                       active=True, must_change=False, created_at=db.now()))
    ids = {}
    for code, name in E.CENTRES:
        r = c.execute(db.users.insert().values(username=name.lower(), password_hash=centre_hash, role="centre", centre=code,
                                               active=True, must_change=False, created_at=db.now()))
        ids[code] = r.inserted_primary_key[0]
    for k, v in {"start_date": start, "demo": "1", "reward_1": "Team lunch (demo)", "reward_2": "Gift vouchers (demo)",
                 "reward_3": "Certificate (demo)"}.items():
        c.execute(db.settings.insert().values(key=k, value=v))
    for dte, lab in hols.items():
        c.execute(db.holidays.insert().values(date=dte, label=lab))

    reliability = {"BPL": .93, "JPR": .86, "DEL": .72, "IDR": .82, "PRY": .6, "JBP": .78, "LKO": .5}
    staff = ["Ritika", "Aman", "Neha", "Karan", "Sana", "Rohit", "Pooja"]
    yesterday = E.add_days(today, -1)
    n = 0
    for code, _ in E.CENTRES:
        cur = start
        while cur <= today:
            if E.is_working_day(cur, set(hols)) and rnd.random() < reliability[code] * (.7 if cur == today else 1):
                for i in range(2 if rnd.random() < .15 else 1):
                    n += 1
                    sid = str(uuid.uuid4())
                    url = f"https://example.com/demo-review/{code.lower()}-{n}"
                    c.execute(db.submissions.insert().values(
                        id=sid, centre=code, review_date=cur, review_url=url, url_norm=db.norm_url(url),
                        reviewer=["Student", "Parent", "Alumnus", "Walk-in visitor"][n % 4], staff=rnd.choice(staff),
                        notes=None, created_at=f"{cur}T1{i}:00:00+05:30", created_by=ids[code]))
                    if cur == today or (cur == yesterday and rnd.random() < .3):
                        continue
                    ok = rnd.random() < .9
                    c.execute(db.decisions.insert().values(
                        submission_id=sid, status="approved" if ok else "rejected",
                        reason=None if ok else "Link opens a different business profile",
                        decided_by=1, decided_at=f"{cur}T18:00:00+05:30", rule=E.RULE_VERSION))
            cur = E.add_days(cur, 1)
print(f"Demo database ready: {n} sample submissions from {start} to {today}.")
