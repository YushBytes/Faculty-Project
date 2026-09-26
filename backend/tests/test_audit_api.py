"""Audit log API and audit coverage of sensitive state changes."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.users.models import Role, User
from tests.conftest import auth_headers

AUDIT = "/api/v1/audit-logs"


def _overwrite(client, faculty, assessment, student) -> None:
    url = f"/api/v1/assessments/{assessment.id}/results"
    for score in (10, 20):
        client.put(
            url,
            json={"results": [{"student_id": str(student.id), "score": score}]},
            headers=auth_headers(faculty),
        )


def test_admin_sees_all_faculty_only_their_offerings(
    client: TestClient,
    admin: User,
    faculty: User,
    make_user,
    cse,
    cse_offering,
    make_assessment,
    make_student,
    org,
    term,
) -> None:
    ct1 = make_assessment(cse_offering)
    student = make_student(cse, enroll_in=[cse_offering])
    _overwrite(client, faculty, ct1, student)

    other_teacher = make_user(Role.FACULTY, email="other@srmist.edu.in")
    other = org.offering(org.course(cse), org.section(cse), term, faculty=[other_teacher])
    other_ct = make_assessment(other)
    other_student = make_student(cse, enroll_in=[other])
    _overwrite(client, other_teacher, other_ct, other_student)

    everything = client.get(AUDIT, headers=auth_headers(admin)).json()
    mine = client.get(AUDIT, headers=auth_headers(faculty)).json()
    assert everything["total"] == 2
    assert mine["total"] == 1 and mine["items"][0]["offering_id"] == str(cse_offering.id)
    assert mine["items"][0]["old_value"]["score"] == "10.00"

    filtered = client.get(
        AUDIT,
        params={"entity": "assessment_result", "action": "update", "offering_id": str(other.id)},
        headers=auth_headers(admin),
    ).json()
    assert filtered["total"] == 1


def test_requires_authentication(client: TestClient) -> None:
    assert client.get(AUDIT).status_code == 401


def test_user_and_student_changes_are_audited(
    client: TestClient,
    admin: User,
    faculty: User,
    hod: User,
    cse,
    make_student,
    db_session: Session,
) -> None:
    headers = auth_headers(admin)
    client.patch(
        f"/api/v1/users/{faculty.id}",
        json={"role": "HOD", "department_id": str(cse.id)},
        headers=headers,
    )
    client.patch(
        f"/api/v1/users/{faculty.id}", json={"password": "another-passphrase"}, headers=headers
    )
    client.post(f"/api/v1/users/{faculty.id}/deactivate", headers=headers)
    client.post(f"/api/v1/users/{faculty.id}/activate", headers=headers)
    student = make_student(cse)
    client.post(f"/api/v1/students/{student.id}/deactivate", headers=auth_headers(hod))

    rows = db_session.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()
    user_actions = [r.action for r in rows if r.entity == "user"]
    assert sorted(user_actions) == ["activate", "deactivate", "password_reset", "update"]
    role_change = next(r for r in rows if r.entity == "user" and r.action == "update")
    assert role_change.old_value["role"] == "FACULTY" and role_change.new_value["role"] == "HOD"
    assert all("password" not in str(r.new_value or {}) for r in rows)  # never store secrets
    student_log = next(r for r in rows if r.entity == "student")
    assert student_log.action == "deactivate" and student_log.actor_id == hod.id
