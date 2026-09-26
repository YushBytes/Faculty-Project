"""Authentication and role-authorisation dependencies used by every protected router.

Authorisation always uses the role stored in the database (not the JWT claim), so a
role change or deactivation takes effect on the user's next request.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.db.session import get_db
from app.modules.auth.service import AuthService
from app.modules.users.models import Role, User

_bearer = HTTPBearer(auto_error=False, description="Access token from /api/v1/auth/login")


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication required.")
    return AuthService(db).authenticate(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    allowed = frozenset(roles)

    def _check(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError("You do not have permission to perform this action.")
        return user

    return _check


AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
