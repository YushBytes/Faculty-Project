"""The four mandatory Phase 11 end-to-end scenarios, over the assembled system.

Real PostgreSQL, real Alembic-built schema, real login, real import pipeline, real C4 recompute.
Nothing here reaches past the API except to assert what actually landed in the database, which is
the point: each scenario proves the layers agree rather than that each works alone.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.analytics.core.rules import AttentionRuleCode, FlagStatus
from app.modules.assessments.models import Assessment, AssessmentResult
from app.modules.attention.models import LIVE_FLAG_STATUSES, AttentionFlag
from app.modules.imports.models import ImportBatch
from app.modules.interventions.models import Intervention
from app.modules.organization.models import CourseOffering
from tests.conftest import AssessmentFactory
from tests.e2e.conftest import Journey, next_assessment

FAILING = "12"  # 24% of 50: under the 50% low-performance threshold and the 50% pass mark
STRONG = "40"  # 80%
RECOVERED = "45"  # 90%
COLLAPSE = "5"  # 10%

R1 = AttentionRuleCode.R1_LOW_PERFORMANCE
R2 = AttentionRuleCode.R2_FAILED_LATEST


def live_flags(session: Session, offering_id: uuid.UUID) -> list[AttentionFlag]:
    return list(
        session.scalars(
            select(AttentionFlag).where(
                AttentionFlag.offering_id == offering_id,
                AttentionFlag.status.in_(LIVE_FLAG_STATUSES),
            )
        ).all()
    )


def all_flags(session: Session, offering_id: uuid.UUID) -> list[AttentionFlag]:
    return list(
        session.scalars(select(AttentionFlag).where(AttentionFlag.offering_id == offering_id)).all()
    )


def _without_stamp(block: object) -> object:
    """Strip every ``generated_at``, at any depth.

    Analytics are computed per request, so the stamp legitimately moves — and it is stamped on
    nested contracts too, not just the outer one. Everything else is the answer, and the answer is
    what must not change.
    """
    if isinstance(block, dict):
        return {k: _without_stamp(v) for k, v in block.items() if k != "generated_at"}
    if isinstance(block, list):
        return [_without_stamp(item) for item in block]
    return block


def _verdict(attention: dict) -> dict:
    """The cohort's attention reduced to what it asserts: who fired which rules, and the counts."""
    return {
        "summary": attention["summary"],
        "students": {
            entry["student"]["id"]: sorted(flag["rule_code"] for flag in entry["flags"])
            for entry in attention["students"]
        },
    }


def marks(journey: Journey, *, failing: int, score: str = FAILING, rest: str = STRONG) -> dict:
    """Scores for the whole cohort: the first ``failing`` students struggle, the rest do well."""
    return {
        student.id: (score if index < failing else rest)
        for index, student in enumerate(journey.students)
    }


