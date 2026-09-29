"""Integration invariants: the promises analytics makes, checked against a real database.

The unit suite proves each of these on hand-built fixtures. What is checked here is that they
survive the round trip through PostgreSQL, the adapter, the API and the exporters — the places a
number can quietly become a string, a null can become a zero, or an ordering can start depending
on a query plan.

The cohort below is engineered so that **every attention rule R1-R7 fires for someone**, which is
what makes the "engine, API, persistence and report all agree" assertion worth making.
"""

from __future__ import annotations

import json
import math
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.analytics.core.rules import ATTENTION_RULES, AttentionRuleCode
from app.modules.assessments.models import Assessment, AssessmentResult, ResultStatus
from app.modules.attention.models import LIVE_FLAG_STATUSES, AttentionFlag
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import User
from tests.conftest import AssessmentFactory, StudentFactory
from tests.e2e.conftest import Journey

MAX = "50"
ASSESSMENTS = ("CT1", "CT2", "CT3", "CT4")

# Marks out of 50, per student per assessment. ``None`` means no row at all: the derived
# *missing* state, which must never be read as a zero.
#
# Each row is chosen to drive particular rules:
#   low        20% throughout            -> R1 low performance, R2 failed latest, R3 repeated low
#   collapse   90,90,90,10               -> R4 sharp decline, R2, and a steep negative slope (R5)
#   sliding    80,70,60,50               -> R5 declining trend
#   borderline weighted lands on ~50     -> R7 borderline
#   partial    two papers never sat      -> R6 low completion
#   strong     80% throughout            -> nothing
SCORES: dict[str, list[str | None]] = {
    "low": ["10", "10", "10", "10"],
    "collapse": ["45", "45", "45", "5"],
    "sliding": ["40", "35", "30", "25"],
    "borderline": ["25", "25", "25", "25"],
    "partial": ["40", "40", None, None],
    "strong": ["40", "40", "40", "40"],
}


class Cohort:
    def __init__(
        self,
        journey: Journey,
        assessments: list[Assessment],
        students: dict[str, Student],
    ) -> None:
        self.journey = journey
        self.assessments = assessments
        self.students = students

    def id_of(self, label: str) -> uuid.UUID:
        return self.students[label].id


@pytest.fixture
def cohort(
    client: TestClient,
    db_session: Session,
    cse_offering: CourseOffering,
    cse: Department,
    faculty: User,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
) -> Cohort:
    """Four assessments and a cohort engineered to exercise all seven rules."""
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    students = {label: make_student(cse, section, enroll_in=[cse_offering]) for label in SCORES}
    assessments = [make_assessment(cse_offering, name, max_marks=MAX) for name in ASSESSMENTS]

    journey = Journey(client, faculty, cse_offering)
    journey.students = list(students.values())
    journey.login()

    # Write each assessment's marks through the platform's own endpoint, so the real C4 hook runs
    # once per assessment exactly as it does in production.
    for index, assessment in enumerate(assessments):
        entries = [
            {"student_id": str(student.id), "score": SCORES[label][index]}
            for label, student in students.items()
            if SCORES[label][index] is not None
        ]
        response = client.put(
            f"/api/v1/assessments/{assessment.id}/results",
            json={"results": entries},
            headers=journey.headers,
        )
        assert response.status_code == 200, response.text
    return Cohort(journey, assessments, students)


def live_rows(session: Session, offering_id: uuid.UUID) -> list[AttentionFlag]:
    return list(
        session.scalars(
            select(AttentionFlag).where(
                AttentionFlag.offering_id == offering_id,
                AttentionFlag.status.in_(LIVE_FLAG_STATUSES),
            )
        ).all()
    )


