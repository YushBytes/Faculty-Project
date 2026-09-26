import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings(database_url="sqlite:///./local.db")


def test_rejects_postgres_url_without_psycopg_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://u:p@localhost/db")


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")

    settings = Settings(_env_file=None)

    assert settings.app_env is Environment.PRODUCTION
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.api_v1_prefix == "/api/v1"