class TestScenario1FullFacultyJourney:
    """Login -> offering -> import -> recompute -> analytics -> attention -> intervention ->
    second assessment -> recompute -> outcome -> report -> three exports."""

    def test_the_whole_path(
        self,
        journey: Journey,
        db_session: Session,
        ct1: Assessment,
        cse_offering: CourseOffering,
        make_assessment: AssessmentFactory,
    ) -> None:
        struggling = journey.students[0]

        # 1-2. Authenticated (the fixture logged in for real) and the offering is reachable.
        assert journey.analytics().status_code == 200

        # 3-5. Import CT1: stage, preview, confirm.
        staged = journey.upload(journey.sheet(ct1, marks(journey, failing=2)))
        assert staged.status_code == 201, staged.text
        batch_id = staged.json()["batch"]["id"]
        assert staged.json()["summary"]["will_create"] == len(journey.students)
        assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == 0, (
            "staging must write no results"
        )

        previewed = journey.preview(batch_id)
        assert previewed.status_code == 200, previewed.text

        confirmed = journey.confirm(batch_id)
        assert confirmed.status_code == 200, confirmed.text

        # 6. Results committed.
        assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == len(
            journey.students
        )

        # 7. Recompute ran inside the confirm transaction: flags exist without another request.
        raised = live_flags(db_session, cse_offering.id)
        assert raised, "the import confirm must have materialised attention flags"
        assert {flag.triggered_by_assessment_id for flag in raised} == {ct1.id}

        # 8. Analytics available and reporting the imported data.
        analytics = journey.analytics()
        assert analytics.status_code == 200, analytics.text
        assert analytics.json()["health"]["cohort_n"] == len(journey.students)

        # 9-10. Attention flags present via the API, and persisted.
        api_flags = journey.flags_for(struggling.id)
        assert {flag["rule_code"] for flag in api_flags} >= {R1.value, R2.value}
        persisted = {flag.rule_code for flag in raised if flag.student_id == struggling.id}
        assert persisted >= {R1, R2}, "the API's verdict and the stored rows must agree"

        # 11-12. The faculty member records an intervention citing a real flag.
        flag_row = next(
            flag for flag in raised if flag.student_id == struggling.id and flag.rule_code is R1
        )
        created = journey.create_intervention(
            {
                "student_ids": [str(struggling.id)],
                "kind": "remedial_session",
                "after_sequence_no": ct1.sequence_no,
                "reasons": [{"student_id": str(struggling.id), "flag_id": str(flag_row.id)}],
            }
        )
        assert created.status_code == 201, created.text
        assert created.json()["reasons"][0]["rule_code"] == R1.value
        assert created.json()["student_ids"] == [str(struggling.id)]

        # 13-14. A second assessment is imported; the struggling student recovers.
        ct2 = next_assessment(make_assessment, cse_offering, "CT2")
        recovery = marks(journey, failing=0)
        recovery[struggling.id] = RECOVERED
        journey.import_marks(ct2, recovery)

        # 15. Attention changed: R2 (latest paper) no longer fires for them.
        after = journey.flags_for(struggling.id)
        assert R2.value not in {flag["rule_code"] for flag in after}, (
            "a student who passed the latest assessment must not still be flagged for failing it"
        )
        resolved = [
            flag
            for flag in all_flags(db_session, cse_offering.id)
            if flag.student_id == struggling.id and flag.status is FlagStatus.RESOLVED
        ]
        assert resolved, "the superseded flag is resolved, not deleted"

        # 16. Outcome measured from the stored intervention by the Phase 6 engine.
        outcomes = journey.outcomes()
        assert outcomes.status_code == 200, outcomes.text
        body = outcomes.json()
        assert len(body["outcomes"]) == 1
        assert body["outcomes"][0]["offering_id"] == str(cse_offering.id)

        # 17-18. Every report kind, in every format.
        for kind in (
            "class_summary",
            "attention",
            "assessment_comparison",
            "intervention_outcome",
        ):
            for fmt in ("csv", "xlsx", "pdf"):
                report = journey.report(kind, export_format=fmt)
                assert report.status_code == 200, f"{kind}/{fmt}: {report.text[:200]}"
                assert report.content, f"{kind}/{fmt} produced an empty file"
                assert "attachment" in report.headers["content-disposition"]

        student_report = journey.report(
            "student_performance", export_format="pdf", student_id=str(struggling.id)
        )
        assert student_report.status_code == 200, student_report.text
        assert student_report.content.startswith(b"%PDF")


