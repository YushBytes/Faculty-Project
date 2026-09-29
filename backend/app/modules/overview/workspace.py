"""Who the signed-in user is, institutionally: role, department, courses coordinated, classes
taught, the terms available and what the UI may offer them. The UI builds its workspace from
this; every capability listed here is also enforced by the endpoint it describes."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.interventions.models import Intervention  # noqa: F401  (mapper registry)
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseCoordinator,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.users.models import Role, User

INSTITUTION = "SRM Institute of Science and Technology"
ROLE_LABELS = {
    Role.ADMIN: "Administrator",
    Role.HOD: "Head of Department",
    Role.ACADEMIC_HEAD: "Academic Head",
    Role.COURSE_COORDINATOR: "Course Coordinator",
    Role.FACULTY: "Faculty",
}


def workspace(session: Session, user: User) -> dict[str, Any]:
    department = session.get(Department, user.department_id) if user.department_id else None
    coordinated = list(
        session.scalars(
            select(Course)
            .join(CourseCoordinator, CourseCoordinator.course_id == Course.id)
            .where(CourseCoordinator.user_id == user.id)
            .order_by(Course.code)
        )
    )
    terms = list(session.scalars(select(AcademicTerm).order_by(AcademicTerm.start_date)))
    current = next((t for t in terms if t.is_current), terms[-1] if terms else None)
    teaching = session.execute(
        select(CourseOffering, Course, Section, AcademicTerm)
        .join(OfferingFaculty, OfferingFaculty.offering_id == CourseOffering.id)
        .join(Course, Course.id == CourseOffering.course_id)
        .join(Section, Section.id == CourseOffering.section_id)
        .join(AcademicTerm, AcademicTerm.id == CourseOffering.term_id)
        .where(OfferingFaculty.user_id == user.id)
        .order_by(AcademicTerm.start_date.desc(), Course.code, Section.name)
    ).all()
    role = user.role
    headline = ROLE_LABELS[role]
    if role is Role.COURSE_COORDINATOR and coordinated:
        headline += " — " + ", ".join(c.name for c in coordinated)
    elif role in (Role.HOD, Role.ACADEMIC_HEAD) and department:
        headline += f" — {department.name}"
    manages_department = role in (Role.ADMIN, Role.HOD)
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": role.value,
            "role_label": ROLE_LABELS[role],
            "designation": user.designation,
            "employee_code": user.employee_code,
        },
        "headline": headline,
        "institution": INSTITUTION,
        "department": (
            {"id": str(department.id), "code": department.code, "name": department.name}
            if department
            else None
        ),
        "coordinated_courses": [
            {
                "id": str(c.id),
                "code": c.code,
                "name": c.name,
                "course_type": c.course_type.value if c.course_type else None,
            }
            for c in coordinated
        ],
        "teaching": [
            {
                "offering_id": str(o.id),
                "course_id": str(c.id),
                "course_code": c.code,
                "course_name": c.name,
                "section_id": str(s.id),
                "section_name": s.name,
                "term_id": str(t.id),
                "term_code": t.code,
                "academic_year": t.academic_year,
                "semester": t.semester.value if t.semester else None,
            }
            for o, c, s, t in teaching
        ],
        "terms": [
            {
                "id": str(t.id),
                "code": t.code,
                "name": t.name,
                "academic_year": t.academic_year,
                "semester": t.semester.value if t.semester else None,
                "is_current": t.is_current,
            }
            for t in terms
        ],
        "academic_years": sorted({t.academic_year for t in terms}, reverse=True),
        "current_term": (
            {
                "id": str(current.id),
                "academic_year": current.academic_year,
                "semester": current.semester.value if current.semester else None,
                "name": current.name,
            }
            if current
            else None
        ),
        "capabilities": {
            "manage_users": role in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD),
            "manage_departments": role is Role.ADMIN,
            "manage_terms": role is Role.ADMIN,
            "manage_sections": manages_department,
            "manage_courses": role in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD),
            "manage_coordinators": role in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD),
            "assign_faculty": role
            in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD, Role.COURSE_COORDINATOR),
            "import_marks": True,
            "view_audit": role in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD),
            "compare_faculty": role is not Role.FACULTY,
        },
    }


def student_overview(session: Session, user: User, student_id: uuid.UUID) -> dict[str, Any]:
    """One student across every class of theirs the user may see, from the engine."""
    from app.modules.analytics.service import AnalyticsService
    from app.modules.organization.scope import visible_offerings
    from app.modules.students.models import Enrollment
    from app.modules.students.service import StudentService

    student = StudentService(session).get(student_id, actor=user)
    rows = session.execute(
        select(CourseOffering, Course, Section, AcademicTerm, Enrollment)
        .join(Enrollment, Enrollment.offering_id == CourseOffering.id)
        .join(Course, Course.id == CourseOffering.course_id)
        .join(Section, Section.id == CourseOffering.section_id)
        .join(AcademicTerm, AcademicTerm.id == CourseOffering.term_id)
        .where(Enrollment.student_id == student.id, visible_offerings(user))
        .order_by(AcademicTerm.start_date.desc(), Course.code)
    ).all()
    analytics = AnalyticsService(session)
    classes = []
    for offering, course, section, term, enrollment in rows:
        entry: dict[str, Any] = {
            "offering_id": str(offering.id),
            "course_code": course.code,
            "course_name": course.name,
            "section_name": section.name,
            "term_name": term.name,
            "semester": term.semester.value if term.semester else None,
            "academic_year": term.academic_year,
            "enrollment": enrollment.status.value,
            "pass_mark": float(offering.pass_percent),
        }
        try:
            result = analytics.student_analytics(offering.id, student.id, actor=user)
            entry["analytics"] = result.model_dump(mode="json")
        except Exception:  # dropped students are not in the analytic cohort
            entry["analytics"] = None
        classes.append(entry)
    section = (
        session.get(Section, student.current_section_id) if student.current_section_id else None
    )
    return {
        "student": {
            "id": str(student.id),
            "register_number": student.register_number,
            "full_name": student.full_name,
            "email": student.email,
            "batch_year": student.batch_year,
            "is_active": student.is_active,
            "section": section.name if section else None,
        },
        "classes": classes,
    }
