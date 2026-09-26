"""User administration. ADMIN manages users; HOD may look users up (read-only) to assign
faculty to offerings."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.auth.dependencies import AdminUser, require_roles
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserCreate, UserRead, UserUpdate
from app.modules.users.service import UserService

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Not permitted"},
    },
)


def get_user_service(db: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(db)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AdminOrHod = Annotated[User, Depends(require_roles(Role.ADMIN, Role.HOD))]
_404 = {404: {"model": ErrorResponse}}


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_user(body: UserCreate, _: AdminUser, service: UserServiceDep) -> UserRead:
    return UserRead.model_validate(service.create_user(body))


@router.get("", response_model=Page[UserRead])
def list_users(
    _: AdminOrHod,
    service: UserServiceDep,
    page: Annotated[PageParams, Depends(page_params)],
    role: Annotated[Role | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[UserRead]:
    return service.list_users(page, role=role, is_active=is_active, department_id=department_id)


@router.get("/{user_id}", response_model=UserRead, responses=_404)
def get_user(user_id: uuid.UUID, _: AdminOrHod, service: UserServiceDep) -> UserRead:
    return UserRead.model_validate(service.get_user(user_id))


@router.patch("/{user_id}", response_model=UserRead, responses=_404)
def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: AdminUser, service: UserServiceDep
) -> UserRead:
    return UserRead.model_validate(service.update_user(user_id, body, actor=actor))


@router.post("/{user_id}/deactivate", response_model=UserRead, responses=_404)
def deactivate_user(user_id: uuid.UUID, actor: AdminUser, service: UserServiceDep) -> UserRead:
    return UserRead.model_validate(service.deactivate_user(user_id, actor=actor))


@router.post("/{user_id}/activate", response_model=UserRead, responses=_404)
def activate_user(user_id: uuid.UUID, _: AdminUser, service: UserServiceDep) -> UserRead:
    return UserRead.model_validate(service.activate_user(user_id))
