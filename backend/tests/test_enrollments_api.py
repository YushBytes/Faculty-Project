"""Offering enrolments and rosters."""

import uuid

from fastapi.testclient import TestClient

from app.modules.organization.models import CourseOffering, Department
from app.modules.users.models import User
from tests.conftest import OrgFactory, StudentFactory, auth_headers


def _url(offering: CourseOffering, suffix: str = "") -> str:
    return f"/api/v1/offerings/{offering.id}{suffix}"


def _roster(client: TestClient, offering: CourseOffering, user: User, **params) -> list[str]:
    response = client.get(_url(offering, "/students"), params=params, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return [e["student"]["register_number"] for e in response.json()]


def test_enroll_is_idempotent_and_reactivates(
    client: TestClient, admin: User, cse: Department, cse_offering, make_student: StudentFactory
) -> None:
    a, b = make_student(cse), make_student(cse)
    body = {"student_ids": [str(a.id), str(b.id), str(a.id)]}
    first = client.post(_url(cse_offering, "/enrollments"), json=body, headers=auth_headers(admin))
    assert first.json() == {"enrolled": 2, "reactivated": 0, "already_enrolled": 0}

    client.delete(_url(cse_offering, f"/enrollments/{a.id}"), headers=auth_headers(admin))
    again = client.post(_url(cse_offering, "/enrollments"), json=body, headers=auth_headers(admin))
    assert again.json() == {"enrolled": 0, "reactivated": 1, "already_enrolled": 1}


def test_enroll_from_section(
    client: TestClient, hod: User, cse: Department, org: OrgFactory, term, make_student
) -> None:
    section = org.section(cse, name="A1")
    offering = org.offering(org.course(cse), section, term)
    make_student(cse, section)
    make_student(cse, section)
    make_student(cse, section, is_active=False)
    make_student(cse, org.section(cse, name="B1"))

    response = client.post(_url(offering, "/enrollments/from-section"), headers=auth_headers(hod))
    assert response.json()["enrolled"] == 2
    repeat = client.post(_url(offering, "/enrollments/from-section"), headers=auth_headers(hod))
    assert repeat.json() == {"enrolled": 0, "reactivated": 0, "already_enrolled": 2}


def test_roster_filters_dropped_and_inactive(
    client: TestClient, faculty: User, admin: User, cse, cse_offering, make_student
) -> None:
    active = make_student(cse, enroll_in=[cse_offering])
    dropped = make_student(cse, enroll_in=[cse_offering])
    inactive = make_student(cse, enroll_in=[cse_offering], is_active=False)
    client.delete(_url(cse_offering, f"/enrollments/{dropped.id}"), headers=auth_headers(admin))

    assert _roster(client, cse_offering, faculty) == [active.register_number]
    assert set(_roster(client, cse_offering, faculty, include_dropped=True)) == {
        active.register_number,
        dropped.register_number,
    }
    assert set(_roster(client, cse_offering, faculty, include_inactive=True)) == {
        active.register_number,
        inactive.register_number,
    }
    full = client.get(
        _url(cse_offering, "/students"),
        params={"include_dropped": True},
        headers=auth_headers(faculty),
    ).json()
    statuses = {e["student"]["register_number"]: e["status"] for e in full}
    assert statuses[dropped.register_number] == "DROPPED"


def test_cannot_enroll_inactive_or_unknown(
    client: TestClient, admin: User, cse, cse_offering, make_student
) -> None:
    inactive = make_student(cse, is_active=False)
    headers = auth_headers(admin)
    response = client.post(
        _url(cse_offering, "/enrollments"),
        json={"student_ids": [str(inactive.id)]},
        headers=headers,
    )
    assert response.status_code == 422
    response = client.post(
        _url(cse_offering, "/enrollments"),
        json={"student_ids": [str(uuid.uuid4())]},
        headers=headers,
    )
    assert response.status_code == 404


def test_faculty_views_but_cannot_change_enrolments(
    client: TestClient, faculty: User, cse, cse_offering, make_student
) -> None:
    student = make_student(cse)
    headers = auth_headers(faculty)
    assert client.get(_url(cse_offering, "/students"), headers=headers).status_code == 200
    assert (
        client.post(
            _url(cse_offering, "/enrollments"),
            json={"student_ids": [str(student.id)]},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(_url(cse_offering, "/enrollments/from-section"), headers=headers).status_code
        == 403
    )


def test_out_of_scope_roster_is_not_found(
    client: TestClient, faculty: User, org: OrgFactory, ece, term
) -> None:
    other = org.offering(org.course(ece), org.section(ece), term)
    response = client.get(_url(other, "/students"), headers=auth_headers(faculty))
    assert response.status_code == 404


def test_drop_unknown_enrolment(client: TestClient, admin: User, cse_offering) -> None:
    response = client.delete(
        _url(cse_offering, f"/enrollments/{uuid.uuid4()}"), headers=auth_headers(admin)
    )
    assert response.status_code == 404


def test_offering_with_enrolments_cannot_be_deleted(
    client: TestClient, admin: User, cse, cse_offering, make_student
) -> None:
    make_student(cse, enroll_in=[cse_offering])
    assert client.delete(_url(cse_offering), headers=auth_headers(admin)).status_code == 409
