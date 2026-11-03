# Contributing to ACADLYTICS

Thanks for working on this. This page covers the layout of the repository, how to get a working
environment, and the checks a change has to pass.

## Repository layout

```
backend/     FastAPI service: app/modules/*, Alembic migrations, the test suite
frontend/    Next.js web app: app/(app)/* pages, components/, lib/api, lib/auth
demo/        Sample TLP reports (fictional students) for trying the import
docs/        Data model, import format, analytics specification, architecture
.github/     CI workflows and issue/PR templates
```

Branches:

- `main` — the reviewed project. Protected by CI.
- `backend` — the working branch for platform and analytics changes.
- `frontend/*` — working branches for web app work.

## Getting set up

The fast path is Docker, which needs nothing but Docker Desktop or Docker Engine with Compose v2:

```bash
cp .env.example .env
docker compose up -d --build
```

For development against the services directly, see [§4 of the README](README.md#4-run-without-docker-development).

## Checks a change must pass

Run these before opening a pull request. CI runs the same commands.

```bash
# backend
cd backend
pytest                       # the full suite, against real PostgreSQL
ruff check .
ruff format --check .

# frontend
cd frontend
npm run lint
npm run build
```

The backend suite does not run on SQLite. It builds its schema by running Alembic against a real
PostgreSQL 16 database and runs each test inside a rolled-back transaction, so a local PostgreSQL
is a requirement. The database user needs `CREATEDB`: the suite creates and drops
`acadlytics_test` plus a scratch migration database.

## Conventions

**Migrations.** Schema changes go in an Alembic revision under `backend/alembic/versions/`, named
in sequence with the existing files. Never edit a migration that has been merged; add a new one.

**Analytics semantics.** The rules in
[`docs/ANALYTICS_SPEC.md`](docs/ANALYTICS_SPEC.md) are not negotiable in a patch: absent, exempt
and missing are never zero; pass percentage is over students who have a result; a trend without
enough assessments reports insufficient data rather than guessing; attention is explained rules,
never a score; intervention outcomes are observations, never causes. A change that bends one of
these needs the spec changed first, in its own commit.

**One engine.** Aggregate views (section, course, faculty, coordinator, department, institution)
must call the class engine's own functions over a wider set of students. Do not add a second
formula for a wider scope — that is how a dashboard and a report start to disagree.

**Scope.** Access rules live in `backend/app/modules/organization/scope.py` and
`modules/users/service.py` and are enforced in the API. An out-of-scope id returns 404, never a
partial answer. The web app only mirrors a rule it cannot bypass, so a UI-only check is not a
check.

**Imports.** Every uploaded file goes stage → preview → fix or exclude → atomic confirm, with an
audit entry. A discard must also remove whatever the staged file set up that nothing else uses.

## Commits and pull requests

Write commit subjects in the imperative, prefixed by area where it helps
(`imports:`, `analytics:`, `web:`, `docs:`, `chore:`). Describe what changed and why; the diff
already says how.

A pull request should say what it changes, how it was verified, and anything a reviewer should
look at closely. Use the template that appears when you open one.

## Reporting a problem

Open an issue using the bug report template. For anything security-related, read
[SECURITY.md](SECURITY.md) first — please do not open a public issue for a vulnerability.
