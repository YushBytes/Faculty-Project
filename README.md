# ACADLYTICS

[![backend](https://github.com/YushBytes/Faculty-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/YushBytes/Faculty-Project/actions/workflows/ci.yml)
[![frontend](https://github.com/YushBytes/Faculty-Project/actions/workflows/frontend.yml/badge.svg)](https://github.com/YushBytes/Faculty-Project/actions/workflows/frontend.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Academic performance intelligence for SRM Institute of Science and Technology.**

```
SRM TLP reports (xlsx / csv / pdf) → validated import → PostgreSQL → deterministic analytics
   → attention → interventions → reports — for every level of the academic hierarchy
```

One application in one repository: a FastAPI backend (`backend/`), a Next.js web app
(`frontend/`) and PostgreSQL, run together with Docker Compose.

| Level | Sees | Can change |
|---|---|---|
| **Administrator** (exactly one) | the whole institution | everything: departments, terms, courses, sections, people and roles, assignments |
| **HOD** (one per department) | the department: every course, section, coordinator, faculty member, student | department staff below them, sections, courses, coordinators, faculty assignment |
| **Academic Head** (one per department) | the department's course portfolio | appoints Course Coordinators, course information, faculty assignment |
| **Course Coordinator** | their course(s) across **every** section and faculty member | faculty assignment for their course; imports and confirms TLP files for any section |
| **Faculty** | only the classes they teach | their classes' marks (TLP upload), interventions |

Every rule above is enforced by the API (`backend/app/modules/organization/scope.py`,
`users/service.py`); an out-of-scope id is a 404, never a leak. The UI only mirrors it.
Department analytics thresholds follow the same scope: the Administrator sees every department,
everyone else their own department and the departments of the classes they can see.

---

## 1. Run it (Docker — recommended)

Prerequisites: **Docker Desktop** (Windows/macOS) or Docker Engine + Compose v2. Nothing else.

```bash
git clone https://github.com/YushBytes/Faculty-Project.git
cd Faculty-Project
cp .env.example .env                  # ports and passwords live here
# edit .env: set ACADLYTICS_ADMIN_PASSWORD (8+ characters) - there is no built-in password
docker compose up -d --build          # db + api + web (web waits until the API is healthy)
```

Open **http://localhost:3001**. The platform starts **empty**: no departments, semesters,
courses, sections, students or marks, and no demo data. Everything comes from what the
Administrator sets up and the TLP reports you upload.

| Service | URL |
|---|---|
| Web app | http://localhost:3001 |
| API | http://localhost:8000 |
| API docs (OpenAPI / Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| PostgreSQL | localhost:55432 |

Stop with `docker compose down` (data is kept in the `pgdata` volume).
`docker compose down -v` deletes the database; the next `up` starts empty again.

## 2. First sign-in

There are no demo accounts and no built-in passwords.

1. **Administrator.** On start, when no Administrator exists, the API creates one from
   `ACADLYTICS_ADMIN_EMAIL` (default `admin@acadlytics.dev`) and `ACADLYTICS_ADMIN_PASSWORD` in
   `.env`. With no password set, nothing is created and the API log says so; set it and restart,
   or run `docker compose exec api python -m app.cli create-admin --email <email> --name <name>`.
2. **Department and its people.** Sign in as the Administrator → *Structure* → add the
   department → *People* → add the HOD (and Academic Head) with a password you give them.
3. **Faculty** accounts are created from the TLP reports as `<staff id>@srmist.edu.in`. They
   cannot sign in until the HOD or Administrator sets a password in *People* (or, if you prefer
   one starting password for all new faculty, set `FACULTY_DEFAULT_PASSWORD` in `.env`).
4. Everyone changes their own password in *Settings → Change password*; doing so signs them out
   of every device.

## 3. Upload TLP reports

Sign in as the HOD, Academic Head or Administrator (create the department first, step 2 above) → **Import TLP marks** → drop the reports
(Excel, CSV or TLP PDF; any number, one per section) → **Upload and validate** → **Confirm**.

From each file the platform reads and sets up, reusing anything that already exists:

| From the report | Becomes |
|---|---|
| `Academic Year : AY2025-26-EVEN` | the semester (the latest one is the current semester) |
| `21CSC201J(Data Structures and Algorithms)` | the course; its type (J = theory + lab) from the code |
| `handled by Dr. Kavya Iyer(902049)` | the faculty member, with a login `902049@srmist.edu.in` (password set in *People*), assigned to the class |
| `Test Name : FJ-II`, `Component Max. Mark: 15.00` | the assessment and its maximum |
| each `Reg. No` + `Name` row | the student (admission year from the register number) and their enrolment |
| `Obtained Mark` / `Absent` | the marks — written only when you confirm; Absent stays absent, never 0 |

**The section** is not printed on TLP reports, so it is taken, in this order, from:
1. where the file's students already are (an earlier upload placed them), else
2. the file name — `DSA_FJ-II_A1.xlsx`, `CSE sec B2.pdf` → A1, B2, else
3. you: the file shows **Section needed** with a box to type it.

Plain mark sheets (not TLP) and the class's own template (*Class → Assessments → Marks
template*) go through the same page from the class's **Upload** button. In **Review**, every
problem is listed: cell errors can be corrected or the row excluded (and included again), and a
column the system cannot match to an assessment can be mapped to one or ignored.

A file name that contradicts where its students already are is stopped with the reason.
Existing student names are never overwritten. **Discarding** a staged file also removes whatever
it set up that nothing else uses, so a wrong file leaves no trace.

`demo/tlp-uploads/` has four sample reports (fictional students, used by the automated
end-to-end check; nothing loads them into the application) to try this on a throwaway platform: two DSA sections, one DSA file without a section in its name, and an OS report for
the A1 students.

## 4. Run without Docker (development)

Prerequisites: Python 3.11+, Node.js 20.9+ (22 recommended), PostgreSQL 16.

```bash
# database (once)
docker compose up -d db                      # PostgreSQL 16 on localhost:55432

# backend
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env.example .env                         # adjust DATABASE_URL if needed
python -m alembic upgrade head
python -m app.cli bootstrap                     # the Administrator from ACADLYTICS_ADMIN_PASSWORD in .env
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm ci
npm run dev -- -p 3001                          # http://localhost:3001
```

The web app forwards `/api/v1/*` to `ACADLYTICS_API_URL` (default `http://localhost:8000`).

## 5. Checks

```bash
cd backend  && pytest && ruff check . && ruff format --check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build

# against a THROWAWAY stack only (they create data; docs/TESTING_AND_VERIFICATION.md)
python scripts/e2e_live.py    --web <web url> --api <api url> --admin-email <email> --admin-password <password>
python scripts/verify_live.py --api <api url> --admin-email <email> --admin-password <password>
cd frontend && E2E_WEB=<web url> E2E_API=<api url> E2E_ADMIN_EMAIL=<email> E2E_ADMIN_PASSWORD=<password> npm run test:e2e
```

| Suite | What it covers |
|---|---|
| Backend pytest (2,003 tests, real PostgreSQL) | auth and the throttle, the five-role scope and IDOR, TLP import in three formats, validation and atomicity, 1,120 analytics engine tests, reports, migrations |
| Frontend Vitest (23) | the HTTP client (token, one shared refresh, error envelope, cache) and display helpers (missing is never 0) |
| Playwright (15, real browser) | sign-in/out, role navigation, every page, CSV import with mapping and exclusion, faculty isolation, threshold visibility per role, report downloads, interventions, phone layout |
| `e2e_live.py` (130 checks) | the whole system over HTTP as the browser does it |
| `verify_live.py` | analytics, attention boundaries and reports recomputed independently from marks it enters itself |

Results of the last full run: [`docs/TESTING_AND_VERIFICATION.md`](docs/TESTING_AND_VERIFICATION.md).

## 6. How it works

**Authentication.** The browser never holds a refresh token. `POST /api/session/login` (a
Next.js route) calls the API and stores the rotating refresh token in an httpOnly,
SameSite=Strict cookie scoped to `/api/session`; the 15-minute access token lives in memory and is
renewed silently. `GET /api/v1/me/workspace` returns the user's role, department, courses
coordinated, classes taught, terms and capabilities; the UI is built from that answer.

**TLP ingestion** (`backend/app/modules/imports/`): SRM TLP5 reports as `.xlsx`, `.csv` or text
PDF (parsed line by line, strictly; a scanned or foreign PDF is refused, never guessed). The title
block (test name, academic year, component maximum, course, faculty id) sets up whatever does
not exist yet (`imports/provision.py`), and with the summary block (strength, absentees,
ranges) it is **checked** against the platform: a maximum that disagrees with the assessment,
marks above it, a % that does not match, or a truncated file block the import. Every file goes
through the same stage → preview → fix/exclude → atomic confirm pipeline, with audit.

**Analytics** (`backend/app/modules/analytics/`): a deterministic engine per class. Every class's
result is materialised in `offering_summaries` (refreshed in the same transaction as any mark
change, and checked by fingerprint on read), and `backend/app/modules/overview/` pools those for a
section, course, faculty member, coordinator, department or the institution with the engine's own
functions — so a department average is the same definition over more students, the dashboard and
the report come from one object, and no number is computed twice in two ways.

**Sign-in protection.** Ten wrong passwords for one account within 15 minutes and that account
is refused (429) until the window passes. Passwords are Argon2id; there are no built-in passwords.

**Semantics that never bend:** absent, exempt and missing are never zero; pass % is over students
with a result (absence is reported as completion); trends need enough assessments or say
"insufficient data"; attention is seven explained rules, not a score; intervention outcomes are
observations, never causes.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Web shows "The ACADLYTICS server is not reachable" | The API is still starting or failed: `docker compose logs api`. |
| `port is already allocated` | Something else uses 55432/8000/3001: set `POSTGRES_PORT`, `API_PORT` or `WEB_PORT` in `.env`. |
| Nobody can sign in on a new platform | `ACADLYTICS_ADMIN_PASSWORD` was empty at first start: set it in `.env` and `docker compose up -d`, or use `create-admin` (section 2). |
| A faculty member cannot sign in | Their account came from a report and has no password yet: set one in *People*. |
| Build fails with `No matching distribution found`, `short read` or `unexpected EOF` | The network dropped during a download (pip and npm already retry). Run `docker compose build` again; finished layers are cached. |
| A file shows **Section needed** | TLP reports do not name the section: type it in the box, or name the file with it (`…_A1.xlsx`). |
| "The file name says section A2, but … are already in section A1" | The file is probably mislabelled; rename it, or type the right section. |
| Need fictional data for development | Never loaded automatically. On an **empty, throwaway** database only: `docker compose exec -e ACADLYTICS_DEMO_PASSWORD=<8+ chars> api python -m app.cli seed-demo` (refused in production and on a database that has data; do not mix with real reports). |
| "Too many failed sign-in attempts" | Ten wrong passwords for that account within 15 minutes. Wait, or have an Administrator/HOD set a new password in *People*. |
| Signed out on every refresh | You are on plain http with `NODE_ENV=production` outside Compose: set `ACADLYTICS_INSECURE_COOKIES=1` (local only). |
| Docker Hub pull errors ("HTTP response to HTTPS client") | Transient registry/proxy issue; run `docker compose up -d --build` again. |
| A PDF is rejected | Only SRM TLP-format text PDFs are read; upload the Excel/CSV export for other layouts. |

## 8. Deployment

Not deployed anywhere yet. `docker-compose.prod.yml` (on top of `docker-compose.yml`) is the
production configuration: it requires every secret, keeps PostgreSQL off the network, binds the
app to 127.0.0.1 behind an HTTPS reverse proxy and makes the session cookie Secure. What the host
must still provide (HTTPS, backups, a proxy rate limit, logs) and the go-live checklist are in
[`docs/DEPLOYMENT_READINESS.md`](docs/DEPLOYMENT_READINESS.md).

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /secure/acadlytics.env up -d --build
```

## 9. Limitations

Assessment-level marks only (no question/topic analytics); no prediction, ML or LLM output;
intervention outcomes are observations; no password-reset email; performance at institutional
scale has not been load-tested. Full list: [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

## 10. Repository

```
backend/            FastAPI app: modules/{auth,users,organization,students,assessments,
                    imports,analytics,attention,interventions,reports,overview,audit},
                    Alembic 0001–0008, 2,003 tests, constraints.txt (pinned versions)
frontend/           Next.js 16 app: app/(app)/* pages, components/, lib/api (typed
                    adapters), lib/auth; tests/ (Vitest), e2e/ (Playwright)
demo/tlp-uploads/   Sample TLP reports (fictional students) for the end-to-end check
scripts/            e2e_live.py, verify_live.py (live checks), load_test.py (read-only load test for staging)
docs/               Data model, import format, analytics spec, contracts, architecture
.github/            CI workflows, issue templates, pull request template
docker-compose.yml  db + api + web (local)
docker-compose.prod.yml  production overrides
.env.example        The tracked template for .env
```

Branches: `main` is the reviewed project, `backend` is the working branch for platform and
analytics changes, `frontend/*` for web app work.

| | |
|---|---|
| **Documentation index** | [`docs/README.md`](docs/README.md) |
| **Current state, audit and readiness** | [`docs/FINAL_ENGINEERING_AUDIT.md`](docs/FINAL_ENGINEERING_AUDIT.md) |
| **Contributing and local checks** | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| **Reporting a vulnerability** | [`SECURITY.md`](SECURITY.md) |
| **What was built, in order** | [`CHANGELOG.md`](CHANGELOG.md) |
| **Licence** | [MIT](LICENSE) |
