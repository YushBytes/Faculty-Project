"""Students, their section history, and offering enrolments.

Historical correctness: results belong to an *enrolment* (student x offering), and an
offering belongs to the section the student was in at the time. Moving a student to a new
section changes ``current_section_id`` and appends to ``student_section_history``; existing
enrolments and their results are never rewritten.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.organization.models import Department, Section


class Student(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("register_number ~ '^[A-Z0-9]{5,20}$'", name="register_number_format"),
        CheckConstraint("email IS NULL OR email = lower(btrim(email))", name="email_normalised"),
        CheckConstraint("length(full_name) > 0", name="full_name_not_blank"),
        CheckConstraint("batch_year BETWEEN 2000 AND 2100", name="batch_year_range"),
    )

    register_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    batch_year: Mapped[int] = mapped_column(Integer, nullable=False)
    current_section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    department: Mapped[Department] = relationship(lazy="joined")
    current_section: Mapped[Section | None] = relationship(lazy="joined")


class StudentSectionHistory(UUIDPrimaryKeyMixin, Base):
    """Every section a student has belonged to; ``ended_at`` is NULL for the current one."""

    __tablename__ = "student_section_history"
    __table_args__ = (
        Index(
            "uq_student_section_history_open",
            "student_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="period_ordered"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    section: Mapped[Section] = relationship(lazy="joined")


class EnrollmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DROPPED = "DROPPED"


class Enrollment(UUIDPrimaryKeyMixin, Base):
    """A student taking a course offering. Dropping keeps the row (and any results)."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("offering_id", "student_id"),
        CheckConstraint(
            "(status = 'DROPPED') = (dropped_at IS NOT NULL)", name="dropped_at_matches_status"
        ),
    )

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        Enum(
            EnrollmentStatus,
            name="enrollment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EnrollmentStatus.ACTIVE,
        server_default=EnrollmentStatus.ACTIVE.value,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship(lazy="joined")
