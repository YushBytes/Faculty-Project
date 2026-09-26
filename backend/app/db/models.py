"""Every ORM model, imported in one place so Alembic sees the complete schema.
Add each new model here."""

from app.db.base import Base
from app.modules.auth.models import RefreshToken
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.users.models import User

__all__ = [
    "AcademicTerm",
    "Base",
    "Course",
    "CourseOffering",
    "Department",
    "OfferingFaculty",
    "RefreshToken",
    "Section",
    "User",
]
