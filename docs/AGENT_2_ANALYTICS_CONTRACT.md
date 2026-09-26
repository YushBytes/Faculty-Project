# ACADLYTICS — Agent 2 Analytics Contract

What the platform (Agent 1) guarantees to the intelligence layer (Agent 2), and how to use it.
Companion documents: `docs/PROJECT_CONTEXT.md` (contracts C1–C12, requests D1–D11),
`docs/DATA_MODEL.md`, `docs/IMPORT_FORMAT.md`.

## 1. Status of your requests

| Id | Request | Status | Where |
|---|---|---|---|
| D1 | assessments: max_marks, weightage, sequence_no, date, type, is_published | delivered | `assessments` |
| D2 | results: nullable score + status enum | delivered | `assessment_results` (DECISION-1 shape) |
| D3 | offerings: pass_percent + config JSONB | delivered | `course_offerings.pass_percent`, `.config` |
| D4 | department settings table | delivered | `settings`, `SettingsService` |
| D5 | interventions + intervention_students | **yours** — per TEAM_OWNERSHIP §2 you own intelligence models and their migration (next id `0007`) | — |
| D6 | attention_flags | **yours**, same as D5 | — |
| D7 | recompute inside confirm and after results writes | delivered | `app/core/recompute.py` (§4) |
| D8 | cohort + results read | delivered | `OfferingResultsService` (§2) |
| D9 | indexes | delivered for platform tables: `assessment_results(assessment_id)`, PK prefix `(student_id)`, unique `assessments(offering_id, sequence_no)`; `attention_flags(offering_id, status)` is yours | — |
| D10 | audit rows on overwrite | delivered | `audit_logs` (§6) |
| D11 | seed data with C11 patterns | delivered | `python -m app.cli seed-demo` (§8) |
| U1 | recompute signature | agreed: `recompute(session, assessment_id) -> None` | §4 |
| C1 | enums | kept beside their models (no `core/enums.py`) | §7 |
| C5 | threshold storage | offering `config` + department `settings`; resolution order is yours | §5 |
| C6/C7/C8 | auth deps, error envelope, pagination | delivered | README "API conventions" |

## 2. Reading academic data (C3 / D8)

One call returns everything an offering-level analytic needs:

```python
from app.modules.assessments.service import OfferingResultsService

data = OfferingResultsService(session).for_user(
    offering_id, actor=user,          # 404 NotFoundError unless user can VIEW the offering
    published_only=True,              # default: unpublished assessments are left out
    include_dropped=False,            # default: ACTIVE enrolments of active students only
)
# In the recompute hook (no user): OfferingResultsService(session).unscoped(offering_id)
# NEVER call unscoped() with an id taken from a request.
```

HTTP equivalent: `GET /api/v1/offerings/{id}/results?published_only=true&include_dropped=false`.

`OfferingResults` (Pydantic, `app/modules/assessments/schemas.py`):

```json
{
  "offering": {"id": "…", "course_code": "21CSC201J", "section_name": "A1", "term_code": "2026-ODD",
               "pass_percent": 50.0, "config": {"TREND_DELTA": 4}, "department_id": "…"},
  "assessments": [
    {"id": "…", "offering_id": "…", "name": "CT1", "assessment_type": "CT",
     "assessment_date": "2026-08-20", "max_marks": 50.0, "weightage": 15.0,
     "sequence_no": 1, "is_published": true, "created_at": "…", "updated_at": "…"}
  ],
  "students": [
    {"id": "…", "register_number": "RA2511003010002", "full_name": "…",
     "enrollment_status": "ACTIVE", "is_active": true}
  ],
  "results": [
    {"student_id": "…", "assessment_id": "…", "status": "present",
     "score": 32.5, "max_marks_snapshot": 50.0, "percentage": 65.0},
    {"student_id": "…", "assessment_id": "…", "status": "absent",
     "score": null, "max_marks_snapshot": 50.0, "percentage": null}
  ]
}
```

- `assessments` are ordered by `sequence_no` (use it for trends); `students` by register number.
- `results` holds **stored rows only**, and only for students in `students`.
- In Python the numeric fields are `Decimal` (exact); over HTTP they are JSON numbers.
- `percentage = 100 × score / max_marks_snapshot`, rounded half-up to 2 dp, `null` unless present.
  It is provided for convenience; analytics may recompute from `score` and `max_marks_snapshot`.

Other reads you may use (all enforce scope when given a user):

