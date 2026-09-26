import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Environment, Settings


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings(database_url="sqlite:///./local.db")


def test_rejects_postgres_url_without_psycopg_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://u:p@localhost/db")


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("JWT_SECRET_KEY", "p" * 48)

    settings = Settings(_env_file=None)

    assert settings.app_env is Environment.PRODUCTION
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.api_v1_prefix == "/api/v1"


def test_production_refuses_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="unique secret in production"):
        Settings(_env_file=None, app_env="production", jwt_secret_key=DEV_JWT_SECRET)


def test_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(_env_file=None, jwt_secret_key="short")


def test_rejects_asymmetric_or_none_jwt_algorithm() -> None:
    for algorithm in ("none", "RS256"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, jwt_algorithm=algorithm)
