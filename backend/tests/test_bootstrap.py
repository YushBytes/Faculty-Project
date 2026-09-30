"""An empty platform starts with its sign-in accounts and no academic data."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.modules.organization.models import Course, Section
from app.modules.students.models import Student
from app.modules.users.models import Role, User


def test_bootstrap_creates_only_the_sign_in_accounts(db_session: Session) -> None:
    created = bootstrap(db_session)
    assert [role for _, role in created] == ["ADMIN", "HOD", "ACADEMIC_HEAD"]
    roles = {u.role for u in db_session.scalars(select(User))}
    assert roles == {Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD}
    for model in (Course, Section, Student):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
    assert bootstrap(db_session) == []  # idempotent
