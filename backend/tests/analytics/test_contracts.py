"""The analytics input contract: what it accepts, and what it refuses.

The refusals matter more than the acceptances. Most of the ways this system could quietly
report a wrong number start with a malformed input, and the most dangerous one is an absent
result arriving with a score of zero.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.contracts import (
    AssessmentRef,
    OfferingSnapshot,
    ResultRecord,
    ResultStatus,
    StudentRef,
)
from tests.analytics import canonical as fx


class TestResultRecord:
    def test_present_result_carries_a_score(self) -> None:
        record = ResultRecord(
            student_id=fx.S1,
            assessment_id=fx.CT1_ID,
            status=ResultStatus.PRESENT,
            score=Decimal("45"),
        )
        assert record.score == Decimal("45")

    def test_present_result_without_a_score_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must carry a score"):
            ResultRecord(student_id=fx.S1, assessment_id=fx.CT1_ID, status=ResultStatus.PRESENT)

    @pytest.mark.parametrize("status", [ResultStatus.ABSENT, ResultStatus.EXEMPT])
    def test_absent_or_exempt_result_may_not_carry_a_score(self, status: ResultStatus) -> None:
        """The central guarantee: absent and exempt are not zero, and cannot be stored as zero."""
        with pytest.raises(ValidationError, match="not zero"):
            ResultRecord(
                student_id=fx.S1,
                assessment_id=fx.CT1_ID,
                status=status,
                score=Decimal("0"),
            )

    def test_negative_score_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResultRecord(
                student_id=fx.S1,
                assessment_id=fx.CT1_ID,
                status=ResultStatus.PRESENT,
                score=Decimal("-1"),
            )

    def test_records_are_immutable(self) -> None:
        record = fx.RESULTS[0]
        with pytest.raises(ValidationError):
            record.score = Decimal("99")  # type: ignore[misc]


class TestAssessmentRef:
    def test_zero_max_marks_is_rejected(self) -> None:
        """A zero maximum would make every percentage a division by zero."""
        with pytest.raises(ValidationError):
            AssessmentRef(id=fx.CT1_ID, code="CT1", sequence_no=1, max_marks=Decimal("0"))

    def test_sequence_starts_at_one(self) -> None:
        with pytest.raises(ValidationError):
            AssessmentRef(id=fx.CT1_ID, code="CT1", sequence_no=0, max_marks=Decimal("50"))

    def test_weightage_defaults_to_one_and_may_be_zero(self) -> None:
        assert fx.CT1.weightage == Decimal("1")
        unweighted = AssessmentRef(
            id=fx.QUIZ1_ID,
            code="Q",
            sequence_no=9,
            max_marks=Decimal("10"),
            weightage=Decimal("0"),
        )
        assert unweighted.weightage == Decimal("0")


class TestOfferingSnapshot:
    def test_canonical_fixture_is_valid(self) -> None:
        snapshot = fx.snapshot()
        assert len(snapshot.assessments) == 4
        assert len(snapshot.students) == 8

    def test_result_for_unknown_student_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown student"):
            OfferingSnapshot(
                offering_id=fx.OFFERING_ID,
                pass_mark_percent=fx.PASS_MARK,
                assessments=(fx.CT1,),
                students=(fx.STUDENTS[0],),
                results=(
                    ResultRecord(
                        student_id=uuid.uuid4(),
                        assessment_id=fx.CT1_ID,
                        status=ResultStatus.PRESENT,
                        score=Decimal("10"),
                    ),
                ),
            )

    def test_result_for_unknown_assessment_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown assessment"):
            OfferingSnapshot(
                offering_id=fx.OFFERING_ID,
                pass_mark_percent=fx.PASS_MARK,
                assessments=(fx.CT1,),
                students=(fx.STUDENTS[0],),
                results=(
                    ResultRecord(
                        student_id=fx.S1,
                        assessment_id=uuid.uuid4(),
                        status=ResultStatus.PRESENT,
                        score=Decimal("10"),
                    ),
                ),
            )

    def test_duplicate_result_for_one_student_and_assessment_is_rejected(self) -> None:
        """Two rows for the same cell would double-count the student in every statistic."""
        with pytest.raises(ValidationError, match="duplicate result"):
            OfferingSnapshot(
                offering_id=fx.OFFERING_ID,
                pass_mark_percent=fx.PASS_MARK,
                assessments=(fx.CT1,),
                students=(fx.STUDENTS[0],),
                results=(
                    ResultRecord(
                        student_id=fx.S1,
                        assessment_id=fx.CT1_ID,
                        status=ResultStatus.PRESENT,
                        score=Decimal("10"),
                    ),
                    ResultRecord(
                        student_id=fx.S1,
                        assessment_id=fx.CT1_ID,
                        status=ResultStatus.PRESENT,
                        score=Decimal("20"),
                    ),
                ),
            )

    def test_score_above_assessment_maximum_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds max_marks"):
            OfferingSnapshot(
                offering_id=fx.OFFERING_ID,
                pass_mark_percent=fx.PASS_MARK,
                assessments=(fx.CT1,),
                students=(fx.STUDENTS[0],),
                results=(
                    ResultRecord(
                        student_id=fx.S1,
                        assessment_id=fx.CT1_ID,
                        status=ResultStatus.PRESENT,
                        score=Decimal("51"),
                    ),
                ),
            )

    def test_duplicate_sequence_number_is_rejected(self) -> None:
        """Two assessments claiming the same position would make ordering arbitrary."""
        clash = AssessmentRef(id=uuid.uuid4(), code="CT1B", sequence_no=1, max_marks=Decimal("50"))
        with pytest.raises(ValidationError, match="duplicate assessment sequence_no"):
            OfferingSnapshot(
                offering_id=fx.OFFERING_ID,
                pass_mark_percent=fx.PASS_MARK,
                assessments=(fx.CT1, clash),
            )

    def test_pass_mark_above_one_hundred_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OfferingSnapshot(offering_id=fx.OFFERING_ID, pass_mark_percent=Decimal("101"))

    def test_ordered_assessments_excludes_unpublished_by_default(self) -> None:
        snapshot = fx.snapshot()
        assert [a.code for a in snapshot.ordered_assessments()] == ["CT1", "CT2", "FT1"]
        assert [a.code for a in snapshot.ordered_assessments(published_only=False)] == [
            "CT1",
            "CT2",
            "FT1",
            "QUIZ1",
        ]

    def test_ordered_assessments_sorts_by_sequence_not_input_order(self) -> None:
        snapshot = OfferingSnapshot(
            offering_id=fx.OFFERING_ID,
            pass_mark_percent=fx.PASS_MARK,
            assessments=(fx.FT1, fx.CT1, fx.CT2),
        )
        assert [a.sequence_no for a in snapshot.ordered_assessments()] == [1, 2, 3]

    def test_active_students_excludes_inactive(self) -> None:
        snapshot = fx.snapshot()
        active = {s.id for s in snapshot.active_students()}
        assert fx.S8 not in active
        assert len(active) == 7

    def test_result_for_returns_none_when_no_row_exists(self) -> None:
        """No row is the derived missing state, and must not be confused with a zero."""
        snapshot = fx.snapshot()
        assert snapshot.result_for(fx.S7, fx.CT2_ID) is None
        assert snapshot.result_for(fx.S7, fx.CT1_ID) is not None

    def test_empty_snapshot_is_valid(self) -> None:
        snapshot = fx.empty_snapshot()
        assert snapshot.ordered_assessments() == ()
        assert snapshot.active_students() == ()


class TestStudentRef:
    def test_display_prefers_name_and_falls_back_to_register_number(self) -> None:
        assert StudentRef(id=fx.S1, register_no="RA001", name="Asha").display == "Asha"
        assert StudentRef(id=fx.S1, register_no="RA001").display == "RA001"

    def test_register_number_is_normalised_to_upper_case(self) -> None:
        assert StudentRef(id=fx.S1, register_no=" ra001 ").register_no == "RA001"
