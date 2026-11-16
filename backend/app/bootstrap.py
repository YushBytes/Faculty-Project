"""First start of a platform: the Administrator account, and nothing else.

Every semester, course, section, student, faculty member and mark comes from the TLP
reports people upload (see ``modules/imports/provision.py``); departments, HODs and Academic
Heads are created by the Administrator in the app (*Structure*, *People*). What cannot come
from anywhere else is the first Administrator, so when no ADMIN account exists this creates:

    ACADLYTICS_ADMIN_EMAIL     (default admin@acadlytics.dev)
    ACADLYTICS_ADMIN_PASSWORD  (no default; at least 8 characters)

There is no built-in password. Without ACADLYTICS_ADMIN_PASSWORD nothing is created and the
caller is told how to create the account (``python -m app.cli create-admin``). Idempotent: does
nothing once an Administrator exists. No academic data is ever created here.
"""

from __future__ import annotations

import os

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.users.models import Role, User
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

DEFAULT_ADMIN_EMAIL = "admin@acadlytics.dev"


class BootstrapError(RuntimeError):
    pass


def admin_password_from_env() -> str | None:
    # ACADLYTICS_INITIAL_PASSWORD is the earlier name of the same setting.
    return os.environ.get("ACADLYTICS_ADMIN_PASSWORD") or os.environ.get(
        "ACADLYTICS_INITIAL_PASSWORD"
    )


def bootstrap(session: Session) -> list[tuple[str, str]]:
    """Create the Administrator when none exists and a password is configured.

    Returns the (email, role) pairs created: empty when an Administrator already exists or no
    password is configured (see :func:`needs_admin`).
    """
    if not needs_admin(session):
        return []
    password = admin_password_from_env()
    if not password:
        return []
    email = os.environ.get("ACADLYTICS_ADMIN_EMAIL") or DEFAULT_ADMIN_EMAIL
    name = os.environ.get("ACADLYTICS_ADMIN_NAME") or "Administrator"
    try:
        data = UserCreate(
            email=email,
            full_name=name,
            password=password,
            role=Role.ADMIN,
            designation="Administrator",
        )
    except ValidationError as exc:
        # Field names and reasons only: never echo the submitted values (the password) to logs.
        reasons = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors(include_input=False)
        )
        raise BootstrapError(f"Invalid administrator settings: {reasons}") from None
    user = UserService(session).create_user(data)
    return [(user.email, Role.ADMIN.value)]


def needs_admin(session: Session) -> bool:
    return not session.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN))
