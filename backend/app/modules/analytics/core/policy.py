"""The missing-data policy, in one place, as executable rules.

Every statistic in every later phase builds on this module, so the policy cannot drift
between formulas.

::

    ABSENT != 0     MISSING != 0     NOT ASSESSED != 0     EXEMPT != 0

Three states are *stored* (present, absent, exempt) and two are *derived*: ``MISSING`` means
no result row exists at all, and incompleteness is the shape of a whole series rather than
one point. The distinction matters because a student who was exempt from an assessment
should not be penalised in a completion figure, whereas one who simply has no row should be
counted as not completed.

How each state is treated:

===========  ==================  =========================  =========================
state        included in mean?   counts as assessed?        in completion denominator?
===========  ==================  =========================  =========================
``ASSESSED`` yes                 yes                        yes
``ABSENT``   no                  no                         yes
``MISSING``  no                  no                         yes
``EXEMPT``   no                  no                         **no**
===========  ==================  =========================  =========================
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.modules.analytics.core.contracts import (
    AssessmentRef,
    OfferingSnapshot,
    ResultStatus,
    StudentRef,
)

PERCENT_PRECISION = Decimal("0.01")
"""Percentages are held to two decimal places, matching the platform's NUMERIC(5, 2)."""


class DerivedState(StrEnum):
    """A result's state for analytics, including the case where no result exists."""

    ASSESSED = "assessed"
    ABSENT = "absent"
    EXEMPT = "exempt"
    MISSING = "missing"

    @property
    def is_assessed(self) -> bool:
        """Whether this point contributes a percentage to statistics."""
        return self is DerivedState.ASSESSED

    @property
    def counts_toward_completion(self) -> bool:
        """Whether this point belongs in the completion denominator.

        Exempt is excluded entirely: the student was not required to sit the assessment, so
        counting it against them would manufacture a completion problem.
        """
        return self is not DerivedState.EXEMPT


def classify(status: ResultStatus | None) -> DerivedState:
    """Map a stored status, or the absence of a row, onto a derived state."""
    match status:
        case None:
            return DerivedState.MISSING
        case ResultStatus.PRESENT:
            return DerivedState.ASSESSED
        case ResultStatus.ABSENT:
            return DerivedState.ABSENT
        case ResultStatus.EXEMPT:
            return DerivedState.EXEMPT
    raise ValueError(f"unhandled result status {status!r}")


def assessment_percentage(score: Decimal, max_marks: Decimal) -> Decimal:
    """``100 * score / max_marks``, to two decimal places.

    Half-up rounding, so 66.665 becomes 66.67 rather than depending on binary
    representation. ``max_marks`` of zero is a data error, not a zero percentage.
    """
    if max_marks <= 0:
        raise ValueError(f"max_marks must be positive to compute a percentage, got {max_marks}")
    if score < 0:
        raise ValueError(f"score must not be negative, got {score}")
    return (Decimal(100) * score / max_marks).quantize(PERCENT_PRECISION, rounding=ROUND_HALF_UP)


