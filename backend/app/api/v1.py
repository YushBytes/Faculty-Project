"""Aggregates every versioned module router under /api/v1.

Module routers (auth, organization, students, assessments, imports) are added here
as their phases land.
"""

from fastapi import APIRouter

api_v1_router = APIRouter()
