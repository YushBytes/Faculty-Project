"""Test infrastructure.

Tests run against a real PostgreSQL database (never SQLite), created fresh per test
session and migrated with Alembic, so the schema under test is the migrated schema.
Each test runs inside a transaction that is rolled back afterwards.
"""

import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

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
from app.modules.organization.models import (  # noqa: E402
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
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
        department: Department | None = None,
    ) -> User:
        self._n += 1
        user = User(
            email=email or f"{role.value.lower()}{self._n}@srmist.edu.in",
            full_name=full_name or f"{role.value.title()} User {self._n}",
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            department_id=department.id if department else None,
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
def hod(make_user: UserFactory, cse: Department) -> User:
    return make_user(
        Role.HOD, email="hod.cse@srmist.edu.in", full_name="Harish HOD", department=cse
    )


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


# ---------------------------------------------------------------- academic structure


@pytest.fixture
def cse(db_session: Session) -> Department:
    department = Department(code="CSE", name="Computer Science and Engineering")
    db_session.add(department)
    db_session.flush()
    return department


@pytest.fixture
def ece(db_session: Session) -> Department:
    department = Department(code="ECE", name="Electronics and Communication Engineering")
    db_session.add(department)
    db_session.flush()
    return department


@pytest.fixture
def term(db_session: Session) -> AcademicTerm:
    academic_term = AcademicTerm(
        code="2026-ODD",
        name="Odd Semester 2026-27",
        academic_year="2026-27",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 11, 30),
        is_current=True,
    )
    db_session.add(academic_term)
    db_session.flush()
    return academic_term


class OrgFactory:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._n = 0

    def course(self, department: Department, code: str | None = None) -> Course:
        self._n += 1
        course = Course(
            department_id=department.id,
            code=code or f"21{department.code}{200 + self._n}J",
            name=f"Course {self._n}",
            credits=Decimal("4"),
        )
        self._session.add(course)
        self._session.flush()
        return course

    def section(self, department: Department, name: str | None = None) -> Section:
        self._n += 1
        section = Section(department_id=department.id, name=name or f"A{self._n}", batch_year=2025)
        self._session.add(section)
        self._session.flush()
        return section

    def offering(
        self,
        course: Course,
        section: Section,
        term: AcademicTerm,
        faculty: list[User] | tuple[User, ...] = (),
    ) -> CourseOffering:
        offering = CourseOffering(course_id=course.id, section_id=section.id, term_id=term.id)
        self._session.add(offering)
        self._session.flush()
        for user in faculty:
            self._session.add(OfferingFaculty(offering_id=offering.id, user_id=user.id))
        self._session.flush()
        self._session.refresh(offering)
        return offering


@pytest.fixture
def org(db_session: Session) -> OrgFactory:
    return OrgFactory(db_session)


@pytest.fixture
def cse_offering(
    org: OrgFactory, cse: Department, term: AcademicTerm, faculty: User
) -> CourseOffering:
    """A CSE offering taught by ``faculty``."""
    return org.offering(org.course(cse), org.section(cse), term, faculty=[faculty])
