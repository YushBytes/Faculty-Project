"""Exactly one active Administrator: the service's checks and the database index behind them.

API-level tests run inside the usual rolled-back transaction. The concurrency tests need real,
committed transactions on separate connections (that is the only way two writers can race), so
they use the session-scoped test engine directly and delete what they created afterwards. The
test database is the isolated ``acadlytics_test``; no application data is involved.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserUpdate
from app.modules.users.service import ADMIN_CONFLICT, UserService
from tests.conftest import UserFactory, auth_headers

API = "/api/v1"


# ---------------------------------------------------------------- through the API


class TestServiceRules:
    def test_creating_a_second_administrator_is_refused(
        self, client: TestClient, admin: User
    ) -> None:
        body = {
            "email": "second.admin@srmist.edu.in",
            "full_name": "Second",
            "password": "a-strong-passphrase",
            "role": "ADMIN",
        }
        response = client.post(f"{API}/users", json=body, headers=auth_headers(admin))
        assert response.status_code == 409
        assert "only one" in response.json()["error"]["message"]
        assert "transfer" not in response.json()["error"]["message"], "no transfer exists"

    def test_promoting_someone_is_refused_while_an_administrator_exists(
        self, client: TestClient, admin: User, faculty: User
    ) -> None:
        response = client.patch(
            f"{API}/users/{faculty.id}", json={"role": "ADMIN"}, headers=auth_headers(admin)
        )
        assert response.status_code == 409

    def test_reactivating_a_former_administrator_is_refused(
        self, client: TestClient, admin: User, make_user: UserFactory
    ) -> None:
        former = make_user(Role.ADMIN, is_active=False)  # allowed: the index covers active only
        response = client.post(f"{API}/users/{former.id}/activate", headers=auth_headers(admin))
        assert response.status_code == 409

    def test_the_administrator_cannot_deactivate_or_demote_themselves(
        self, client: TestClient, admin: User
    ) -> None:
        headers = auth_headers(admin)
        assert client.post(f"{API}/users/{admin.id}/deactivate", headers=headers).status_code == 422
        demote = client.patch(f"{API}/users/{admin.id}", json={"role": "HOD"}, headers=headers)
        assert demote.status_code == 422
        me = client.get(f"{API}/auth/me", headers=headers).json()
        assert me["role"] == "ADMIN" and me["is_active"] is True

    def test_nobody_else_can_create_an_administrator(
        self, client: TestClient, admin: User, hod: User
    ) -> None:
        body = {
            "email": "hod.made.admin@srmist.edu.in",
            "full_name": "X",
            "password": "a-strong-passphrase",
            "role": "ADMIN",
        }
        assert client.post(f"{API}/users", json=body, headers=auth_headers(hod)).status_code == 403

    def test_the_administrator_still_manages_everyone(
        self, client: TestClient, admin: User, cse
    ) -> None:
        body = {
            "email": "new.faculty@srmist.edu.in",
            "full_name": "New Faculty",
            "password": "a-strong-passphrase",
            "role": "FACULTY",
            "department_id": str(cse.id),
        }
        created = client.post(f"{API}/users", json=body, headers=auth_headers(admin))
        assert created.status_code == 201 and created.json()["role"] == "FACULTY"


class TestDatabaseIndex:
    def test_the_index_rejects_a_second_active_administrator_directly(
        self, db_session: Session, admin: User
    ) -> None:
        intruder = User(
            email="raw.insert@srmist.edu.in",
            full_name="Raw insert",
            password_hash=hash_password("not-used-anywhere"),
            role=Role.ADMIN,
            is_active=True,
        )
        with (
            pytest.raises(IntegrityError, match="uq_users_single_active_admin"),
            db_session.begin_nested(),
        ):
            db_session.add(intruder)
            db_session.flush()

    def test_inactive_administrators_do_not_count(
        self, db_session: Session, admin: User, make_user: UserFactory
    ) -> None:
        make_user(Role.ADMIN, is_active=False)
        make_user(Role.ADMIN, is_active=False)
        active = db_session.scalar(
            select(func.count()).where(User.role == Role.ADMIN, User.is_active.is_(True))
        )
        assert active == 1

    def test_the_index_exists_with_the_right_predicate(self, db_session: Session) -> None:
        definition = db_session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_users_single_active_admin'")
        )
        assert definition is not None
        assert "UNIQUE" in definition and "is_active" in definition and "ADMIN" in definition


# ---------------------------------------------------------------- real concurrency


@pytest.fixture
def committed(engine: Engine) -> Iterator[list[uuid.UUID]]:
    """Ids of users committed by a test; removed (with their audit rows) afterwards."""
    ids: list[uuid.UUID] = []
    with Session(engine) as check:
        assert not check.scalar(select(func.count()).where(User.role == Role.ADMIN)), (
            "the isolated test database must start without committed administrators"
        )
    yield ids
    with Session(engine) as cleanup:
        cleanup.execute(delete(AuditLog).where(AuditLog.actor_id.in_(ids)))
        cleanup.execute(delete(AuditLog).where(AuditLog.entity_id.in_([str(i) for i in ids])))
        cleanup.execute(delete(User).where(User.id.in_(ids)))
        cleanup.commit()


def _race(monkeypatch: pytest.MonkeyPatch, work) -> list[object]:
    """Run ``work(i)`` in two threads that both pass the service's count check before either
    writes — the window the database index exists for."""
    barrier = threading.Barrier(2, timeout=20)
    original = UserRepository.count_active_admins

    def counted_then_wait(self: UserRepository) -> int:
        value = original(self)
        barrier.wait()  # both threads have now seen "no administrator"
        return value

    monkeypatch.setattr(UserRepository, "count_active_admins", counted_then_wait)
    outcomes: list[object] = [None, None]

    def run(i: int) -> None:
        try:
            outcomes[i] = work(i)
        except Exception as exc:  # noqa: BLE001 - recorded and asserted by the test
            outcomes[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return outcomes


def _active_admins(engine: Engine) -> int:
    with Session(engine) as s:
        return s.scalar(
            select(func.count()).where(User.role == Role.ADMIN, User.is_active.is_(True))
        )


def test_two_concurrent_creations_produce_exactly_one_administrator(
    engine: Engine, committed: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    def create(i: int) -> User:
        with Session(engine, expire_on_commit=False) as session:
            user = UserService(session).create_user(
                UserCreate(
                    email=f"race.admin{i}.{uuid.uuid4().hex[:6]}@srmist.edu.in",
                    full_name=f"Race Admin {i}",
                    password="a-strong-passphrase",
                    role=Role.ADMIN,
                )
            )
            committed.append(user.id)
            return user

    outcomes = _race(monkeypatch, create)
    winners = [o for o in outcomes if isinstance(o, User)]
    losers = [o for o in outcomes if isinstance(o, ConflictError)]
    assert len(winners) == 1 and len(losers) == 1, outcomes
    assert ADMIN_CONFLICT in losers[0].message
    assert _active_admins(engine) == 1


def test_two_concurrent_promotions_produce_exactly_one_administrator(
    engine: Engine, committed: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine, expire_on_commit=False) as setup:
        # The acting account: an Administrator record that is not active, so the institution
        # has no active Administrator and both promotions pass the service's count check.
        actor = User(
            email=f"race.actor.{uuid.uuid4().hex[:6]}@srmist.edu.in",
            full_name="Race actor",
            password_hash=hash_password("not-used-anywhere"),
            role=Role.ADMIN,
            is_active=False,
        )
        candidates = [
            User(
                email=f"race.faculty{i}.{uuid.uuid4().hex[:6]}@srmist.edu.in",
                full_name=f"Race Faculty {i}",
                password_hash=hash_password("not-used-anywhere"),
                role=Role.FACULTY,
                is_active=True,
            )
            for i in range(2)
        ]
        setup.add_all([actor, *candidates])
        setup.commit()
        committed.extend([actor.id, *(c.id for c in candidates)])

    def promote(i: int) -> User:
        with Session(engine, expire_on_commit=False) as session:
            acting = session.get(User, actor.id)
            return UserService(session).update_user(
                candidates[i].id, UserUpdate(role=Role.ADMIN), actor=acting
            )

    outcomes = _race(monkeypatch, promote)
    assert sum(isinstance(o, User) for o in outcomes) == 1, outcomes
    assert sum(isinstance(o, ConflictError) for o in outcomes) == 1, outcomes
    assert _active_admins(engine) == 1


def test_concurrent_bootstrap_is_not_a_startup_failure(
    engine: Engine, committed: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two API processes starting on an empty database: one creates the Administrator, the
    other sees the index refuse its copy and carries on."""
    from app import bootstrap as bootstrap_module

    monkeypatch.setenv("ACADLYTICS_ADMIN_PASSWORD", "a-strong-passphrase")

    def start(i: int) -> list:
        monkeypatch.setenv("ACADLYTICS_ADMIN_EMAIL", "first.admin@srmist.edu.in")
        with Session(engine, expire_on_commit=False) as session:
            created = bootstrap_module.bootstrap(session)
            for email, _ in created:
                committed.append(session.scalar(select(User.id).where(User.email == email)))
            return created

    outcomes = _race(monkeypatch, start)
    assert all(isinstance(o, list) for o in outcomes), outcomes
    assert sorted(len(o) for o in outcomes) == [0, 1]
    assert _active_admins(engine) == 1
