"""Interventions, their targets and their reasons (dependency D5).

Three tables, matching the shape D5 asks for plus the reason trail the contract requires:

``interventions``
    who/what/when/status, and the pre/post boundary as an **assessment sequence** rather than
    a date (see :class:`app.modules.analytics.core.contracts.Intervention`: dates are optional
    on assessments here, so a date boundary is unresolvable for real data).

``intervention_students``
    the targets. A composite primary key ``(intervention_id, student_id)`` *is* the "no
    duplicate relationship" rule, so it cannot be violated rather than merely being checked.

``intervention_reasons``
    why, one row per stated reason. Normalised rather than a JSON blob for two reasons: a
    reason must be able to **reference the attention flag it came from** by foreign key, and
    "why was this student helped?" is a query, not an opaque document. It carries the value and
    threshold *frozen at the moment of the decision* -- recomputing the flag next week may give
    a different number, which is precisely why the original is kept.

    Its ``(intervention_id, student_id)`` is a composite foreign key onto
    ``intervention_students``, so the database enforces what the contract's validator also
    enforces: a reason can only name a student who is actually a target.
"""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.analytics.core.results import Unit
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSource
from app.modules.analytics.core.vocabulary import (
    InterventionKind,
    InterventionStatus,
    StudentFindingCode,
)


def _values(enum: type[StrEnum]) -> list[str]:
    return [m.value for m in enum]


class Intervention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One recorded action, for one or more students of one offering."""

    __tablename__ = "interventions"
    __table_args__ = (
        # Every read is "the interventions of this offering", newest first.
        Index(None, "offering_id"),
        CheckConstraint("after_sequence_no >= 0", name="after_sequence_no_non_negative"),
        CheckConstraint("note IS NULL OR length(btrim(note)) > 0", name="note_not_blank"),
    )

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[InterventionKind] = mapped_column(
        Enum(InterventionKind, name="intervention_kind", values_callable=_values), nullable=False
    )
    status: Mapped[InterventionStatus] = mapped_column(
        Enum(InterventionStatus, name="intervention_status", values_callable=_values),
        nullable=False,
        default=InterventionStatus.COMPLETED,
        server_default=InterventionStatus.COMPLETED.value,
    )
    after_sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    """Sequence of the last assessment already sat when this was raised. ``0`` = before any."""

    recorded_on: Mapped[date | None] = mapped_column(Date)
    """For display and audit only. Assessment order never depends on a date."""

    note: Mapped[str | None] = mapped_column(Text)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class InterventionStudent(Base):
    """One target of one intervention. The composite PK forbids listing a student twice."""

    __tablename__ = "intervention_students"
    __table_args__ = (
        # "Which interventions has this student had?" -- the reverse of the primary key.
        Index(None, "student_id"),
    )

    intervention_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interventions.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), primary_key=True
    )


class InterventionReason(UUIDPrimaryKeyMixin, Base):
    """Why an intervention was raised for one of its targets, frozen at that moment."""

    __tablename__ = "intervention_reasons"
    __table_args__ = (
        # The reason's student must be a target of the intervention, enforced here rather
        # than only in Python. Cascades when the target (or the intervention) goes.
        ForeignKeyConstraint(
            ["intervention_id", "student_id"],
            ["intervention_students.intervention_id", "intervention_students.student_id"],
            ondelete="CASCADE",
            name="fk_intervention_reasons_target",
        ),
        Index(None, "intervention_id"),
        # Mirrors InterventionReason._says_something: an intervention with no stated reason
        # cannot be explained later.
        CheckConstraint(
            "rule_code IS NOT NULL OR finding IS NOT NULL OR note IS NOT NULL",
            name="says_something",
        ),
        CheckConstraint(
            "observed_value IS NULL OR (observed_unit IS NOT NULL AND observed_n IS NOT NULL)",
            name="observed_complete",
        ),
        CheckConstraint(
            "threshold_key IS NULL "
            "OR (threshold_value IS NOT NULL AND threshold_source IS NOT NULL)",
            name="threshold_complete",
        ),
        CheckConstraint("note IS NULL OR length(btrim(note)) > 0", name="note_not_blank"),
    )

    intervention_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    rule_code: Mapped[AttentionRuleCode | None] = mapped_column(
        Enum(AttentionRuleCode, name="attention_rule_code", values_callable=_values)
    )
    finding: Mapped[StudentFindingCode | None] = mapped_column(
        Enum(StudentFindingCode, name="student_finding_code", values_callable=_values)
    )

    # The value as it stood when the intervention was raised, not as it stands now.
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    observed_unit: Mapped[Unit | None] = mapped_column(
        Enum(Unit, name="measure_unit", values_callable=_values)
    )
    observed_n: Mapped[int | None] = mapped_column(Integer)

    threshold_key: Mapped[ThresholdKey | None] = mapped_column(
        Enum(ThresholdKey, name="threshold_key", values_callable=_values)
    )
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    threshold_source: Mapped[ThresholdSource | None] = mapped_column(
        Enum(ThresholdSource, name="threshold_source", values_callable=_values)
    )

    assessments: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text)

    # The flag this reason was taken from, where it came from analytics. SET NULL rather than
    # CASCADE: the reason is a frozen record of the decision and must outlive the flag row.
    source_flag_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attention_flags.id", ondelete="SET NULL")
    )
