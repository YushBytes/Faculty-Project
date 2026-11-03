"""Assessment definitions and assessment-level results — the source of truth for analytics.

There is no question/topic layer (DECISION-1): a result is one row per
(student, assessment). Assessment names are rows ("CT1", "FT2", ...), never columns.

Missing-data policy (contract C2):
    present  score NOT NULL                     counts in averages
    absent   score NULL                         not completed; never 0
    exempt   score NULL                         excluded from the denominator
    missing  no row at all (derived, not stored)
Enforced by a CHECK constraint, so absent/exempt cannot hold a number and present
cannot be blank.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.students.models import Student


class AssessmentType(StrEnum):
    """Assessment families. The SRM component codes (regulation 2021) are first-class:
    FT/FJ/FL formative tests of theory, joint and practical courses, LLT/LLJ life-long
    learning, FP unit tests and PBL project components of PBL courses, FM non-credit
    assessments. The generic ones remain for other institutions and older data."""

    CT = "CT"  # cycle test
    FT = "FT"  # formative test (theory)
    FJ = "FJ"  # formative test (joint course)
    FL = "FL"  # formative experiments (practical course)
    FP = "FP"  # unit test (project based learning course)
    FM = "FM"  # non-credit course assessment
    LLT = "LLT"  # life-long learning (theory)
    LLJ = "LLJ"  # life-long learning (joint course)
    PBL = "PBL"  # project based learning review
    VIVA = "VIVA"  # report and viva voce
    PRACTICAL = "PRACTICAL"  # practical examination
    QUIZ = "QUIZ"
    ASSIGNMENT = "ASSIGNMENT"
    LAB = "LAB"
    INTERNAL = "INTERNAL"
    OTHER = "OTHER"


class ResultStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    EXEMPT = "exempt"


class ResultSource(StrEnum):
    MANUAL = "manual"  # PUT /assessments/{id}/results
    IMPORT = "import"  # confirmed import batch


def _values(enum: type[StrEnum]) -> list[str]:
    return [m.value for m in enum]


class Assessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("offering_id", "sequence_no"),
        # Names are unique per offering regardless of case ("CT1" == "ct1").
        Index("uq_assessments_offering_name", "offering_id", func.lower(text("name")), unique=True),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("max_marks > 0", name="max_marks_positive"),
        CheckConstraint("weightage >= 0 AND weightage <= 100", name="weightage_range"),
        CheckConstraint("sequence_no > 0", name="sequence_positive"),
    )

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    assessment_type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, name="assessment_type", values_callable=_values), nullable=False
    )
    assessment_date: Mapped[date | None] = mapped_column(Date)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    weightage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AssessmentResult(Base):
    __tablename__ = "assessment_results"
    __table_args__ = (
        CheckConstraint("(status = 'present') = (score IS NOT NULL)", name="score_matches_status"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= max_marks_snapshot)", name="score_range"
        ),
        CheckConstraint("max_marks_snapshot > 0", name="max_marks_snapshot_positive"),
        Index(None, "assessment_id"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), primary_key=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), primary_key=True
    )
    # Nullable with no default: absent/exempt can never silently become 0.
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[ResultStatus] = mapped_column(
        Enum(ResultStatus, name="result_status", values_callable=_values), nullable=False
    )
    max_marks_snapshot: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    source: Mapped[ResultSource] = mapped_column(
        Enum(ResultSource, name="result_source", values_callable=_values), nullable=False
    )
    # The import batch that last wrote this result (provenance), if any.
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), index=True
    )
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    student: Mapped[Student] = relationship(lazy="joined")
