"""Application settings, loaded from environment variables (and an optional .env file)."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only acceptable outside production; production refuses to start with it.
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-0123456789abcdef"


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

    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    @field_validator("database_url")
    @classmethod
    def _require_postgres_psycopg(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+psycopg://' "
                "(PostgreSQL is the only supported database)."
            )
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def _only_hmac(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be one of HS256, HS384, HS512.")
        return value

    @model_validator(mode="after")
    def _secure_secret(self) -> "Settings":
        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters.")
        if self.app_env is Environment.PRODUCTION and self.jwt_secret_key == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a unique secret in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
