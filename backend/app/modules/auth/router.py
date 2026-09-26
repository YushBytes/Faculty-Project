from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

_401 = {401: {"model": ErrorResponse, "description": "Not authenticated"}}


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login", response_model=TokenPair, responses=_401, summary="Log in")
def login(body: LoginRequest, service: AuthServiceDep) -> TokenPair:
    return service.login(body.email, body.password)


@router.post(
    "/refresh",
    response_model=TokenPair,
    responses=_401,
    summary="Rotate refresh token",
    description=(
        "Exchanges a refresh token for a new access + refresh token pair. The presented "
        "token is revoked. Presenting an already-rotated token revokes the whole session."
    ),
)
def refresh(body: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    return service.refresh(body.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out (revoke session)",
    description="Revokes the session the refresh token belongs to. Always returns 204.",
)
def logout(body: RefreshRequest, service: AuthServiceDep) -> None:
    service.logout(body.refresh_token)


@router.get("/me", response_model=UserRead, responses=_401, summary="Current user")
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