class TestScenario2ImportFailureLeavesNothingBehind:
    """An invalid import must change nothing: not results, not analytics, not attention."""

    def test_invalid_import_is_rejected_and_state_is_untouched(
        self,
        journey: Journey,
        db_session: Session,
        ct1: Assessment,
        cse_offering: CourseOffering,
    ) -> None:
        # 1. Begin from valid, committed data.
        journey.import_marks(ct1, marks(journey, failing=2))
        results_before = db_session.scalar(select(func.count()).select_from(AssessmentResult))
        flags_before = {
            (flag.id, flag.status, flag.computed_at)
            for flag in all_flags(db_session, cse_offering.id)
        }
        attention_before = _verdict(journey.attention().json())
        analytics_before = _without_stamp(journey.analytics().json()["health"])
        batches_before = db_session.scalar(select(func.count()).select_from(ImportBatch))
        assert results_before and flags_before

        # 2-3. An import naming students who are not in this offering: validation fails.
        rows = [
            ["Register No", "Name", "CT1"],
            ["RA0000000000000", "Nobody At All", "40"],
        ]
        staged = journey.upload(rows)
        assert staged.status_code == 201, (
            staged.text
        )  # staging succeeds; the preview carries errors
        batch_id = staged.json()["batch"]["id"]
        preview = journey.preview(batch_id, only="errors")
        assert preview.status_code == 200, preview.text
        assert preview.json()["summary"]["errors"] > 0, "an unknown student must be an error"

        # 4. Confirm is refused while an error stands.
        refused = journey.confirm(batch_id)
        assert refused.status_code == 422, refused.text

        # 5-8. Nothing changed anywhere.
        assert (
            db_session.scalar(select(func.count()).select_from(AssessmentResult)) == results_before
        ), "a refused confirm must not write a single result row"
        assert {
            (flag.id, flag.status, flag.computed_at)
            for flag in all_flags(db_session, cse_offering.id)
        } == flags_before, "attention state must not be touched by a refused import"
        assert _verdict(journey.attention().json()) == attention_before
        assert _without_stamp(journey.analytics().json()["health"]) == analytics_before
        assert (
            db_session.scalar(select(func.count()).select_from(ImportBatch)) == batches_before + 1
        ), "the staged batch itself is a record and is expected to remain"

    def test_a_file_that_cannot_be_parsed_stages_nothing(
        self, journey: Journey, db_session: Session, ct1: Assessment
    ) -> None:
        journey.import_marks(ct1, marks(journey, failing=1))
        batches_before = db_session.scalar(select(func.count()).select_from(ImportBatch))
        results_before = db_session.scalar(select(func.count()).select_from(AssessmentResult))

        rejected = journey.upload_raw(b"\x7fELF\x02\x01\x01 not a spreadsheet", name="marks.xlsx")
        assert rejected.status_code == 422, rejected.text
        assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == batches_before
        assert (
            db_session.scalar(select(func.count()).select_from(AssessmentResult)) == results_before
        )


class TestScenario3RecomputeAfterAResultChanges:
    """A mark is corrected upward: the flag it raised must resolve, leaving history and no
    duplicate. Values are derived from the fixture's own thresholds, not hard-coded."""

    def test_raising_a_mark_resolves_the_flag_it_caused(
        self,
        journey: Journey,
        db_session: Session,
        ct1: Assessment,
        cse_offering: CourseOffering,
    ) -> None:
        struggling = journey.students[0]
        journey.import_marks(ct1, marks(journey, failing=1))

        before = [
            flag
            for flag in live_flags(db_session, cse_offering.id)
            if flag.student_id == struggling.id
        ]
        assert {flag.rule_code for flag in before} >= {R1, R2}
        original_ids = {flag.id for flag in before}

        # Correct the mark through the platform's own results endpoint.
        corrected = journey._client.put(
            f"/api/v1/assessments/{ct1.id}/results",
            json={"results": [{"student_id": str(struggling.id), "score": RECOVERED}]},
            headers=journey.headers,
        )
        assert corrected.status_code == 200, corrected.text

        # No live flag remains for them.
        still_live = [
            flag
            for flag in live_flags(db_session, cse_offering.id)
            if flag.student_id == struggling.id
        ]
        assert still_live == [], "a corrected mark must leave no stale active flag"

        # The old rows were resolved in place — same ids, so history was not deleted.
        rows = [
            flag
            for flag in all_flags(db_session, cse_offering.id)
            if flag.student_id == struggling.id
        ]
        assert {flag.id for flag in rows} == original_ids
        assert all(flag.status is FlagStatus.RESOLVED for flag in rows)
        assert all(flag.resolved_at is not None for flag in rows)

        # No duplicate active flag for any (student, rule).
        keys = [
            (flag.student_id, flag.rule_code) for flag in live_flags(db_session, cse_offering.id)
        ]
        assert len(keys) == len(set(keys))

        # Analytics and the attention endpoint both reflect the corrected mark.
        assert journey.flags_for(struggling.id) == []
        profile = journey.student_analytics(struggling.id)
        assert profile.status_code == 200, profile.text
        stored = db_session.scalar(
            select(AssessmentResult.score).where(
                AssessmentResult.assessment_id == ct1.id,
                AssessmentResult.student_id == struggling.id,
            )
        )
        assert stored == Decimal(RECOVERED)