class SeriesPoint(BaseModel):
    """One assessment in one student's history, with its state made explicit.

    ``percentage`` is ``None`` for every state except ``ASSESSED``. There is deliberately no
    way to read a score out of an absent, exempt or missing point.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: uuid.UUID
    assessment_code: str
    sequence_no: int
    state: DerivedState
    percentage: Decimal | None = None
    score: Decimal | None = None
    max_marks: Decimal
    weightage: Decimal = Decimal("1")
    """The assessment's weight in the course score.

    Carried on the point so the weighted course score (F2) is computable from a series
    alone; without it every caller would have to hold the snapshot as well, and the series
    would stop being a complete description of the student.
    """

    @property
    def is_assessed(self) -> bool:
        return self.state.is_assessed


class StudentSeries(BaseModel):
    """One student's ordered history within an offering.

    The building block for trends, decline, consistency and the weighted course score. It
    reports its own sample sizes so a caller never has to recount, and so an explanation can
    quote them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    student_id: uuid.UUID
    offering_id: uuid.UUID
    points: tuple[SeriesPoint, ...]

    @property
    def assessed_points(self) -> tuple[SeriesPoint, ...]:
        """Points that carry a percentage, in chronological order."""
        return tuple(p for p in self.points if p.is_assessed)

    @property
    def percentages(self) -> tuple[Decimal, ...]:
        """The percentage series used by trend, decline and consistency."""
        return tuple(p.percentage for p in self.assessed_points if p.percentage is not None)

    @property
    def completed_count(self) -> int:
        """Assessments the student was actually assessed in."""
        return len(self.assessed_points)

    @property
    def completion_denominator(self) -> int:
        """Published assessments the student was expected to sit, excluding exempt ones."""
        return sum(1 for p in self.points if p.state.counts_toward_completion)

    @property
    def latest_assessed(self) -> SeriesPoint | None:
        """The most recent assessed point, or ``None`` when the student has none."""
        assessed = self.assessed_points
        return assessed[-1] if assessed else None

    @property
    def has_any_result(self) -> bool:
        """Whether any row exists at all, in any state."""
        return any(p.state is not DerivedState.MISSING for p in self.points)


def build_student_series(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    *,
    published_only: bool = True,
) -> StudentSeries:
    """Assemble one student's ordered series from a snapshot.

    Every published assessment produces a point, including those with no result row, because
    a gap is information: it is what makes a completion figure meaningful.
    """
    if all(student.id != student_id for student in snapshot.students):
        raise ValueError(f"student {student_id} is not in this offering snapshot")

    points: list[SeriesPoint] = []
    for assessment in snapshot.ordered_assessments(published_only=published_only):
        result = snapshot.result_for(student_id, assessment.id)
        state = classify(result.status if result else None)
        score = result.score if result else None
        percentage = (
            assessment_percentage(score, assessment.max_marks)
            if state.is_assessed and score is not None
            else None
        )
        points.append(
            SeriesPoint(
                assessment_id=assessment.id,
                assessment_code=str(assessment.code),
                sequence_no=assessment.sequence_no,
                state=state,
                percentage=percentage,
                score=score,
                max_marks=assessment.max_marks,
                weightage=assessment.weightage,
            )
        )

    return StudentSeries(
        student_id=student_id,
        offering_id=snapshot.offering_id,
        points=tuple(points),
    )


def build_all_series(
    snapshot: OfferingSnapshot,
    *,
    active_only: bool = True,
    published_only: bool = True,
) -> tuple[StudentSeries, ...]:
    """Every student's series, in the snapshot's student order."""
    students = snapshot.active_students() if active_only else snapshot.students
    return tuple(
        build_student_series(snapshot, student.id, published_only=published_only)
        for student in students
    )


def assessed_scores(
    snapshot: OfferingSnapshot,
    assessment: AssessmentRef,
    *,
    active_only: bool = True,
) -> tuple[tuple[StudentRef, Decimal], ...]:
    """Assessed students in one assessment, each with their percentage, in cohort order.

    The input to every group statistic, and the single place the "who counts" filter is
    written: absent, exempt and missing students contribute nothing rather than a zero.
    Order is the snapshot's own student order, which makes tie-breaking in
    :func:`app.modules.analytics.core.statistics.extremes` stable.
    """
    students = snapshot.active_students() if active_only else snapshot.students
    pairs: list[tuple[StudentRef, Decimal]] = []
    for student in students:
        result = snapshot.result_for(student.id, assessment.id)
        if result is None or not classify(result.status).is_assessed or result.score is None:
            continue
        pairs.append((student, assessment_percentage(result.score, assessment.max_marks)))
    return tuple(pairs)


def assessed_percentages(
    snapshot: OfferingSnapshot,
    assessment: AssessmentRef,
    *,
    active_only: bool = True,
) -> tuple[Decimal, ...]:
    """Just the percentages from :func:`assessed_scores`, for callers that need no names."""
    return tuple(
        percentage
        for _, percentage in assessed_scores(snapshot, assessment, active_only=active_only)
    )
