"""Persisted attention flags (dependency D6).

One row per fired rule per student, materialised from
:func:`app.modules.analytics.core.attention.cohort_attention` by the C4 recompute hook.

**Why rows are resolved and never deleted.** PROJECT_CONTEXT D6 requires that "flags are
persisted so history survives recompute". A flag that stops firing is therefore stamped
``status = resolved`` with a ``resolved_at``, and a flag that fires again later becomes a new
row. Deleting and re-inserting the current set would be simpler and would lose exactly the
thing the requirement asks for: that a reader can see a student was flagged in week 4 even
though the mark they since earned cleared it.

**What is stored is the decision, not its rendering.** D6 names the persisted fields:
``rule_code``, ``severity``, ``threshold``, ``actual_value``, ``message``, ``status`` and
``computed_at``. Those plus the offering, the student, the assessments quoted and the sample
size are enough to reproduce why the rule fired. The contract's ``Explanation`` block (its
evidence items, formula text and caveats) is *derived presentation*: the engine regenerates it
from the same inputs, so storing it would be a second copy that can disagree with the first.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
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
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity, FlagStatus
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSource

LIVE_FLAG_STATUSES = (FlagStatus.OPEN, FlagStatus.ACKNOWLEDGED)
"""A flag still standing. ``RESOLVED`` is history and is excluded from the live unique index."""


def _values(enum: type[StrEnum]) -> list[str]:
    """Store the enum's *values*, matching Agent 1's convention (see assessments.models)."""
    return [m.value for m in enum]


class AttentionFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One fired rule for one student, as it stood when it was last evaluated.

    ``created_at`` is when the flag was first raised and never moves; ``computed_at`` moves
    every time a recompute finds the rule still firing. Keeping both is what lets a report say
    "flagged since week 4, still firing today".
    """

    __tablename__ = "attention_flags"
    __table_args__ = (
        # D9: the dashboard reads one offering's live flags.
        Index("ix_attention_flags_offering_id_status", "offering_id", "status"),
        # "Every flag for this student", across offerings, for a student report.
        Index(None, "student_id"),
        # At most one *live* flag per (student, rule): the database guarantee behind an
        # idempotent recompute, so a concurrent second run cannot duplicate a row. Resolved
        # rows are excluded, which is what lets the same rule fire again later as a new row.
        Index(
            "uq_attention_flags_offering_id_student_id_rule_code_live",
            "offering_id",
            "student_id",
            "rule_code",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        CheckConstraint("actual_n >= 0", name="actual_n_non_negative"),
        CheckConstraint(
            "threshold_key IS NULL "
            "OR (threshold_value IS NOT NULL AND threshold_source IS NOT NULL)",
            name="threshold_complete",
        ),
        # A flag must say what it compared against: a resolved threshold, or (R2) the
        # offering's pass mark. Mirrors AttentionFlag._states_what_it_compared.
        CheckConstraint(
            "threshold_key IS NOT NULL OR pass_mark_percent IS NOT NULL",
            name="states_its_comparison",
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        CheckConstraint("length(btrim(message)) > 0", name="message_not_blank"),
    )

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="RESTRICT"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    rule_code: Mapped[AttentionRuleCode] = mapped_column(
        Enum(AttentionRuleCode, name="attention_rule_code", values_callable=_values),
        nullable=False,
    )
    severity: Mapped[FlagSeverity] = mapped_column(
        Enum(FlagSeverity, name="flag_severity", values_callable=_values), nullable=False
    )
    status: Mapped[FlagStatus] = mapped_column(
        Enum(FlagStatus, name="flag_status", values_callable=_values),
        nullable=False,
        default=FlagStatus.OPEN,
        server_default=FlagStatus.OPEN.value,
    )

    # The value that fired the rule, with its scale and sample size: a bare number cannot be
    # read later without knowing whether it is a percentage, a count or a slope.
    actual_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    actual_unit: Mapped[Unit] = mapped_column(
        Enum(Unit, name="measure_unit", values_callable=_values), nullable=False
    )
    actual_n: Mapped[int] = mapped_column(Integer, nullable=False)

    # What it was compared against. Null for R2, which quotes the pass mark instead.
    threshold_key: Mapped[ThresholdKey | None] = mapped_column(
        Enum(ThresholdKey, name="threshold_key", values_callable=_values)
    )
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    threshold_source: Mapped[ThresholdSource | None] = mapped_column(
        Enum(ThresholdSource, name="threshold_source", values_callable=_values)
    )
    pass_mark_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    # The assessment labels the message quotes, in the engine's order.
    reference_assessments: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """When the rule was last evaluated and still fired. ``created_at`` is the first raise."""

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Which results write set this state off. Provenance for the audit trail, not an input:
    # the flag is computed over the whole offering, not over one assessment.
    triggered_by_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="SET NULL")
    )


# The C4 recompute hook is what keeps this table in step with the engine, so it is installed
# wherever these tables are registered. `app/cli.py` imports only `app.db.models`, which reaches
# this module but never the API's routers, and `seed-demo` writes results through the platform's
# ResultWriter — without this line the seeded demo database would carry no flags at all.
# Imported last, after the model above exists, because the hook's own imports read it.
import app.modules.analytics.recompute  # noqa: E402,F401  (side effect: installs C4)
