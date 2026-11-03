"""First start of an empty platform: the sign-in accounts, and nothing else.

Every semester, course, section, student, faculty member and mark comes from the TLP
reports people upload (see ``modules/imports/provision.py``). What cannot come from a report
is who runs the platform, so a database with no users gets:

    admin@acadlytics.dev          ADMIN          the whole institution
    hod.cse@acadlytics.dev        HOD            Computer Science and Engineering
    academic.head@acadlytics.dev  ACADEMIC_HEAD  Computer Science and Engineering

with the password in ACADLYTICS_INITIAL_PASSWORD (default ``Demo@2026pass`` outside
production; production refuses to start without one being set). Names, emails and passwords
can be changed afterwards in the app. Idempotent: does nothing once any user exists.
"""

from __future__ import annotations

import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.modules.organization.models import Department
from app.modules.users.models import Role, User

DEFAULT_PASSWORD = "Demo@2026pass"
ACCOUNTS = (
    ("admin@acadlytics.dev", "Administrator", Role.ADMIN, "Administrator"),
    ("hod.cse@acadlytics.dev", "Head of Department", Role.HOD, "Professor and Head"),
    ("academic.head@acadlytics.dev", "Academic Head", Role.ACADEMIC_HEAD, "Academic Head"),
)


class BootstrapError(RuntimeError):
    pass


def bootstrap(session: Session) -> list[tuple[str, str]]:
    """Create the sign-in accounts when there are no users. Returns (email, role) created."""
    if session.scalar(select(func.count()).select_from(User)):
        return []
    password = os.environ.get("ACADLYTICS_INITIAL_PASSWORD")
    if not password:
        if get_settings().app_env is Environment.PRODUCTION:
            raise BootstrapError(
                "Set ACADLYTICS_INITIAL_PASSWORD to create the first accounts in production."
            )
        password = DEFAULT_PASSWORD
    department = session.scalar(select(Department).where(Department.code == "CSE"))
    if department is None:
        department = Department(code="CSE", name="Computer Science and Engineering")
        session.add(department)
        session.flush()
    hashed = hash_password(password)
    created = []
    for email, name, role, designation in ACCOUNTS:
        session.add(
            User(
                email=email,
                full_name=name,
                password_hash=hashed,
                role=role,
                is_active=True,
                designation=designation,
                department_id=None if role is Role.ADMIN else department.id,
            )
        )
        created.append((email, role.value))
    session.commit()
    return created