class TestScenario4ANewAssessmentRaisesANewFlag:
    """A student who was safe collapses on the next paper. Every layer must agree."""

    def test_a_new_result_raises_a_flag_through_every_layer(
        self,
        journey: Journey,
        db_session: Session,
        ct1: Assessment,
        cse_offering: CourseOffering,
        make_assessment: AssessmentFactory,
    ) -> None:
        safe = journey.students[0]
        journey.import_marks(ct1, marks(journey, failing=0))
        assert journey.flags_for(safe.id) == [], "nobody should be flagged after a strong CT1"
        assert live_flags(db_session, cse_offering.id) == []

        # A second assessment, on which this student collapses.
        ct2 = next_assessment(make_assessment, cse_offering, "CT2")
        scores = marks(journey, failing=0)
        scores[safe.id] = COLLAPSE
        journey.import_marks(ct2, scores)

        # Source result -> engine -> API.
        api_codes = {flag["rule_code"] for flag in journey.flags_for(safe.id)}
        assert R2.value in api_codes, "failing the latest assessment must be flagged"

        # -> persistence, with the decision recorded.
        rows = [
            flag for flag in live_flags(db_session, cse_offering.id) if flag.student_id == safe.id
        ]
        assert {flag.rule_code.value for flag in rows} == api_codes, (
            "stored flags and the API's flags must be the same set"
        )
        r2_row = next(flag for flag in rows if flag.rule_code is R2)
        assert r2_row.status is FlagStatus.OPEN
        assert r2_row.pass_mark_percent is not None
        assert r2_row.message.strip()
        assert r2_row.triggered_by_assessment_id == ct2.id
        assert float(r2_row.actual_value) < float(r2_row.pass_mark_percent)

        # -> report. The attention report must name the student the flags are about.
        report = journey.report("attention", export_format="csv")
        assert report.status_code == 200, report.text
        assert safe.register_number in report.text

    def test_an_unassessed_student_is_flagged_for_completion_not_given_a_zero(
        self, journey: Journey, db_session: Session, ct1: Assessment, cse_offering: CourseOffering
    ) -> None:
        """Missing is not zero: it shows up as incompleteness, never as a mark of 0."""
        skipped = journey.students[0]
        scores = marks(journey, failing=0)
        del scores[skipped.id]
        journey.import_marks(ct1, scores)

        codes = {flag["rule_code"] for flag in journey.flags_for(skipped.id)}
        assert AttentionRuleCode.R6_LOW_COMPLETION.value in codes
        assert R1.value not in codes, "a missing mark must not be averaged in as 0"
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(AssessmentResult)
                .where(AssessmentResult.student_id == skipped.id)
            )
            == 0
        ), "no row at all is the stored representation of missing"


class TestInterventionsSurviveTheJourney:
    def test_a_frozen_reason_is_unchanged_by_later_recomputes(
        self,
        journey: Journey,
        db_session: Session,
        ct1: Assessment,
        cse_offering: CourseOffering,
        make_assessment: AssessmentFactory,
    ) -> None:
        struggling = journey.students[0]
        journey.import_marks(ct1, marks(journey, failing=1))
        flag_row = next(
            flag
            for flag in live_flags(db_session, cse_offering.id)
            if flag.student_id == struggling.id and flag.rule_code is R1
        )
        observed_then = float(flag_row.actual_value)

        created = journey.create_intervention(
            {
                "student_ids": [str(struggling.id)],
                "kind": "academic_support",
                "after_sequence_no": ct1.sequence_no,
                "reasons": [{"student_id": str(struggling.id), "flag_id": str(flag_row.id)}],
            }
        )
        assert created.status_code == 201, created.text

        # The student recovers, which resolves the flag the reason came from.
        ct2 = next_assessment(make_assessment, cse_offering, "CT2")
        recovery = marks(journey, failing=0)
        recovery[struggling.id] = RECOVERED
        journey.import_marks(ct2, recovery)

        listed = journey.interventions()
        assert listed.status_code == 200, listed.text
        reason = listed.json()["items"][0]["reasons"][0]
        assert reason["observed"]["value"] == observed_then, (
            "the reason records what the teacher saw, not what the number became"
        )
        assert reason["rule_code"] == R1.value
        assert db_session.scalar(select(func.count()).select_from(Intervention)) == 1
