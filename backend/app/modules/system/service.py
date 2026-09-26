import logging

from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.modules.system.repository import SystemRepository
from app.modules.system.schemas import HealthResponse

logger = logging.getLogger(__name__)


class SystemService:
    def __init__(self, repository: SystemRepository) -> None:
        self._repository = repository

    def health(self) -> HealthResponse:
        try:
            self._repository.ping()
            revision = self._repository.current_migration_revision()
        except SQLAlchemyError:
            logger.exception("Health check: database unreachable")
            return HealthResponse(
                status="degraded",
                database="unavailable",
                migration_revision=None,
                version=__version__,
            )
        return HealthResponse(
            status="ok", database="ok", migration_revision=revision, version=__version__
        )
