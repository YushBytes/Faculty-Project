"""Every /api/v1 router, registered in one place. Add yours to the list."""

from fastapi import APIRouter

from app.modules.analytics.router import ROUTERS as ANALYTICS_ROUTERS
from app.modules.assessments.router import ROUTERS as ASSESSMENT_ROUTERS
from app.modules.audit.router import ROUTERS as AUDIT_ROUTERS
from app.modules.auth.router import router as auth_router
from app.modules.imports.router import ROUTERS as IMPORT_ROUTERS
from app.modules.interventions.router import ROUTERS as INTERVENTION_ROUTERS
from app.modules.organization.router import ROUTERS as ORGANIZATION_ROUTERS
from app.modules.overview.router import ROUTERS as OVERVIEW_ROUTERS
from app.modules.students.router import ROUTERS as STUDENT_ROUTERS
from app.modules.users.router import router as users_router

ROUTERS: list[APIRouter] = [
    auth_router,
    users_router,
    *ORGANIZATION_ROUTERS,
    *STUDENT_ROUTERS,
    *ASSESSMENT_ROUTERS,
    *IMPORT_ROUTERS,
    *AUDIT_ROUTERS,
    *ANALYTICS_ROUTERS,
    *INTERVENTION_ROUTERS,
    *OVERVIEW_ROUTERS,
]

api_v1_router = APIRouter()
for _router in ROUTERS:
    api_v1_router.include_router(_router)
