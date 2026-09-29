"""The real C4 recompute: attention flags materialised on the results write path.

Every test drives the *platform's own* write endpoint rather than calling the hook by hand,
because the thing under test is the integration: Agent 1 calls the hook inside its transaction,
and the flags have to land with the results that caused them.

Note on the fixtures: a student with **no** result has 0% completion and fires R6, so every
write below records a result for the whole cohort. Leaving one out would flag them for something
the test was not about.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.recompute import recompute, reset_recompute, set_recompute
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity, FlagStatus
from app.modules.analytics.recompute import recompute_assessment, recompute_offering
from app.modules.assessments.models import Assessment
from app.modules.attention.models import AttentionFlag
from app.modules.organization.models import AcademicTerm, CourseOffering, Department, Section
from app.modules.users.models import User
from tests.conftest import AssessmentFactory, OrgFactory, StudentFactory, auth_headers

LOW_SCORE = "10"  # 20% of 50: below the 50% low-performance threshold and the 50% pass mark
HIGH_SCORE = "45"  # 90%: clears both

R1 = AttentionRuleCode.R1_LOW_PERFORMANCE
R2 = AttentionRuleCode.R2_FAILED_LATEST


class Cohort:
    """One offering, one published assessment, a struggling student and a thriving one."""

    def __init__(
        self,
        offering: CourseOffering,
        assessment: Assessment,
        struggling: uuid.UUID,
        thriving: uuid.UUID,
    ) -> None:
        self.offering = offering
        self.assessment = assessment
        self.struggling = struggling
        self.thriving = thriving

    def entries(self, struggling: str, thriving: str) -> list[dict[str, object]]:
        return [
            {"student_id": str(self.struggling), "score": struggling},
            {"student_id": str(self.thriving), "score": thriving},
        ]


@pytest.fixture
def cohort(
    db_session: Session,
    cse_offering: CourseOffering,
    cse: Department,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
) -> Cohort:
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    struggling = make_student(cse, section, enroll_in=[cse_offering])
    thriving = make_student(cse, section, enroll_in=[cse_offering])
    return Cohort(
        cse_offering,
        make_assessment(cse_offering, "CT1", max_marks="50"),
        struggling.id,
        thriving.id,
    )


def put_results(
    client: TestClient, assessment: Assessment, actor: User, entries: list[dict[str, object]]
) -> None:
    response = client.put(
        f"/api/v1/assessments/{assessment.id}/results",
        json={"results": entries},
        headers=auth_headers(actor),
    )
    assert response.status_code == 200, response.text


def record(
    client: TestClient,
    cohort: Cohort,
    actor: User,
    *,
    struggling: str,
    thriving: str = HIGH_SCORE,
) -> None:
    """Record a result for the whole cohort, so nobody is flagged for incompleteness."""
    put_results(client, cohort.assessment, actor, cohort.entries(struggling, thriving))


def flags_of(session: Session, offering_id: uuid.UUID) -> list[AttentionFlag]:
    return list(
        session.scalars(
            select(AttentionFlag)
            .where(AttentionFlag.offering_id == offering_id)
            .order_by(AttentionFlag.student_id, AttentionFlag.rule_code, AttentionFlag.created_at)
        ).all()
    )


def live_of(session: Session, offering_id: uuid.UUID) -> list[AttentionFlag]:
    return [row for row in flags_of(session, offering_id) if row.status is not FlagStatus.RESOLVED]


def probe_flag(offering_id: uuid.UUID, student_id: uuid.UUID, message: str) -> AttentionFlag:
    """A hand-built flag, for exercising database constraints directly."""
    return AttentionFlag(
        offering_id=offering_id,
        student_id=student_id,
        rule_code=R1,
        severity=FlagSeverity.HIGH,
        actual_value=20,
        actual_unit="percent",
        actual_n=1,
        pass_mark_percent=50,
        message=message,
        computed_at=datetime.now(UTC),
    )


class TestFlagsAreMaterialised:
    def test_results_write_persists_the_flags_that_fired(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=LOW_SCORE)

        live = live_of(db_session, cohort.offering.id)
        assert {row.student_id for row in live} == {cohort.struggling}, (
            "only the struggling student should be flagged"
        )
        assert {row.rule_code for row in live} >= {R1, R2}

    def test_a_flag_carries_the_decision_that_produced_it(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        """D6's persisted fields, and enough of them to explain the flag a semester later."""
        record(client, cohort, faculty, struggling=LOW_SCORE)
        live = live_of(db_session, cohort.offering.id)

        r1 = next(row for row in live if row.rule_code is R1)
        assert r1.severity is FlagSeverity.HIGH
        assert r1.status is FlagStatus.OPEN
        assert float(r1.actual_value) == pytest.approx(20, abs=0.01)
        assert r1.actual_unit is not None
        assert r1.actual_n >= 1
        assert float(r1.threshold_value) == pytest.approx(50, abs=0.01)
        assert r1.threshold_source is not None
        assert "CT1" in r1.reference_assessments
        assert r1.message.strip()
        assert r1.resolved_at is None
        assert r1.triggered_by_assessment_id == cohort.assessment.id

        # R2 compares against the offering's pass mark, so it quotes that instead of a threshold.
        r2 = next(row for row in live if row.rule_code is R2)
        assert r2.threshold_key is None
        assert r2.pass_mark_percent is not None

    def test_nothing_is_written_when_no_rule_fires(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=HIGH_SCORE)
        assert live_of(db_session, cohort.offering.id) == []

    def test_an_unassessed_student_is_flagged_for_completion(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        """The other side of the fixture note: missing is not zero, but it is not nothing."""
        put_results(
            client,
            cohort.assessment,
            faculty,
            [{"student_id": str(cohort.thriving), "score": HIGH_SCORE}],
        )
        live = live_of(db_session, cohort.offering.id)
        assert {row.rule_code for row in live if row.student_id == cohort.struggling} == {
            AttentionRuleCode.R6_LOW_COMPLETION
        }


class TestIdempotence:
    def test_recomputing_unchanged_data_twice_adds_no_rows(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=LOW_SCORE)
        first = {row.id: row.created_at for row in live_of(db_session, cohort.offering.id)}
        assert first

        recompute_assessment(db_session, cohort.assessment.id)
        recompute_assessment(db_session, cohort.assessment.id)

        second = {row.id: row.created_at for row in live_of(db_session, cohort.offering.id)}
        assert second == first, "a repeated recompute must reuse the same rows, not insert new ones"
        assert len(flags_of(db_session, cohort.offering.id)) == len(first), "no resolved duplicates"

    def test_repeated_recompute_reports_nothing_raised_or_resolved(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=LOW_SCORE)
        again = recompute_offering(db_session, cohort.offering.id, cohort.assessment.id)
        assert again.flags_raised == 0
        assert again.flags_resolved == 0
        assert again.students_evaluated == 2

    def test_the_database_refuses_a_duplicate_live_flag(
        self, db_session: Session, cohort: Cohort
    ) -> None:
        """Idempotence is enforced by the partial unique index, not only by the Python path."""
        db_session.add(probe_flag(cohort.offering.id, cohort.struggling, "first"))
        db_session.flush()
        db_session.add(probe_flag(cohort.offering.id, cohort.struggling, "duplicate"))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_resolved_flag_does_not_block_the_rule_firing_again(
        self, db_session: Session, cohort: Cohort
    ) -> None:
        """The unique index is partial, which is what makes history and idempotence coexist."""
        earlier = probe_flag(cohort.offering.id, cohort.struggling, "earlier occurrence")
        earlier.status = FlagStatus.RESOLVED
        earlier.resolved_at = datetime.now(UTC)
        db_session.add(earlier)
        db_session.flush()

        db_session.add(probe_flag(cohort.offering.id, cohort.struggling, "fires again"))
        db_session.flush()  # must not raise
        assert len(flags_of(db_session, cohort.offering.id)) == 2


class TestResolution:
    def test_a_flag_that_stops_firing_is_resolved_not_left_active(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=LOW_SCORE)
        raised = {row.id for row in live_of(db_session, cohort.offering.id)}
        assert raised

        # The student re-sits and clears the mark: the rules no longer fire.
        record(client, cohort, faculty, struggling=HIGH_SCORE)

        assert live_of(db_session, cohort.offering.id) == [], "stale flags must not remain active"
        resolved = flags_of(db_session, cohort.offering.id)
        assert {row.id for row in resolved} == raised, "resolved in place, not deleted and replaced"
        assert all(row.status is FlagStatus.RESOLVED for row in resolved)
        assert all(row.resolved_at is not None for row in resolved)

    def test_history_survives_recompute(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        """D6: a flag that fires, clears, then fires again leaves two rows, not one rewritten."""
        record(client, cohort, faculty, struggling=LOW_SCORE)
        record(client, cohort, faculty, struggling=HIGH_SCORE)
        record(client, cohort, faculty, struggling=LOW_SCORE)

        occurrences = [
            row for row in flags_of(db_session, cohort.offering.id) if row.rule_code is R1
        ]
        assert len(occurrences) == 2, "the earlier occurrence is kept as history"
        assert sorted(row.status.value for row in occurrences) == ["open", "resolved"]

    def test_acknowledgement_is_not_undone_by_a_recompute(
        self, client: TestClient, db_session: Session, faculty: User, cohort: Cohort
    ) -> None:
        record(client, cohort, faculty, struggling=LOW_SCORE)
        flag = next(row for row in live_of(db_session, cohort.offering.id) if row.rule_code is R1)
        flag.status = FlagStatus.ACKNOWLEDGED
        db_session.flush()

        recompute_assessment(db_session, cohort.assessment.id)
        db_session.refresh(flag)
        assert flag.status is FlagStatus.ACKNOWLEDGED, (
            "a still-firing flag someone has read must not silently reopen"
        )


class TestScopeAndSafety:
    def test_recompute_touches_only_the_offering_that_changed(
        self,
        client: TestClient,
        db_session: Session,
        cse: Department,
        org: OrgFactory,
        faculty: User,
        term: AcademicTerm,
        make_student: StudentFactory,
        make_assessment: AssessmentFactory,
        cohort: Cohort,
    ) -> None:
        other = org.offering(org.course(cse), org.section(cse), term, faculty=[faculty])
        other_student = make_student(cse, enroll_in=[other])
        other_assessment = make_assessment(other, "CT1", max_marks="50")
        put_results(
            client,
            other_assessment,
            faculty,
            [{"student_id": str(other_student.id), "score": LOW_SCORE}],
        )
        before = {row.id: row.computed_at for row in flags_of(db_session, other.id)}
        assert before

        record(client, cohort, faculty, struggling=LOW_SCORE)

        assert {row.id: row.computed_at for row in flags_of(db_session, other.id)} == before, (
            "the other offering's flags must not be re-derived, restamped or resolved"
        )

    def test_a_deleted_assessment_is_a_no_op(self, db_session: Session) -> None:
        """POST /admin/recompute walks assessments; one going away must not abort the write."""
        assert recompute_assessment(db_session, uuid.uuid4()) is None

    def test_the_hook_does_not_commit(self, db_session: Session, cohort: Cohort) -> None:
        """Contract C4/D-003: the caller owns the transaction, so its rollback discards flags."""
        db_session.add(probe_flag(cohort.offering.id, cohort.struggling, "rolled back"))
        db_session.flush()
        assert live_of(db_session, cohort.offering.id)

        db_session.rollback()
        assert flags_of(db_session, cohort.offering.id) == []


class TestHookIsolation:
    """The hook's own plumbing, which decides whether every test above means anything.

    A test that borrows the hook must not be able to leave analytics disabled for whatever runs
    next. Before this was fixed, ``reset_recompute()`` restored the platform's no-op, so the first
    suite to install a spy silently switched off persistence for the rest of the session and the
    assertions above passed vacuously against an empty table.
    """

    def test_reset_restores_the_installed_implementation_not_the_noop(self) -> None:
        set_recompute(lambda session, assessment_id: None)
        reset_recompute()
        assert recompute.__module__ == "app.core.recompute"
        from app.core import recompute as hook

        assert hook._impl is recompute_assessment

    def test_reset_is_idempotent_and_safe_with_nothing_replaced(self) -> None:
        """Fixture teardown calls it whether or not that test installed a spy."""
        from app.core import recompute as hook

        reset_recompute()
        reset_recompute()
        assert hook._impl is recompute_assessment

    def test_a_spy_still_replaces_the_hook_while_it_is_installed(self) -> None:
        """Agent 1's suites depend on this half: the replacement must actually take effect."""
        from app.core import recompute as hook

        calls: list[uuid.UUID] = []
        set_recompute(lambda session, assessment_id: calls.append(assessment_id))
        try:
            assert hook._impl is not recompute_assessment
            hook.recompute(None, uuid.uuid4())  # type: ignore[arg-type]
            assert len(calls) == 1
        finally:
            reset_recompute()
        assert hook._impl is recompute_assessment
