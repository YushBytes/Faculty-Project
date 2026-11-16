"""Department settings (analytics threshold storage) and who may read or change them.

Read scope (organization/scope.py::threshold_department_ids):
    ADMIN    every department
    others   their own department + the department of every offering they can view
Out of scope is 404, indistinguishable from a department that does not exist. Writing needs
ADMIN or the department's HOD; a department the actor cannot see is 404 for writes too, one they
can see but not manage is 403.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.organization.models import CourseCoordinator, Department
from app.modules.users.models import Role, User
from tests.conftest import OrgFactory, UserFactory, auth_headers


def _url(department, key: str = "") -> str:
    department_id = department if isinstance(department, uuid.UUID) else department.id
    base = f"/api/v1/departments/{department_id}/settings"
    return f"{base}/{key}" if key else base


def _read(client: TestClient, user: User, department) -> int:
    return client.get(_url(department), headers=auth_headers(user)).status_code


@pytest.fixture
def settings_both(client: TestClient, admin: User, cse: Department, ece: Department) -> None:
    for department, value in ((cse, 55), (ece, 60)):
        response = client.put(
            _url(department, "low_performance_percent"),
            json={"value": value},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200


def test_hod_manages_own_department(
    client: TestClient, hod: User, cse, db_session: Session
) -> None:
    headers = auth_headers(hod)
    created = client.put(_url(cse, "TREND_DELTA"), json={"value": 5}, headers=headers)
    assert created.status_code == 200 and created.json()["value"] == 5
    updated = client.put(_url(cse, "TREND_DELTA"), json={"value": {"pp": 4.5}}, headers=headers)
    assert updated.json()["value"] == {"pp": 4.5}
    listed = client.get(_url(cse), headers=headers).json()
    assert [(s["key"], s["value"]) for s in listed] == [("TREND_DELTA", {"pp": 4.5})]

    assert client.delete(_url(cse, "TREND_DELTA"), headers=headers).status_code == 204
    assert client.delete(_url(cse, "TREND_DELTA"), headers=headers).status_code == 404
    actions = [
        log.action
        for log in db_session.scalars(
            select(AuditLog).where(AuditLog.entity == "setting").order_by(AuditLog.created_at)
        )
    ]
    assert sorted(actions) == ["create", "delete", "update"]


class TestReadScope:
    def test_admin_reads_every_department(
        self, client: TestClient, admin: User, cse, ece, settings_both
    ) -> None:
        assert _read(client, admin, cse) == _read(client, admin, ece) == 200
        values = client.get(_url(ece), headers=auth_headers(admin)).json()
        assert [(s["key"], s["value"]) for s in values] == [("low_performance_percent", 60)]

    def test_hod_reads_only_their_department(
        self, client: TestClient, hod: User, cse, ece, settings_both
    ) -> None:
        assert _read(client, hod, cse) == 200
        assert _read(client, hod, ece) == 404

    def test_academic_head_reads_their_department(
        self, client: TestClient, make_user: UserFactory, cse, ece, settings_both
    ) -> None:
        head = make_user(Role.ACADEMIC_HEAD, department=cse)
        assert _read(client, head, cse) == 200
        assert _read(client, head, ece) == 404

    def test_faculty_reads_their_home_department(
        self, client: TestClient, make_user: UserFactory, cse, ece, settings_both
    ) -> None:
        teacher = make_user(Role.FACULTY, department=cse)
        assert _read(client, teacher, cse) == 200
        assert _read(client, teacher, ece) == 404

    def test_faculty_reads_the_departments_of_the_classes_they_teach(
        self,
        client: TestClient,
        make_user: UserFactory,
        org: OrgFactory,
        term,
        cse,
        ece,
        settings_both,
    ) -> None:
        teacher = make_user(Role.FACULTY)  # no home department
        org.offering(org.course(ece), org.section(ece), term, faculty=[teacher])
        assert _read(client, teacher, ece) == 200
        assert _read(client, teacher, cse) == 404

    def test_faculty_with_no_department_and_no_class_reads_nothing(
        self, client: TestClient, faculty: User, cse, ece, settings_both
    ) -> None:
        assert _read(client, faculty, cse) == _read(client, faculty, ece) == 404

    def test_a_course_coordinator_reads_the_departments_of_their_courses(
        self,
        client: TestClient,
        make_user: UserFactory,
        org: OrgFactory,
        term,
        cse,
        ece,
        db_session: Session,
        settings_both,
    ) -> None:
        coordinator = make_user(Role.COURSE_COORDINATOR, department=cse)
        course = org.course(ece)
        org.offering(course, org.section(ece), term)
        db_session.add(CourseCoordinator(course_id=course.id, user_id=coordinator.id))
        db_session.flush()
        assert _read(client, coordinator, cse) == 200
        assert _read(client, coordinator, ece) == 200

    def test_being_removed_from_a_class_removes_access(
        self,
        client: TestClient,
        make_user: UserFactory,
        org: OrgFactory,
        term,
        ece,
        admin: User,
        settings_both,
    ) -> None:
        teacher = make_user(Role.FACULTY)
        offering = org.offering(org.course(ece), org.section(ece), term, faculty=[teacher])
        assert _read(client, teacher, ece) == 200
        removed = client.delete(
            f"/api/v1/offerings/{offering.id}/faculty/{teacher.id}", headers=auth_headers(admin)
        )
        assert removed.status_code in (200, 204)
        assert _read(client, teacher, ece) == 404

    def test_out_of_scope_looks_exactly_like_a_missing_department(
        self, client: TestClient, hod: User, ece, settings_both
    ) -> None:
        hidden = client.get(_url(ece), headers=auth_headers(hod))
        missing = client.get(_url(uuid.uuid4()), headers=auth_headers(hod))
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json()

    def test_anonymous_is_401(self, client: TestClient, cse) -> None:
        assert client.get(_url(cse)).status_code == 401


class TestWriteScope:
    def test_admin_writes_any_department(self, client: TestClient, admin: User, ece) -> None:
        body = {"value": 1}
        assert client.put(_url(ece, "K"), json=body, headers=auth_headers(admin)).status_code == 200

    def test_another_departments_hod_gets_404(self, client: TestClient, hod: User, ece) -> None:
        body = {"value": 1}
        assert client.put(_url(ece, "K"), json=body, headers=auth_headers(hod)).status_code == 404
        assert client.delete(_url(ece, "K"), headers=auth_headers(hod)).status_code == 404

    def test_faculty_can_read_but_not_change_their_department(
        self, client: TestClient, make_user: UserFactory, cse
    ) -> None:
        teacher = make_user(Role.FACULTY, department=cse)
        headers = auth_headers(teacher)
        assert client.get(_url(cse), headers=headers).status_code == 200
        assert client.put(_url(cse, "K"), json={"value": 1}, headers=headers).status_code == 403
        assert client.delete(_url(cse, "K"), headers=headers).status_code == 403

    def test_faculty_outside_the_department_gets_404_for_writes(
        self, client: TestClient, faculty: User, ece
    ) -> None:
        response = client.put(_url(ece, "K"), json={"value": 1}, headers=auth_headers(faculty))
        assert response.status_code == 404

    def test_academic_head_cannot_change_settings(
        self, client: TestClient, make_user: UserFactory, cse
    ) -> None:
        head = make_user(Role.ACADEMIC_HEAD, department=cse)
        response = client.put(_url(cse, "K"), json={"value": 1}, headers=auth_headers(head))
        assert response.status_code == 403


class TestWorkspaceListsReadableDepartments:
    def _departments(self, client: TestClient, user: User) -> dict[str, bool]:
        body = client.get("/api/v1/me/workspace", headers=auth_headers(user)).json()
        return {d["code"]: d["can_edit"] for d in body["threshold_departments"]}

    def test_matches_the_api_rule_for_each_role(
        self,
        client: TestClient,
        admin: User,
        hod: User,
        make_user: UserFactory,
        org: OrgFactory,
        term,
        cse,
        ece,
    ) -> None:
        assert self._departments(client, admin) == {"CSE": True, "ECE": True}
        assert self._departments(client, hod) == {"CSE": True}
        teacher = make_user(Role.FACULTY, department=cse)
        org.offering(org.course(ece), org.section(ece), term, faculty=[teacher])
        assert self._departments(client, teacher) == {"CSE": False, "ECE": False}
        assert self._departments(client, make_user(Role.FACULTY)) == {}

    def test_every_listed_department_is_readable_and_no_other(
        self,
        client: TestClient,
        make_user: UserFactory,
        org: OrgFactory,
        term,
        cse,
        ece,
        db_session: Session,
    ) -> None:
        teacher = make_user(Role.FACULTY)
        org.offering(org.course(ece), org.section(ece), term, faculty=[teacher])
        listed = set(self._departments(client, teacher))
        for department in db_session.scalars(select(Department)):
            expected = 200 if department.code in listed else 404
            assert _read(client, teacher, department) == expected, department.code


def test_key_format(client: TestClient, admin: User, cse) -> None:
    response = client.put(_url(cse, "bad key!"), json={"value": 1}, headers=auth_headers(admin))
    assert response.status_code == 422


def test_unknown_department(client: TestClient, admin: User) -> None:
    response = client.get(_url(uuid.uuid4()), headers=auth_headers(admin))
    assert response.status_code == 404


def test_analytics_still_resolves_a_departments_thresholds_for_its_offerings(
    db_session: Session,
    cse,
) -> None:
    """The engine's own read (no actor) is not scoped: it runs for an offering the caller was
    already authorised to view."""
    from app.modules.assessments.service import SettingsService
    from app.modules.organization.models import Department as Dept

    assert SettingsService(db_session).as_dict(db_session.get(Dept, cse.id).id) == {}
