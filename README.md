# ACADLYTICS

Academic Performance Intelligence Platform.

```
Academic data -> validated ingestion -> PostgreSQL -> deterministic analytics
  -> teacher intelligence -> actions/interventions -> outcome measurement -> reports
```

One application, built by two agents working in the same codebase on the `backend` branch:

| Part | Built by | Scope |
|---|---|---|
| Data platform | Agent 1 | Auth, users, RBAC and faculty scope, departments/terms/courses/sections/offerings, students, assessments and results, Excel/CSV import pipeline, audit |
| Intelligence | Agent 2 | Analytics, attention/segmentation, interventions and outcomes, reports |

Stack: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pytest, Docker.

## Status

| Phase | Built by | State |
|---|---|---|
| 1. Skeleton: config, DB session, Alembic, `/health`, Docker, test infra | Agent 1 | Done |
| 2. Users, Argon2 passwords, JWT access + rotating refresh tokens, RBAC | Agent 1 | Done |
| 3. Departments, terms, courses, sections, offerings, faculty scope | Agent 1 | Next |
| 4. Students | Agent 1 | |
| 5. Assessments and assessment-level results | Agent 1 | |
| 6. Import pipeline (parse, validate, stage, preview, fix, confirm) | Agent 1 | |
| 7. Audit, seed data, analytics data contract | Agent 1 | |

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
      auth/ users/                 (done)
      organization/ students/ assessments/ imports/ audit/   Agent 1
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
4. **Migrations:** `git pull`, `alembic upgrade head`, then
   `alembic revision --autogenerate -m "..."` and rename the revision ID to the next number
   (`0003`, `0004`, ...). `tests/test_migrations.py` fails on two heads or on model/schema
   drift; if two heads appear after a pull, point the newer migration's `down_revision` at
   the other one.
5. **Before every push:** `git pull --rebase origin backend`, then `pytest` and
   `ruff check . && ruff format --check .` must pass.

## Run with Docker Compose

```bash
cp .env.example .env          # set JWT_SECRET_KEY to a long random value
docker compose up --build
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
python -m app.cli create-admin --email admin@srmist.edu.in --name "Admin"
uvicorn app.main:app --reload
```

`create-admin` reads the password from `ACADLYTICS_ADMIN_PASSWORD` or prompts for it.

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
- **No login rate limiting yet** (no Redis by design). Add at the reverse proxy.
- **Access tokens stay valid until expiry (max 15 min) after logout;** deactivation still
  cuts them off immediately because every request re-reads the user.
