"""Database-level guarantees, independent of the service layer."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role, User


def _user(**overrides) -> User:
    values = {
        "email": "x@srmist.edu.in",
        "full_name": "X",
        "password_hash": "h",
        "role": Role.FACULTY,
    }
    return User(**{**values, **overrides})


def test_email_unique(db_session: Session) -> None:
    db_session.add_all([_user(), _user(full_name="Y")])
    with pytest.raises(IntegrityError, match="uq_users_email"):
        db_session.flush()


def test_email_must_be_normalised(db_session: Session) -> None:
    db_session.add(_user(email="Mixed@SRMIST.edu.in"))
    with pytest.raises(IntegrityError, match="ck_users_email_normalised"):
        db_session.flush()


def test_blank_name_rejected(db_session: Session) -> None:
    db_session.add(_user(full_name=""))
    with pytest.raises(IntegrityError, match="ck_users_full_name_not_blank"):
        db_session.flush()


def test_role_enum_enforced(db_session: Session) -> None:
    with pytest.raises(DataError):
        db_session.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash, role) "
                "VALUES ('r@srmist.edu.in', 'R', 'h', 'SUPERUSER')"
            )
        )


def test_defaults_applied(db_session: Session) -> None:
    user = _user()
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    assert isinstance(user.id, uuid.UUID)
    assert user.is_active is True
    assert user.created_at is not None and user.updated_at is not None


def test_refresh_token_hash_unique_and_cascade_on_user_delete(db_session: Session) -> None:
    user = _user()
    db_session.add(user)
    db_session.flush()
    expires = datetime.now(UTC) + timedelta(days=1)
    family = uuid.uuid4()
    db_session.add(
        RefreshToken(user_id=user.id, token_hash="a" * 64, family_id=family, expires_at=expires)
    )
    db_session.flush()

    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    remaining = db_session.execute(text("SELECT count(*) FROM refresh_tokens")).scalar_one()
    assert remaining == 0


def test_refresh_token_hash_unique(db_session: Session) -> None:
    user = _user()
    db_session.add(user)
    db_session.flush()
    expires = datetime.now(UTC) + timedelta(days=1)
    for _ in range(2):
        db_session.add(
            RefreshToken(
                user_id=user.id, token_hash="b" * 64, family_id=uuid.uuid4(), expires_at=expires
            )
        )
    with pytest.raises(IntegrityError, match="uq_refresh_tokens_token_hash"):
        db_session.flush()
