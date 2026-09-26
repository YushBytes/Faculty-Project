from sqlalchemy import text
from sqlalchemy.orm import Session


class SystemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ping(self) -> None:
        """Round-trip to the database; raises SQLAlchemyError if unreachable."""
        self._session.execute(text("SELECT 1"))

    def current_migration_revision(self) -> str | None:
        """Alembic revision the database is at, or None if migrations never ran."""
        exists = self._session.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
        if not exists:
            return None
        return self._session.execute(text("SELECT version_num FROM alembic_version")).scalar()
