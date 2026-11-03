"""A hand-computed offering snapshot, used to prove the analytics core.

Not a test module. Every number below was worked out by hand and the divisors were chosen so
that each percentage is exact, which means a test failure is a real disagreement rather than
a rounding argument.

The cohort deliberately contains every awkward case the policy has to handle:

======  ===================================  ==============================================
who     pattern                              why it is here
======  ===================================  ==============================================
S1      90, 92, 95                           high performer, improving
S2      80, 60, 40                           steady decline
S3      90, 88, 50                           sharp drop against an earlier mean of 89
S4      42, 40, 41                           borderline, hovering at a pass mark of 40
S5      30, 32, 35                           persistently below the pass mark
S6      absent, exempt, 60                   exempt must leave the completion denominator
S7      50, no row, no row                    single assessment: too little data for a trend
S8      60, 70, no row                       inactive: excluded from the active cohort
======  ===================================  ==============================================

``QUIZ1`` is unpublished, so it must not appear in a series or a statistic by default.

The pass mark is 40.00, the platform's own default for an offering. It is passed through the
snapshot rather than assumed, and a second fixture below uses 50.00 so tests can prove that
no rule has baked a pass mark in.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.analytics.core.contracts import (
    AssessmentRef,
    OfferingSnapshot,
    ResultRecord,
    ResultStatus,
    StudentRef,
)

OFFERING_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

CT1_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
CT2_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
FT1_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a3")
QUIZ1_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a4")

S1 = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
S2 = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
S3 = uuid.UUID("00000000-0000-4000-8000-0000000000b3")
S4 = uuid.UUID("00000000-0000-4000-8000-0000000000b4")
S5 = uuid.UUID("00000000-0000-4000-8000-0000000000b5")
S6 = uuid.UUID("00000000-0000-4000-8000-0000000000b6")
S7 = uuid.UUID("00000000-0000-4000-8000-0000000000b7")
S8 = uuid.UUID("00000000-0000-4000-8000-0000000000b8")

PASS_MARK = Decimal("40.00")

CT1 = AssessmentRef(
    id=CT1_ID,
    code="CT1",
    name="Cycle Test 1",
    sequence_no=1,
    max_marks=Decimal("50.00"),
    weightage=Decimal("1"),
)
CT2 = AssessmentRef(
    id=CT2_ID,
    code="CT2",
    name="Cycle Test 2",
    sequence_no=2,
    max_marks=Decimal("50.00"),
    weightage=Decimal("1"),
)
FT1 = AssessmentRef(
    id=FT1_ID,
    code="FT1",
    name="Final Test 1",
    sequence_no=3,
    max_marks=Decimal("100.00"),
    weightage=Decimal("2"),
)
QUIZ1 = AssessmentRef(
    id=QUIZ1_ID,
    code="QUIZ1",
    name="Quiz 1",
    sequence_no=4,
    max_marks=Decimal("20.00"),
    weightage=Decimal("0.5"),
    is_published=False,
)

STUDENTS = (
    StudentRef(id=S1, register_no="RA001", name="S1 High"),
    StudentRef(id=S2, register_no="RA002", name="S2 Declining"),
    StudentRef(id=S3, register_no="RA003", name="S3 Sharp Drop"),
    StudentRef(id=S4, register_no="RA004", name="S4 Borderline"),
    StudentRef(id=S5, register_no="RA005", name="S5 Persistently Low"),
    StudentRef(id=S6, register_no="RA006", name="S6 Absent And Exempt"),
    StudentRef(id=S7, register_no="RA007", name="S7 Single Assessment"),
    StudentRef(id=S8, register_no="RA008", name="S8 Inactive", is_active=False),
)


def _present(student: uuid.UUID, assessment: uuid.UUID, score: str) -> ResultRecord:
    return ResultRecord(
        student_id=student,
        assessment_id=assessment,
        status=ResultStatus.PRESENT,
        score=Decimal(score),
    )


def _no_score(student: uuid.UUID, assessment: uuid.UUID, status: ResultStatus) -> ResultRecord:
    return ResultRecord(student_id=student, assessment_id=assessment, status=status)


RESULTS = (
    # S1: 45/50 = 90, 46/50 = 92, 95/100 = 95. Also an unpublished quiz that must be ignored.
    _present(S1, CT1_ID, "45"),
    _present(S1, CT2_ID, "46"),
    _present(S1, FT1_ID, "95"),
    _present(S1, QUIZ1_ID, "18"),
    # S2: 40/50 = 80, 30/50 = 60, 40/100 = 40.
    _present(S2, CT1_ID, "40"),
    _present(S2, CT2_ID, "30"),
    _present(S2, FT1_ID, "40"),
    # S3: 45/50 = 90, 44/50 = 88, 50/100 = 50. Earlier mean 89 -> drop of 39 pp.
    _present(S3, CT1_ID, "45"),
    _present(S3, CT2_ID, "44"),
    _present(S3, FT1_ID, "50"),
    # S4: 21/50 = 42, 20/50 = 40, 41/100 = 41. Straddles a pass mark of 40.
    _present(S4, CT1_ID, "21"),
    _present(S4, CT2_ID, "20"),
    _present(S4, FT1_ID, "41"),
    # S5: 15/50 = 30, 16/50 = 32, 35/100 = 35. Never reaches the pass mark.
    _present(S5, CT1_ID, "15"),
    _present(S5, CT2_ID, "16"),
    _present(S5, FT1_ID, "35"),
    # S6: absent, then exempt, then 60/100 = 60. Neither no-score row carries a score.
    _no_score(S6, CT1_ID, ResultStatus.ABSENT),
    _no_score(S6, CT2_ID, ResultStatus.EXEMPT),
    _present(S6, FT1_ID, "60"),
    # S7: 25/50 = 50, then no rows at all for CT2 and FT1 (the derived missing state).
    _present(S7, CT1_ID, "25"),
    # S8: inactive, 30/50 = 60 and 35/50 = 70.
    _present(S8, CT1_ID, "30"),
    _present(S8, CT2_ID, "35"),
)


def snapshot(*, pass_mark: Decimal = PASS_MARK) -> OfferingSnapshot:
    """The canonical snapshot. ``pass_mark`` varies so tests can prove it is never assumed."""
    return OfferingSnapshot(
        offering_id=OFFERING_ID,
        pass_mark_percent=pass_mark,
        assessments=(CT1, CT2, FT1, QUIZ1),
        students=STUDENTS,
        results=RESULTS,
    )


def empty_snapshot() -> OfferingSnapshot:
    """An offering with no assessments and no students: the zero-data edge case."""
    return OfferingSnapshot(offering_id=OFFERING_ID, pass_mark_percent=PASS_MARK)


def single_assessment_snapshot() -> OfferingSnapshot:
    """One assessment, three students: enough for a mean, never enough for a trend."""
    return OfferingSnapshot(
        offering_id=OFFERING_ID,
        pass_mark_percent=PASS_MARK,
        assessments=(CT1,),
        students=STUDENTS[:3],
        results=(
            _present(S1, CT1_ID, "45"),
            _present(S2, CT1_ID, "40"),
            _present(S3, CT1_ID, "45"),
        ),
    )


# Hand-computed expectations, quoted by the tests so the arithmetic is reviewable here.
EXPECTED_PERCENTAGES: dict[uuid.UUID, tuple[str, ...]] = {
    S1: ("90.00", "92.00", "95.00"),
    S2: ("80.00", "60.00", "40.00"),
    S3: ("90.00", "88.00", "50.00"),
    S4: ("42.00", "40.00", "41.00"),
    S5: ("30.00", "32.00", "35.00"),
    S6: ("60.00",),
    S7: ("50.00",),
}

# CT1, active students only, assessed only: S6 was absent and S8 is inactive.
EXPECTED_CT1_ASSESSED = ("90.00", "80.00", "90.00", "42.00", "30.00", "50.00")
# FT1, active students only: S7 has no row.
EXPECTED_FT1_ASSESSED = ("95.00", "40.00", "50.00", "41.00", "35.00", "60.00")
