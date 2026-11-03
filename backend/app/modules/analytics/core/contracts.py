"""Typed inputs the analytics core consumes.

These are *analytics* contracts, deliberately independent of the database. A later phase
adds an adapter that builds an :class:`OfferingSnapshot` by calling the platform's own
services/repositories; nothing here assumes a table, a column name or an ORM class.

``ResultStatus`` below is the analytics-side vocabulary for the three *stored* result
states. The platform owns the persisted enum (assessment results are a later platform
phase); when it lands, the adapter maps it one-to-one onto this enum. It is not a second
source of truth, and it must not be widened: ``missing`` and ``incomplete`` are *derived*
states meaning "no row exists" and "not all assessments have a row", so they live in
:mod:`app.modules.analytics.core.policy`, never in stored data.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.types import Code, JsonDecimal, Name, Percent
from app.modules.analytics.core.results import Measure
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.analytics.core.thresholds import ResolvedThreshold
from app.modules.analytics.core.vocabulary import (
    InterventionKind,
    InterventionStatus,
    StudentFindingCode,
)

AssessmentLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
"""How an assessment is named to a reader: the platform's own ``assessments.name``.

Not :data:`app.core.types.Code`. The platform has no separate assessment code — the label a
faculty member types ("CT1", but also "Unit Test 2 (retest)") is free text up to 100
characters. Forcing it through ``Code`` would upper-case it and reject anything past 32
characters, so a real assessment would either be refused or silently relabelled in the
explanation text that quotes it.
"""


class ResultStatus(StrEnum):
    """How a student's result for one assessment was recorded.

    Only ``PRESENT`` carries a score. ``ABSENT`` and ``EXEMPT`` are recorded facts with no
    score, and neither may ever be read as zero.
    """

    PRESENT = "present"
    ABSENT = "absent"
    EXEMPT = "exempt"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StudentRef(_Frozen):
    """A student, as analytics needs to identify and label one.

    Deliberately minimal: analytics never needs contact details, and keeping PII out of the
    core limits how far it can travel into logs, reports and error messages.
    """

    id: uuid.UUID
    register_no: Code
    name: Name | None = None
    is_active: bool = True

    @property
    def display(self) -> str:
        """Short label for explanation text. Falls back to the register number."""
        return self.name or str(self.register_no)


class AssessmentRef(_Frozen):
    """One assessment within an offering.

    ``sequence_no`` defines chronological order for trends and comparisons; dates are
    optional in real faculty data, so order never depends on ``held_on``.
    """

    id: uuid.UUID
    code: AssessmentLabel
    name: Name | None = None
    sequence_no: int = Field(ge=1)
    max_marks: JsonDecimal = Field(gt=0, max_digits=6, decimal_places=2)
    weightage: JsonDecimal = Field(default=Decimal("1"), ge=0, max_digits=6, decimal_places=3)
    held_on: date | None = None
    is_published: bool = True

    @property
    def display(self) -> str:
        return str(self.code)


class ResultRecord(_Frozen):
    """One student's result for one assessment: the atomic stored fact.

    A score exists only when the status is ``PRESENT``. That invariant is enforced here so
    an absent or exempt row can never silently arrive carrying ``0``.
    """

    student_id: uuid.UUID
    assessment_id: uuid.UUID
    status: ResultStatus
    score: JsonDecimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)

    @model_validator(mode="after")
    def _score_matches_status(self) -> ResultRecord:
        if self.status is ResultStatus.PRESENT:
            if self.score is None:
                raise ValueError("a present result must carry a score")
        elif self.score is not None:
            raise ValueError(
                f"a {self.status.value} result must not carry a score "
                f"(got {self.score}); absent and exempt are not zero"
            )
        return self


class OfferingSnapshot(_Frozen):
    """Everything the analytics core needs about one course offering, at one instant.

    This is the single entry point for every analytic: the core reads a snapshot and
    returns results. It holds no identifiers the platform has not already authorised the
    caller to see, so scope enforcement stays in the platform layer that built it.

    ``pass_mark_percent`` comes from the offering, never from a constant. Institutions
    differ and the platform default is not a universal academic standard.
    """

    offering_id: uuid.UUID
    pass_mark_percent: Percent
    assessments: tuple[AssessmentRef, ...] = ()
    students: tuple[StudentRef, ...] = ()
    results: tuple[ResultRecord, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> OfferingSnapshot:
        assessment_ids = {a.id for a in self.assessments}
        if len(assessment_ids) != len(self.assessments):
            raise ValueError("duplicate assessment id in snapshot")

        sequences = [a.sequence_no for a in self.assessments]
        if len(set(sequences)) != len(sequences):
            raise ValueError("duplicate assessment sequence_no in snapshot")

        student_ids = {s.id for s in self.students}
        if len(student_ids) != len(self.students):
            raise ValueError("duplicate student id in snapshot")

        max_marks = {a.id: a.max_marks for a in self.assessments}
        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for result in self.results:
            key = (result.student_id, result.assessment_id)
            if key in seen:
                raise ValueError(
                    f"duplicate result for student {result.student_id} "
                    f"on assessment {result.assessment_id}"
                )
            seen.add(key)

            if result.student_id not in student_ids:
                raise ValueError(f"result references unknown student {result.student_id}")
            if result.assessment_id not in assessment_ids:
                raise ValueError(f"result references unknown assessment {result.assessment_id}")
            if result.score is not None and result.score > max_marks[result.assessment_id]:
                raise ValueError(
                    f"score {result.score} exceeds max_marks "
                    f"{max_marks[result.assessment_id]} for assessment {result.assessment_id}"
                )
        return self

    def ordered_assessments(self, *, published_only: bool = True) -> tuple[AssessmentRef, ...]:
        """Assessments in chronological order, by ``sequence_no``.

        Unpublished assessments are excluded by default: a faculty member who has created
        but not published an assessment has not yet told students it counts, and including
        it would distort completion and trends.
        """
        chosen = [a for a in self.assessments if a.is_published or not published_only]
        return tuple(sorted(chosen, key=lambda a: a.sequence_no))

    def active_students(self) -> tuple[StudentRef, ...]:
        """Enrolled, active students: the denominator basis for completion."""
        return tuple(s for s in self.students if s.is_active)

    @functools.cached_property
    def _result_index(self) -> Mapping[tuple[uuid.UUID, uuid.UUID], ResultRecord]:
        """``(student, assessment) -> result``, built once per snapshot.

        A linear scan per lookup is fine for one student and quadratic for a cohort: every
        analytic asks this question once per student per assessment, so the scan is walked
        ``n * m`` times over ``n * m`` rows. At 800 students and 10 assessments that is tens
        of millions of comparisons for a dashboard read.

        The cache lives in the instance dictionary rather than in a field: the model stays
        frozen, hashable and equal to an identical snapshot, and the index is never part of
        the contract or its serialisation. The snapshot is immutable, so the index cannot go
        stale.
        """
        return {(r.student_id, r.assessment_id): r for r in self.results}

    def result_for(self, student_id: uuid.UUID, assessment_id: uuid.UUID) -> ResultRecord | None:
        """The stored result, or ``None`` when no row exists (the derived *missing* state)."""
        return self._result_index.get((student_id, assessment_id))


class InterventionReason(_Frozen):
    """Why an intervention was raised, tied to the evidence that prompted it.

    A free-text note is allowed but is never the only record: where the reason came from the
    analytics layer it carries the rule or finding code, the value observed at the time and
    the threshold it was compared against, so a reader a semester later can see what the
    teacher saw. The value is frozen at the moment of the decision — recomputing the flag
    later may give a different number, and that is exactly why the original is kept.

    Built from an :class:`~app.modules.analytics.core.outputs.AttentionFlag` by
    :func:`~app.modules.analytics.core.interventions.reason_from_flag`; the flag itself is
    not stored here because a flag is derived data with its own lifecycle, and because the
    contracts layer must not depend on the outputs layer.
    """

    student_id: uuid.UUID
    rule_code: AttentionRuleCode | None = None
    finding: StudentFindingCode | None = None
    observed: Measure | None = None
    """The value as it stood when the intervention was raised."""

    threshold: ResolvedThreshold | None = None
    assessments: tuple[str, ...] = ()
    note: str | None = None

    @model_validator(mode="after")
    def _says_something(self) -> InterventionReason:
        if self.rule_code is None and self.finding is None and not self.note:
            raise ValueError(
                "a reason must name a rule, a finding or a note; an intervention with no "
                "stated reason cannot be explained later"
            )
        return self


class Intervention(_Frozen):
    """One recorded action a faculty member took for one or more students.

    An *input* to analytics, like a result row: the platform stores it, this layer reads it
    and measures what happened afterwards. It is not an output and not a workflow engine —
    there is no assignment, no reminder, no escalation, because none of that is needed to
    report an observed change.

    **The pre/post boundary is an assessment sequence, not a date.** ``after_sequence_no`` is
    the sequence number of the last assessment that had already happened when the
    intervention was raised: everything at or below it is the baseline, the next published
    assessment is the follow-up. Dates are optional on assessments in this system and
    ordering never depends on them (see :class:`AssessmentRef`), so a date-based boundary
    would be unresolvable for real data.
    :func:`~app.modules.analytics.core.interventions.boundary_from_date` converts a date to
    a sequence where the data allows it, and refuses where it does not.
    """

    id: uuid.UUID
    offering_id: uuid.UUID
    student_ids: tuple[uuid.UUID, ...] = Field(min_length=1)
    kind: InterventionKind
    status: InterventionStatus = InterventionStatus.COMPLETED
    after_sequence_no: int = Field(ge=0)
    """The assessment sequence the intervention follows. ``0`` means "before any assessment"."""

    recorded_on: date | None = None
    """When it was raised, for display and audit. Never used to order assessments."""

    reasons: tuple[InterventionReason, ...] = ()
    note: str | None = None

    @model_validator(mode="after")
    def _targets_and_reasons_agree(self) -> Intervention:
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

    @property
    def targets(self) -> frozenset[uuid.UUID]:
        return frozenset(self.student_ids)

    def reasons_for(self, student_id: uuid.UUID) -> tuple[InterventionReason, ...]:
        return tuple(reason for reason in self.reasons if reason.student_id == student_id)
