"""Every /api/v1 router, registered in one place. Add yours to the list."""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.organization.router import ROUTERS as ORGANIZATION_ROUTERS
from app.modules.users.router import router as users_router

ROUTERS: list[APIRouter] = [
    auth_router,
    users_router,
    *ORGANIZATION_ROUTERS,
]

api_v1_router = APIRouter()
for _router in ROUTERS:
    api_v1_router.include_router(_router)
