from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import create_app


def test_health_ok_reports_database_and_migration(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["migration_revision"] == "0001"
    assert body["version"]


def test_health_returns_503_when_database_unreachable() -> None:
    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )

    def unreachable_db() -> Iterator[Session]:
        session = Session(bind=dead_engine)
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = unreachable_db
    with TestClient(app) as client:
        response = client.get("/health")

    dead_engine.dispose()
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unavailable"


def test_openapi_exposes_health(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "HealthResponse" in schema["components"]["schemas"]
