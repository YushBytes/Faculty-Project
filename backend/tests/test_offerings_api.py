"""Course offerings and faculty scope — the core access rule of the platform."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.organization.models import AcademicTerm, CourseOffering, Department
from app.modules.organization.scope import visible_offering_ids
from app.modules.users.models import Role, User
from tests.conftest import OrgFactory, auth_headers

OFFERINGS = "/api/v1/offerings"


@pytest.fixture
def world(
    org: OrgFactory, cse: Department, ece: Department, term: AcademicTerm, make_user, faculty
):
    """Two departments, three offerings, several staff."""
    other_faculty = make_user(Role.FACULTY, email="other.fac@srmist.edu.in")
    ece_hod = make_user(Role.HOD, email="hod.ece@srmist.edu.in", department=ece)
    cse_a = org.offering(org.course(cse), org.section(cse), term, faculty=[faculty])
    cse_b = org.offering(org.course(cse), org.section(cse), term, faculty=[other_faculty])
    ece_a = org.offering(org.course(ece), org.section(ece), term, faculty=[other_faculty])
    return {
        "cse_a": cse_a,
        "cse_b": cse_b,
        "ece_a": ece_a,
        "other_faculty": other_faculty,
        "ece_hod": ece_hod,
    }


def _ids(response) -> set[str]:
    return {o["id"] for o in response.json()["items"]}


class TestScopeOnList:
    def test_faculty_sees_only_assigned(self, client: TestClient, faculty: User, world) -> None:
        response = client.get(OFFERINGS, headers=auth_headers(faculty))
        assert response.status_code == 200
        assert _ids(response) == {str(world["cse_a"].id)}
        assert response.json()["total"] == 1

    def test_hod_sees_own_department(self, client: TestClient, hod: User, world) -> None:
        response = client.get(OFFERINGS, headers=auth_headers(hod))
        assert _ids(response) == {str(world["cse_a"].id), str(world["cse_b"].id)}

    def test_hod_also_sees_offerings_they_teach_elsewhere(
        self, client: TestClient, hod: User, world, db_session: Session
    ) -> None:
        from app.modules.organization.models import OfferingFaculty

        db_session.add(OfferingFaculty(offering_id=world["ece_a"].id, user_id=hod.id))
        db_session.flush()
        response = client.get(OFFERINGS, headers=auth_headers(hod))
        assert str(world["ece_a"].id) in _ids(response)

    def test_admin_sees_all(self, client: TestClient, admin: User, world) -> None:
        assert client.get(OFFERINGS, headers=auth_headers(admin)).json()["total"] == 3

    def test_filters_cannot_widen_scope(self, client: TestClient, faculty: User, world) -> None:
        response = client.get(
            OFFERINGS,
            params={"faculty_id": str(world["other_faculty"].id)},
            headers=auth_headers(faculty),
        )
        assert response.json()["total"] == 0

    def test_filters(self, client: TestClient, admin: User, world) -> None:
        response = client.get(
            OFFERINGS,
            params={"faculty_id": str(world["other_faculty"].id)},
            headers=auth_headers(admin),
        )
        assert _ids(response) == {str(world["cse_b"].id), str(world["ece_a"].id)}
        response = client.get(
            OFFERINGS,
            params={"course_id": str(world["ece_a"].course_id)},
            headers=auth_headers(admin),
        )
        assert _ids(response) == {str(world["ece_a"].id)}


class TestScopeOnDetail:
    def test_faculty_can_open_assigned(self, client: TestClient, faculty: User, world) -> None:
        response = client.get(f"{OFFERINGS}/{world['cse_a'].id}", headers=auth_headers(faculty))
        assert response.status_code == 200
        body = response.json()
        assert body["pass_mark_percent"] == 40.0
        assert [f["id"] for f in body["faculty"]] == [str(faculty.id)]
        assert {"course", "term", "section"} <= body.keys()

    def test_cross_offering_access_is_not_found(
        self, client: TestClient, faculty: User, world
    ) -> None:
        for key in ("cse_b", "ece_a"):
            response = client.get(f"{OFFERINGS}/{world[key].id}", headers=auth_headers(faculty))
            assert response.status_code == 404
            assert response.json()["error"]["message"] == "Course offering not found."

    def test_hod_cannot_open_other_department(self, client: TestClient, hod: User, world) -> None:
        response = client.get(f"{OFFERINGS}/{world['ece_a'].id}", headers=auth_headers(hod))
        assert response.status_code == 404

    def test_faculty_cannot_modify_even_when_assigned(
        self, client: TestClient, faculty: User, world
    ) -> None:
        headers = auth_headers(faculty)
        offering_id = world["cse_a"].id
        assert (
            client.patch(
                f"{OFFERINGS}/{offering_id}", json={"pass_mark_percent": 50}, headers=headers
            ).status_code
            == 403
        )
        assert client.delete(f"{OFFERINGS}/{offering_id}", headers=headers).status_code == 403
        assert (
            client.post(
                f"{OFFERINGS}/{offering_id}/faculty",
                json={"user_id": str(faculty.id)},
                headers=headers,
            ).status_code
            == 403
        )

    def test_hod_teaching_elsewhere_can_view_but_not_administer(
        self, client: TestClient, hod: User, world, db_session: Session
    ) -> None:
        from app.modules.organization.models import OfferingFaculty

        db_session.add(OfferingFaculty(offering_id=world["ece_a"].id, user_id=hod.id))
        db_session.flush()
        headers = auth_headers(hod)
        offering_id = world["ece_a"].id
        assert client.get(f"{OFFERINGS}/{offering_id}", headers=headers).status_code == 200
        response = client.patch(
            f"{OFFERINGS}/{offering_id}", json={"pass_mark_percent": 50}, headers=headers
        )
        assert response.status_code == 403


class TestCreate:
    def _body(self, course, section, term, **extra) -> dict:
        return {
            "course_id": str(course.id),
            "section_id": str(section.id),
            "term_id": str(term.id),
            **extra,
        }

    def test_admin_creates_with_faculty(
        self, client: TestClient, admin: User, faculty: User, org: OrgFactory, cse, term
    ) -> None:
        body = self._body(
            org.course(cse),
            org.section(cse),
            term,
            pass_mark_percent=45.5,
            faculty_ids=[str(faculty.id), str(faculty.id)],
        )
        response = client.post(OFFERINGS, json=body, headers=auth_headers(admin))
        assert response.status_code == 201
        created = response.json()
        assert created["pass_mark_percent"] == 45.5
        assert [f["id"] for f in created["faculty"]] == [str(faculty.id)]

        # The assigned faculty can now see it.
        mine = client.get(OFFERINGS, headers=auth_headers(faculty))
        assert created["id"] in _ids(mine)

    def test_duplicate_offering_conflicts(
        self, client: TestClient, admin: User, cse_offering: CourseOffering
    ) -> None:
        body = self._body(cse_offering.course, cse_offering.section, cse_offering.term)
        assert client.post(OFFERINGS, json=body, headers=auth_headers(admin)).status_code == 409

    def test_hod_can_offer_own_course_to_other_department_section(
        self, client: TestClient, hod: User, org: OrgFactory, cse, ece, term
    ) -> None:
        body = self._body(org.course(cse), org.section(ece), term)
        assert client.post(OFFERINGS, json=body, headers=auth_headers(hod)).status_code == 201

    def test_hod_cannot_offer_other_department_course(
        self, client: TestClient, hod: User, org: OrgFactory, cse, ece, term
    ) -> None:
        body = self._body(org.course(ece), org.section(cse), term)
        assert client.post(OFFERINGS, json=body, headers=auth_headers(hod)).status_code == 403

    def test_faculty_cannot_create(
        self, client: TestClient, faculty: User, org: OrgFactory, cse, term
    ) -> None:
        body = self._body(org.course(cse), org.section(cse), term)
        assert client.post(OFFERINGS, json=body, headers=auth_headers(faculty)).status_code == 403

    @pytest.mark.parametrize("bad_role", ["admin", "inactive"])
    def test_only_active_teaching_staff_assignable(
        self,
        client: TestClient,
        admin: User,
        make_user,
        org: OrgFactory,
        cse,
        term,
        bad_role: str,
    ) -> None:
        target = admin if bad_role == "admin" else make_user(Role.FACULTY, is_active=False)
        body = self._body(org.course(cse), org.section(cse), term, faculty_ids=[str(target.id)])
        response = client.post(OFFERINGS, json=body, headers=auth_headers(admin))
        assert response.status_code == 422

    def test_unknown_references(
        self, client: TestClient, admin: User, org: OrgFactory, cse, term
    ) -> None:
        body = self._body(org.course(cse), org.section(cse), term)
        response = client.post(
            OFFERINGS, json={**body, "term_id": str(uuid.uuid4())}, headers=auth_headers(admin)
        )
        assert response.status_code == 404
        response = client.post(
            OFFERINGS,
            json={**body, "faculty_ids": [str(uuid.uuid4())]},
            headers=auth_headers(admin),
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("mark", [-1, 100.01, "abc"])
    def test_pass_mark_range(
        self, client: TestClient, admin: User, org: OrgFactory, cse, term, mark
    ) -> None:
        body = self._body(org.course(cse), org.section(cse), term, pass_mark_percent=mark)
        assert client.post(OFFERINGS, json=body, headers=auth_headers(admin)).status_code == 422


class TestAdminister:
    def test_hod_updates_pass_mark(
        self, client: TestClient, hod: User, cse_offering: CourseOffering
    ) -> None:
        response = client.patch(
            f"{OFFERINGS}/{cse_offering.id}",
            json={"pass_mark_percent": 50},
            headers=auth_headers(hod),
        )
        assert response.status_code == 200 and response.json()["pass_mark_percent"] == 50.0

    def test_assign_and_unassign_controls_access(
        self,
        client: TestClient,
        admin: User,
        make_user,
        cse_offering: CourseOffering,
    ) -> None:
        newcomer = make_user(Role.FACULTY, email="new.fac@srmist.edu.in")
        url = f"{OFFERINGS}/{cse_offering.id}"
        assert client.get(url, headers=auth_headers(newcomer)).status_code == 404

        assigned = client.post(
            f"{url}/faculty", json={"user_id": str(newcomer.id)}, headers=auth_headers(admin)
        )
        assert assigned.status_code == 200
        assert str(newcomer.id) in [f["id"] for f in assigned.json()["faculty"]]
        again = client.post(
            f"{url}/faculty", json={"user_id": str(newcomer.id)}, headers=auth_headers(admin)
        )
        assert again.status_code == 200 and len(again.json()["faculty"]) == 2  # idempotent
        assert client.get(url, headers=auth_headers(newcomer)).status_code == 200

        removed = client.delete(f"{url}/faculty/{newcomer.id}", headers=auth_headers(admin))
        assert removed.status_code == 200
        assert client.get(url, headers=auth_headers(newcomer)).status_code == 404
        assert (
            client.delete(f"{url}/faculty/{newcomer.id}", headers=auth_headers(admin)).status_code
            == 404
        )

    def test_delete_offering(
        self, client: TestClient, admin: User, cse_offering: CourseOffering
    ) -> None:
        url = f"{OFFERINGS}/{cse_offering.id}"
        assert client.delete(url, headers=auth_headers(admin)).status_code == 204
        assert client.get(url, headers=auth_headers(admin)).status_code == 404


def test_visible_offering_ids_subquery(
    db_session: Session, faculty: User, admin: User, world
) -> None:
    """The reusable subquery other modules (students, results, analytics) filter with."""
    mine = set(db_session.scalars(visible_offering_ids(faculty)))
    everything = set(db_session.scalars(visible_offering_ids(admin)))
    assert mine == {world["cse_a"].id}
    assert everything == {world["cse_a"].id, world["cse_b"].id, world["ece_a"].id}
