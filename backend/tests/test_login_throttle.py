"""Failed sign-in throttle (app/core/throttle.py): password guessing against one account stops."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.throttle import LoginThrottle
from app.modules.users.models import User
from tests.conftest import DEFAULT_PASSWORD

LOGIN = "/api/v1/auth/login"
LIMIT = get_settings().login_max_failures
WINDOW = get_settings().login_window_seconds


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestThrottleUnit:
    def test_limit_then_refused_until_the_oldest_failure_ages_out(self) -> None:
        clock = Clock()
        throttle = LoginThrottle(clock)
        for _ in range(LIMIT - 1):
            throttle.failed("a@x")
        assert throttle.retry_after("a@x") is None, "one below the limit is still allowed"
        throttle.failed("a@x")
        wait = throttle.retry_after("a@x")
        assert wait is not None and 0 < wait <= WINDOW + 1
        clock.now += WINDOW - 1
        assert throttle.retry_after("a@x") is not None
        clock.now += 1
        assert throttle.retry_after("a@x") is None, "the window is fixed; it does not grow"

    def test_success_clears_and_accounts_are_independent(self) -> None:
        throttle = LoginThrottle(Clock())
        for _ in range(LIMIT):
            throttle.failed("a@x")
        assert throttle.retry_after("b@x") is None
        throttle.succeeded("a@x")
        assert throttle.retry_after("a@x") is None

    def test_disabled_with_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(get_settings(), "login_max_failures", 0)
        throttle = LoginThrottle(Clock())
        for _ in range(50):
            throttle.failed("a@x")
        assert throttle.retry_after("a@x") is None

    def test_memory_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.throttle as module

        monkeypatch.setattr(module, "_MAX_TRACKED", 5)
        throttle = LoginThrottle(Clock())
        for n in range(20):
            throttle.failed(f"spray{n}@x")
        assert len(throttle._failures) <= 5


class TestThrottleApi:
    def _fail(self, client: TestClient, email: str) -> int:
        return client.post(LOGIN, json={"email": email, "password": "wrong-password"}).status_code

    def test_guessing_stops_even_with_the_right_password(
        self, client: TestClient, faculty: User
    ) -> None:
        assert all(self._fail(client, faculty.email) == 401 for _ in range(LIMIT))
        blocked = client.post(LOGIN, json={"email": faculty.email, "password": DEFAULT_PASSWORD})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "too_many_attempts"
        assert int(blocked.headers["retry-after"]) > 0
        assert "refresh_token" not in blocked.text

    def test_case_and_spacing_do_not_evade_it(self, client: TestClient, faculty: User) -> None:
        variants = [faculty.email.upper(), f"  {faculty.email} ", faculty.email.title()]
        for n in range(LIMIT):
            self._fail(client, variants[n % len(variants)])
        assert self._fail(client, faculty.email) == 429

    def test_unknown_emails_are_throttled_identically(self, client: TestClient) -> None:
        email = "nobody@srmist.edu.in"
        assert all(self._fail(client, email) == 401 for _ in range(LIMIT))
        assert self._fail(client, email) == 429

    def test_other_accounts_still_sign_in(
        self, client: TestClient, faculty: User, admin: User
    ) -> None:
        for _ in range(LIMIT):
            self._fail(client, faculty.email)
        ok = client.post(LOGIN, json={"email": admin.email, "password": DEFAULT_PASSWORD})
        assert ok.status_code == 200

    def test_a_successful_sign_in_resets_the_count(self, client: TestClient, faculty: User) -> None:
        for _ in range(LIMIT - 1):
            self._fail(client, faculty.email)
        ok = client.post(LOGIN, json={"email": faculty.email, "password": DEFAULT_PASSWORD})
        assert ok.status_code == 200
        assert all(self._fail(client, faculty.email) == 401 for _ in range(LIMIT - 1))
