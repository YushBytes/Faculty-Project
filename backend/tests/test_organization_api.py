"""Departments, terms, courses and sections: CRUD, validation and role rules."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.modules.organization.models import AcademicTerm, Department
from app.modules.users.models import Role, User
from tests.conftest import OrgFactory, auth_headers

API = "/api/v1"
TERM = {
    "code": "2027-even",
    "name": "Even Semester 2026-27",
    "academic_year": "2026-27",
    "start_date": "2027-01-05",
    "end_date": "2027-05-20",
}


class TestDepartments:
    def test_any_signed_in_user_can_read(self, client: TestClient, faculty: User, cse) -> None:
        response = client.get(f"{API}/departments", headers=auth_headers(faculty))
        assert response.status_code == 200
        assert [d["code"] for d in response.json()["items"]] == ["CSE"]
        assert client.get(f"{API}/departments").status_code == 401

    def test_admin_creates_with_normalised_code(self, client: TestClient, admin: User) -> None:
        response = client.post(
            f"{API}/departments",
            json={"code": " mech ", "name": "Mechanical Engineering"},
            headers=auth_headers(admin),
        )
        assert response.status_code == 201 and response.json()["code"] == "MECH"

    def test_duplicate_code_conflicts(self, client: TestClient, admin: User, cse) -> None:
        response = client.post(
            f"{API}/departments", json={"code": "cse", "name": "Dup"}, headers=auth_headers(admin)
        )
        assert response.status_code == 409

    @pytest.mark.parametrize("role_fixture", ["hod", "faculty"])
    def test_only_admin_writes(
        self, client: TestClient, request: pytest.FixtureRequest, role_fixture: str, cse
    ) -> None:
        headers = auth_headers(request.getfixturevalue(role_fixture))
        assert (
            client.post(
                f"{API}/departments", json={"code": "X", "name": "X"}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"{API}/departments/{cse.id}", json={"name": "X"}, headers=headers
            ).status_code
            == 403
        )
        assert client.delete(f"{API}/departments/{cse.id}", headers=headers).status_code == 403

    def test_update_and_delete(self, client: TestClient, admin: User, ece: Department) -> None:
        headers = auth_headers(admin)
        response = client.patch(
            f"{API}/departments/{ece.id}", json={"name": "ECE Dept"}, headers=headers
        )
        assert response.status_code == 200 and response.json()["name"] == "ECE Dept"
        assert client.delete(f"{API}/departments/{ece.id}", headers=headers).status_code == 204
        assert client.get(f"{API}/departments/{ece.id}", headers=headers).status_code == 404

    def test_delete_in_use_conflicts(
        self, client: TestClient, admin: User, cse: Department, org: OrgFactory
    ) -> None:
        org.course(cse)
        response = client.delete(f"{API}/departments/{cse.id}", headers=auth_headers(admin))
        assert response.status_code == 409
        assert (
            client.get(f"{API}/departments/{cse.id}", headers=auth_headers(admin)).status_code
            == 200
        )


class TestTerms:
    def test_create_normalises_and_lists(self, client: TestClient, admin: User) -> None:
        response = client.post(f"{API}/terms", json=TERM, headers=auth_headers(admin))
        assert response.status_code == 201
        assert response.json()["code"] == "2027-EVEN" and response.json()["is_current"] is False

    @pytest.mark.parametrize(
        "override",
        [
            {"end_date": "2027-01-05"},  # not after start
            {"academic_year": "2026-2027"},
            {"academic_year": "2026-28"},  # not consecutive
            {"code": ""},
        ],
    )
    def test_invalid_terms_rejected(self, client: TestClient, admin: User, override: dict) -> None:
        response = client.post(
            f"{API}/terms", json={**TERM, **override}, headers=auth_headers(admin)
        )
        assert response.status_code == 422

    def test_only_one_current_term(
        self, client: TestClient, admin: User, term: AcademicTerm
    ) -> None:
        headers = auth_headers(admin)
        created = client.post(f"{API}/terms", json={**TERM, "is_current": True}, headers=headers)
        assert created.status_code == 201 and created.json()["is_current"] is True

        current = client.get(f"{API}/terms", params={"is_current": True}, headers=headers).json()
        assert current["total"] == 1 and current["items"][0]["id"] == created.json()["id"]

        switched = client.patch(
            f"{API}/terms/{term.id}", json={"is_current": True}, headers=headers
        )
        assert switched.status_code == 200
        current = client.get(f"{API}/terms", params={"is_current": True}, headers=headers).json()
        assert [t["id"] for t in current["items"]] == [str(term.id)]

    def test_patch_cannot_invert_dates(
        self, client: TestClient, admin: User, term: AcademicTerm
    ) -> None:
        response = client.patch(
            f"{API}/terms/{term.id}", json={"end_date": "2026-01-01"}, headers=auth_headers(admin)
        )
        assert response.status_code == 422

    def test_duplicate_code(self, client: TestClient, admin: User, term: AcademicTerm) -> None:
        response = client.post(
            f"{API}/terms", json={**TERM, "code": term.code}, headers=auth_headers(admin)
        )
        assert response.status_code == 409

    def test_faculty_cannot_write(self, client: TestClient, faculty: User) -> None:
        assert (
            client.post(f"{API}/terms", json=TERM, headers=auth_headers(faculty)).status_code == 403
        )

    def test_delete_term_with_offerings_conflicts(
        self, client: TestClient, admin: User, cse_offering
    ) -> None:
        response = client.delete(f"{API}/terms/{cse_offering.term_id}", headers=auth_headers(admin))
        assert response.status_code == 409


class TestCourses:
    def _body(self, department: Department, **extra) -> dict:
        return {"department_id": str(department.id), "code": "21csc201j", "name": "DSA", **extra}

    def test_admin_creates_in_any_department(
        self, client: TestClient, admin: User, ece: Department
    ) -> None:
        response = client.post(f"{API}/courses", json=self._body(ece), headers=auth_headers(admin))
        assert response.status_code == 201
        body = response.json()
        assert body["code"] == "21CSC201J" and body["department"]["code"] == "ECE"

    def test_hod_limited_to_own_department(
        self, client: TestClient, hod: User, cse: Department, ece: Department
    ) -> None:
        headers = auth_headers(hod)
        assert (
            client.post(f"{API}/courses", json=self._body(cse), headers=headers).status_code == 201
        )
        other = client.post(
            f"{API}/courses", json=self._body(ece, code="21ECC101J"), headers=headers
        )
        assert other.status_code == 403

    def test_hod_cannot_edit_other_department_course(
        self, client: TestClient, hod: User, ece: Department, org: OrgFactory
    ) -> None:
        course = org.course(ece)
        headers = auth_headers(hod)
        assert (
            client.patch(
                f"{API}/courses/{course.id}", json={"name": "X"}, headers=headers
            ).status_code
            == 403
        )
        assert client.delete(f"{API}/courses/{course.id}", headers=headers).status_code == 403

    def test_faculty_cannot_create(self, client: TestClient, faculty: User, cse) -> None:
        response = client.post(
            f"{API}/courses", json=self._body(cse), headers=auth_headers(faculty)
        )
        assert response.status_code == 403

    def test_validation_and_conflicts(
        self, client: TestClient, admin: User, cse: Department, org: OrgFactory
    ) -> None:
        headers = auth_headers(admin)
        existing = org.course(cse)
        dup = client.post(
            f"{API}/courses", json=self._body(cse, code=existing.code.lower()), headers=headers
        )
        assert dup.status_code == 409
        bad_credits = client.post(
            f"{API}/courses", json=self._body(cse, credits=31), headers=headers
        )
        assert bad_credits.status_code == 422
        missing_dept = client.post(
            f"{API}/courses",
            json={**self._body(cse), "department_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert missing_dept.status_code == 404

    def test_list_filters_and_search(
        self, client: TestClient, faculty: User, cse: Department, ece: Department, org: OrgFactory
    ) -> None:
        org.course(cse, code="21CSC301T")
        org.course(ece, code="21ECC301T")
        headers = auth_headers(faculty)
        by_dept = client.get(
            f"{API}/courses", params={"department_id": str(cse.id)}, headers=headers
        ).json()
        assert [c["code"] for c in by_dept["items"]] == ["21CSC301T"]
        found = client.get(f"{API}/courses", params={"q": "ecc"}, headers=headers).json()
        assert [c["code"] for c in found["items"]] == ["21ECC301T"]

    def test_delete_course_with_offering_conflicts(
        self, client: TestClient, admin: User, cse_offering
    ) -> None:
        response = client.delete(
            f"{API}/courses/{cse_offering.course_id}", headers=auth_headers(admin)
        )
        assert response.status_code == 409


class TestSections:
    def test_create_and_uniqueness(self, client: TestClient, hod: User, cse: Department) -> None:
        headers = auth_headers(hod)
        body = {
            "department_id": str(cse.id),
            "name": "a1",
            "batch_year": 2025,
            "program": "B.Tech CSE",
        }
        created = client.post(f"{API}/sections", json=body, headers=headers)
        assert created.status_code == 201 and created.json()["name"] == "A1"
        assert client.post(f"{API}/sections", json=body, headers=headers).status_code == 409
        next_batch = client.post(
            f"{API}/sections", json={**body, "batch_year": 2026}, headers=headers
        )
        assert next_batch.status_code == 201

    def test_hod_other_department_forbidden(
        self, client: TestClient, hod: User, ece: Department
    ) -> None:
        body = {"department_id": str(ece.id), "name": "B1", "batch_year": 2025}
        assert (
            client.post(f"{API}/sections", json=body, headers=auth_headers(hod)).status_code == 403
        )

    def test_invalid_batch_year(self, client: TestClient, admin: User, cse: Department) -> None:
        body = {"department_id": str(cse.id), "name": "B1", "batch_year": 1999}
        assert (
            client.post(f"{API}/sections", json=body, headers=auth_headers(admin)).status_code
            == 422
        )

    def test_list_filters(
        self, client: TestClient, faculty: User, cse: Department, org: OrgFactory
    ) -> None:
        org.section(cse, name="A1")
        response = client.get(
            f"{API}/sections", params={"batch_year": 2025}, headers=auth_headers(faculty)
        )
        assert response.status_code == 200 and response.json()["total"] == 1


class TestUserRoleValidation:
    def test_make_user_helper_respects_hod_rule(self, make_user, cse: Department) -> None:
        assert make_user(Role.HOD, department=cse).department_id == cse.id
