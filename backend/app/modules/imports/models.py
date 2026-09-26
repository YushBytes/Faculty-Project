"""Import staging and history.

An ``ImportBatch`` holds an uploaded sheet exactly as parsed (raw strings), plus the
faculty's column-mapping overrides, cell fixes and row exclusions. Nothing is written to
``assessment_results`` until the batch is confirmed; confirmation is one transaction.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ImportStatus(StrEnum):
    PREVIEWED = "previewed"
    COMMITTED = "committed"
    DISCARDED = "discarded"


class ImportFormat(StrEnum):
    WIDE = "wide"  # one column per assessment
    LONG = "long"  # one row per (student, assessment)


def _values(enum: type[StrEnum]) -> list[str]:
    return [m.value for m in enum]


class ImportBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index(None, "offering_id", "created_at"),
        Index(None, "file_sha256"),
        CheckConstraint(
            "(status = 'committed') = (committed_at IS NOT NULL)", name="committed_at_matches"
        ),
    )

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="RESTRICT"), nullable=False
    )
    # Set when the import targets a single assessment (POST /assessments/{id}/import).
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="SET NULL")
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", values_callable=_values),
        nullable=False,
        default=ImportStatus.PREVIEWED,
        server_default=ImportStatus.PREVIEWED.value,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_format: Mapped[ImportFormat] = mapped_column(
        Enum(ImportFormat, name="import_format", values_callable=_values), nullable=False
    )
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    headers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # [{"row": <spreadsheet row>, "values": {header: raw string | null}}]
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    skipped_empty_rows: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    # header -> assessment id (str) or "ignore"; overrides automatic detection.
    column_mapping: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    # "row|column" -> {"value": raw | null, "original": raw | null, "by": user id, "at": iso}
    fixes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    excluded_rows: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    # Last computed validation summary (refreshed on every preview/fix; final at confirm).
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