| Need | Call |
|---|---|
| one offering (404 out of scope) | `OfferingAccess(session).get(user, offering_id, Access.VIEW)` |
| filter any query by scope | `visible_offerings(user)` (SQL condition), `visible_offering_ids(user)` (subquery) — `app/modules/organization/scope.py` |
| students a user may see | `visible_students(user)` — `app/modules/students/service.py` |
| assessments of an offering + counts | `AssessmentService(session).list(offering_id, actor=user)` |
| one assessment (404 out of scope) | `AssessmentService(session).get(assessment_id, actor=user)` |
| grid for one assessment | `AssessmentService(session).results_grid(assessment_id, actor=user)` |
| department settings | `SettingsService(session).as_dict(department_id)` |
| offerings a user teaches | `GET /api/v1/offerings?faculty_id=` or `visible_offerings` |

If you need a query that does not exist, ask for a repository/service method (TEAM_OWNERSHIP §4)
rather than querying platform tables directly.

## 3. Missing-data semantics (C2) — what each state looks like

| State | In `results` | Meaning for analytics |
|---|---|---|
| present | row, `score` not null | include |
| absent | row, `status="absent"`, `score` null | not completed; never 0 |
| exempt | row, `status="exempt"`, `score` null | exclude from the denominator |
| missing | **no row** for (student, assessment) | not completed; never 0 |
| unpublished assessment | not in `assessments` (default) | ignore |

Guarantees you can rely on:

- The database rejects a present row without a score and an absent/exempt row with one, and any
  score outside `0..max_marks_snapshot`. A 0 is only ever a real, deliberately entered 0.
- `max_marks` of an assessment cannot change once it has results.
- Blank upload cells become `absent` (with a warning to the faculty), never 0; manual API entries
  cannot be blank.
- Results of a student who later **dropped** stay stored; with `include_dropped=False` they are not
  in the cohort and their rows are not returned. `include_dropped=True` returns every enrolled
  student (including inactive ones) with `enrollment_status` / `is_active` so you can decide.
- A student's section can change; results never move with it.
- Weightages are whatever faculty entered: they may not sum to 100 (the assessment list API warns
  above 100). Renormalising over completed assessments is analytics' job.
- The platform never decides "insufficient data" — it returns the rows; the C10 shape is yours.

Edge cases present in real use and in the seed: an offering with no assessments or no students
(empty lists), a student with a single result, all-absent assessments, exempt rows, a cohort of 4.

## 4. The recompute hook (C4 / D7 / U1)

```python
# app/core/recompute.py
recompute(session: Session, assessment_id: uuid.UUID) -> None
set_recompute(fn)        # install your implementation (call once at import time)
reset_recompute()        # back to the no-op (tests)
```

Called **inside the writer's transaction, after the results are flushed and before commit**, once
per changed assessment, by:

- `PUT /assessments/{id}/results` (only when something changed),
- `DELETE /assessments/{id}/results/{student_id}`,
- `POST /imports/{id}/confirm` (once per assessment written),
- `POST /admin/recompute?offering_id=` (every assessment of the offering; ADMIN),
- the demo seed.

Rules: use the given `session`; **never commit or roll back** in the hook; read through
`OfferingResultsService(session).unscoped(...)` (the new rows are visible). If the hook raises, the
whole write is rolled back (tested on real transactions in `tests/test_import_atomicity.py`), so a
bug in analytics cannot leave results and flags out of step.

Install it where your module is imported, e.g. at the bottom of
`app/modules/analytics/recompute.py`, and import that module from your router module so it is loaded
whenever the app starts:

```python
from app.core.recompute import set_recompute
set_recompute(recompute_assessment)
```

Scripts that do not import the API (`app/cli.py`) load `app.db.models` only — if your hook must
run there too, import it from your models module as well.

## 5. Thresholds (C5)

- `course_offerings.config` — JSON object of per-offering overrides. `PATCH /offerings/{id}`
  with `{"config": {...}}` replaces it; the assigned faculty may do this (the pass mark itself
  needs ADMIN/HOD). Default `{}`.
