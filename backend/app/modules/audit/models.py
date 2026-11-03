"""Append-only change history (contract C12).

Services call ``AuditService.record(...)`` inside their own transaction; the audit row
commits or rolls back together with the change it describes. Nothing here commits.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(None, "entity", "entity_id"),
        Index(None, "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    entity: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. assessment_result
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # create/update/delete/...
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Offering the change belongs to, when there is one (for scoped history queries).
    offering_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
