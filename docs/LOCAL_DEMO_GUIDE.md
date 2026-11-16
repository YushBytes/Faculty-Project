# Running ACADLYTICS locally

Everything here was run on 2026-11-14 and re-checked on 2026-11-16 on Windows 11 with Docker Desktop. The application starts
empty: there is no demo data and there are no built-in passwords.

## Addresses

| What | Address |
|---|---|
| Web app | http://localhost:3001 |
| API | http://localhost:8000 |
| API documentation (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| PostgreSQL 16 | `localhost:55432`, database `acadlytics`, user `acadlytics` |

The ports are `WEB_PORT`, `API_PORT` and `POSTGRES_PORT` in `.env`. They default to 3001, 8000
and 55432 so that ACADLYTICS can run next to projects that use 3000 and 5432. If one is taken,
change it in `.env` and run `docker compose up -d` again; nothing else needs editing.

## Start and stop

```bash
cp .env.example .env        # first time only
# in .env set ACADLYTICS_ADMIN_PASSWORD=<8+ characters>   (first time only)
docker compose up -d --build
docker compose ps           # db and api show "healthy"; web starts after the api is healthy
```

```bash
docker compose logs -f api  # migrations, the admin-account line, requests
docker compose stop         # stop, keep everything
docker compose down         # remove the containers, keep the data (volume pgdata)
```

`docker compose down -v` deletes the database. Do not run it on a database with real marks unless
you have a backup (below).

On every start the API container applies migrations (`alembic upgrade head`), creates the
Administrator if there is none and a password is configured, then serves. Both steps do nothing
when there is nothing to do.

## First sign-in

1. Open http://localhost:3001 → **Sign in** → `ACADLYTICS_ADMIN_EMAIL` / `ACADLYTICS_ADMIN_PASSWORD`
   from `.env` (the email defaults to `admin@acadlytics.dev`).
2. **Structure** → add the department (for example `CSE`, Computer Science and Engineering).
3. **People** → add the HOD for that department, with a password you hand to them.
4. Faculty accounts appear when a TLP report naming them is uploaded
   (`<staff id>@srmist.edu.in`). Open **People**, find the person, set a password. Until then
   the account cannot sign in. To give every new faculty account the same starting password
   instead, set `FACULTY_DEFAULT_PASSWORD` in `.env` before uploading.
5. Anyone changes their own password under **Settings → Change password**. It signs them out
   everywhere.

If the password was empty at the first start, the API log says
`No Administrator account exists and ACADLYTICS_ADMIN_PASSWORD is not set`. Set it and run
`docker compose up -d`, or:

```bash
docker compose exec api python -m app.cli create-admin --email you@example.edu --name "Your Name"
```

## A teacher's walk-through

| Step | Where | What to look at |
|---|---|---|
| 1. HOD uploads the TLP reports | **Import TLP marks** → drop `.xlsx` / `.csv` / TLP `.pdf` files → *Upload and validate* | Each file shows the class it was routed to, what it will set up, and any problem. Nothing is written yet. |
| 2. Correct, map or exclude | the file's **Review** drawer | A mark above the maximum, an unknown register number or a duplicate row blocks the file until fixed or excluded (an excluded row stays listed with *Include*). A column the system cannot match to an assessment (`Cycle Test 2` for `CT2`) is listed under *Columns*: map it to the assessment or ignore it. |
| 3. Confirm | *Confirm* | Marks are written in one transaction; analytics and attention are recomputed in the same transaction. |
| 4. Faculty signs in | after the HOD set their password | The faculty member sees only the classes they teach. |
| 5. Dashboard | **Dashboard** | Average, pass %, completion, trend, distribution. Absent and missing are shown as such, never as 0. |
| 6. Class | **Classes** → a class | Marks grid, assessments, class analytics, downloads. |
| 7. Student | a student's name | Their assessments, trend against the pass mark, flags, interventions. |
| 8. Attention | **Attention** | Seven explained rules. Each flag states the value, the threshold and the assessments it used. |
| 9. Intervention | tick students → *Record intervention* | Reasons come from their live flags or a note. |
| 10. Outcome | **Interventions** → an entry | What was observed at the next assessment, beside the peer group. Stated as an observation, never as a cause. Says "insufficient data" until a follow-up assessment exists. |
| 11. Reports | **Reports**, or a class's download buttons | PDF, Excel, CSV from the same numbers as the screens. |
| 12. Sign out, sign in | **Settings** → *Sign out* | The session ends on the server; the old refresh token no longer works. |

A blank mark cell in an upload is recorded as **absent** with a warning (never 0). A student who
is not in the file stays **missing**. A typed `0` stays a real 0. See `IMPORT_FORMAT.md`.

## End-to-end check

`scripts/e2e_live.py` drives a running stack over HTTP exactly as the browser does (session
cookie routes, the `/api/v1` proxy, the API): 130 checks covering sign-in, set-up, Excel + PDF +
CSV import with every invalid case, atomic refusal, zero / absent / missing, analytics, attention,
interventions, all 15 report downloads, isolation between two faculty members, input hardening,
refresh-token reuse, logout and password change.

It creates data, so run it on a **throwaway** stack, never on the one with real marks. It refuses
to run if the platform already has classes.

```bash
# a second, isolated stack with its own empty volume
export POSTGRES_PORT=55433 API_PORT=8002 WEB_PORT=3003 ACADLYTICS_ADMIN_PASSWORD=Throwaway-pass-1
docker compose -p acadlytics-clean up -d --build

python scripts/e2e_live.py --web http://localhost:3003 --api http://localhost:8002 \
    --admin-email admin@acadlytics.dev --admin-password Throwaway-pass-1

docker compose -p acadlytics-clean down -v --rmi local     # remove it completely
```

(The script needs Python 3.11+ and `openpyxl`; the backend virtualenv has both:
`backend/.venv/Scripts/python` on Windows, `backend/.venv/bin/python` elsewhere.)

## Automated checks

```bash
cd backend  && pytest && ruff check . && ruff format --check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

The backend suite creates and drops its own database (`TEST_DATABASE_URL`, `acadlytics_test`);
it never touches `acadlytics`. Run one pytest session at a time: two sessions share that
database and break each other.

Against a **throwaway** stack (like the one above), three live checks:

```bash
python scripts/e2e_live.py    --web http://localhost:3003 --api http://localhost:8002 --admin-email ... --admin-password ...
python scripts/verify_live.py --api http://localhost:8002 --admin-email ... --admin-password ...   # repeatable
cd frontend && E2E_WEB=http://localhost:3003 E2E_API=http://localhost:8002 E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... npm run test:e2e   # repeatable
```

`verify_live.py` and the Playwright suite create their own uniquely named department on each run,
so they can run many times on the same stack. Details: `TESTING_AND_VERIFICATION.md`.

## Backup and restore

```bash
# backup
docker compose exec -T db pg_dump -U acadlytics -d acadlytics -Fc > acadlytics-$(date +%F).dump

# restore into an empty database
docker compose exec -T db psql -U acadlytics -d postgres -c "create database acadlytics_restore owner acadlytics"
docker compose exec -T db pg_restore -U acadlytics -d acadlytics_restore < acadlytics-2026-11-14.dump
```

Keep dumps outside the repository: they contain student names and marks.

## Fictional data for development

Nothing loads it automatically. On an empty, throwaway database only:

```bash
docker compose exec -e ACADLYTICS_DEMO_PASSWORD=<8+ characters> api python -m app.cli seed-demo
```

The command refuses to run in production, without a password, or on a database that already has
data. Do not mix it with real reports: there is no supported way to separate them afterwards
other than the kind of scoped clean-up recorded in `ACADLYTICS_FINAL_QUALITY_AUDIT.md` §4.
