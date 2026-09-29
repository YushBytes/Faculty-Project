"""Authorization and IDOR across the whole offering-scoped surface.

The security contract (`app/modules/organization/scope.py`, README "Access scope") is that an
offering outside a user's VIEW scope is reported as **404, identically to one that does not
exist**. So these tests do not merely assert "not 200": they assert that the response for another
faculty member's offering is *indistinguishable* from the response for a random UUID. A 403 here
would itself be the leak, because it confirms the resource exists.

Every route is swept from one table, so a new offering-scoped endpoint that forgets scope fails
here rather than being discovered later. There is no second authorization system in this file —
the assertions are about the platform's `OfferingAccess`, exercised over HTTP.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.organization.models import AcademicTerm, CourseOffering, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import Role, User
from tests.conftest import AssessmentFactory, OrgFactory, StudentFactory, UserFactory, auth_headers

REPORT_KINDS = (
    "class_summary",
    "attention",
    "assessment_comparison",
    "intervention_outcome",
)


def read_paths(offering_id: uuid.UUID, student_id: uuid.UUID) -> list[str]:
    """Every GET an offering exposes, Agent 2's surface plus the platform reads it builds on."""
    base = f"/api/v1/offerings/{offering_id}"
    return [
        f"{base}/analytics",
        f"{base}/attention",
        f"{base}/insights",
        f"{base}/students/{student_id}/analytics",
        f"{base}/interventions",
        f"{base}/interventions/outcomes",
        f"{base}/students/{student_id}/interventions",
        *[f"{base}/reports/{kind}?format=csv" for kind in REPORT_KINDS],
        *[f"{base}/reports/class_summary?format={fmt}" for fmt in ("xlsx", "pdf")],
        # Platform reads an analytics consumer depends on, to prove the isolation is end-to-end.
        f"{base}/students",
        f"{base}/assessments",
        f"{base}/results",
    ]


def intervention_payload(student_id: uuid.UUID) -> dict:
    return {
        "student_ids": [str(student_id)],
        "kind": "academic_support",
        "after_sequence_no": 0,
        "note": "attempted from outside the offering",
    }


class World:
    """Two faculty members, each with their own offering, plus a foreign department."""

    def __init__(
        self,
        mine: CourseOffering,
        my_student: Student,
        theirs: CourseOffering,
        their_student: Student,
        owner: User,
        stranger: User,
    ) -> None:
        self.mine = mine
        self.my_student = my_student
        self.theirs = theirs
        self.their_student = their_student
        self.owner = owner
        self.stranger = stranger


@pytest.fixture
def world(
    db_session: Session,
    cse: Department,
    term: AcademicTerm,
    org: OrgFactory,
    faculty: User,
    make_user: UserFactory,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
    cse_offering: CourseOffering,
) -> World:
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    mine_student = make_student(cse, section, enroll_in=[cse_offering])
    make_assessment(cse_offering, "CT1", max_marks="50")

    stranger = make_user(Role.FACULTY, email="stranger.faculty@srmist.edu.in")
    theirs = org.offering(org.course(cse), org.section(cse), term, faculty=[stranger])
    their_student = make_student(cse, enroll_in=[theirs])
    make_assessment(theirs, "CT1", max_marks="50")
    return World(cse_offering, mine_student, theirs, their_student, faculty, stranger)


class TestOutOfScopeIsIndistinguishableFromNonexistent:
    def test_every_read_returns_the_same_answer_for_absent_and_forbidden(
        self, client: TestClient, world: World
    ) -> None:
        """The core anti-IDOR property: existence is never disclosed."""
        headers = auth_headers(world.stranger)
        absent_id = uuid.uuid4()

        for forbidden, absent in zip(
            read_paths(world.mine.id, world.my_student.id),
            read_paths(absent_id, world.my_student.id),
            strict=True,
        ):
            forbidden_response = client.get(forbidden, headers=headers)
            absent_response = client.get(absent, headers=headers)
            assert forbidden_response.status_code == 404, (
                f"{forbidden} leaked {forbidden_response.status_code}"
            )
            assert absent_response.status_code == 404, (
                f"{absent} gave {absent_response.status_code}"
            )
            assert forbidden_response.json() == absent_response.json(), (
                f"{forbidden} distinguishes a forbidden offering from a nonexistent one"
            )

    def test_the_owner_can_read_everything_the_stranger_cannot(
        self, client: TestClient, world: World
    ) -> None:
        """The sweep would pass trivially if these routes were broken for everyone."""
        headers = auth_headers(world.owner)
        for path in read_paths(world.mine.id, world.my_student.id):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, (
                f"{path}: {response.status_code} {response.text[:160]}"
            )


