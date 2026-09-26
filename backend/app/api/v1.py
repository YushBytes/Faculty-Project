"""Mounts every /api/v1 router. Shared file: agents register routers in their own list
(routes_platform.py / routes_intelligence.py), not here."""

from fastapi import APIRouter

from app.api.routes_intelligence import INTELLIGENCE_ROUTERS
from app.api.routes_platform import PLATFORM_ROUTERS

api_v1_router = APIRouter()
for _router in (*PLATFORM_ROUTERS, *INTELLIGENCE_ROUTERS):
    api_v1_router.include_router(_router)
