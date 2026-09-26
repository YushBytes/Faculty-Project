"""Scenario builders: small, exact offerings with one awkward property each.

The canonical fixture in :mod:`tests.analytics.canonical` is one rich cohort for proving
the policy end to end. These builders are the opposite: each makes the *smallest* offering
that exhibits one condition, so a failing test names the condition rather than a student
number.

Two conventions make every number here checkable by eye.

*Percentages are the input.* ``max_marks`` defaults to 100, so a cell written ``60`` is a
score of 60 out of 100 and a percentage of exactly 60.00. No scenario depends on rounding.

*The four states are written, not implied.* A cell is a number, or one of
:data:`ABSENT`, :data:`EXEMPT`, :data:`MISSING`. A short row is padded with ``MISSING``,
which is what a student who stopped sitting assessments actually looks like.

Ids are derived with ``uuid5`` from the student's key, so the same scenario produces the
same ids on every run and a failure message can be traced back to "s2" rather than to a
random uuid.

The scenarios, and what each exists to pin down:

=============================  ==============================================================
builder                        the condition it isolates
=============================  ==============================================================
``single_student``             n = 1: student analytics work, every group statistic must refuse
``small_class``                n = 3, below ``MIN_GROUP_N``: a mean exists but must not be labelled
``multi_assessment_class``     4 assessments, mixed shapes: the general case for trends
``missing_results``            no result rows at all, including a student with none anywhere
``absent_students``            absent vs exempt: the two denominators must differ
``improving_students``         rising series either side of ``TREND_DELTA_PP``
``declining_students``         falling series, plus one sharp drop against its own earlier mean
``borderline_students``        sitting on the pass mark, inside and outside the band
``volatile_students``          same mean, opposite consistency
=============================  ==============================================================
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Final

from app.modules.analytics.core.contracts import (
    AssessmentRef,
    OfferingSnapshot,
    ResultRecord,
    ResultStatus,
    StudentRef,
)

NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f1e0b1c-0000-4000-8000-00000000acad")
"""Fixed namespace, so every id below is stable across runs and machines."""

DEFAULT_PASS_MARK: Final[Decimal] = Decimal("40.00")
DEFAULT_MAX_MARKS: Final[Decimal] = Decimal("100.00")


class Mark(StrEnum):
    """A cell that carries no score. Spelled out so a fixture can never mean 0 by accident."""

    ABSENT = "absent"
    EXEMPT = "exempt"
    MISSING = "missing"


ABSENT: Final[Mark] = Mark.ABSENT
EXEMPT: Final[Mark] = Mark.EXEMPT
MISSING: Final[Mark] = Mark.MISSING

Cell = Decimal | int | str | Mark
Rows = Mapping[str, Sequence[Cell]]


def offering_id(key: str = "offering") -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"offering:{key}")


def student_id(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"student:{key}")


def assessment_id(code: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"assessment:{code}")


def _cell(value: Cell) -> Mark | Decimal:
    if isinstance(value, Mark):
        return value
    percentage = Decimal(str(value))
    if not Decimal("0") <= percentage <= Decimal("100"):
        raise ValueError(f"fixture percentage must be between 0 and 100, got {percentage}")
    return percentage


def build_snapshot(
    rows: Rows,
    *,
    codes: Sequence[str] | None = None,
    pass_mark: Cell = DEFAULT_PASS_MARK,
    max_marks: Cell = DEFAULT_MAX_MARKS,
    weightages: Mapping[str, Cell] | None = None,
    inactive: Sequence[str] = (),
    unpublished: Sequence[str] = (),
    key: str = "offering",
) -> OfferingSnapshot:
    """Build an offering from a table of percentages.

    ``rows`` maps a student key to that student's cells in assessment order. Rows shorter
    than the longest are padded with ``MISSING``; a ``MISSING`` cell produces **no result
    row at all**, which is the only honest way to represent data that does not exist.
    """
    width = max((len(cells) for cells in rows.values()), default=0)
    assessment_codes = list(codes) if codes else [f"CT{i}" for i in range(1, width + 1)]
    if len(assessment_codes) < width:
        raise ValueError(f"{len(assessment_codes)} codes for {width} columns of marks")

    maximum = Decimal(str(max_marks))
    assessments = tuple(
        AssessmentRef(
            id=assessment_id(code),
            code=code,
            name=f"Assessment {code}",
            sequence_no=index + 1,
            max_marks=maximum,
            weightage=Decimal(str((weightages or {}).get(code, 1))),
            is_published=code not in set(unpublished),
        )
        for index, code in enumerate(assessment_codes[:width])
    )

    students = tuple(
        StudentRef(
            id=student_id(student_key),
            register_no=f"RA{index + 1:04d}",
            name=f"Student {student_key.upper()}",
            is_active=student_key not in set(inactive),
        )
        for index, student_key in enumerate(rows)
    )

    results: list[ResultRecord] = []
    for student_key, cells in rows.items():
        padded = list(cells) + [MISSING] * (width - len(cells))
        for assessment, raw in zip(assessments, padded, strict=True):
            value = _cell(raw)
            if value is MISSING:
                continue  # No row: the derived "missing" state.
            if value is ABSENT or value is EXEMPT:
                results.append(
                    ResultRecord(
                        student_id=student_id(student_key),
                        assessment_id=assessment.id,
                        status=ResultStatus(str(value)),
                    )
                )
                continue
            results.append(
                ResultRecord(
                    student_id=student_id(student_key),
                    assessment_id=assessment.id,
                    status=ResultStatus.PRESENT,
                    score=(Decimal(value) * maximum / Decimal(100)).quantize(Decimal("0.01")),
                )
            )

    return OfferingSnapshot(
        offering_id=offering_id(key),
        pass_mark_percent=Decimal(str(pass_mark)),
        assessments=assessments,
        students=students,
        results=tuple(results),
    )


# --------------------------------------------------------------------------- scenarios


def single_student() -> OfferingSnapshot:
    """One student, three assessments: 70, 74, 78.

    Slope +4 pp per assessment — below the default ``TREND_DELTA_PP`` of 5, so this student
    is Stable, not Improving. Every group statistic over this offering has n = 1 and must
    return insufficient data rather than "the class average is 74%".
    """
    return build_snapshot({"s1": (70, 74, 78)}, key="single-student")


def small_class() -> OfferingSnapshot:
    """Three students, two assessments. Mean is computable; a class label is not.

    n = 3 is below the default ``MIN_GROUP_N`` of 5. Two completed assessments is exactly
    ``MIN_TREND_POINTS``, so trends are allowed here by the two-point method while group
    statistics are withheld — the two gates are independent and this fixture proves it.

    CT1 mean = (60 + 40 + 80) / 3 = 60.00; CT2 mean = (65 + 35 + 80) / 3 = 60.00.
    """
    return build_snapshot(
        {"s1": (60, 65), "s2": (40, 35), "s3": (80, 80)},
        key="small-class",
    )


def multi_assessment_class() -> OfferingSnapshot:
    """Six students, four assessments, one of them unpublished. The general case.

    ======  =========================  ===============================================
    key     CT1 CT2 CT3 / CT4          shape
    ======  =========================  ===============================================
    s1      88, 90, 92 / 95            high, drifting up
    s2      70, 65, 60 / 58            steady decline, slope -5
    s3      45, 44, 46 / 45            flat, just above the pass mark
    s4      30, 35, 38 / 40            low but rising
    s5      62, absent, 64 / 66        an absence in the middle of a good series
    s6      55, 58, missing / missing   stops sitting assessments
    ======  =========================  ===============================================

    CT4 is unpublished, so by default no statistic may see it: published CT1-CT3 means are
    (88+70+45+30+62+55)/6 = 58.33, (90+65+44+35+58)/5 = 58.40 (s5 absent), and
    (92+60+46+38+64)/5 = 60.00 (s6 missing).
    """
    return build_snapshot(
        {
            "s1": (88, 90, 92, 95),
            "s2": (70, 65, 60, 58),
            "s3": (45, 44, 46, 45),
            "s4": (30, 35, 38, 40),
            "s5": (62, ABSENT, 64, 66),
            "s6": (55, 58, MISSING, MISSING),
        },
        unpublished=("CT4",),
        key="multi-assessment",
    )


def missing_results() -> OfferingSnapshot:
    """Gaps, including a student with no result row anywhere.

    ``s3`` has never been assessed: completion 0%, no trend, no weighted score, and no
    segment. The temptation is to drop such a student from the cohort; that would quietly
    improve every class statistic, so they stay in and are reported as having no data.
    """
    return build_snapshot(
        {
            "s1": (55, 60, 65),
            "s2": (70, MISSING, MISSING),
            "s3": (MISSING, MISSING, MISSING),
            "s4": (48, 52, MISSING),
        },
        key="missing-results",
    )


def absent_students() -> OfferingSnapshot:
    """Absent and exempt side by side, which the two denominators must treat differently.

    Over CT1-CT3, per student: ``s1`` 3 assessed; ``s2`` 2 assessed + 1 absent (denominator
    3, completion 66.67%); ``s3`` 2 assessed + 1 exempt (denominator 2, completion 100%);
    ``s4`` absent throughout (denominator 3, completion 0%, no mean at all — never 0%).

    The pair ``s2``/``s3`` is the whole point: identical numbers of sat papers, different
    completion, because an exemption is not a failure to turn up.
    """
    return build_snapshot(
        {
            "s1": (60, 62, 64),
            "s2": (60, ABSENT, 64),
            "s3": (60, EXEMPT, 64),
            "s4": (ABSENT, ABSENT, ABSENT),
        },
        key="absent-students",
    )


def improving_students() -> OfferingSnapshot:
    """Rising series either side of the trend threshold, including the boundary.

    ``s1`` 40, 50, 60 -> slope +10, clearly Improving.
    ``s2`` 55, 60, 65 -> slope exactly +5, the default ``TREND_DELTA_PP``. The rule is
    ``>=``, so this is Improving; it is here so an off-by-one comparison fails a test.
    ``s3`` 50, 52, 54 -> slope +2, Stable. Rising is not the same as improving.
    ``s4`` 30, 70 -> two points, +40 by the two-point method, no fitted slope.
    """
    return build_snapshot(
        {
            "s1": (40, 50, 60),
            "s2": (55, 60, 65),
            "s3": (50, 52, 54),
            "s4": (30, 70, MISSING),
        },
        key="improving",
    )


def declining_students() -> OfferingSnapshot:
    """Falling series, plus the sharp-decline case, which is a different rule.

    ``s1`` 80, 70, 60 -> slope -10, Declining.
    ``s2`` 65, 60, 55 -> slope exactly -5, the boundary: Declining.
    ``s3`` 54, 52, 50 -> slope -2, Stable.
    ``s4`` 90, 88, 50 -> slope -20 *and* a drop of 39 pp against its earlier mean of 89,
    which is what ``DECLINE_DROP_PP`` (15) catches. A gradual decline and a cliff are
    different events and must raise different flags.
    """
    return build_snapshot(
        {
            "s1": (80, 70, 60),
            "s2": (65, 60, 55),
            "s3": (54, 52, 50),
            "s4": (90, 88, 50),
        },
        key="declining",
    )


def borderline_students() -> OfferingSnapshot:
    """Sitting on a pass mark of 40, inside and outside the ±5 band.

    Weighted course scores: ``s1`` 40.00 (on the mark), ``s2`` 44.00, ``s3`` 36.00,
    ``s4`` 45.00 (the upper edge — inside, because the band is inclusive), ``s5`` 50.00
    (outside). Nothing here is hard-coded to 50%: the same fixture with
    ``pass_mark=50`` must move every one of these answers.
    """
    return build_snapshot(
        {
            "s1": (40, 40, 40),
            "s2": (42, 44, 46),
            "s3": (38, 36, 34),
            "s4": (45, 45, 45),
            "s5": (50, 50, 50),
        },
        key="borderline",
    )


def volatile_students() -> OfferingSnapshot:
    """Identical means, opposite consistency — the case an average hides completely.

    ``s1`` 90, 30, 85, 35 and ``s2`` 60, 60, 60, 60 both average 60.00. Population standard
    deviations are 27.61 and 0.00; ranges are 60 and 0. ``s3`` 62, 58, 61, 59 averages
    60.00 with a standard deviation of 1.58: steady, not identical.
    """
    return build_snapshot(
        {
            "s1": (90, 30, 85, 35),
            "s2": (60, 60, 60, 60),
            "s3": (62, 58, 61, 59),
        },
        key="volatile",
    )


def empty_offering() -> OfferingSnapshot:
    """No students, no assessments. Every analytic must survive it."""
    return build_snapshot({}, key="empty")


SCENARIOS: Final[dict[str, Callable[[], OfferingSnapshot]]] = {
    "single_student": single_student,
    "small_class": small_class,
    "multi_assessment_class": multi_assessment_class,
    "missing_results": missing_results,
    "absent_students": absent_students,
    "improving_students": improving_students,
    "declining_students": declining_students,
    "borderline_students": borderline_students,
    "volatile_students": volatile_students,
    "empty_offering": empty_offering,
}
"""Every builder by name, so a test can sweep all of them without listing them again."""
