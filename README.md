# JG Reviews League

Internal Streamlit app that tracks daily Google review logging across the seven Judiciary Gold offline centres (Bhopal, Jaipur, Delhi, Indore, Prayagraj, Jabalpur, Lucknow).

It covers:
- Centre logins and an admin login
- A daily submission form
- An admin verification queue
- Working-day streaks with a Monday bonus
- A live leaderboard
- Monthly rewards (top three centres with 15+ points)
- CSV/XLSX reports
- An audit log

## How it fits together

| File | Job |
|---|---|
| `engine.py` | All scoring rules. Pure Python, no database. The single source of truth for points, streaks, ranks and rewards. |
| `db.py` | Tables, reads and writes. SQLite on your laptop, Postgres (Supabase) in production. Admin-only writes check the role on the server. |
| `auth.py` | Bcrypt password hashing, sign-in, first-run admin, password changes. |
| `app.py` | The Streamlit pages. |
| `seed_demo.py` | Builds a local demo database with sample data. |
| `tests/` | 15 scoring tests (spec scenarios A–L and more) plus end-to-end app tests. |

Scores are never stored. They are recalculated from approved submissions on every page load. Approving, rejecting or invalidating anything, or adding a holiday, updates every streak, point, rank and reward instantly. Decisions are append-only: each change adds a row, so the full history stays visible.

## Why Supabase and not a file

Streamlit Community Cloud does not keep files between restarts. A SQLite file there would be wiped when the app sleeps, reboots or redeploys, taking every streak with it. A free Supabase Postgres database keeps the data. Locally you can skip Supabase entirely.

---

## 1. Run it on your laptop (10 minutes)

You need Python 3.10+ and Git.

```bash
git clone https://github.com/<you>/jg-reviews-league.git
cd jg-reviews-league
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Try the demo first:**

```bash
python seed_demo.py
DATABASE_URL=sqlite:///demo.db streamlit run app.py
```

- On Windows PowerShell, run `$env:DATABASE_URL="sqlite:///demo.db"` first, then `streamlit run app.py`.
- Sign in as `admin` / `demo-admin-2026`, or as `bhopal` / `demo-centre-2026` (any centre name works the same way).
- The demo data is invented sample data, and the app shows a demo banner while it's loaded.

**Run with your own empty database:**

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit it: delete the DATABASE_URL line (to use local SQLite) and set ADMIN_USERNAME / ADMIN_PASSWORD
streamlit run app.py
```

**Run the tests:**

```bash
pip install pytest
pytest -q
```

## 2. Put it on GitHub

1. Create an empty **private** repository on GitHub named `jg-reviews-league`.
2. Run:

```bash
git init
git add .
git commit -m "JG Reviews League"
git branch -M main
git remote add origin https://github.com/<you>/jg-reviews-league.git
git push -u origin main
```

`.gitignore` keeps `secrets.toml` and any `.db` file out of the repo. Check `git status` before your first push anyway.

## 3. Create the database (Supabase, free tier)

1. Sign up at supabase.com and create a new project. Pick the **Mumbai (ap-south-1)** region and save the database password.
2. Open the project, click **Connect**, and copy the **Session pooler** connection string.
   - Use the pooler string, not the "Direct connection" string. The direct one may need IPv6, which Streamlit Cloud may not support.
3. Put your database password into the string where it says `[YOUR-PASSWORD]`.

You don't need to create tables. The app creates them on first start.

## 4. Deploy on Streamlit Community Cloud

1. Go to share.streamlit.io and sign in with GitHub.
2. Click **Create app**, choose your repo, branch `main`, and main file `app.py`.
3. Open **Advanced settings → Secrets** and paste:

```toml
DATABASE_URL = "postgresql://postgres.xxxx:YOUR-PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
ADMIN_USERNAME = "pj"
ADMIN_PASSWORD = "a-long-first-password"
```

4. Deploy. The first load creates the tables and your admin account. Sign in and set your own password when asked.

Every `git push` to `main` redeploys automatically. Your data stays in Supabase.

> **Sleeping apps:** on the free tier, an app nobody opens for a while goes to sleep, and the next visitor waits about a minute while it wakes. That's harmless for this league, because data lives in Supabase. Ask one centre to open it each morning, or upgrade later if the wait annoys people.

## 5. First-day setup (admin)

1. **Settings:** set the league start date and describe the three rewards. Working days before the start date are ignored.
2. **Working-day calendar:** add network-wide holidays (Diwali and so on). Holidays and weekends never break a streak.
3. **User management:** create one account per centre, for example `bhopal`.
   - Each password is shown once. Send it privately; the centre sets its own at first sign-in.
   - To add a co-admin, create an `admin` account.
4. Send the app link to each centre.

**Daily routine:**
- **Centres:** *Submit review*: paste the Google review link (Google Maps → the review → Share), add your name, optionally attach a screenshot.
- **Admin:** *Verification queue*: open the link, then Approve, or Reject with a reason. Only approved reviews score.

## Scoring rules (v1)

- 1 point per working day (Mon–Fri, minus configured holidays) with an approved review.
- **Monday bonus:** Monday earns 2 points if the previous working day also had an approved review.
  - A Friday holiday doesn't break it: Thursday counts as the previous working day.
  - A Monday holiday moves the next score to Tuesday, at 1 point.
- Missing a working day resets the streak. The next approved day starts again at 1.
- One score per centre per day. Extra reviews are logged but earn nothing extra.
- Duplicate review links are blocked by the database.
- Pending, flagged, rejected or invalidated submissions earn nothing.
- Monthly points count only dates inside that month. Streaks can carry across months.
- **Leaderboard order:** points, then approved days, then current streak. Ties stay ties.
- **Rewards:**
  - A centre needs 15+ points in the month to qualify.
  - The top three qualifying centres win.
  - Centres below 15 stay on the leaderboard but cannot win.

## Security notes

- There is no public sign-up. The admin creates every account.
- Passwords are stored as bcrypt hashes. The first admin comes from secrets, and there is no default password.
- Five wrong passwords lock that browser session for 60 seconds.
- Centre accounts only see their own submissions; the leaderboard is shared by design. All checks run on the server.
- Every write is recorded in the audit log.
- **Known limit:** there is no self-service password reset by email. The admin resets passwords from User management.

## Optional later: Google Business Profile API

The app verifies reviews manually: someone opens the link and approves it. Automatic checks would need Google Business Profile API access, which Google approves per project, plus OAuth for each location. Treat it as a later enhancement once the league proves useful.
