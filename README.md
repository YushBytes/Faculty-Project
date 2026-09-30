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
docker compose up -d --build          # db + api (runs migrations) + web
docker compose exec api python -m app.cli seed-demo   # ~2-3 minutes, once
```

Then open **http://localhost:3000** and sign in with a demo account (below).

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs (OpenAPI / Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Stop with `docker compose down` (data is kept in the `pgdata` volume);
`docker compose down -v` also deletes the database. To re-seed, run `down -v`, `up -d` and
`seed-demo` again — seed-demo only runs on an empty database.

## 2. Demo accounts (fictional)

Every account uses the password **`Demo@2026pass`**. All people, names, register numbers
(`RA2411999…`) and staff ids (`9xxxxx`) are generated; nothing is real.

| Role | Email |
|---|---|
| Administrator | `admin@acadlytics.dev` |
| HOD, Computer Science and Engineering | `hod.cse@acadlytics.dev` |
| Academic Head | `academic.head@acadlytics.dev` |
| Course Coordinator — Data Structures and Algorithms (21CSC201J) | `coord.dsa@acadlytics.dev` |
| Course Coordinator — Operating Systems (21CSC202J) | `coord.os@acadlytics.dev` |
| Course Coordinator — Advanced Programming Practice (21CSC203P) | `coord.app@acadlytics.dev` |
| Course Coordinator — Design Thinking and Methodology (21DCS201P) | `coord.dt@acadlytics.dev` |
| Course Coordinators — DAA (21CSC204J), DBMS (21CSC205P), odd semester | `coord.daa@…`, `coord.dbms@…` |
| Faculty | `faculty1@acadlytics.dev` … `faculty100@acadlytics.dev` |

### The demo institution

One department with the full hierarchy, **97 sections** (A1 … N6) of the 2024 batch,
**~4,100 students**, **106 teaching staff**, and AY 2025-26:

* **Odd semester (complete):** 21CSC204J DAA, 21CSC205P DBMS
* **Even semester (current, in progress):** 21CSC201J DSA, 21CSC202J OS, 21CSC203P APP,
  21DCS201P Design Thinking

Assessments follow the SRM scheme for each course type (joint: FJ-I, LLJ-I, FJ-II, FJ-III,
LLJ-II; project: FP-I, PBL-I…), with component maximum = contribution as on TLP reports. Sections
have deliberately different, reproducible profiles — high performing, average, borderline, high
failure, declining, improving, incomplete data, volatile — and DSA's FJ-II is a harder paper, so
the charts show real spikes and drops. DSA's FJ-II marks for 12 sections were imported through the
real TLP pipeline (so import history is genuine), and FJ-III is still missing for 37 sections —
that is what the upload demo fills in.

The section count is data, not code: add or remove sections under **Academic structure**, or run
`seed-demo --sections 20` for a smaller demo.

## 3. Demonstration flows

1. **Administrator** → Overview (institution) → *Departments* → CSE → *Courses* → a course →
   *Sections* → a class → *Reports* → PDF.
2. **HOD** → Overview: 97 sections, course/section/faculty comparisons, heat maps, attention →
   *Sections* (the 97-tile map) → *Faculty* → *Attention* → *Reports*.
3. **Academic Head** → *Coordinators* (portfolio, assign/replace a coordinator) → *Courses* →
   a course → *Faculty* tab → *Reports*.
4. **DSA Course Coordinator** → Overview (all 97 DSA sections) → *Faculty* comparison →
   *Import TLP marks* → drop **every file in `demo/tlp-uploads/`** at once:
   * 8 files (xlsx, csv and TLP pdf) route themselves to sections I5–J5 and to FJ-III → **Valid**
   * `*_wrong-max.pdf` → **Errors**: the report's component maximum is 20, FJ-III is out of 15
   * `*_needs-fix.xlsx` → **Errors**: one mark above the maximum → *Review* → type the corrected
     mark → *Apply* (audited) → it becomes valid
   * **Confirm** → marks are written, FJ-III is published, analytics recompute; the dashboard,
     heat map and attention change immediately → *Reports*.
5. **Faculty** (`faculty1@…`) → *My classes* → a class → *Marks*, *Assessments*, *Attention* →
   *Intervene* on a flagged student → *Interventions* → *Reports*.

All flows use one database. The real SRM FP-I PDF also parses (title block, 58 rows, summary),
but its students are not in the demo, so it is rejected with "none of the file's students is
enrolled" — the correct answer.

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
python -m app.cli seed-demo
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
IDOR checks, TLP import in all three formats, routing and title-block verification, aggregate
analytics consistency with the class engine, report downloads, migrations, seed.

## 6. How it works

**Authentication.** The browser never holds a refresh token. `POST /api/session/login` (a
Next.js route) calls the API and stores the rotating refresh token in an httpOnly,
SameSite=Strict cookie scoped to `/api/session`; the 15-minute access token lives in memory and is
renewed silently. `GET /api/v1/me/workspace` returns the user's role, department, courses
coordinated, classes taught, terms and capabilities; the UI is built from that answer.

**TLP ingestion** (`backend/app/modules/imports/`): SRM TLP5 reports as `.xlsx`, `.csv` or text
PDF (parsed line by line, strictly; a scanned or foreign PDF is refused, never guessed). The title
block (test name, academic year, component maximum, course, faculty id) and summary block
(strength, absentees, ranges) are kept and **checked** against the platform: wrong course,
semester, assessment or maximum, or a truncated file, block the import. Multi-file uploads route
each file to its section by the register numbers it contains. Every file goes through the same
stage → preview → fix/exclude → atomic confirm pipeline, with audit.

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
| `seed-demo` says the database already has users | It only seeds an empty database: `docker compose down -v`, `up -d`, seed again. |
| Signed out on every refresh | You are on plain http with `NODE_ENV=production` outside Compose: set `ACADLYTICS_INSECURE_COOKIES=1` (local only). |
| Docker Hub pull errors ("HTTP response to HTTPS client") | Transient registry/proxy issue; run `docker compose up -d --build` again. |
| A PDF is rejected | Only SRM TLP-format text PDFs are read; upload the Excel/CSV export for other layouts. |

## 8. Repository

```
backend/    FastAPI app: modules/{auth,users,organization,students,assessments,imports,
            analytics,attention,interventions,reports,overview,audit}, Alembic 0001–0008, tests
frontend/   Next.js 16 app: app/(app)/* pages, components/, lib/api (typed adapters), lib/auth
demo/       TLP upload demo files (generated by seed-demo; fictional)
docs/       data model, import format, analytics specification and contracts
```

Documentation: [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md),
[`docs/IMPORT_FORMAT.md`](docs/IMPORT_FORMAT.md), [`docs/ANALYTICS_SPEC.md`](docs/ANALYTICS_SPEC.md),
[`docs/AGENT_2_ANALYTICS_CONTRACT.md`](docs/AGENT_2_ANALYTICS_CONTRACT.md).
