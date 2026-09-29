"""Hostile and malformed input on the write surface Phase 10 added.

The point of these tests is not that bad input is *rejected* — much of it is, by the schema — but
that input is only ever treated as **data**. SQL and script payloads that are valid text survive a
round trip byte-for-byte and change nothing about the database; ones that violate a stated rule
come back as the error envelope. Neither outcome involves string filtering, which is why the
injection tests assert the value is *stored verbatim* rather than scrubbed: sanitising would hide
whether the query was parameterised.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.modules.interventions.models import Intervention
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import User
from tests.conftest import AssessmentFactory, StudentFactory, auth_headers

SQL_PAYLOADS = [
    "Robert'); DROP TABLE interventions;--",
    "' OR '1'='1",
    "1; DELETE FROM assessment_results WHERE 1=1; --",
    "%' UNION SELECT password_hash FROM users --",
    "\\'; SELECT pg_sleep(0); --",
]

SCRIPT_PAYLOADS = [
    "<script>alert(document.cookie)</script>",
    "<img src=x onerror=alert(1)>",
    '=HYPERLINK("http://evil.example","click")',  # spreadsheet formula injection
    "javascript:alert(1)",
]


class Fixture:
    def __init__(self, offering: CourseOffering, student: Student, actor: User) -> None:
        self.offering = offering
        self.student = student
        self.actor = actor

    @property
    def url(self) -> str:
        return f"/api/v1/offerings/{self.offering.id}/interventions"

    def payload(self, **overrides: object) -> dict:
        body: dict = {
            "student_ids": [str(self.student.id)],
            "kind": "academic_support",
            "after_sequence_no": 0,
            "note": "baseline",
        }
        body.update(overrides)
        return body


@pytest.fixture
def setup(
    db_session: Session,
    cse: Department,
    cse_offering: CourseOffering,
    faculty: User,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
) -> Fixture:
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    student = make_student(cse, section, enroll_in=[cse_offering])
    make_assessment(cse_offering, "CT1", max_marks="50")
    return Fixture(cse_offering, student, faculty)


class TestInjectionIsData:
    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_a_note_is_stored_verbatim_and_executes_nothing(
        self, client: TestClient, db_session: Session, setup: Fixture, payload: str
    ) -> None:
        response = client.post(
            setup.url, json=setup.payload(note=payload), headers=auth_headers(setup.actor)
        )
        assert response.status_code == 201, response.text
        assert response.json()["note"] == payload, "the note must round-trip unmodified"

        stored = db_session.scalar(select(Intervention.note))
        assert stored == payload
        # The statement was data, not SQL: the tables it named are all still here.
        tables = set(inspect(db_session.get_bind()).get_table_names())
        assert {"interventions", "assessment_results", "users"} <= tables
        assert db_session.scalar(select(func.count()).select_from(Intervention)) == 1

    @pytest.mark.parametrize("payload", SCRIPT_PAYLOADS)
    def test_script_like_input_is_stored_as_text_not_escaped_or_stripped(
        self, client: TestClient, setup: Fixture, payload: str
    ) -> None:
        """Escaping belongs to the renderer. The API must not silently rewrite what was typed."""
        response = client.post(
            setup.url, json=setup.payload(note=payload), headers=auth_headers(setup.actor)
        )
        assert response.status_code == 201, response.text
        assert response.json()["note"] == payload

    def test_a_payload_in_a_register_number_finds_no_student(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        """The import path resolves students by value, so a crafted one simply does not match."""
        before = db_session.scalar(select(func.count()).select_from(Intervention))
        response = client.post(
            f"/api/v1/offerings/{setup.offering.id}/imports",
            files={"file": ("m.csv", b"Register No,CT1\n' OR 1=1 --,40\n")},
            headers=auth_headers(setup.actor),
        )
        # Either staged with a row-level error or rejected outright; never a successful match.
        assert response.status_code in (201, 422), response.text
        if response.status_code == 201:
            assert response.json()["summary"]["errors"] >= 1
        assert db_session.scalar(select(func.count()).select_from(Intervention)) == before
        assert db_session.scalar(text("SELECT count(*) FROM students")) == 1


class TestMalformedIdentifiers:
    @pytest.mark.parametrize(
        "bad",
        ["not-a-uuid", "12345", "", "../../etc/passwd", "00000000-0000-0000-0000-00000000000z"],
    )
    def test_a_malformed_offering_id_is_a_validation_error_not_a_crash(
        self, client: TestClient, setup: Fixture, bad: str
    ) -> None:
        response = client.get(
            f"/api/v1/offerings/{bad}/attention", headers=auth_headers(setup.actor)
        )
        assert response.status_code in (404, 422), response.text
        assert "error" in response.json()

    def test_a_malformed_student_id_in_a_body_is_rejected(
        self, client: TestClient, setup: Fixture
    ) -> None:
        response = client.post(
            setup.url,
            json=setup.payload(student_ids=["not-a-uuid"]),
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"

    def test_a_wellformed_but_unknown_student_is_refused(
        self, client: TestClient, setup: Fixture
    ) -> None:
        response = client.post(
            setup.url,
            json=setup.payload(student_ids=[str(uuid.uuid4())]),
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text


class TestTypesAndBounds:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("student_ids", "not-a-list"),
            ("student_ids", [None]),
            ("kind", 7),
            ("kind", None),
            ("after_sequence_no", "first"),
            ("after_sequence_no", 1.5),
            ("after_sequence_no", -1),
            ("status", "invented_status"),
            ("recorded_on", "not-a-date"),
            ("reasons", "not-a-list"),
        ],
    )
    def test_unexpected_types_and_invalid_enums_are_422(
        self, client: TestClient, setup: Fixture, field: str, value: object
    ) -> None:
        response = client.post(
            setup.url, json=setup.payload(**{field: value}), headers=auth_headers(setup.actor)
        )
        assert response.status_code == 422, f"{field}={value!r} gave {response.status_code}"
        assert response.json()["error"]["code"] in (
            "validation_error",
            "business_rule_violation",
        )

    def test_an_empty_note_is_not_a_reason(self, client: TestClient, setup: Fixture) -> None:
        """A blank string must not satisfy "say why": it explains nothing later."""
        response = client.post(
            setup.url, json=setup.payload(note="   "), headers=auth_headers(setup.actor)
        )
        assert response.status_code == 422, response.text

    def test_an_excessively_long_note_is_rejected(self, client: TestClient, setup: Fixture) -> None:
        response = client.post(
            setup.url, json=setup.payload(note="x" * 5000), headers=auth_headers(setup.actor)
        )
        assert response.status_code == 422, response.text

    def test_an_oversized_target_list_is_rejected_without_a_partial_write(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        response = client.post(
            setup.url,
            json=setup.payload(student_ids=[str(uuid.uuid4()) for _ in range(500)]),
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text
        assert db_session.scalar(select(func.count()).select_from(Intervention)) == 0

    def test_unknown_fields_are_refused(self, client: TestClient, setup: Fixture) -> None:
        """extra="forbid": a typo must not be silently ignored."""
        response = client.post(
            setup.url,
            json=setup.payload(is_admin=True, offering_id=str(uuid.uuid4())),
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text


class TestScoreBounds:
    def test_a_negative_score_is_refused(
        self, client: TestClient, setup: Fixture, make_assessment: AssessmentFactory
    ) -> None:
        assessment = make_assessment(setup.offering, "CT9", max_marks="50")
        response = client.put(
            f"/api/v1/assessments/{assessment.id}/results",
            json={"results": [{"student_id": str(setup.student.id), "score": -5}]},
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text

    def test_a_score_above_the_maximum_is_refused(
        self, client: TestClient, setup: Fixture, make_assessment: AssessmentFactory
    ) -> None:
        assessment = make_assessment(setup.offering, "CT8", max_marks="50")
        response = client.put(
            f"/api/v1/assessments/{assessment.id}/results",
            json={"results": [{"student_id": str(setup.student.id), "score": 999}]},
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422, response.text

    def test_a_genuine_zero_is_accepted_and_kept(
        self,
        client: TestClient,
        db_session: Session,
        setup: Fixture,
        make_assessment: AssessmentFactory,
    ) -> None:
        """Zero is a real mark. Only blanks and absences are not numbers."""
        assessment = make_assessment(setup.offering, "CT7", max_marks="50")
        response = client.put(
            f"/api/v1/assessments/{assessment.id}/results",
            json={"results": [{"student_id": str(setup.student.id), "score": 0}]},
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 200, response.text
        score, status = db_session.execute(
            text("SELECT score, status FROM assessment_results WHERE assessment_id = :a"),
            {"a": assessment.id},
        ).one()
        assert float(score) == 0.0, "an explicit 0 is stored as a real mark"
        assert status == "present", "0 is present, never absent or missing"

    def test_an_assessment_from_another_offering_is_not_writable(
        self,
        client: TestClient,
        setup: Fixture,
        org,
        cse: Department,
        term,
        make_user,
        make_assessment,
    ) -> None:
        from app.modules.users.models import Role

        stranger = make_user(Role.FACULTY, email="other.owner@srmist.edu.in")
        theirs = org.offering(org.course(cse), org.section(cse), term, faculty=[stranger])
        foreign = make_assessment(theirs, "CT1", max_marks="50")
        response = client.put(
            f"/api/v1/assessments/{foreign.id}/results",
            json={"results": [{"student_id": str(setup.student.id), "score": 10}]},
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 404, response.text


class TestErrorsDoNotLeak:
    def test_the_envelope_never_carries_a_stack_trace_or_sql(
        self, client: TestClient, setup: Fixture
    ) -> None:
        response = client.post(
            setup.url,
            json=setup.payload(student_ids=[str(uuid.uuid4())]),
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 422
        body = response.text.lower()
        for leak in ("traceback", "sqlalchemy", "psycopg", "select ", 'file "', "site-packages"):
            assert leak not in body, f"the error envelope leaked {leak!r}"

    def test_an_unknown_report_format_is_refused_without_echoing_a_path(
        self, client: TestClient, setup: Fixture
    ) -> None:
        response = client.get(
            f"/api/v1/offerings/{setup.offering.id}/reports/class_summary",
            params={"format": "../../etc/passwd"},
            headers=auth_headers(setup.actor),
        )
        assert response.status_code == 404, response.text
        assert "etc/passwd" not in response.headers.get("content-disposition", "")
