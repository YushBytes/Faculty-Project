# ACADLYTICS

Academic Performance Intelligence Platform.

```
Academic data -> validated ingestion -> PostgreSQL -> deterministic analytics
  -> teacher intelligence -> actions/interventions -> outcome measurement -> reports
```

One application, in one repository:

```
/
├── backend/     FastAPI + SQLAlchemy + Alembic, the whole API and the analytics engine
├── frontend/    Next.js teacher-facing app
├── docs/        scope, contracts, data model, import format, analytics specification
├── docker-compose.yml
├── .env.example
└── .github/     CI
```

| Part | Built by | Scope |
|---|---|---|
| Data platform | Agent 1 | Auth, users, RBAC and faculty scope, departments/terms/courses/sections/offerings, students, assessments and results, Excel/CSV import pipeline, audit |
| Intelligence | Agent 2 | Analytics, attention/segmentation, interventions and outcomes, reports |
| Teacher UI | Agent 3 | `frontend/` — Next.js app the faculty member actually uses |

Backend stack: Python 3.11+ (developed on 3.12), FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16,
pytest, Docker. Frontend stack: Next.js 16, React 19, TypeScript 5, Tailwind 4, Recharts.

Work happens on `backend`; `main` receives reviewed merges. The `frontend/nachiketa-ui` branch is
the frontend's original history and was merged here — it is kept, not deleted.

## Status

| Phase | Built by | State |
|---|---|---|
| 1. Skeleton: config, DB session, Alembic, `/health`, Docker, test infra | Agent 1 | Done |
| 2. Users, Argon2 passwords, JWT access + rotating refresh tokens, RBAC | Agent 1 | Done |
| 3. Departments, terms, courses, sections, offerings, faculty scope | Agent 1 | Done |
| 4. Students, section history, enrolments, student bulk import | Agent 1 | Done |
| 5. Assessments, assessment-level results, settings, audit log, recompute hook | Agent 1 | Done |
| 6. Import pipeline (parse, validate, stage, preview, fix, confirm) | Agent 1 | Done |
| 7. Audit API, seed/demo data, analytics data contract, docs | Agent 1 | Done |

## One codebase, one branch

Agent 1 and Agent 2 build the **same application**: one FastAPI app, one PostgreSQL
database, one Alembic migration chain, one test suite. Both push to the **`backend`**
branch. `main` only receives reviewed merges from `backend`.

```
backend/
  app/
    core/            config, security, errors, pagination
    db/
      base.py, session.py, mixins.py
      models.py      every ORM model imported here (one list, both agents add to it)
    api/v1.py        every router registered here (one list, both agents add to it)
    modules/         one package per feature module, from both agents, side by side:
      auth/ users/ organization/ students/ assessments/ audit/ imports/   (done)
      analytics/ attention/ interventions/ reports/          Agent 2
  alembic/versions/  one linear migration chain
  tests/             one suite: test_<module>*.py, shared fixtures in conftest.py
  pyproject.toml     one dependency list
docker-compose.yml, .env.example, README.md
```

### Working rules

1. **Same structure for every module:** `models.py`, `schemas.py`, `repository.py`,
   `service.py`, `router.py`. Routers never touch the session; services own the
   transaction (one `commit()` per operation); repositories never commit.
2. **New module = new folder** under `app/modules/`, plus one line in `app/api/v1.py`
   (router) and one in `app/db/models.py` (models).
3. **Reuse, don't duplicate.** Analytics reads students, offerings, assessments and
   results through the existing services/repositories, so faculty scope and PII rules are
   enforced in one place. Protect endpoints with `CurrentUser` / `require_roles(...)` from
   `app.modules.auth.dependencies`. If a query you need is missing, add it to the owning
   module's repository rather than querying its tables from elsewhere.
   Anything tied to an offering must pass through `OfferingAccess` / `visible_offering_ids`
   (see "Access scope").
4. **Writes:** validate first, mutate after. Make the change inside
   `with write_guard(session, conflict=..., in_use=...)` (from `app.db.repository`): it runs
   in a SAVEPOINT and turns unique / foreign-key / check violations into 409 / 409 / 422
   without breaking the session.
5. **Migrations:** `git pull`, `alembic upgrade head`, then
   `alembic revision --autogenerate -m "..."` and rename the revision ID to the next number
   (`0003`, `0004`, ...). `tests/test_migrations.py` fails on two heads or on model/schema
   drift; if two heads appear after a pull, point the newer migration's `down_revision` at
   the other one.
6. **Before every push:** `git pull --rebase origin backend`, then `pytest` and
   `ruff check . && ruff format --check .` must pass.

## Run with Docker Compose

