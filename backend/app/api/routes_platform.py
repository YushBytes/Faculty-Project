"""Routers owned by Agent 1 (platform: auth, users, organisation, students, assessments, imports).

Agent 1 edits this file only. Agent 2 registers its routers in routes_intelligence.py.
"""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router

PLATFORM_ROUTERS: list[APIRouter] = [
    auth_router,
    users_router,
]