- `course_offerings.pass_percent` — NUMERIC 0–100, default 50.
- `settings` — department key → any JSON value. API: `GET /departments/{id}/settings`,
  `PUT /departments/{id}/settings/{key}` `{"value": …}`, `DELETE …/{key}` (ADMIN or that
  department's HOD). Service: `SettingsService(session).as_dict(department_id)`.
- Key names, types, defaults and the resolution order are yours; the platform stores and audits.

## 6. Import metadata and history (C12)

- Each result carries `source` (`manual` / `import`), `import_batch_id` (the batch that last wrote
  it), `recorded_by_id`, `recorded_at`, `updated_at`.
- `GET /api/v1/imports` (scoped history) and `GET /api/v1/imports/{id}` give file name, sha256,
  format, summary, uploader, committed_at.
- Every overwrite or deletion of a result writes `audit_logs` with the old and new value
  (`entity="assessment_result"`, `entity_id="<assessment_id>:<student_id>"`, `offering_id`).
  `GET /api/v1/audit-logs?entity=assessment_result&offering_id=…` lists them (scoped).
  Outcome measurement must treat the current row as the truth and the audit log as history.

## 7. Enums (C1)

| Enum | Import from | Values |
|---|---|---|
| `Role` | `app.modules.users.models` | ADMIN, HOD, FACULTY |
| `AssessmentType` | `app.modules.assessments.models` | CT, FT, QUIZ, ASSIGNMENT, LAB, INTERNAL, OTHER |
| `ResultStatus` | `app.modules.assessments.models` | present, absent, exempt |
| `EnrollmentStatus` | `app.modules.students.models` | ACTIVE, DROPPED |

Import them; never redefine them. Your enums live in your modules.

## 8. Seed data (C11)

`python -m app.cli seed-demo` on an empty database (refused in production and on non-empty
databases). Password: `ACADLYTICS_DEMO_PASSWORD` (default `Demo@2026pass`). Fictional people,
`@acadlytics.dev` emails.

- Accounts: `admin@`, `hod.cse@`, `priya.nair@` (DSA-A1, OS-C1), `arjun.mehta@` (DSA-B1, OS-A1),
  `kavya.reddy@` (no offerings).
- One department (CSE), current term 2026-ODD, courses 21CSC201J (DSA) and 21CSC202J (OS),
  sections A1 (30), B1 (26), C1 (4). Four offerings, pass mark 50. Each has CT1, CT2, CT3
  (published, max 50) and FT1 (unpublished, max 100, no results).

Patterns in **21CSC201J / A1** (percentages CT1, CT2, CT3):

| Register no | Pattern | Values |
|---|---|---|
| RA2511003010001 | high performer | 90, 92, 88 |
| RA2511003010002 | steady decline | 78, 65, 52 |
| RA2511003010003 | sharp drop on latest | 80, 82, 40 |
| RA2511003010004 | improving | 40, 55, 72 |
| RA2511003010005 | persistently low | 30, 28, 34 |
| RA2511003010006–08 | borderline cluster around 50 | 48/52/50, 46/54/51, 52/49/47 |
| RA2511003010009 | absent on CT2 | 70, absent, 68 |
| RA2511003010010 | exempt on CT2 | 60, exempt, 62 |
| RA2511003010011 | single assessment | 65, missing, missing |
| RA2511003010012 | volatile | 90, 35, 85 |

Also: 21CSC202J / C1 has a cohort of 4; one B1 student dropped the course but keeps results; one
B1 student is inactive. Other students are deterministic random (seed 2026). `tests/test_seed.py`
asserts every pattern, so they stay stable.

## 9. Authorization expectations (C6)

- Every analytics route takes `CurrentUser` (or `require_roles(...)`) from
  `app.modules.auth.dependencies`. Roles are re-read from the database on each request.
- Offering-level analytics call `OfferingAccess(...).get(user, offering_id, Access.VIEW)` first:
  out of scope is **404**, never 403, so existence is not disclosed.
- Student-level analytics also check the student is visible (`visible_students(user)`), and
  restrict to offerings in `visible_offering_ids(user)`.
- Cross-offering lists (dashboards) filter with `visible_offerings(user)`; query filters must
  never widen scope.

## 10. Working in the shared codebase

```bash
git pull --rebase origin backend
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
docker compose up -d db                               # or any PostgreSQL 16
alembic upgrade head
python -m app.cli seed-demo
uvicorn app.main:app --reload                         # http://localhost:8000/docs
pytest && ruff check . && ruff format --check .
```

- Your modules: `app/modules/analytics/`, `attention/`, `interventions/`, `reports/`, each with
  `models.py, schemas.py, repository.py, service.py, router.py`; register routers in
  `app/api/v1.py` and models in `app/db/models.py` (one additive line each).
- Your migrations continue the single chain: next id `0007`, `down_revision = '0006'`.
- Useful fixtures in `tests/conftest.py`: `db_session`, `client`, `make_user`, `admin` / `hod` /
  `faculty`, `auth_headers(user)`, `cse` / `ece`, `term`, `org` (course / section / offering
  factory), `cse_offering`, `make_student(department, section, enroll_in=[...])`,
  `make_assessment(offering, name, max_marks=..., published=...)`. Seeded data:
  `seed_demo(db_session, password=...)` from `app.seed`.
- Error envelope: raise `NotFoundError`, `PermissionDeniedError`, `BusinessRuleError`, … from
  `app.core.errors`. Pagination: `Page[T]` and `page_params` from `app.core.pagination`.