```bash
cp .env.example .env          # set JWT_SECRET_KEY to a long random value
docker compose up --build
docker compose exec api python -m app.cli seed-demo      # demo data (empty DB only), or:
docker compose exec api python -m app.cli create-admin --email admin@srmist.edu.in --name "Admin"
curl http://localhost:8000/health
```

API docs: http://localhost:8000/docs

## Run locally

Needs PostgreSQL 16 (for example `docker compose up -d db`).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env.example .env
alembic upgrade head
python -m app.cli seed-demo        # optional synthetic demo data (see docs/AGENT_2_ANALYTICS_CONTRACT.md §8)
python -m app.cli create-admin --email admin@srmist.edu.in --name "Admin"
uvicorn app.main:app --reload
```

`create-admin` reads the password from `ACADLYTICS_ADMIN_PASSWORD` or prompts for it.
`seed-demo` loads fictional users (`admin@acadlytics.dev`, `priya.nair@acadlytics.dev`, ...,
password `ACADLYTICS_DEMO_PASSWORD`, default `Demo@2026pass`), four offerings, 60 students and
results with known patterns. It refuses to run in production or on a non-empty database.

## Documentation

| Document | For |
|---|---|
| `docs/AGENT_2_ANALYTICS_CONTRACT.md` | how analytics reads data, the recompute hook, thresholds, seed patterns, scope rules — the Agent 1 → Agent 2 handoff |
| `docs/DATA_MODEL.md` | every table, constraint and migration |
| `docs/IMPORT_FORMAT.md` | spreadsheet layouts, value rules, every validation code |
| `docs/PROJECT_CONTEXT.md`, `docs/TEAM_OWNERSHIP.md` | scope, contracts, ownership (shared) |
| `http://localhost:8000/docs` | live OpenAPI |

## Tests and lint

Tests run against real PostgreSQL. They create and drop `acadlytics_test` and a scratch
migration database, so the DB user needs `CREATEDB` (the Compose user has it). Override
with `TEST_DATABASE_URL`.

```bash
cd backend
pytest                       # everything
pytest tests/test_auth_api.py   # one file
ruff check . && ruff format --check .
```

Shared fixtures in `tests/conftest.py`: `db_session` (rolled back after each test),
`client`, `make_user(role, ...)`, `admin` / `hod` / `faculty`, `auth_headers(user)`,
`login(client, email)`.

### Layers

| Where | What it covers |
|---|---|
| `tests/analytics/`, `tests/reports/` | the pure engine and report builders, against hand-computed fixtures; no database |
| `tests/test_<module>*.py` | one module's API and models: auth, RBAC, organisation, students, assessments, results, imports, audit |
| `tests/api/` | the analytics service and routers with the platform read stubbed |
| `tests/e2e/` | whole-system journeys over HTTP: login, import, recompute, analytics, attention, intervention, outcome, report, export — plus the integration invariant sweep (no NaN/Infinity, absent/missing/exempt are never zero, R1–R7 agree across engine, API, persistence and report) |
| `tests/security/` | authorization and IDOR across every offering-scoped route, hostile input, and upload validation |
| `tests/test_api_contract.py` | the OpenAPI document: every route documented, nothing internal published, attention not writable |
| `tests/test_schema_integrity.py` | the migrated schema itself: foreign keys and delete rules, the partial unique index, enum labels against their Python enums, constraints that actually reject bad rows |
| `tests/test_query_budget.py` | query **shape**: a read must not issue more SQL for a bigger cohort |

CI runs lint, the format check and the whole suite against a `postgres:16-alpine` service on
every push and pull request to `backend` and `main` (`.github/workflows/ci.yml`). It needs no
secrets: the service credentials are the documented defaults, so `tests/conftest.py` resolves
`TEST_DATABASE_URL` from its own fallback.

## API conventions

- Base path `/api/v1`; `GET /health` is unversioned (200 ok / 503 degraded, reports the
  migration revision).
- Auth: `Authorization: Bearer <access_token>`.
- IDs are UUIDs. Lists return `{items, total, limit, offset}` (`limit` 1-200, default 50).
- Every error uses one envelope; `details` carries field/row/cell items:

```json
{"error": {"code": "validation_error", "message": "Request validation failed.",
           "details": [{"loc": ["body", "email"], "message": "...", "code": "value_error"}]}}
```

Codes: `not_authenticated` 401, `permission_denied` 403, `not_found` 404, `conflict` 409,
`validation_error` / `business_rule_violation` 422.

