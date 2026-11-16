"""Sign-in role confirmation: optional at the API, compared with the stored role after the
password, never a source of permissions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role, User
from tests.conftest import DEFAULT_PASSWORD, UserFactory

LOGIN = "/api/v1/auth/login"
MISMATCH = "The selected role does not match your account. Please choose your assigned role."


def _login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD, **extra):
    return client.post(LOGIN, json={"email": email, "password": password, **extra})


def _tokens(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(RefreshToken)) or 0


@pytest.fixture
def people(make_user: UserFactory, admin: User, hod: User, cse) -> dict[Role, User]:
    return {
        Role.ADMIN: admin,
        Role.HOD: hod,
        Role.ACADEMIC_HEAD: make_user(Role.ACADEMIC_HEAD, department=cse),
        Role.COURSE_COORDINATOR: make_user(Role.COURSE_COORDINATOR, department=cse),
        Role.FACULTY: make_user(Role.FACULTY, department=cse),
    }


class TestEveryRole:
    @pytest.mark.parametrize("role", list(Role))
    def test_the_right_role_signs_in(
        self, client: TestClient, people: dict[Role, User], role: Role
    ) -> None:
        response = _login(client, people[role].email, role=role.value)
        assert response.status_code == 200, response.text
        claims = decode_access_token(response.json()["access_token"])
        assert claims.role == role.value

    @pytest.mark.parametrize("role", list(Role))
    def test_every_other_role_is_refused_without_tokens(
        self, client: TestClient, people: dict[Role, User], role: Role, db_session: Session
    ) -> None:
        user = people[role]
        for other in (r for r in Role if r is not role):
            before = _tokens(db_session)
            response = _login(client, user.email, role=other.value)
            assert response.status_code == 401, (role, other)
            error = response.json()["error"]
            assert error["code"] == "role_mismatch" and error["message"] == MISMATCH
            assert "access_token" not in response.text and "refresh_token" not in response.text
            assert _tokens(db_session) == before, "a mismatch must not issue a refresh token"


class TestNeverGrantsPermissions:
    def test_faculty_selecting_administrator_is_refused(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        response = _login(client, people[Role.FACULTY].email, role="ADMIN")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "role_mismatch"

    def test_the_token_carries_the_stored_role_and_admin_routes_stay_closed(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        token = _login(client, people[Role.FACULTY].email, role="FACULTY").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/users", headers=headers).status_code == 403
        assert (
            client.post(
                "/api/v1/departments", json={"code": "X", "name": "X"}, headers=headers
            ).status_code
            == 403
        )
        assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "FACULTY"

    def test_extra_fields_cannot_smuggle_a_role(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        email = people[Role.FACULTY].email
        for extra in ({"is_admin": True}, {"claims": {"role": "ADMIN"}}, {"roles": ["ADMIN"]}):
            assert _login(client, email, role="FACULTY", **extra).status_code == 422

    @pytest.mark.parametrize("bad", ["SUPERUSER", "admin ", "", 1, ["ADMIN"], {"r": "ADMIN"}, True])
    def test_unknown_or_malformed_roles_are_rejected(
        self, client: TestClient, people: dict[Role, User], bad: object
    ) -> None:
        response = _login(client, people[Role.ADMIN].email, role=bad)
        assert response.status_code == 422
        assert "access_token" not in response.text


class TestCredentialsFirst:
    def test_wrong_password_keeps_the_generic_message_whatever_the_role(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        email = people[Role.HOD].email
        right_role = _login(client, email, "wrong-password", role="HOD")
        wrong_role = _login(client, email, "wrong-password", role="FACULTY")
        unknown = _login(client, "nobody@srmist.edu.in", "wrong-password", role="HOD")
        assert right_role.status_code == wrong_role.status_code == unknown.status_code == 401
        assert right_role.json() == wrong_role.json() == unknown.json()
        assert right_role.json()["error"]["code"] == "not_authenticated"

    def test_an_inactive_account_gets_the_generic_message_not_a_role_hint(
        self, client: TestClient, make_user: UserFactory
    ) -> None:
        gone = make_user(Role.FACULTY, is_active=False)
        for role in ("FACULTY", "ADMIN"):
            response = _login(client, gone.email, role=role)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "not_authenticated"

    def test_mismatches_count_towards_the_sign_in_throttle(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        from app.core.config import get_settings

        email = people[Role.FACULTY].email
        for _ in range(get_settings().login_max_failures):
            assert _login(client, email, role="HOD").status_code == 401
        assert _login(client, email, role="FACULTY").status_code == 429


class TestBackwardCompatibility:
    def test_no_role_keeps_the_existing_behaviour(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        for user in people.values():
            response = _login(client, user.email)
            assert response.status_code == 200
            assert decode_access_token(response.json()["access_token"]).role == user.role.value

    def test_null_role_is_the_same_as_no_role(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        assert _login(client, people[Role.FACULTY].email, role=None).status_code == 200

    def test_refresh_and_logout_are_unchanged_after_a_role_sign_in(
        self, client: TestClient, people: dict[Role, User]
    ) -> None:
        pair = _login(client, people[Role.HOD].email, role="HOD").json()
        rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert rotated.status_code == 200
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert replay.status_code in (200, 401)  # 10-second race allowance, then reuse detection
        out = client.post(
            "/api/v1/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]}
        )
        assert out.status_code == 204
