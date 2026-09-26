# ACADLYTICS — Backend

Academic Performance Intelligence Platform. This repository currently contains the
**Agent 1** backend: platform, PostgreSQL schema, authentication, academic data, and
the validated import pipeline. Analytics/intelligence (Agent 2) and the frontend live
outside this scope.

Stack: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pytest, Docker.

## Layout

```
backend/
  app/
    core/          settings
    db/            declarative base, engine/session, model registry
    api/v1.py      /api/v1 router aggregator
    modules/       one package per domain: router -> service -> repository
  alembic/         migrations
  tests/
docs/DECISIONS.md  design decisions and assumptions
docker-compose.yml PostgreSQL + API
```

## Run with Docker Compose

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

OpenAPI docs: http://localhost:8000/docs

## Run locally

Requires PostgreSQL 16 (for example `docker compose up -d db`).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Tests

Tests need a reachable PostgreSQL. They create and drop `acadlytics_test` (and a
scratch migration database), so the DB user needs `CREATEDB`
(the Compose user is a superuser).

```bash
cd backend
pytest
ruff check . && ruff format --check .
```

Override the test database with `TEST_DATABASE_URL`.

## Migrations

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```

A model change without a migration fails `tests/test_migrations.py`.
