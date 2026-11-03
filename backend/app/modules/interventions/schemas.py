"""Request and response bodies for interventions.

One rule shapes the request: **a client cannot invent an analytics reason.** A reason may name a
*persisted attention flag* (``flag_id``), and the service then freezes that flag's rule, value
and threshold into the stored reason. It may also carry a plain finding or a note. What it may
not do is assert a ``rule_code`` directly, because a rule code that never came from a fired rule
would read exactly like one that did, and the whole point of the reason trail is that a reader a
semester later can tell the difference.

Everything else mirrors :class:`app.modules.analytics.core.contracts.Intervention`, whose
validators are the definition and are re-run when the stored rows are mapped back to it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.analytics.core.results import Measure
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.analytics.core.thresholds import ResolvedThreshold
from app.modules.analytics.core.vocabulary import (
    InterventionKind,
    InterventionStatus,
    StudentFindingCode,
)

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class InterventionReasonIn(BaseModel):
    """One stated reason, for one of the intervention's targets."""

    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    flag_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "A live attention flag of this offering for this student. Its rule, observed value "
            "and threshold are frozen into the reason as they stand now."
        ),
    )
    finding: StudentFindingCode | None = None
    note: Note | None = None

    @model_validator(mode="after")
    def _says_something(self) -> InterventionReasonIn:
        if self.flag_id is None and self.finding is None and not self.note:
            raise ValueError(
                "a reason must name an attention flag, a finding or a note; an intervention "
                "with no stated reason cannot be explained later"
            )
        return self


class InterventionCreate(BaseModel):
    """Record one action taken for one or more students of an offering."""

    model_config = ConfigDict(extra="forbid")

    student_ids: tuple[uuid.UUID, ...] = Field(min_length=1)
    kind: InterventionKind
    status: InterventionStatus = InterventionStatus.COMPLETED
    after_sequence_no: int = Field(
        ge=0,
        description=(
            "Sequence number of the last assessment already sat when this was raised; 0 means "
            "before any. The pre/post boundary is an assessment sequence, never a date."
        ),
    )
    recorded_on: date | None = None
    reasons: tuple[InterventionReasonIn, ...] = ()
    note: Note | None = None

    @model_validator(mode="after")
    def _targets_and_reasons_agree(self) -> InterventionCreate:
        if len(set(self.student_ids)) != len(self.student_ids):
            raise ValueError("a student is listed twice as a target of this intervention")
        if not self.reasons and not self.note:
            raise ValueError(
                "an intervention must record why it was raised: a reason drawn from the "
                "analytics layer, or a note"
            )
        targets = set(self.student_ids)
        stray = sorted(str(r.student_id) for r in self.reasons if r.student_id not in targets)
        if stray:
            raise ValueError(f"reasons name students who are not targets: {stray}")
        return self


class InterventionReasonRead(BaseModel):
    """A stored reason, as it was frozen when the intervention was raised."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    student_id: uuid.UUID
    rule_code: AttentionRuleCode | None = None
    finding: StudentFindingCode | None = None
    observed: Measure | None = None
    threshold: ResolvedThreshold | None = None
    assessments: tuple[str, ...] = ()
    note: str | None = None
    source_flag_id: uuid.UUID | None = None
    """The attention flag this was taken from, when it came from one. Null once that flag row
    is gone: the reason outlives it, because it is the record of a decision."""


class InterventionRead(BaseModel):
    """One stored intervention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    offering_id: uuid.UUID
    student_ids: tuple[uuid.UUID, ...]
    kind: InterventionKind
    status: InterventionStatus
    after_sequence_no: int
    recorded_on: date | None = None
    note: str | None = None
    reasons: tuple[InterventionReasonRead, ...] = ()
    recorded_by_id: uuid.UUID | None = None
    created_at: datetime
