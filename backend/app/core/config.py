"""Application settings, loaded from environment variables (and an optional .env file)."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ACADLYTICS API"
    app_env: Environment = Environment.DEVELOPMENT
    api_v1_prefix: str = "/api/v1"

    database_url: str = Field(
        default="postgresql+psycopg://acadlytics:acadlytics@localhost:5432/acadlytics",
        description="SQLAlchemy URL. Must use the psycopg (v3) PostgreSQL driver.",
    )
    database_echo: bool = False

    @field_validator("database_url")
    @classmethod
    def _require_postgres_psycopg(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+psycopg://' "
                "(PostgreSQL is the only supported database)."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
