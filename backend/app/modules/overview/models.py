"""Materialised per-offering analytics and the report-generation history.

``offering_summaries`` holds, for each offering, the numbers the analytics engine produced
for it (class statistics, per-assessment statistics, the students' course scores, attention
counts). Higher levels — course, faculty, coordinator, department, institution — are
aggregated *from these rows*, so a department average and the class averages it is made of
come from the same engine run and can never disagree.

A row carries a ``fingerprint`` of the inputs it was computed from (results, assessments,
enrolments, thresholds). A read that finds the fingerprint out of date recomputes that
offering first, so a summary is never served stale, and the C4 recompute hook refreshes it
inside the write transaction that changed the results.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class OfferingSummary(Base):
    __tablename__ = "offering_summaries"

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="CASCADE"), primary_key=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class GeneratedReport(UUIDPrimaryKeyMixin, Base):
    """One report a user generated: what scope, which format, when. The file itself is not
    stored — re-downloading regenerates it from current data, and the history row records
    exactly which scope and period to regenerate."""

    __tablename__ = "generated_reports"
    __table_args__ = (Index(None, "generated_by_id", "created_at"),)

    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    export_format: Mapped[str] = mapped_column(String(8), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
