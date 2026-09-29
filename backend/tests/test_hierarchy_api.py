"""The five-level hierarchy: ADMIN > HOD > ACADEMIC_HEAD > COURSE_COORDINATOR > FACULTY.

Scope is enforced server-side; these tests call the API as each role and check both what
it can reach and what it cannot (404 for out-of-scope offerings, 403 for visible but not
administrable ones).
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.organization.models import CourseCoordinator
from app.modules.users.models import Role
from tests.conftest import auth_headers

API = "/api/v1"


def _coordinate(db: Session, course, user) -> None:
    db.add(CourseCoordinator(course_id=course.id, user_id=user.id))
    db.flush()


class TestHierarchyScope:
    def _world(self, make_user, org, cse, ece, term):
        dsa, os_ = org.course(cse, "21CSC201J"), org.course(cse, "21CSC202J")
        ece_course = org.course(ece, "21ECC201J")
        a1, a2 = org.section(cse, "A1"), org.section(cse, "A2")
        e1 = org.section(ece, "E1")
        teacher = make_user(Role.FACULTY, department=cse)
        other_teacher = make_user(Role.FACULTY, department=cse)
        coord = make_user(Role.COURSE_COORDINATOR, department=cse)
        head = make_user(Role.ACADEMIC_HEAD, department=cse)
        offerings = {
            "dsa_a1": org.offering(dsa, a1, term, [teacher]),
            "dsa_a2": org.offering(dsa, a2, term, [other_teacher]),
            "os_a1": org.offering(os_, a1, term, [other_teacher]),
            "ece": org.offering(ece_course, e1, term),
        }
        return dsa, os_, teacher, other_teacher, coord, head, offerings

    def test_each_role_sees_exactly_its_scope(
        self, client: TestClient, db_session, make_user, org, cse, ece, term, admin, hod
    ) -> None:
        dsa, _, teacher, _, coord, head, o = self._world(make_user, org, cse, ece, term)
        _coordinate(db_session, dsa, coord)

        def visible(user) -> set:
            r = client.get(f"{API}/offerings", params={"limit": 200}, headers=auth_headers(user))
            assert r.status_code == 200
            return {item["id"] for item in r.json()["items"]}

        ids = {k: str(v.id) for k, v in o.items()}
        assert visible(admin) == set(ids.values())
        assert visible(hod) == {ids["dsa_a1"], ids["dsa_a2"], ids["os_a1"]}
        assert visible(head) == {ids["dsa_a1"], ids["dsa_a2"], ids["os_a1"]}
        assert visible(coord) == {ids["dsa_a1"], ids["dsa_a2"]}
        assert visible(teacher) == {ids["dsa_a1"]}

        # Out of scope is indistinguishable from non-existent.
        assert (
            client.get(f"{API}/offerings/{ids['os_a1']}", headers=auth_headers(coord)).status_code
            == 404
        )
        assert (
            client.get(
                f"{API}/offerings/{ids['dsa_a2']}", headers=auth_headers(teacher)
            ).status_code
            == 404
        )
        assert (
            client.get(f"{API}/offerings/{ids['ece']}", headers=auth_headers(head)).status_code
            == 404
        )

    def test_coordinator_administers_only_their_course(
        self, client: TestClient, db_session, make_user, org, cse, ece, term
    ) -> None:
        dsa, _, teacher, other, coord, _, o = self._world(make_user, org, cse, ece, term)
        _coordinate(db_session, dsa, coord)
        headers = auth_headers(coord)
        # Reassign a DSA section to another teacher: allowed.
        r = client.post(
            f"{API}/offerings/{o['dsa_a1'].id}/faculty",
            json={"user_id": str(other.id)},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert {f["id"] for f in r.json()["faculty"]} == {str(teacher.id), str(other.id)}
        # OS is not theirs: not even visible.
        r = client.post(
            f"{API}/offerings/{o['os_a1'].id}/faculty",
            json={"user_id": str(teacher.id)},
            headers=headers,
        )
        assert r.status_code == 404
        # A faculty member can view their offering but not administer it.
        r = client.post(
            f"{API}/offerings/{o['dsa_a1'].id}/faculty",
            json={"user_id": str(other.id)},
            headers=auth_headers(teacher),
        )
        assert r.status_code == 403

    def test_academic_head_appoints_coordinators(
        self, client: TestClient, db_session, make_user, org, cse, ece, term
    ) -> None:
        dsa, _, teacher, _, coord, head, _ = self._world(make_user, org, cse, ece, term)
        headers = auth_headers(head)
        # A plain faculty member cannot coordinate until their role changes.
        r = client.post(
            f"{API}/courses/{dsa.id}/coordinators",
            json={"user_id": str(teacher.id)},
            headers=headers,
        )
        assert r.status_code == 422
        r = client.post(
            f"{API}/courses/{dsa.id}/coordinators", json={"user_id": str(coord.id)}, headers=headers
        )
        assert r.status_code == 200, r.text
        assert [c["id"] for c in r.json()["coordinators"]] == [str(coord.id)]
        # The Academic Head can promote a faculty member to coordinator ...
        r = client.patch(
            f"{API}/users/{teacher.id}", json={"role": "COURSE_COORDINATOR"}, headers=headers
        )
        assert r.status_code == 200, r.text
        # ... but cannot create another Academic Head or touch the HOD level.
        body = {
            "email": "x.head@srmist.edu.in",
            "full_name": "X",
            "password": "a-strong-passphrase",
            "role": "ACADEMIC_HEAD",
        }
        assert client.post(f"{API}/users", json=body, headers=headers).status_code == 403
        # Demoting a coordinator removes their course ownership (history stays in the audit log).
        r = client.patch(f"{API}/users/{coord.id}", json={"role": "FACULTY"}, headers=headers)
        assert r.status_code == 200
        assert (
            db_session.scalar(
                select(CourseCoordinator).where(CourseCoordinator.user_id == coord.id)
            )
            is None
        )
        # Coordinators and faculty cannot appoint coordinators.
        r = client.post(
            f"{API}/courses/{dsa.id}/coordinators",
            json={"user_id": str(teacher.id)},
            headers=auth_headers(teacher),
        )
        assert r.status_code == 403


class TestSingleHeads:
    def test_exactly_one_admin(self, client: TestClient, admin) -> None:
        body = {
            "email": "second.admin@srmist.edu.in",
            "full_name": "Second",
            "password": "a-strong-passphrase",
            "role": "ADMIN",
        }
        r = client.post(f"{API}/users", json=body, headers=auth_headers(admin))
        assert r.status_code == 409

    def test_one_hod_and_one_academic_head_per_department(
        self, client: TestClient, admin, hod, cse, make_user
    ) -> None:
        headers = auth_headers(admin)
        body = {
            "email": "second.hod@srmist.edu.in",
            "full_name": "Second HOD",
            "password": "a-strong-passphrase",
            "role": "HOD",
            "department_id": str(cse.id),
        }
        assert client.post(f"{API}/users", json=body, headers=headers).status_code == 409
        make_user(Role.ACADEMIC_HEAD, department=cse)
        body = {**body, "email": "second.head@srmist.edu.in", "role": "ACADEMIC_HEAD"}
        assert client.post(f"{API}/users", json=body, headers=headers).status_code == 409

    def test_department_roles_need_a_department(self, client: TestClient, admin) -> None:
        body = {
            "email": "coord@srmist.edu.in",
            "full_name": "Coordinator",
            "password": "a-strong-passphrase",
            "role": "COURSE_COORDINATOR",
        }
        assert (
            client.post(f"{API}/users", json=body, headers=auth_headers(admin)).status_code == 422
        )

    def test_course_type_and_semester_are_derived(self, client: TestClient, admin, cse) -> None:
        headers = auth_headers(admin)
        r = client.post(
            f"{API}/courses",
            json={"department_id": str(cse.id), "code": "21DCS201P", "name": "Design Thinking"},
            headers=headers,
        )
        assert r.status_code == 201 and r.json()["course_type"] == "P"
        r = client.post(
            f"{API}/terms",
            json={
                "code": "AY2025-26-EVEN",
                "name": "Even Semester 2025-26",
                "academic_year": "2025-26",
                "start_date": "2026-01-05",
                "end_date": "2026-05-30",
            },
            headers=headers,
        )
        assert r.status_code == 201 and r.json()["semester"] == "EVEN"
