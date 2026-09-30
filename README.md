# ACADLYTICS

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

---

## 1. Run it (Docker — recommended)

Prerequisites: **Docker Desktop** (Windows/macOS) or Docker Engine + Compose v2. Nothing else.

```bash
git clone https://github.com/YushBytes/Faculty-Project.git
cd Faculty-Project
git checkout backend
docker compose up -d --build          # db + api + web
```

Open **http://localhost:3000**. The platform starts **empty**: no semesters, courses,
sections, students or marks. Everything comes from the TLP reports you upload.

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs (OpenAPI / Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Stop with `docker compose down` (data is kept in the `pgdata` volume).
`docker compose down -v` deletes the database; the next `up` starts empty again.

## 2. Sign-in accounts

On an empty database the API creates only the people who run the platform:

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@acadlytics.dev` | `Demo@2026pass` |
| HOD, Computer Science and Engineering | `hod.cse@acadlytics.dev` | `Demo@2026pass` |
| Academic Head, CSE | `academic.head@acadlytics.dev` | `Demo@2026pass` |
| **Faculty** — created from the reports | `<staff id>@srmist.edu.in` (e.g. `902049@srmist.edu.in`) | `Faculty@2026` |

Set `ACADLYTICS_INITIAL_PASSWORD` (and `FACULTY_DEFAULT_PASSWORD`) in `.env` to change the
initial passwords; production refuses to start without the first one. Course Coordinators are
appointed in the app (*Team & roles*) once their courses exist.

## 3. Upload TLP reports

Sign in as the HOD, Academic Head or Administrator → **Import TLP marks** → drop the reports
(Excel, CSV or TLP PDF; any number, one per section) → **Upload and validate** → **Confirm**.

From each file the platform reads and sets up, reusing anything that already exists:

| From the report | Becomes |
|---|---|
| `Academic Year : AY2025-26-EVEN` | the semester (the latest one is the current semester) |
| `21CSC201J(Data Structures and Algorithms)` | the course; its type (J = theory + lab) from the code |
| `handled by Dr. Kavya Iyer(902049)` | the faculty member, with a login `902049@srmist.edu.in`, assigned to the class |
| `Test Name : FJ-II`, `Component Max. Mark: 15.00` | the assessment and its maximum |
| each `Reg. No` + `Name` row | the student (admission year from the register number) and their enrolment |
| `Obtained Mark` / `Absent` | the marks — written only when you confirm; Absent stays absent, never 0 |

**The section** is not printed on TLP reports, so it is taken, in this order, from:
1. where the file's students already are (an earlier upload placed them), else
2. the file name — `DSA_FJ-II_A1.xlsx`, `CSE sec B2.pdf` → A1, B2, else
3. you: the file shows **Section needed** with a box to type it.

A file name that contradicts where its students already are is stopped with the reason.
Existing student names are never overwritten. **Discarding** a staged file also removes whatever
it set up that nothing else uses, so a wrong file leaves no trace.

`demo/tlp-uploads/` has four sample reports (fictional students) to try this on an empty
platform: two DSA sections, one DSA file without a section in its name, and an OS report for
the A1 students.

## 4. Run without Docker (development)

Prerequisites: Python 3.11+, Node.js 20.9+ (22 recommended), PostgreSQL 16.

```bash
# database (once)
createuser -s acadlytics --pwprompt          # password: acadlytics
createdb -O acadlytics acadlytics

# backend
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env.example .env                         # adjust DATABASE_URL if needed
alembic upgrade head
python -m app.cli bootstrap                     # the sign-in accounts (empty database only)
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm ci
npm run dev                                     # http://localhost:3000
```

The web app forwards `/api/v1/*` to `ACADLYTICS_API_URL` (default `http://localhost:8000`).

## 5. Checks

```bash
cd backend && pytest && ruff check . && ruff format --check .
cd frontend && npm run lint && npm run build
```

The backend suite (~1,900 tests) runs against real PostgreSQL: auth, the five-role scope and
IDOR checks, TLP import in all three formats, set-up from the reports, routing and title-block verification, aggregate
analytics consistency with the class engine, report downloads, migrations, seed.

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

**Semantics that never bend:** absent, exempt and missing are never zero; pass % is over students
with a result (absence is reported as completion); trends need enough assessments or say
"insufficient data"; attention is seven explained rules, not a score; intervention outcomes are
observations, never causes.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Web shows "The ACADLYTICS server is not reachable" | The API is still starting or failed: `docker compose logs api`. |
| `port is already allocated` | Something else uses 5432/8000/3000: set `POSTGRES_PORT`, `API_PORT` or `WEB_PORT` in `.env`. |
| Build fails with `No matching distribution found`, `short read` or `unexpected EOF` | The network dropped during a download (pip and npm already retry). Run `docker compose build` again; finished layers are cached. |
| A file shows **Section needed** | TLP reports do not name the section: type it in the box, or name the file with it (`…_A1.xlsx`). |
| "The file name says section A2, but … are already in section A1" | The file is probably mislabelled; rename it, or type the right section. |
| Want the old 97-section demo institution | `docker compose exec api python -m app.cli seed-demo` on an **empty** database (fictional data; do not mix with real reports). |
| Signed out on every refresh | You are on plain http with `NODE_ENV=production` outside Compose: set `ACADLYTICS_INSECURE_COOKIES=1` (local only). |
| Docker Hub pull errors ("HTTP response to HTTPS client") | Transient registry/proxy issue; run `docker compose up -d --build` again. |
| A PDF is rejected | Only SRM TLP-format text PDFs are read; upload the Excel/CSV export for other layouts. |

## 8. Repository

```
backend/    FastAPI app: modules/{auth,users,organization,students,assessments,imports,
            analytics,attention,interventions,reports,overview,audit}, Alembic 0001–0008, tests
frontend/   Next.js 16 app: app/(app)/* pages, components/, lib/api (typed adapters), lib/auth
demo/       sample TLP reports (fictional students) for trying uploads
docs/       data model, import format, analytics specification and contracts
```

Documentation: [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md),
[`docs/IMPORT_FORMAT.md`](docs/IMPORT_FORMAT.md), [`docs/ANALYTICS_SPEC.md`](docs/ANALYTICS_SPEC.md),
[`docs/AGENT_2_ANALYTICS_CONTRACT.md`](docs/AGENT_2_ANALYTICS_CONTRACT.md).
