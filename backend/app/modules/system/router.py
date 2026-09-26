from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.system.repository import SystemRepository
from app.modules.system.schemas import HealthResponse
from app.modules.system.service import SystemService

router = APIRouter(tags=["system"])


def get_system_service(db: Annotated[Session, Depends(get_db)]) -> SystemService:
    return SystemService(SystemRepository(db))


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
    summary="Liveness and database readiness",
)
def health(
    response: Response, service: Annotated[SystemService, Depends(get_system_service)]
) -> HealthResponse:
    result = service.health()
    if result.database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