class TestCrossOfferingWrites:
    def test_a_stranger_cannot_record_an_intervention_on_another_offering(
        self, client: TestClient, world: World
    ) -> None:
        response = client.post(
            f"/api/v1/offerings/{world.mine.id}/interventions",
            json=intervention_payload(world.my_student.id),
            headers=auth_headers(world.stranger),
        )
        assert response.status_code == 404

    def test_an_owner_cannot_target_a_student_from_another_offering(
        self, client: TestClient, world: World
    ) -> None:
        """Visible offering, invisible student: a data-rule violation, not a 404."""
        response = client.post(
            f"/api/v1/offerings/{world.mine.id}/interventions",
            json=intervention_payload(world.their_student.id),
            headers=auth_headers(world.owner),
        )
        assert response.status_code == 422, response.text
        assert "not active enrolments" in response.json()["error"]["message"]

    def test_an_intervention_recorded_elsewhere_is_not_visible_here(
        self, client: TestClient, world: World
    ) -> None:
        created = client.post(
            f"/api/v1/offerings/{world.theirs.id}/interventions",
            json=intervention_payload(world.their_student.id),
            headers=auth_headers(world.stranger),
        )
        assert created.status_code == 201, created.text

        mine = client.get(
            f"/api/v1/offerings/{world.mine.id}/interventions", headers=auth_headers(world.owner)
        )
        assert mine.status_code == 200, mine.text
        assert mine.json()["total"] == 0, "interventions must not cross offering boundaries"

    def test_a_flag_from_another_offering_cannot_be_cited_as_a_reason(
        self, client: TestClient, world: World, db_session: Session
    ) -> None:
        """A stolen flag id must not become a reason on an offering it has nothing to do with."""
        from datetime import UTC, datetime

        from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity
        from app.modules.attention.models import AttentionFlag

        foreign = AttentionFlag(
            offering_id=world.theirs.id,
            student_id=world.their_student.id,
            rule_code=AttentionRuleCode.R1_LOW_PERFORMANCE,
            severity=FlagSeverity.HIGH,
            actual_value=20,
            actual_unit="percent",
            actual_n=1,
            pass_mark_percent=50,
            message="another offering's flag",
            computed_at=datetime.now(UTC),
        )
        db_session.add(foreign)
        db_session.flush()

        response = client.post(
            f"/api/v1/offerings/{world.mine.id}/interventions",
            json={
                "student_ids": [str(world.my_student.id)],
                "kind": "academic_support",
                "reasons": [{"student_id": str(world.my_student.id), "flag_id": str(foreign.id)}],
                "after_sequence_no": 0,
            },
            headers=auth_headers(world.owner),
        )
        assert response.status_code == 422, response.text


class TestStudentScoping:
    def test_a_student_of_another_offering_is_not_readable_here(
        self, client: TestClient, world: World
    ) -> None:
        response = client.get(
            f"/api/v1/offerings/{world.mine.id}/students/{world.their_student.id}/analytics",
            headers=auth_headers(world.owner),
        )
        assert response.status_code == 404, response.text

    def test_a_nonexistent_student_looks_the_same_as_a_foreign_one(
        self, client: TestClient, world: World
    ) -> None:
        headers = auth_headers(world.owner)
        foreign = client.get(
            f"/api/v1/offerings/{world.mine.id}/students/{world.their_student.id}/analytics",
            headers=headers,
        )
        absent = client.get(
            f"/api/v1/offerings/{world.mine.id}/students/{uuid.uuid4()}/analytics", headers=headers
        )
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()

    def test_a_student_report_for_a_foreign_student_is_refused(
        self, client: TestClient, world: World
    ) -> None:
        response = client.get(
            f"/api/v1/offerings/{world.mine.id}/reports/student_performance",
            params={"format": "csv", "student_id": str(world.their_student.id)},
            headers=auth_headers(world.owner),
        )
        assert response.status_code == 404, response.text


class TestRoleScoping:
    def test_an_hod_of_another_department_sees_nothing(
        self, client: TestClient, world: World, make_user: UserFactory, ece: Department
    ) -> None:
        other_hod = make_user(Role.HOD, email="hod.other@srmist.edu.in", department=ece)
        for path in read_paths(world.mine.id, world.my_student.id):
            response = client.get(path, headers=auth_headers(other_hod))
            assert response.status_code == 404, f"{path} visible to a foreign HOD"

    def test_the_departments_own_hod_can_see_it(
        self, client: TestClient, world: World, hod: User
    ) -> None:
        response = client.get(
            f"/api/v1/offerings/{world.mine.id}/attention", headers=auth_headers(hod)
        )
        assert response.status_code == 200, response.text

    def test_an_admin_sees_every_offering(
        self, client: TestClient, world: World, admin: User
    ) -> None:
        for offering_id in (world.mine.id, world.theirs.id):
            response = client.get(
                f"/api/v1/offerings/{offering_id}/attention", headers=auth_headers(admin)
            )
            assert response.status_code == 200, response.text

    def test_a_deactivated_faculty_loses_access_immediately(
        self, client: TestClient, world: World, db_session: Session
    ) -> None:
        headers = auth_headers(world.owner)
        assert (
            client.get(f"/api/v1/offerings/{world.mine.id}/attention", headers=headers).status_code
            == 200
        )
        world.owner.is_active = False
        db_session.flush()
        assert (
            client.get(f"/api/v1/offerings/{world.mine.id}/attention", headers=headers).status_code
            == 401
        ), "every request re-reads the user, so deactivation cuts off a live token"


class TestUnauthenticated:
    def test_every_offering_route_requires_a_token(self, client: TestClient, world: World) -> None:
        for path in read_paths(world.mine.id, world.my_student.id):
            assert client.get(path).status_code == 401, f"{path} served an anonymous caller"

    def test_writes_require_a_token(self, client: TestClient, world: World) -> None:
        response = client.post(
            f"/api/v1/offerings/{world.mine.id}/interventions",
            json=intervention_payload(world.my_student.id),
        )
        assert response.status_code == 401
