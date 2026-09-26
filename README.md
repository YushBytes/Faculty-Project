# ACADLYTICS

Academic Performance Intelligence Platform.

```
Academic data -> validated ingestion -> PostgreSQL -> deterministic analytics
  -> teacher intelligence -> actions/interventions -> outcome measurement -> reports
```

One repository, one API, one database. Two workstreams build it:

| Workstream | Owner | Scope |
|---|---|---|
| **Platform** | Agent 1 | Auth, users, RBAC and faculty scope, departments/terms/courses/sections/offerings, students, assessments and results, Excel/CSV import pipeline, audit |
| **Intelligence** | Agent 2 | Analytics, attention/segmentation, interventions and outcomes, reports |

Stack: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pytest, Docker.

## Status

| Phase | Workstream | State |
|---|---|---|
| 1. Skeleton: config, DB session, Alembic, `/health`, Docker, test infra | Platform | Done |
| 2. Users, Argon2 passwords, JWT access + rotating refresh tokens, RBAC | Platform | Done |
| 3. Departments, terms, courses, sections, offerings, faculty scope | Platform | Next |
| 4. Students | Platform | |
| 5. Assessments and assessment-level results | Platform | |
| 6. Import pipeline (parse, validate, stage, preview, fix, confirm) | Platform | |
| 7. Audit, seed data, analytics data contract | Platform | |

## Repository layout and ownership

Each workstream owns its own files. Shared files are few and each has one rule.

```
backend/
  app/
    core/                      SHARED  config, security, errors, pagination
    db/
      base.py, session.py,     SHARED
      mixins.py, models.py
      models_platform.py       Agent 1 registers its ORM models here
      models_intelligence.py   Agent 2 registers its ORM models here
    api/
      v1.py                    SHARED  mounts both router lists; no edits needed
      routes_platform.py       Agent 1 registers its routers here
      routes_intelligence.py   Agent 2 registers its routers here
    modules/                   Agent 1  one package per domain module
    intelligence/              Agent 2  one package per domain module
  alembic/versions/            SHARED  one linear chain (rules below)
  tests/
    conftest.py                SHARED  DB fixtures, user factory, auth helpers
    platform/                  Agent 1 tests
    intelligence/              Agent 2 tests
  pyproject.toml               SHARED  add deps under your workstream's comment
docker-compose.yml, .env.example, README.md   SHARED
```

### Rules that prevent clashes

1. **Stay in your own folders.** Agent 1: `app/modules/`, `tests/platform/`. Agent 2:
   `app/intelligence/`, `tests/intelligence/`. Register routers and models only in your
   own `routes_*.py` / `models_*.py`.
2. **Every module has the same layers:** `router.py -> service.py -> repository.py`, plus
   `models.py` and `schemas.py`. Routers never touch the session; services own the
   transaction (`commit()` once per operation); repositories never commit.
3. **Migrations are one linear chain.** Before creating one, `git pull` and
   `alembic upgrade head`, then `alembic revision --autogenerate`. Revision IDs:
   Agent 1 `0001, 0002, ...`, Agent 2 `i0001, i0002, ...`, filename
   `YYYYMMDD_<rev>_<slug>.py`. `tests/platform/test_migrations.py` fails if there are two
   heads or if models and migrations drift; if two heads appear, the later migration
   updates its `down_revision` to the other head.
4. **Intelligence reads academic data through platform services/repositories**, never by
   ad-hoc queries on platform tables, so faculty scope and PII rules stay in one place.
   Needed data that is missing is requested as a platform endpoint/service method.
5. **Shared files** (`core/`, `conftest.py`, `pyproject.toml`, `README.md`) take small,
   additive edits only; pull right before editing them.
6. `git pull --rebase` before every push. Line endings are normalised to LF via
   `.gitattributes`.

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
pytest tests/platform        # one workstream
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
