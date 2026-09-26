"""Server-side data-access scope. Every module that exposes offering-level data (students,
assessments, results, imports, analytics) must go through ``OfferingAccess``.

Who can see an offering (VIEW) — and therefore its students, assessments and results:
    ADMIN    every offering
    HOD      offerings of courses in their department, plus offerings they teach
    FACULTY  only offerings they are assigned to

Who can administer an offering (ADMINISTER) — pass mark, faculty assignment, deletion:
    ADMIN    every offering
    HOD      offerings of courses in their department

An offering outside VIEW scope is reported as 404 (its existence is not disclosed);
one that is visible but not administrable is 403.
"""

import uuid
from enum import StrEnum

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.organization.models import Course, CourseOffering, OfferingFaculty
from app.modules.organization.repository import OfferingRepository
from app.modules.users.models import Role, User


class Access(StrEnum):
    VIEW = "view"
    ADMINISTER = "administer"


def _taught_by(user_id: uuid.UUID) -> ColumnElement[bool]:
    return CourseOffering.id.in_(
        select(OfferingFaculty.offering_id).where(OfferingFaculty.user_id == user_id)
    )


def _in_department(department_id: uuid.UUID | None) -> ColumnElement[bool]:
    return CourseOffering.course_id.in_(
        select(Course.id).where(Course.department_id == department_id)
    )


def visible_offerings(user: User) -> ColumnElement[bool]:
    """SQL condition on CourseOffering restricting rows to what ``user`` may view."""
    if user.role is Role.ADMIN:
        return true()
    if user.role is Role.HOD:
        return _in_department(user.department_id) | _taught_by(user.id)
    return _taught_by(user.id)


def visible_offering_ids(user: User):
    """Subquery of offering ids ``user`` may view (for filtering other tables)."""
    return select(CourseOffering.id).where(visible_offerings(user))


def can_manage_department(user: User, department_id: uuid.UUID) -> bool:
    return user.role is Role.ADMIN or (
        user.role is Role.HOD and user.department_id == department_id
    )


def can_administer(user: User, offering: CourseOffering) -> bool:
    return can_manage_department(user, offering.course.department_id)


class OfferingAccess:
    def __init__(self, session: Session) -> None:
        self._offerings = OfferingRepository(session)

    def get(
        self, user: User, offering_id: uuid.UUID, access: Access = Access.VIEW
    ) -> CourseOffering:
        offering = self._offerings.get_visible(offering_id, visible_offerings(user))
        if offering is None:
            raise NotFoundError("Course offering not found.")
        if access is Access.ADMINISTER and not can_administer(user, offering):
            raise PermissionDeniedError("You cannot administer this course offering.")
        return offering
