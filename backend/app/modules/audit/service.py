import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)  # exact; never a float
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class AuditService:
    """Writes audit rows in the caller's transaction. Never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        actor_id: uuid.UUID | None,
        entity: str,
        entity_id: str | uuid.UUID,
        action: str,
        old: dict[str, Any] | None = None,
        new: dict[str, Any] | None = None,
        offering_id: uuid.UUID | None = None,
    ) -> AuditLog:
        row = AuditLog(
            actor_id=actor_id,
            entity=entity,
            entity_id=str(entity_id),
            action=action,
            old_value=_jsonable(old),
            new_value=_jsonable(new),
            offering_id=offering_id,
        )
        self._session.add(row)
        return row
