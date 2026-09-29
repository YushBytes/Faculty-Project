"""Server-side data-access scope. Every module that exposes offering-level data (students,
assessments, results, imports, analytics, reports) goes through this module.

Who can see an offering (VIEW) — and therefore its students, assessments and results:
    ADMIN               every offering
    HOD                 offerings of courses in their department, plus offerings they teach
    ACADEMIC_HEAD       offerings of courses in their department, plus offerings they teach
    COURSE_COORDINATOR  offerings of the courses they coordinate, plus offerings they teach
    FACULTY             only offerings they are assigned to

Who can administer an offering (ADMINISTER) — pass mark, faculty assignment, assessments of
others, confirming anyone's import, deletion:
    ADMIN               every offering
    HOD, ACADEMIC_HEAD  offerings of courses in their department
    COURSE_COORDINATOR  offerings of the courses they coordinate

An offering outside VIEW scope is reported as 404 (its existence is not disclosed);
one that is visible but not administrable is 403.
"""

import uuid
from enum import StrEnum

from sqlalchemy import ColumnElement, false, select, true
from sqlalchemy.orm import Session, object_session

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.organization.models import (
    Course,
    CourseCoordinator,
    CourseOffering,
    OfferingFaculty,
)
from app.modules.organization.repository import OfferingRepository
from app.modules.users.models import Role, User

DEPARTMENT_WIDE = frozenset((Role.HOD, Role.ACADEMIC_HEAD))


class Access(StrEnum):
    VIEW = "view"
    ADMINISTER = "administer"


def _taught_by(user_id: uuid.UUID) -> ColumnElement[bool]:
    return CourseOffering.id.in_(
        select(OfferingFaculty.offering_id).where(OfferingFaculty.user_id == user_id)
    )


def _in_department(department_id: uuid.UUID | None) -> ColumnElement[bool]:
    if department_id is None:
        return false()
    return CourseOffering.course_id.in_(
        select(Course.id).where(Course.department_id == department_id)
    )


def coordinated_course_ids(user_id: uuid.UUID):
    """Subquery of the course ids ``user_id`` coordinates."""
    return select(CourseCoordinator.course_id).where(CourseCoordinator.user_id == user_id)


def _coordinated_by(user_id: uuid.UUID) -> ColumnElement[bool]:
    return CourseOffering.course_id.in_(coordinated_course_ids(user_id))


def visible_offerings(user: User) -> ColumnElement[bool]:
    """SQL condition on CourseOffering restricting rows to what ``user`` may view."""
    if user.role is Role.ADMIN:
        return true()
    if user.role in DEPARTMENT_WIDE:
        return _in_department(user.department_id) | _taught_by(user.id)
    if user.role is Role.COURSE_COORDINATOR:
        return _coordinated_by(user.id) | _taught_by(user.id)
    return _taught_by(user.id)


def administrable_offerings(user: User) -> ColumnElement[bool]:
    """SQL condition on CourseOffering: offerings ``user`` may administer."""
    if user.role is Role.ADMIN:
        return true()
    if user.role in DEPARTMENT_WIDE:
        return _in_department(user.department_id)
    if user.role is Role.COURSE_COORDINATOR:
        return _coordinated_by(user.id)
    return false()


def visible_offering_ids(user: User):
    """Subquery of offering ids ``user`` may view (for filtering other tables)."""
    return select(CourseOffering.id).where(visible_offerings(user))


def can_manage_department(user: User, department_id: uuid.UUID) -> bool:
    """Department records: sections, students, settings, staff. ADMIN, or the department's
    HOD."""
    return user.role is Role.ADMIN or (
        user.role is Role.HOD and user.department_id == department_id
    )


def can_manage_courses(user: User, department_id: uuid.UUID) -> bool:
    """Course-level academic information and coordinator assignment: ADMIN, or the
    department's HOD or Academic Head."""
    return user.role is Role.ADMIN or (
        user.role in DEPARTMENT_WIDE and user.department_id == department_id
    )


def coordinates(session: Session, user: User, course_id: uuid.UUID) -> bool:
    if user.role is not Role.COURSE_COORDINATOR:
        return False
    return (
        session.scalar(
            select(CourseCoordinator.course_id).where(
                CourseCoordinator.course_id == course_id, CourseCoordinator.user_id == user.id
            )
        )
        is not None
    )


def can_administer(user: User, offering: CourseOffering) -> bool:
    if can_manage_courses(user, offering.course.department_id):
        return True
    if user.role is Role.COURSE_COORDINATOR:
        session = object_session(offering)
        return session is not None and coordinates(session, user, offering.course_id)
    return False


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
