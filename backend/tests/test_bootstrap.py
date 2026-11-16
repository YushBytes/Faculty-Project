"""A new platform starts with one Administrator, no built-in password and no academic data."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli
from app.bootstrap import BootstrapError, bootstrap, needs_admin
from app.modules.organization.models import Course, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import Role, User

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ACADLYTICS_ADMIN_EMAIL",
        "ACADLYTICS_ADMIN_PASSWORD",
        "ACADLYTICS_INITIAL_PASSWORD",
        "ACADLYTICS_ADMIN_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_without_a_password_nothing_is_created(db_session: Session) -> None:
    assert bootstrap(db_session) == []
    assert _count(db_session, User) == 0
    assert needs_admin(db_session)


def test_creates_only_the_administrator(
    db_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACADLYTICS_ADMIN_EMAIL", "Registrar@Example.edu")
    monkeypatch.setenv("ACADLYTICS_ADMIN_PASSWORD", "A-real-secret-2026")
    created = bootstrap(db_session)
    assert created == [("registrar@example.edu", "ADMIN")]
    assert [u.role for u in db_session.scalars(select(User))] == [Role.ADMIN]
    # No fabricated department, course, section or student.
    for model in (Department, Course, Section, Student):
        assert _count(db_session, model) == 0
    assert bootstrap(db_session) == []  # idempotent

    ok = client.post(
        f"{API}/auth/login",
        json={"email": "registrar@example.edu", "password": "A-real-secret-2026"},
    )
    assert ok.status_code == 200, ok.text
    for old_default in ("admin", "Admin@123", "password", "registrar"):
        denied = client.post(
            f"{API}/auth/login", json={"email": "registrar@example.edu", "password": old_default}
        )
        assert denied.status_code == 401


def test_legacy_variable_name_still_works(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACADLYTICS_INITIAL_PASSWORD", "A-real-secret-2026")
    assert bootstrap(db_session) == [("admin@acadlytics.dev", "ADMIN")]


def test_short_password_is_refused(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACADLYTICS_ADMIN_PASSWORD", "shrt-pw")
    with pytest.raises(BootstrapError) as info:
        bootstrap(db_session)
    assert "password" in str(info.value)
    assert "shrt-pw" not in str(info.value)  # the value itself never reaches the logs
    assert _count(db_session, User) == 0


def test_demo_seed_requires_an_explicit_password(capsys: pytest.CaptureFixture[str]) -> None:
    # The development seed has no built-in password either; without one it refuses to run.
    assert cli.main(["seed-demo", "--minimal"]) == 2
    assert "ACADLYTICS_DEMO_PASSWORD" in capsys.readouterr().err


def test_create_admin_never_echoes_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACADLYTICS_ADMIN_PASSWORD", "tiny-pw")
    assert cli.main(["create-admin", "--email", "a@example.edu", "--name", "A"]) == 2
    err = capsys.readouterr().err
    assert "password" in err and "tiny-pw" not in err