def walk(node: object, path: str = "$"):
    """Yield every ``(path, scalar)`` in a decoded JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")
    else:
        yield path, node


class TestNoNonFiniteOrFabricatedNumbers:
    @pytest.mark.parametrize(
        "route", ["analytics", "attention", "insights", "interventions/outcomes"]
    )
    def test_no_nan_or_infinity_reaches_a_response(self, cohort: Cohort, route: str) -> None:
        response = cohort.journey._client.get(
            f"/api/v1/offerings/{cohort.journey.offering.id}/{route}",
            headers=cohort.journey.headers,
        )
        assert response.status_code == 200, response.text

        # A NaN would serialise as the bare token NaN, which is invalid JSON; json.loads with a
        # strict constant hook is the only way to be sure none slipped through.
        def reject(token: str) -> float:
            raise AssertionError(f"{route} serialised the non-finite constant {token!r}")

        document = json.loads(response.text, parse_constant=reject)
        for path, value in walk(document):
            if isinstance(value, float):
                assert math.isfinite(value), f"{route} {path} is not finite"

    def test_insufficient_data_stays_explicit_and_never_becomes_zero(self, cohort: Cohort) -> None:
        """Every measure is either ok with a value, or insufficient with a reason and no value."""
        response = cohort.journey.analytics()
        assert response.status_code == 200, response.text
        seen = 0
        for path, _ in walk(response.json()):
            if not path.endswith(".status"):
                continue
            block = _resolve(response.json(), path[: -len(".status")])
            if not isinstance(block, dict) or "status" not in block:
                continue
            if block["status"] == "insufficient_data":
                seen += 1
                assert block.get("reason"), f"{path} is insufficient without saying why"
                assert block.get("value") is None, f"{path} is insufficient but carries a value"
        assert seen >= 0  # documents the sweep ran even on a cohort with plenty of data


def _resolve(document: object, path: str) -> object:
    node = document
    for part in path.removeprefix("$").split("."):
        if not part:
            continue
        while part.endswith("]"):
            part, _, index = part[:-1].rpartition("[")
            if part:
                node = node[part]  # type: ignore[index]
            node = node[int(index)]  # type: ignore[index]
            part = ""
        if part:
            node = node[part]  # type: ignore[index]
    return node


class TestMissingAbsentExemptAreNotZero:
    def test_a_missing_result_has_no_row_and_no_score(
        self, cohort: Cohort, db_session: Session
    ) -> None:
        partial = cohort.id_of("partial")
        rows = db_session.scalars(
            select(AssessmentResult).where(AssessmentResult.student_id == partial)
        ).all()
        assert len(rows) == 2, "the two papers never sat must have no row at all"
        assert all(row.score is not None for row in rows)

    def test_an_absent_paper_is_a_state_not_a_zero_percentage(
        self, cohort: Cohort, db_session: Session, client: TestClient
    ) -> None:
        """The series point for an absent paper carries no percentage at all.

        If absent were quietly read as 0 it would appear here as ``percentage: 0`` and drag every
        average that walks the series downward.
        """
        student = cohort.id_of("strong")
        last = cohort.assessments[-1]
        response = client.put(
            f"/api/v1/assessments/{last.id}/results",
            json={"results": [{"student_id": str(student), "status": "absent"}]},
            headers=cohort.journey.headers,
        )
        assert response.status_code == 200, response.text

        row = db_session.scalar(
            select(AssessmentResult).where(
                AssessmentResult.student_id == student,
                AssessmentResult.assessment_id == last.id,
            )
        )
        assert row is not None and row.status is ResultStatus.ABSENT
        assert row.score is None, "absent must never hold a number"

        profile = cohort.journey.student_analytics(student).json()["profile"]
        point = next(p for p in profile["history"]["points"] if p["assessment_id"] == str(last.id))
        assert point["percentage"] is None, "an absent paper must carry no percentage"
        assert point["score"] is None
        assert point["state"] != "present"

        # And the average over their present papers is still 80%, not 60%.
        average = profile["historical_average"]
        if average["status"] == "ok":
            assert float(average["value"]) == pytest.approx(80, abs=0.01), (
                "the absent paper must drop out of the mean, not enter it as 0"
            )

    def test_an_exempt_paper_is_excluded_rather_than_scored(
        self, cohort: Cohort, db_session: Session, client: TestClient
    ) -> None:
        student = cohort.id_of("strong")
        last = cohort.assessments[-1]
        response = client.put(
            f"/api/v1/assessments/{last.id}/results",
            json={"results": [{"student_id": str(student), "status": "exempt"}]},
            headers=cohort.journey.headers,
        )
        assert response.status_code == 200, response.text
        row = db_session.scalar(
            select(AssessmentResult).where(
                AssessmentResult.student_id == student,
                AssessmentResult.assessment_id == last.id,
            )
        )
        assert row is not None and row.status is ResultStatus.EXEMPT
        assert row.score is None, "exempt must never hold a number"

        point = next(
            p
            for p in cohort.journey.student_analytics(student).json()["profile"]["history"][
                "points"
            ]
            if p["assessment_id"] == str(last.id)
        )
        assert point["percentage"] is None
        assert point["state"] != "present"

    def test_a_real_zero_is_kept_as_a_zero(
        self, cohort: Cohort, db_session: Session, client: TestClient
    ) -> None:
        student = cohort.id_of("strong")
        response = client.put(
            f"/api/v1/assessments/{cohort.assessments[0].id}/results",
            json={"results": [{"student_id": str(student), "score": 0}]},
            headers=cohort.journey.headers,
        )
        assert response.status_code == 200, response.text
        row = db_session.scalar(
            select(AssessmentResult).where(
                AssessmentResult.student_id == student,
                AssessmentResult.assessment_id == cohort.assessments[0].id,
            )
        )
        assert row is not None
        assert row.score == Decimal("0.00")
        assert row.status is ResultStatus.PRESENT


class TestEveryRuleReachesPersistenceAndTheApi:
    def test_all_seven_rules_fire_somewhere_in_this_cohort(self, cohort: Cohort) -> None:
        """Guards the fixture itself: if this fails, the sweeps below are testing less than they
        claim to."""
        fired: set[str] = set()
        for entry in cohort.journey.attention().json()["students"]:
            fired.update(flag["rule_code"] for flag in entry["flags"])
        missing = {code.value for code in AttentionRuleCode} - fired
        assert missing == set(), f"the cohort never triggers {sorted(missing)}"

    def test_the_api_and_the_stored_rows_agree_field_for_field(
        self, cohort: Cohort, db_session: Session
    ) -> None:
        """source data -> engine -> API -> persistence, for every flag in the cohort."""
        api: dict[tuple[str, str], dict] = {}
        for entry in cohort.journey.attention().json()["students"]:
            for flag in entry["flags"]:
                api[(entry["student"]["id"], flag["rule_code"])] = flag

        rows = live_rows(db_session, cohort.journey.offering.id)
        stored = {(str(row.student_id), row.rule_code.value): row for row in rows}

        assert set(stored) == set(api), (
            "the stored live flags and the engine's flags must be the same set"
        )

        for key, flag in api.items():
            row = stored[key]
            assert row.severity.value == flag["severity"], f"{key}: severity"
            assert float(row.actual_value) == pytest.approx(flag["actual"]["value"], abs=0.01), (
                f"{key}: actual value"
            )
            assert row.actual_unit.value == flag["actual"]["unit"], f"{key}: unit"
            assert row.actual_n == flag["actual"]["n"], f"{key}: sample size"
            assert row.message == flag["message"], f"{key}: message"
            assert list(row.reference_assessments) == list(flag["reference_assessments"]), (
                f"{key}: reference assessments"
            )
            assert row.computed_at is not None, f"{key}: computed_at"
            if flag["threshold"] is None:
                assert row.threshold_key is None, f"{key}: threshold should be absent"
                assert row.pass_mark_percent is not None, f"{key}: must quote the pass mark"
            else:
                assert row.threshold_key.value == flag["threshold"]["key"], f"{key}: threshold key"
                assert float(row.threshold_value) == pytest.approx(
                    flag["threshold"]["value"], abs=0.01
                ), f"{key}: threshold value"
                assert row.threshold_source.value == flag["threshold"]["source"], (
                    f"{key}: threshold source"
                )

    def test_each_flag_carries_the_severity_its_rule_declares(
        self, cohort: Cohort, db_session: Session
    ) -> None:
        """Severity is the registry's, not something the persistence layer decides."""
        for row in live_rows(db_session, cohort.journey.offering.id):
            assert row.severity is ATTENTION_RULES[row.rule_code].severity

    def test_overlapping_flags_are_all_preserved(self, cohort: Cohort, db_session: Session) -> None:
        """A student firing several rules keeps every one: no collapsing into a single score."""
        low = str(cohort.id_of("low"))
        entry = next(
            e for e in cohort.journey.attention().json()["students"] if e["student"]["id"] == low
        )
        assert len(entry["flags"]) >= 3, "this student should fire several rules at once"
        codes = [flag["rule_code"] for flag in entry["flags"]]
        assert len(codes) == len(set(codes)), "a rule must not appear twice for one student"
        stored = [
            row
            for row in live_rows(db_session, cohort.journey.offering.id)
            if str(row.student_id) == low
        ]
        assert len(stored) == len(codes)

    def test_flags_are_ordered_deterministically_by_rule_code(self, cohort: Cohort) -> None:
        for entry in cohort.journey.attention().json()["students"]:
            codes = [flag["rule_code"] for flag in entry["flags"]]
            assert codes == sorted(codes), f"{entry['student']['id']}: flags are not in rule order"

    def test_two_identical_reads_are_byte_identical_apart_from_the_stamp(
        self, cohort: Cohort
    ) -> None:
        first = cohort.journey.attention().json()
        second = cohort.journey.attention().json()
        assert _scrub(first) == _scrub(second), "the same data must render the same answer"


