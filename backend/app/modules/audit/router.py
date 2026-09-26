import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.audit.models import AuditLog
from app.modules.auth.dependencies import CurrentUser
from app.modules.organization.scope import visible_offering_ids
from app.modules.users.models import Role, User


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    entity: str
    entity_id: str
    action: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    offering_id: uuid.UUID | None
    created_at: datetime


class AuditReader:
    """Read side of the audit log (the write side is app.modules.audit.service)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list(
        self,
        page: PageParams,
        *,
        actor: User,
        entity: str | None,
        entity_id: str | None,
        action: str | None,
        offering_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Page[AuditLogRead]:
        query = select(AuditLog)
        if actor.role is not Role.ADMIN:
            # Non-admins see the history of offerings they can view, nothing else.
            query = query.where(AuditLog.offering_id.in_(visible_offering_ids(actor)))
        for column, value in (
            (AuditLog.entity, entity),
            (AuditLog.entity_id, entity_id),
            (AuditLog.action, action),
            (AuditLog.offering_id, offering_id),
            (AuditLog.actor_id, actor_id),
        ):
            if value is not None:
                query = query.where(column == value)
        if since is not None:
            query = query.where(AuditLog.created_at >= since)
        if until is not None:
            query = query.where(AuditLog.created_at < until)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id)
            .limit(page.limit)
            .offset(page.offset)
        )
        return Page[AuditLogRead](
            items=[AuditLogRead.model_validate(r) for r in rows], total=total, **page.model_dump()
        )


router = APIRouter(
    prefix="/audit-logs",
    tags=["audit"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.get(
    "",
    response_model=Page[AuditLogRead],
    description="Newest first. ADMIN sees everything; others see entries of offerings they "
    "can view (result overwrites/deletions, import fixes and confirmations).",
)
def list_audit_logs(
    actor: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[PageParams, Depends(page_params)],
    entity: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=128)] = None,
    action: Annotated[str | None, Query(max_length=32)] = None,
    offering_id: Annotated[uuid.UUID | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[AuditLogRead]:
    return AuditReader(db).list(
        page,
        actor=actor,
        entity=entity,
        entity_id=entity_id,
        action=action,
        offering_id=offering_id,
        actor_id=actor_id,
        since=since,
        until=until,
    )


ROUTERS = [router]
