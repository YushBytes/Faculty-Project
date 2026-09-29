"""Every ORM model, imported in one place so Alembic sees the complete schema.
Add each new model here."""

from app.db.base import Base
from app.modules.assessments.models import Assessment, AssessmentResult
from app.modules.attention.models import AttentionFlag
from app.modules.audit.models import AuditLog
from app.modules.auth.models import RefreshToken
from app.modules.imports.models import ImportBatch
from app.modules.interventions.models import (
    Intervention,
    InterventionReason,
    InterventionStudent,
)
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseCoordinator,
    CourseOffering,
    Department,
    DepartmentSetting,
    OfferingFaculty,
    Section,
)
from app.modules.overview.models import GeneratedReport, OfferingSummary
from app.modules.students.models import Enrollment, Student, StudentSectionHistory
from app.modules.users.models import User

__all__ = [
    "AcademicTerm",
    "Assessment",
    "AssessmentResult",
    "AttentionFlag",
    "AuditLog",
    "Base",
    "Course",
    "CourseCoordinator",
    "CourseOffering",
    "GeneratedReport",
    "OfferingSummary",
    "Department",
    "DepartmentSetting",
    "OfferingFaculty",
    "RefreshToken",
    "Enrollment",
    "ImportBatch",
    "Intervention",
    "InterventionReason",
    "InterventionStudent",
    "Section",
    "Student",
    "StudentSectionHistory",
    "User",
]
