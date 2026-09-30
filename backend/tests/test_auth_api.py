from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_refresh_token
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from tests.conftest import DEFAULT_PASSWORD, auth_headers, login

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def _stored(db: Session, raw_refresh: str) -> RefreshToken:
    return db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
    )


class TestLogin:
    def test_success_returns_token_pair_and_records_login(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        body = login(client, faculty.email)

        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]
        assert body["refresh_token_expires_at"] > body["access_token_expires_at"]
        db_session.refresh(faculty)
        assert faculty.last_login_at is not None
        stored = _stored(db_session, body["refresh_token"])
        assert stored is not None and stored.revoked_at is None
        assert stored.token_hash != body["refresh_token"]  # never stored in plaintext

    def test_email_is_case_and_whitespace_insensitive(
        self, client: TestClient, faculty: User
    ) -> None:
        response = client.post(
            LOGIN, json={"email": "  Faculty.ONE@SRMIST.EDU.IN ", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 200

    def test_wrong_password_and_unknown_email_look_identical(
        self, client: TestClient, faculty: User
    ) -> None:
        wrong_pw = client.post(LOGIN, json={"email": faculty.email, "password": "nope-nope"})
        unknown = client.post(LOGIN, json={"email": "ghost@srmist.edu.in", "password": "nope-nope"})

        assert wrong_pw.status_code == unknown.status_code == 401
        assert wrong_pw.json() == unknown.json()
        assert wrong_pw.json()["error"]["code"] == "not_authenticated"
        assert wrong_pw.headers["www-authenticate"] == "Bearer"

    def test_inactive_user_cannot_log_in(self, client: TestClient, make_user) -> None:
        user = make_user(is_active=False)
        response = client.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid email or password."

    def test_missing_fields_use_error_envelope(self, client: TestClient) -> None:
        response = client.post(LOGIN, json={"email": "a@b.c"})
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert error["details"][0]["loc"] == ["body", "password"]

    def test_unknown_fields_rejected(self, client: TestClient, faculty: User) -> None:
        response = client.post(
            LOGIN, json={"email": faculty.email, "password": DEFAULT_PASSWORD, "role": "ADMIN"}
        )
        assert response.status_code == 422


class TestMe:
    def test_returns_current_user_without_secrets(self, client: TestClient, faculty: User) -> None:
        tokens = login(client, faculty.email)
        response = client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == faculty.email and body["role"] == "FACULTY"
        assert "password_hash" not in body and "password" not in body

    def test_requires_token(self, client: TestClient) -> None:
        response = client.get(ME)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    def test_rejects_garbage_and_expired_tokens(self, client: TestClient, faculty: User) -> None:
        expired, _ = create_access_token(
            faculty.id, faculty.role.value, expires_delta=timedelta(seconds=-1)
        )
        for token in ("garbage", expired):
            response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 401

    def test_refresh_token_cannot_be_used_as_access_token(
        self, client: TestClient, faculty: User
    ) -> None:
        tokens = login(client, faculty.email)
        response = client.get(ME, headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
        assert response.status_code == 401

    def test_deactivated_user_loses_access_immediately(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        headers = auth_headers(faculty)
        assert client.get(ME, headers=headers).status_code == 200

        faculty.is_active = False
        db_session.flush()

        assert client.get(ME, headers=headers).status_code == 401

    def test_role_comes_from_database_not_token(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        token, _ = create_access_token(faculty.id, "ADMIN")  # stale/forged role claim
        response = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def _age_rotation(db_session: Session, raw_token: str, seconds: int = 120) -> None:
    """Move a rotation out of the concurrent-refresh grace window, so reusing the token
    is a replay rather than a race."""
    stored = _stored(db_session, raw_token)
    stored.revoked_at = stored.revoked_at - timedelta(seconds=seconds)
    db_session.flush()


class TestRefreshRotation:
    def test_rotation_issues_new_pair_and_revokes_old(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        first = login(client, faculty.email)
        response = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})

        assert response.status_code == 200
        second = response.json()
        assert second["refresh_token"] != first["refresh_token"]
        old, new = (
            _stored(db_session, first["refresh_token"]),
            _stored(db_session, second["refresh_token"]),
        )
        assert old.revoked_at is not None and old.replaced_by_id == new.id
        assert new.family_id == old.family_id and new.revoked_at is None
        me = client.get(ME, headers={"Authorization": f"Bearer {second['access_token']}"})
        assert me.status_code == 200

    def test_reuse_of_rotated_token_revokes_whole_family(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        first = login(client, faculty.email)
        second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()
        _age_rotation(db_session, first["refresh_token"])

        replay = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        assert replay.status_code == 401
        assert "reuse" in replay.json()["error"]["message"]

        # The legitimate newest token is now dead too.
        assert (
            client.post(REFRESH, json={"refresh_token": second["refresh_token"]}).status_code == 401
        )
        assert _stored(db_session, second["refresh_token"]).revoked_at is not None

    def test_other_sessions_unaffected_by_reuse(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        laptop = login(client, faculty.email)
        phone = login(client, faculty.email)
        client.post(REFRESH, json={"refresh_token": laptop["refresh_token"]})
        _age_rotation(db_session, laptop["refresh_token"])
        replay = client.post(REFRESH, json={"refresh_token": laptop["refresh_token"]})
        assert replay.status_code == 401

        assert (
            client.post(REFRESH, json={"refresh_token": phone["refresh_token"]}).status_code == 200
        )

    def test_concurrent_refresh_within_grace_keeps_session(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        """Two tabs refreshing with the same cookie at once must not log the user out."""
        first = login(client, faculty.email)
        tab_a = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        tab_b = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})

        assert tab_a.status_code == 200 and tab_b.status_code == 200
        for tab in (tab_a.json(), tab_b.json()):
            assert _stored(db_session, tab["refresh_token"]).revoked_at is None
            me = client.get(ME, headers={"Authorization": f"Bearer {tab['access_token']}"})
            assert me.status_code == 200
        assert (
            _stored(db_session, tab_a.json()["refresh_token"]).family_id
            == _stored(db_session, first["refresh_token"]).family_id
        )

    def test_grace_does_not_survive_logout(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        first = login(client, faculty.email)
        second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()
        client.post(LOGOUT, json={"refresh_token": second["refresh_token"]})

        replay = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        assert replay.status_code == 401

    def test_expired_refresh_token_rejected(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        tokens = login(client, faculty.email)
        _stored(db_session, tokens["refresh_token"]).expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        db_session.flush()

        assert (
            client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]}).status_code == 401
        )

    def test_unknown_refresh_token_rejected(self, client: TestClient) -> None:
        response = client.post(REFRESH, json={"refresh_token": "never-issued"})
        assert response.status_code == 401

    def test_deactivated_user_cannot_refresh(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        tokens = login(client, faculty.email)
        faculty.is_active = False
        db_session.flush()

        assert (
            client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]}).status_code == 401
        )


class TestLogout:
    def test_logout_revokes_session(
        self, client: TestClient, faculty: User, db_session: Session
    ) -> None:
        first = login(client, faculty.email)
        second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()

        response = client.post(LOGOUT, json={"refresh_token": second["refresh_token"]})

        assert response.status_code == 204
        assert (
            client.post(REFRESH, json={"refresh_token": second["refresh_token"]}).status_code == 401
        )
        assert _stored(db_session, second["refresh_token"]).revoked_at is not None

    def test_logout_is_idempotent_and_does_not_leak(
        self, client: TestClient, faculty: User
    ) -> None:
        tokens = login(client, faculty.email)
        assert (
            client.post(LOGOUT, json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        )
        assert (
            client.post(LOGOUT, json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        )
        assert client.post(LOGOUT, json={"refresh_token": "never-issued"}).status_code == 204
