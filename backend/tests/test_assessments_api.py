"""Assessment definitions: scope, ordering, uniqueness, weightage and max-marks rules."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.modules.organization.models import CourseOffering
from app.modules.users.models import Role, User
from tests.conftest import AssessmentFactory, StudentFactory, auth_headers


def _url(offering: CourseOffering) -> str:
    return f"/api/v1/offerings/{offering.id}/assessments"


BODY = {"name": "CT1", "assessment_type": "CT", "max_marks": 50, "weightage": 20}


class TestCreate:
    def test_assigned_faculty_creates_with_auto_sequence(
        self, client: TestClient, faculty: User, cse_offering: CourseOffering
    ) -> None:
        headers = auth_headers(faculty)
        first = client.post(_url(cse_offering), json=BODY, headers=headers)
        second = client.post(
            _url(cse_offering),
            json={**BODY, "name": "CT2", "assessment_date": "2026-09-01"},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        assert (first.json()["sequence_no"], second.json()["sequence_no"]) == (1, 2)
        assert first.json()["is_published"] is False
        assert first.json()["max_marks"] == 50.0
        assert first.json()["result_counts"] == {
            "present": 0,
            "absent": 0,
            "exempt": 0,
            "missing": 0,
            "enrolled": 0,
        }

    def test_names_unique_case_insensitively(
        self, client: TestClient, faculty: User, cse_offering: CourseOffering
    ) -> None:
        headers = auth_headers(faculty)
        client.post(_url(cse_offering), json=BODY, headers=headers)
        dup = client.post(_url(cse_offering), json={**BODY, "name": " ct1 "}, headers=headers)
        assert dup.status_code == 409

    def test_sequence_conflict(
        self, client: TestClient, faculty: User, cse_offering: CourseOffering
    ) -> None:
        headers = auth_headers(faculty)
        client.post(_url(cse_offering), json={**BODY, "sequence_no": 3}, headers=headers)
        dup = client.post(
            _url(cse_offering), json={**BODY, "name": "CT2", "sequence_no": 3}, headers=headers
        )
        assert dup.status_code == 409

    @pytest.mark.parametrize(
        "override",
        [
            {"max_marks": 0},
            {"max_marks": -5},
            {"max_marks": 10000},
            {"weightage": 101},
            {"weightage": -1},
            {"assessment_type": "EXAM"},
            {"name": ""},
            {"sequence_no": 0},
            {"max_marks": "12.345"},
        ],
    )
    def test_invalid(
        self, client: TestClient, faculty: User, cse_offering: CourseOffering, override: dict
    ) -> None:
        response = client.post(
            _url(cse_offering), json={**BODY, **override}, headers=auth_headers(faculty)
        )
        assert response.status_code == 422

    def test_out_of_scope_faculty_gets_404(
        self, client: TestClient, make_user, cse_offering: CourseOffering
    ) -> None:
        stranger = make_user(Role.FACULTY, email="stranger@srmist.edu.in")
        headers = auth_headers(stranger)
        assert client.post(_url(cse_offering), json=BODY, headers=headers).status_code == 404
        assert client.get(_url(cse_offering), headers=headers).status_code == 404


class TestListAndDetail:
    def test_ordered_with_weightage_warning(
        self, client: TestClient, faculty: User, cse_offering, make_assessment: AssessmentFactory
    ) -> None:
        make_assessment(cse_offering, "FT1", weightage="60", sequence_no=3)
        make_assessment(cse_offering, "CT1", weightage="30", sequence_no=1)
        make_assessment(cse_offering, "CT2", weightage="30", sequence_no=2)
        body = client.get(_url(cse_offering), headers=auth_headers(faculty)).json()
        assert [a["name"] for a in body["items"]] == ["CT1", "CT2", "FT1"]
        assert body["weightage_total"] == 120.0
        assert "exceeds 100" in body["warnings"][0]

    def test_counts_reflect_cohort(
        self,
        client: TestClient,
        faculty: User,
        cse,
        cse_offering,
        make_assessment,
        make_student: StudentFactory,
    ) -> None:
        assessment = make_assessment(cse_offering)
        students = [make_student(cse, enroll_in=[cse_offering]) for _ in range(3)]
        client.put(
            f"/api/v1/assessments/{assessment.id}/results",
            json={
                "results": [
                    {"student_id": str(students[0].id), "score": 40},
                    {"student_id": str(students[1].id), "status": "absent"},
                ]
            },
            headers=auth_headers(faculty),
        )
        detail = client.get(f"/api/v1/assessments/{assessment.id}", headers=auth_headers(faculty))
        assert detail.json()["result_counts"] == {
            "present": 1,
            "absent": 1,
            "exempt": 0,
            "missing": 1,
            "enrolled": 3,
        }

    def test_detail_out_of_scope(
        self, client: TestClient, make_user, cse_offering, make_assessment
    ) -> None:
        assessment = make_assessment(cse_offering)
        stranger = make_user(Role.FACULTY, email="stranger@srmist.edu.in")
        response = client.get(
            f"/api/v1/assessments/{assessment.id}", headers=auth_headers(stranger)
        )
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Assessment not found."
        missing = client.get(f"/api/v1/assessments/{uuid.uuid4()}", headers=auth_headers(stranger))
        assert missing.status_code == 404


class TestUpdateAndDelete:
    def test_publish_and_rename(
        self, client: TestClient, faculty: User, cse_offering, make_assessment
    ) -> None:
        assessment = make_assessment(cse_offering, published=False)
        response = client.patch(
            f"/api/v1/assessments/{assessment.id}",
            json={"is_published": True, "name": "Cycle Test 1", "weightage": 25},
            headers=auth_headers(faculty),
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["is_published"], body["name"], body["weightage"]) == (
            True,
            "Cycle Test 1",
            25.0,
        )

    def test_max_marks_locked_once_results_exist(
        self, client: TestClient, faculty: User, cse, cse_offering, make_assessment, make_student
    ) -> None:
        assessment = make_assessment(cse_offering)
        url = f"/api/v1/assessments/{assessment.id}"
        headers = auth_headers(faculty)
        assert client.patch(url, json={"max_marks": 60}, headers=headers).status_code == 200
        student = make_student(cse, enroll_in=[cse_offering])
        client.put(
            f"{url}/results",
            json={"results": [{"student_id": str(student.id), "score": 10}]},
            headers=headers,
        )
        locked = client.patch(url, json={"max_marks": 100}, headers=headers)
        assert locked.status_code == 422
        assert "max_marks cannot change" in locked.json()["error"]["message"]
        same = client.patch(url, json={"max_marks": 60, "name": "CT-1"}, headers=headers)
        assert same.status_code == 200

    def test_delete_blocked_by_results(
        self, client: TestClient, faculty: User, cse, cse_offering, make_assessment, make_student
    ) -> None:
        with_results = make_assessment(cse_offering, "CT1")
        empty = make_assessment(cse_offering, "CT2")
        student = make_student(cse, enroll_in=[cse_offering])
        headers = auth_headers(faculty)
        client.put(
            f"/api/v1/assessments/{with_results.id}/results",
            json={"results": [{"student_id": str(student.id), "score": 10}]},
            headers=headers,
        )
        assert (
            client.delete(f"/api/v1/assessments/{with_results.id}", headers=headers).status_code
            == 409
        )
        assert client.delete(f"/api/v1/assessments/{empty.id}", headers=headers).status_code == 204

    def test_offering_with_assessments_cannot_be_deleted(
        self, client: TestClient, admin: User, cse_offering, make_assessment
    ) -> None:
        make_assessment(cse_offering)
        response = client.delete(
            f"/api/v1/offerings/{cse_offering.id}", headers=auth_headers(admin)
        )
        assert response.status_code == 409


def test_no_question_or_topic_tables_exist(db_session) -> None:
    """Guard against scope creep (RISK-7): the question/topic layer must not exist."""
    from sqlalchemy import inspect

    tables = set(inspect(db_session.connection()).get_table_names())
    forbidden = {"questions", "topics", "question_topics", "marks", "student_topic_summary"}
    assert tables & forbidden == set()
    assert "assessment_results" in tables
