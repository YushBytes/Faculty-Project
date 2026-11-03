"""The platform-to-analytics mapping, proved without a database.

`snapshot_from_offering_results` is pure, so every field can be checked by handing it a
constructed `OfferingResults` — which is worth doing precisely because this is the one file
where a value could be read from the wrong column and every number downstream would still
look plausible.

The database-backed half (`AnalyticsRepository`, which calls the platform's service and then
this mapper) needs PostgreSQL and is covered by the platform's own service tests plus the
scoping rules in contract C6.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.analytics.core.contracts import ResultStatus
from app.modules.analytics.core.policy import DerivedState, build_student_series
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSource
from app.modules.analytics.repository import (
    AnalyticsRepository,
    snapshot_from_offering_results,
)
from app.modules.assessments.models import AssessmentType
from app.modules.assessments.models import ResultStatus as StoredResultStatus
from app.modules.assessments.schemas import (
    AssessmentRead,
    MatrixOffering,
    MatrixResult,
    MatrixStudent,
    OfferingResults,
)
from app.modules.students.models import EnrollmentStatus

NOW = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)
OFFERING_ID = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
DEPARTMENT_ID = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000002")
CT1_ID = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000001")
CT2_ID = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")
S1_ID = uuid.UUID("cccccccc-0000-4000-8000-000000000001")
S2_ID = uuid.UUID("cccccccc-0000-4000-8000-000000000002")


def assessment(
    assessment_id: uuid.UUID = CT1_ID,
    *,
    name: str = "CT1",
    sequence_no: int = 1,
    max_marks: str = "50.00",
    weightage: str = "15.00",
    held_on: date | None = date(2026, 8, 20),
    is_published: bool = True,
) -> AssessmentRead:
    return AssessmentRead(
        id=assessment_id,
        offering_id=OFFERING_ID,
        name=name,
        assessment_type=AssessmentType.CT,
        assessment_date=held_on,
        max_marks=Decimal(max_marks),
        weightage=Decimal(weightage),
        sequence_no=sequence_no,
        is_published=is_published,
        created_at=NOW,
        updated_at=NOW,
    )


def student(
    student_id: uuid.UUID = S1_ID,
    *,
    register_number: str = "RA2511003010001",
    full_name: str = "Test Student",
    enrollment_status: EnrollmentStatus = EnrollmentStatus.ACTIVE,
    is_active: bool = True,
) -> MatrixStudent:
    return MatrixStudent(
        id=student_id,
        register_number=register_number,
        full_name=full_name,
        enrollment_status=enrollment_status,
        is_active=is_active,
    )


def result(
    *,
    student_id: uuid.UUID = S1_ID,
    assessment_id: uuid.UUID = CT1_ID,
    status: StoredResultStatus = StoredResultStatus.PRESENT,
    score: str | None = "40.00",
    max_marks_snapshot: str = "50.00",
    percentage: str | None = "80.00",
) -> MatrixResult:
    return MatrixResult(
        student_id=student_id,
        assessment_id=assessment_id,
        status=status,
        score=Decimal(score) if score is not None else None,
        max_marks_snapshot=Decimal(max_marks_snapshot),
        percentage=Decimal(percentage) if percentage is not None else None,
    )


def offering_results(
    *,
    assessments: list[AssessmentRead] | None = None,
    students: list[MatrixStudent] | None = None,
    results: list[MatrixResult] | None = None,
    pass_percent: str = "50.00",
    config: dict | None = None,
) -> OfferingResults:
    return OfferingResults(
        offering=MatrixOffering(
            id=OFFERING_ID,
            course_code="21CSC201J",
            section_name="A1",
            term_code="2026-ODD",
            pass_percent=Decimal(pass_percent),
            config=config or {},
            department_id=DEPARTMENT_ID,
        ),
        assessments=assessments if assessments is not None else [assessment()],
        students=students if students is not None else [student()],
        results=results if results is not None else [result()],
    )


class TestTheStatusVocabularyMatches:
    def test_the_platform_and_analytics_agree_on_every_stored_status(self) -> None:
        """If the platform adds a status, analytics must decide what it means for a mean.

        This assertion is the tripwire: it fails on the day a fourth status appears, which is
        far better than a mapping that quietly treats it as "not assessed".
        """
        assert {s.value for s in StoredResultStatus} == {s.value for s in ResultStatus}


class TestFieldMapping:
    def test_the_offerings_pass_mark_comes_from_the_offering(self) -> None:
        snapshot = snapshot_from_offering_results(offering_results(pass_percent="33.50"))
        assert snapshot.pass_mark_percent == Decimal("33.50")
        assert snapshot.offering_id == OFFERING_ID

    def test_an_assessment_keeps_its_name_marks_weight_date_and_order(self) -> None:
        snapshot = snapshot_from_offering_results(offering_results())
        mapped = snapshot.assessments[0]
        assert mapped.code == "CT1"
        assert mapped.max_marks == Decimal("50.00")
        assert mapped.weightage == Decimal("15.00")
        assert mapped.held_on == date(2026, 8, 20)
        assert mapped.sequence_no == 1
        assert mapped.is_published is True

    def test_a_long_or_mixed_case_assessment_name_survives_intact(self) -> None:
        """The platform allows 100 characters of free text; the label must not be mangled."""
        name = "Unit Test 2 (retest for students who missed the original sitting) - Section A1"
        snapshot = snapshot_from_offering_results(
            offering_results(assessments=[assessment(name=name)])
        )
        assert snapshot.assessments[0].code == name

    def test_a_present_result_keeps_its_score(self) -> None:
        snapshot = snapshot_from_offering_results(offering_results())
        assert snapshot.results[0].status is ResultStatus.PRESENT
        assert snapshot.results[0].score == Decimal("40.00")

    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            (StoredResultStatus.ABSENT, ResultStatus.ABSENT),
            (StoredResultStatus.EXEMPT, ResultStatus.EXEMPT),
        ],
    )
    def test_a_no_score_result_arrives_without_one(
        self, stored: StoredResultStatus, expected: ResultStatus
    ) -> None:
        snapshot = snapshot_from_offering_results(
            offering_results(results=[result(status=stored, score=None, percentage=None)])
        )
        assert snapshot.results[0].status is expected
        assert snapshot.results[0].score is None

    def test_a_student_with_no_row_is_missing_rather_than_absent(self) -> None:
        snapshot = snapshot_from_offering_results(
            offering_results(
                assessments=[assessment(), assessment(CT2_ID, name="CT2", sequence_no=2)],
                results=[result()],
            )
        )
        states = [p.state for p in build_student_series(snapshot, S1_ID).points]
        assert states == [DerivedState.ASSESSED, DerivedState.MISSING]

    def test_the_percentage_is_recomputed_not_copied(self) -> None:
        """One rounding rule in the system. A wrong stored percentage must not be believed."""
        snapshot = snapshot_from_offering_results(
            offering_results(results=[result(score="40.00", percentage="99.99")])
        )
        series = build_student_series(snapshot, S1_ID)
        assert series.percentages == (Decimal("80.00"),), "40 of 50 is 80%, whatever was stored"


class TestCohortMembership:
    def test_an_enrolled_active_student_is_in_the_cohort(self) -> None:
        snapshot = snapshot_from_offering_results(offering_results())
        assert snapshot.active_students()[0].register_no == "RA2511003010001"

    def test_a_dropped_student_is_kept_but_left_out_of_the_cohort(self) -> None:
        """Their results are history and stay readable; class statistics are not over them."""
        snapshot = snapshot_from_offering_results(
            offering_results(
                students=[student(enrollment_status=EnrollmentStatus.DROPPED)],
            )
        )
        assert snapshot.students[0].is_active is False
        assert snapshot.active_students() == ()

    def test_a_deactivated_student_record_is_also_out(self) -> None:
        snapshot = snapshot_from_offering_results(
            offering_results(students=[student(is_active=False)])
        )
        assert snapshot.active_students() == ()

    def test_both_flags_must_hold(self) -> None:
        snapshot = snapshot_from_offering_results(
            offering_results(
                students=[
                    student(S1_ID, register_number="RA0000000000001"),
                    student(
                        S2_ID,
                        register_number="RA0000000000002",
                        enrollment_status=EnrollmentStatus.DROPPED,
                        is_active=True,
                    ),
                ],
                results=[result()],
            )
        )
        assert [s.is_active for s in snapshot.students] == [True, False]


class TestDataIntegrityGuards:
    def test_a_result_recorded_against_a_different_maximum_is_refused(self) -> None:
        """The platform guarantees max_marks cannot move once results exist.

        If that guarantee is ever broken, the score's denominator is ambiguous, and guessing
        would silently change a student's percentage. Fail loudly instead.
        """
        with pytest.raises(ValueError, match="data inconsistency"):
            snapshot_from_offering_results(
                offering_results(results=[result(max_marks_snapshot="100.00")])
            )

    def test_an_empty_offering_maps_to_an_empty_snapshot(self) -> None:
        snapshot = snapshot_from_offering_results(
            offering_results(assessments=[], students=[], results=[])
        )
        assert snapshot.assessments == ()
        assert snapshot.students == ()
        assert snapshot.results == ()


class TestThresholdWiring:
    """C5's stored layers, wired to the resolver.

    The repository is constructed without a session and its settings reader replaced: the
    wiring under test is "offering config beats department settings beats the defaults", and
    that does not need a database to prove.
    """

    def repository(self, settings: dict) -> AnalyticsRepository:
        repo = AnalyticsRepository.__new__(AnalyticsRepository)
        repo._settings = _StubSettings(settings)  # type: ignore[attr-defined]
        return repo

    def test_an_offering_config_key_overrides_everything(self) -> None:
        resolved = self.repository({}).thresholds_from(
            offering_results(config={"trend_delta_pp": "8"})
        )
        assert resolved.value(ThresholdKey.TREND_DELTA_PP) == Decimal("8")
        assert resolved.source(ThresholdKey.TREND_DELTA_PP) is ThresholdSource.OFFERING_OVERRIDE

    def test_a_department_setting_is_used_when_the_offering_is_silent(self) -> None:
        resolved = self.repository({"borderline_band_pp": "3"}).thresholds_from(offering_results())
        assert resolved.value(ThresholdKey.BORDERLINE_BAND_PP) == Decimal("3")
        assert resolved.source(ThresholdKey.BORDERLINE_BAND_PP) is (
            ThresholdSource.DEPARTMENT_SETTING
        )

    def test_the_offering_wins_over_the_department(self) -> None:
        resolved = self.repository({"low_performance_percent": "45"}).thresholds_from(
            offering_results(config={"low_performance_percent": "55"})
        )
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("55")

    def test_the_pass_mark_comes_from_the_offering_column_not_the_config(self) -> None:
        resolved = self.repository({}).thresholds_from(offering_results(pass_percent="45.00"))
        assert resolved.pass_mark_percent == Decimal("45.00")

    def test_a_setting_analytics_does_not_know_is_ignored_and_reported(self) -> None:
        """A newer configuration document must not break an older deployment."""
        resolved = self.repository({}).thresholds_from(
            offering_results(config={"TREND_DELTA": 4, "trend_delta_pp": "6"})
        )
        assert resolved.value(ThresholdKey.TREND_DELTA_PP) == Decimal("6")
        assert resolved.ignored_keys == ("TREND_DELTA",)


class _StubSettings:
    def __init__(self, values: dict) -> None:
        self._values = values

    def as_dict(self, department_id: uuid.UUID) -> dict:
        assert department_id == DEPARTMENT_ID
        return self._values
