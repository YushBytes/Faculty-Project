"""Test infrastructure.

Tests run against a real PostgreSQL database (never SQLite), created fresh per test
session and migrated with Alembic, so the schema under test is the migrated schema.
Each test runs inside a transaction that is rolled back afterwards.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://acadlytics:acadlytics@localhost:5432/acadlytics_test",
)
# Must be set before the app reads settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import get_db, get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.users.models import Role, User  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config(database_url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


def recreate_database(database_url: str) -> None:
    url = make_url(database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def drop_database(database_url: str) -> None:
    url = make_url(database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    recreate_database(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    eng = get_engine()
    yield eng
    eng.dispose()
    drop_database(TEST_DATABASE_URL)


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        trans = conn.begin()
        yield conn
        trans.rollback()


@pytest.fixture
def db_session(connection: Connection) -> Iterator[Session]:
    # Service-level commit() releases a SAVEPOINT; the outer transaction is rolled back.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------- users & auth helpers

DEFAULT_PASSWORD = "correct-horse-battery"


class UserFactory:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._n = 0

    def __call__(
        self,
        role: Role = Role.FACULTY,
        *,
        email: str | None = None,
        password: str = DEFAULT_PASSWORD,
        is_active: bool = True,
        full_name: str | None = None,
    ) -> User:
        self._n += 1
        user = User(
            email=email or f"{role.value.lower()}{self._n}@srmist.edu.in",
            full_name=full_name or f"{role.value.title()} User {self._n}",
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        self._session.add(user)
        self._session.flush()
        return user


@pytest.fixture
def make_user(db_session: Session) -> UserFactory:
    return UserFactory(db_session)


@pytest.fixture
def admin(make_user: UserFactory) -> User:
    return make_user(Role.ADMIN, email="admin@srmist.edu.in", full_name="Asha Admin")


@pytest.fixture
def hod(make_user: UserFactory) -> User:
    return make_user(Role.HOD, email="hod.cse@srmist.edu.in", full_name="Harish HOD")


@pytest.fixture
def faculty(make_user: UserFactory) -> User:
    return make_user(Role.FACULTY, email="faculty.one@srmist.edu.in", full_name="Farah Faculty")


def auth_headers(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()