## Authentication and roles

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login` | email + password -> access token (15 min) + refresh token (7 days) |
| `POST /api/v1/auth/refresh` | rotate: old refresh token revoked, new pair issued |
| `POST /api/v1/auth/logout` | revoke the session; always 204 |
| `GET /api/v1/auth/me` | current user |
| `/api/v1/users` | create, list, get, patch, `/deactivate`, `/activate` (ADMIN only) |

- Passwords: Argon2id, 8-128 characters. Wrong password, unknown email and inactive account
  all return the same 401.
- Refresh tokens are opaque and stored only as SHA-256. Replaying a rotated token revokes
  that whole session (theft detection); other sessions are unaffected.
- Every request re-reads the user: deactivation and role changes apply immediately, and the
  role in the JWT is never trusted for authorisation.
- Password reset by an admin and deactivation revoke all of that user's sessions.
- Roles: `ADMIN`, `HOD`, `FACULTY`. Use `require_roles(...)` / `CurrentUser` from
  `app.modules.auth.dependencies` in any router. Department scope for HOD and offering scope
  for FACULTY arrive in Phase 3.

## Academic structure and access scope

| Resource | Read | Write |
|---|---|---|
| `/departments`, `/terms` | any signed-in user | ADMIN |
| `/courses`, `/sections` | any signed-in user | ADMIN; HOD for their own department |
| `/offerings` | scoped (below) | ADMIN; HOD for courses of their department |
| `/offerings/{id}/faculty` | scoped | ADMIN; HOD for courses of their department |
| `/users` | ADMIN, HOD (look-up for assigning faculty) | ADMIN |

A **course offering** (course x term x section) is the unit of teaching and of data access.
Faculty are assigned to offerings; everything attached to an offering (students, assessments,
results, imports, analytics) inherits its scope:

| Role | Can view an offering when | Can administer it when |
|---|---|---|
| ADMIN | always | always |
| HOD | its course is in their department, or they teach it | its course is in their department |
| FACULTY | they are assigned to it | never |

Enforced server-side in `app/modules/organization/scope.py`:

- `OfferingAccess(session).get(user, offering_id, Access.VIEW | Access.ADMINISTER)` returns the
  offering, **404** if outside the user's scope (existence is not disclosed), **403** if visible
  but not administrable.
- `visible_offerings(user)` / `visible_offering_ids(user)` give a SQL condition / subquery to
  filter any query by scope. List endpoints use these, so filters can never widen scope.

### Students and enrolments

| Endpoint | Who |
|---|---|
| `GET /students`, `GET /students/{id}`, `GET /students/{id}/sections` | scoped (below) |
| `POST /students`, `PATCH`, `/deactivate`, `/activate` | ADMIN; HOD for their department |
| `POST /students/bulk` (JSON), `POST /students/import` (CSV/XLSX) | ADMIN; HOD for their department |
| `GET /offerings/{id}/students` (roster) | anyone who can view the offering |
| `POST /offerings/{id}/enrollments`, `/enrollments/from-section`, `DELETE /enrollments/{student_id}` | who can administer the offering |

Student records are PII. **FACULTY** see only students enrolled in their offerings; **HOD** see
their department's students plus students in offerings they can view; **ADMIN** see all.
Anything else is 404. Use `visible_students(user)` (`app/modules/students/service.py`) to filter.

- **Historical correctness:** results hang off an *enrolment* (student x offering). Moving a
  student to another section updates `current_section` and closes/opens a
  `student_section_history` entry; old enrolments and their results are never rewritten.
- **Dropping** an enrolment sets `status=DROPPED` and keeps the row. Rosters default to ACTIVE
  enrolments of active students (`include_dropped`, `include_inactive` to widen).
- **Bulk import** upserts by `register_number`, validates every row first and writes all rows or
  none. Errors are row/field level with the offending value; file imports report spreadsheet row
  numbers. `dry_run` validates without writing. Headers are matched flexibly
  (`Reg No` / `Register Number`, `Name`, `Dept`, `Batch`, `Section`, `Email`).

### Assessments and results

| Endpoint | Who |
|---|---|
| `GET/POST /offerings/{id}/assessments`, `GET/PATCH/DELETE /assessments/{id}` | anyone who can view the offering |
| `GET/PUT /assessments/{id}/results`, `DELETE /assessments/{id}/results/{student_id}` | anyone who can view the offering |
| `GET /offerings/{id}/results` (full results of an offering, for analytics) | anyone who can view the offering |
| `GET /departments/{id}/settings`; `PUT/DELETE .../settings/{key}` | any signed-in user; ADMIN or that department's HOD |
| `POST /admin/recompute?offering_id=` | ADMIN |

- **Assessments are rows** (`CT1`, `FT2`, ...; names unique per offering, case-insensitive),
  with `assessment_type`, `max_marks`, `weightage`, `sequence_no`, `is_published`. Total
  weightage above 100 is returned as a warning. `max_marks` is locked once results exist.
- **Results** are one row per `(student_id, assessment_id)` in `assessment_results`:
  `status` is `present | absent | exempt`, `score` is nullable with no default, and a database
  CHECK makes `score` present exactly when `status = present`, within `0..max_marks_snapshot`.
  **Missing** = no row. Absent, exempt and missing are never 0. Blank manual entries are
  rejected; an explicit `0` is a real score.
- `PUT .../results` is all-or-nothing with per-entry errors. New results need an ACTIVE
  enrolment; existing results of dropped students stay visible and editable.
- **Overwrites and deletions are audited** (`audit_logs`, old and new values, actor, offering).
- **Recompute hook (C4):** every results write calls `app.core.recompute.recompute(session,
  assessment_id)` inside the transaction, before commit. It is a no-op until the analytics
  layer installs its implementation with `set_recompute(fn)`; the hook must not commit, and an
  exception aborts the write.
- **Offering pass mark:** `course_offerings.pass_percent` (default 50) and `config` (JSON object
  of threshold overrides; the assigned faculty may edit it, the pass mark needs ADMIN/HOD).

### Audit log

`GET /audit-logs?entity=&entity_id=&action=&offering_id=&actor_id=&since=&until=` — ADMIN sees
everything; others see entries of offerings they can view. Written in the same transaction as the
change: result overwrites and deletions, import fixes and confirmations, user role / department /
password / activation changes, student (de)activation, settings changes.

### Marks import

```
POST /offerings/{id}/imports | POST /assessments/{id}/import   (multipart .xlsx/.csv, <= 5 MB)
  -> staged batch + preview            nothing written to results
