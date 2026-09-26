import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.users.models import Role, User
from tests.conftest import auth_headers, login

USERS = "/api/v1/users"
NEW_USER = {
    "email": "Priya.Raman@SRMIST.edu.in",
    "full_name": "  Priya Raman ",
    "password": "a-strong-passphrase",
    "role": "FACULTY",
}


class TestAuthorisation:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", USERS),
            ("post", USERS),
            ("get", f"{USERS}/{uuid.uuid4()}"),
            ("patch", f"{USERS}/{uuid.uuid4()}"),
            ("post", f"{USERS}/{uuid.uuid4()}/deactivate"),
            ("post", f"{USERS}/{uuid.uuid4()}/activate"),
        ],
    )
    def test_every_endpoint_requires_authentication(
        self, client: TestClient, method: str, path: str
    ) -> None:
        response = client.request(method, path, json={})
        assert response.status_code == 401

    def test_faculty_is_forbidden(self, client: TestClient, faculty: User) -> None:
        headers = auth_headers(faculty)

        assert client.get(USERS, headers=headers).status_code == 403
        assert client.post(USERS, json=NEW_USER, headers=headers).status_code == 403
        response = client.get(f"{USERS}/{faculty.id}", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"

    def test_hod_can_look_up_but_not_manage_users(
        self, client: TestClient, hod: User, faculty: User
    ) -> None:
        headers = auth_headers(hod)

        assert client.get(USERS, headers=headers).status_code == 200
        assert client.get(f"{USERS}/{faculty.id}", headers=headers).status_code == 200
        assert client.post(USERS, json=NEW_USER, headers=headers).status_code == 403
        assert (
            client.patch(
                f"{USERS}/{faculty.id}", json={"full_name": "X"}, headers=headers
            ).status_code
            == 403
        )
        assert client.post(f"{USERS}/{faculty.id}/deactivate", headers=headers).status_code == 403


class TestCreate:
    def test_admin_creates_user_with_normalised_email(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post(USERS, json=NEW_USER, headers=auth_headers(admin))

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "priya.raman@srmist.edu.in"
        assert body["full_name"] == "Priya Raman"
        assert body["role"] == "FACULTY" and body["is_active"] is True
        assert "password" not in body and "password_hash" not in body

    def test_created_user_can_log_in(self, client: TestClient, admin: User) -> None:
        client.post(USERS, json=NEW_USER, headers=auth_headers(admin))
        tokens = login(client, "priya.raman@srmist.edu.in", NEW_USER["password"])
        assert tokens["access_token"]

    def test_duplicate_email_is_conflict_regardless_of_case(
        self, client: TestClient, admin: User, faculty: User
    ) -> None:
        response = client.post(
            USERS, json={**NEW_USER, "email": faculty.email.upper()}, headers=auth_headers(admin)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("email", "not-an-email"),
            ("password", "short"),
            ("password", "x" * 129),
            ("full_name", "   "),
            ("role", "SUPERUSER"),
        ],
    )
    def test_invalid_input_rejected(
        self, client: TestClient, admin: User, field: str, value: str
    ) -> None:
        response = client.post(USERS, json={**NEW_USER, field: value}, headers=auth_headers(admin))
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["loc"][:2] == ["body", field]


class TestReadAndList:
    def test_get_by_id_and_404(self, client: TestClient, admin: User, faculty: User) -> None:
        headers = auth_headers(admin)
        assert client.get(f"{USERS}/{faculty.id}", headers=headers).json()["id"] == str(faculty.id)

        missing = client.get(f"{USERS}/{uuid.uuid4()}", headers=headers)
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

        malformed = client.get(f"{USERS}/not-a-uuid", headers=headers)
        assert malformed.status_code == 422

    def test_list_paginates_and_filters(self, client: TestClient, admin: User, make_user) -> None:
        for _ in range(3):
            make_user(Role.FACULTY)
        make_user(Role.FACULTY, is_active=False)
        headers = auth_headers(admin)

        page = client.get(USERS, params={"limit": 2, "offset": 0}, headers=headers).json()
        assert page["total"] == 5 and len(page["items"]) == 2 and page["limit"] == 2

        active_faculty = client.get(
            USERS, params={"role": "FACULTY", "is_active": "true"}, headers=headers
        ).json()
        assert active_faculty["total"] == 3

        assert client.get(USERS, params={"limit": 0}, headers=headers).status_code == 422
        assert client.get(USERS, params={"limit": 201}, headers=headers).status_code == 422


class TestUpdate:
    def test_update_name_role_and_department(
        self, client: TestClient, admin: User, faculty: User, cse
    ) -> None:
        response = client.patch(
            f"{USERS}/{faculty.id}",
            json={"full_name": "Farah K", "role": "HOD", "department_id": str(cse.id)},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["full_name"] == "Farah K" and body["role"] == "HOD"
        assert body["department_id"] == str(cse.id)

    def test_hod_requires_department(self, client: TestClient, admin: User, faculty: User) -> None:
        response = client.patch(
            f"{USERS}/{faculty.id}", json={"role": "HOD"}, headers=auth_headers(admin)
        )
        assert response.status_code == 422
        assert "department" in response.json()["error"]["message"]

        created = client.post(USERS, json={**NEW_USER, "role": "HOD"}, headers=auth_headers(admin))
        assert created.status_code == 422

    def test_unknown_department_rejected(self, client: TestClient, admin: User) -> None:
        response = client.post(
            USERS,
            json={**NEW_USER, "department_id": str(uuid.uuid4())},
            headers=auth_headers(admin),
        )
        assert response.status_code == 404

    def test_clearing_department(self, client: TestClient, admin: User, make_user, cse) -> None:
        user = make_user(Role.FACULTY, department=cse)
        response = client.patch(
            f"{USERS}/{user.id}", json={"department_id": None}, headers=auth_headers(admin)
        )
        assert response.status_code == 200 and response.json()["department_id"] is None

    def test_password_reset_revokes_existing_sessions(
        self, client: TestClient, admin: User, faculty: User
    ) -> None:
        old = login(client, faculty.email)
        response = client.patch(
            f"{USERS}/{faculty.id}",
            json={"password": "brand-new-passphrase"},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200
        refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
        assert refresh.status_code == 401
        assert login(client, faculty.email, "brand-new-passphrase")["access_token"]

    def test_admin_cannot_demote_self(self, client: TestClient, admin: User) -> None:
        response = client.patch(
            f"{USERS}/{admin.id}", json={"role": "FACULTY"}, headers=auth_headers(admin)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "business_rule_violation"

    def test_unknown_fields_rejected(self, client: TestClient, admin: User, faculty: User) -> None:
        response = client.patch(
            f"{USERS}/{faculty.id}", json={"is_active": False}, headers=auth_headers(admin)
        )
        assert response.status_code == 422


class TestActivation:
    def test_deactivate_blocks_login_and_revokes_sessions(
        self, client: TestClient, admin: User, faculty: User
    ) -> None:
        tokens = login(client, faculty.email)

        response = client.post(f"{USERS}/{faculty.id}/deactivate", headers=auth_headers(admin))

        assert response.status_code == 200 and response.json()["is_active"] is False
        assert (
            client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            ).status_code
            == 401
        )
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    def test_reactivate(self, client: TestClient, admin: User, make_user) -> None:
        user = make_user(is_active=False)
        response = client.post(f"{USERS}/{user.id}/activate", headers=auth_headers(admin))
        assert response.status_code == 200 and response.json()["is_active"] is True

    def test_admin_cannot_deactivate_self(self, client: TestClient, admin: User) -> None:
        response = client.post(f"{USERS}/{admin.id}/deactivate", headers=auth_headers(admin))
        assert response.status_code == 422

    def test_deactivation_is_idempotent(
        self, client: TestClient, admin: User, make_user, db_session: Session
    ) -> None:
        user = make_user(is_active=False)
        response = client.post(f"{USERS}/{user.id}/deactivate", headers=auth_headers(admin))
        assert response.status_code == 200 and response.json()["is_active"] is False