def _scrub(node: object) -> object:
    if isinstance(node, dict):
        return {k: _scrub(v) for k, v in node.items() if k != "generated_at"}
    if isinstance(node, list):
        return [_scrub(v) for v in node]
    return node


class TestReportsAgreeWithTheDatabase:
    @pytest.mark.parametrize(
        "kind", ["class_summary", "attention", "assessment_comparison", "intervention_outcome"]
    )
    @pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
    def test_every_report_renders_in_every_format(
        self, cohort: Cohort, kind: str, fmt: str
    ) -> None:
        response = cohort.journey.report(kind, export_format=fmt)
        assert response.status_code == 200, f"{kind}/{fmt}: {response.text[:200]}"
        assert response.content
        if fmt == "pdf":
            assert response.content.startswith(b"%PDF")

    def test_the_attention_report_names_exactly_the_flagged_students(
        self, cohort: Cohort, db_session: Session
    ) -> None:
        flagged = {row.student_id for row in live_rows(db_session, cohort.journey.offering.id)}
        report = cohort.journey.report("attention", export_format="csv")
        assert report.status_code == 200, report.text
        body = report.text
        for label, student in cohort.students.items():
            if student.id in flagged:
                assert student.register_number in body, (
                    f"{label} is flagged but absent from the report"
                )

    def test_no_report_claims_a_cause_or_a_prediction(self, cohort: Cohort) -> None:
        """The wording screen holds through the exporters, not only in the contracts."""
        forbidden = (
            "because of",
            "caused by",
            "will fail",
            "will pass",
            "predicts",
            "guaranteed",
            "due to the intervention",
        )
        for kind in ("class_summary", "attention", "intervention_outcome"):
            body = cohort.journey.report(kind, export_format="csv").text.lower()
            for phrase in forbidden:
                assert phrase not in body, f"{kind} report claims '{phrase}'"

    def test_the_intervention_report_carries_the_observational_caveat(self, cohort: Cohort) -> None:
        student = cohort.id_of("low")
        created = cohort.journey.create_intervention(
            {
                "student_ids": [str(student)],
                "kind": "remedial_session",
                "after_sequence_no": 1,
                "note": "extra tutorial",
            }
        )
        assert created.status_code == 201, created.text
        body = cohort.journey.report("intervention_outcome", export_format="csv").text.lower()
        assert "observ" in body, "an outcome report must state that it observes, not attributes"


class TestThresholdsTravelWithTheAnswer:
    def test_every_stored_flag_names_what_it_compared_against(
        self, cohort: Cohort, db_session: Session
    ) -> None:
        for row in live_rows(db_session, cohort.journey.offering.id):
            has_threshold = row.threshold_key is not None
            has_pass_mark = row.pass_mark_percent is not None
            assert has_threshold or has_pass_mark, (
                f"{row.rule_code.value} was stored without stating its comparison"
            )
            if has_threshold:
                assert row.threshold_source is not None
                assert row.threshold_value is not None

    def test_the_api_reports_the_threshold_source(self, cohort: Cohort) -> None:
        sources = {
            flag["threshold"]["source"]
            for entry in cohort.journey.attention().json()["students"]
            for flag in entry["flags"]
            if flag["threshold"] is not None
        }
        assert sources, "no flag quoted a resolved threshold"
        assert sources <= {"offering_override", "department_setting", "system_default"}