GET  /imports/{id}/preview?only=all|issues|errors
POST /imports/{id}/fix | /exclude | /mapping                   each returns the revalidated preview
POST /imports/{id}/confirm                                     one transaction
POST /imports/{id}/discard       GET /imports (history)        GET .../imports/template (.xlsx)
```

- Wide sheets (`Register No | Name | CT1 | CT2 ...`, headers like `CT1 (max 50)` accepted) and
  long sheets (`Register No | Assessment | Score | [Max] | [Percentage] | [Status]`) are
  detected automatically. Assessment columns are matched by name; unmatched or ambiguous
  columns are errors until mapped or ignored — never guessed.
- Cells are read as raw strings. Blank = **absent** (warning, never 0); `AB` `A` `-` = absent;
  `EX` = exempt; anything else non-numeric is an error. Turning a blank into `0` is an explicit,
  audited fix.
- Checks: file type (from bytes), missing/ambiguous register-number column, empty or duplicate
  headers, unknown / not enrolled / dropped students, duplicate student rows, conflicting identity
  (name belongs to another student) and name mismatch, unknown / duplicate / ambiguous assessment
  columns, max-marks mismatch, invalid numbers, too many decimals, score below 0 or above max,
  impossible percentage, invalid status, students missing from the file, results that will be
  overwritten, the same file already imported.
- **Confirm** revalidates against current data, refuses while any error remains, then writes
  results (with `import_batch_id` provenance), audit rows for overwrites, the batch state and the
  recompute hook in **one transaction** — proven by a test that crashes mid-confirm on real
  transactions and finds nothing written. Batches expire after 24 h; only the uploader or an
  offering administrator may change or confirm one.

Other rules: at most one current term (`/terms?is_current=true`); an HOD must belong to a
department; codes are stored upper-case; deleting anything still referenced returns 409.

## Design decisions

- **Modular monolith**, one package per domain, strict router/service/repository layers.
- **Sync SQLAlchemy 2.x + psycopg 3.** Workload is CRUD and batch imports; sync code is
  simpler to make transactional and to test.
- **PostgreSQL only, including tests.** Tests build the schema by running migrations
  (never `create_all`), and each test runs in a rolled-back transaction.
- **Fixed constraint naming convention**, so migrations and constraint errors are
  predictable.
- **Migration drift fails the build** (single head, full down/up round trip, models ==
  schema).
- **The API container runs `alembic upgrade head` on start.** Fine for one instance; move to
  a one-off job if the API is scaled out.
- **Refresh token in the JSON body**, not a cookie, so any client can use it; switching to an
  httpOnly cookie is a router-only change if the frontend wants it.
- **Uploads are read with openpyxl and the csv module, not pandas.** Cells come back as raw
  strings; each importer validates types explicitly. pandas' type inference turns `"007"` into
  `7` and blanks into `NaN`, which would break "bad data never silently becomes a number".
  Limits: 5 MB, 5000 rows, 200 columns; `.xlsx` and UTF-8 `.csv` (`,` `;` or tab) only, detected
  from the file bytes.
- **No login rate limiting yet** (no Redis by design). Add at the reverse proxy.
- **Access tokens stay valid until expiry (max 15 min) after logout;** deactivation still
  cuts them off immediately because every request re-reads the user.
