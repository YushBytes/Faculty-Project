"""Atomic confirm, tested against real transactions (no rolled-back test session).

The import writes two assessments; the analytics hook fails on the second one. The whole
confirm must roll back: no results, no audit rows, batch still previewed. Then the same
batch confirms cleanly once the failure is gone.
"""

import io
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.recompute import reset_recompute, set_recompute
from app.core.security import hash_password
from app.db.session import get_session_factory
from app.main import create_app
from app.modules.assessments.models import Assessment, AssessmentResult, AssessmentType
from app.modules.audit.models import AuditLog
from app.modules.imports.models import ImportBatch, ImportStatus
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.students.models import Enrollment, Student
from app.modules.users.models import Role, User
from tests.conftest import auth_headers


@pytest.fixture
def committed(engine: Engine) -> Iterator[dict]:
    session = get_session_factory()()
    department = Department(code="CSE", name="CSE")
    session.add(department)
    session.flush()
    term = AcademicTerm(
        code="T1",
        name="T1",
        academic_year="2026-27",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 12, 1),
    )
    course = Course(department_id=department.id, code="C1", name="C1")
    section = Section(department_id=department.id, name="A1", batch_year=2025)
    teacher = User(
        email="t@srmist.edu.in",
        full_name="T",
        password_hash=hash_password("x" * 8),
        role=Role.FACULTY,
    )
    session.add_all([term, course, section, teacher])
    session.flush()
    offering = CourseOffering(course_id=course.id, term_id=term.id, section_id=section.id)
    session.add(offering)
    session.flush()
    session.add(OfferingFaculty(offering_id=offering.id, user_id=teacher.id))
    students = [
        Student(
            register_number=f"RA2500000000{i:03d}",
            full_name=f"S{i}",
            department_id=department.id,
            batch_year=2025,
        )
        for i in range(3)
    ]
    session.add_all(students)
    session.flush()
    session.add_all(Enrollment(offering_id=offering.id, student_id=s.id) for s in students)
    for seq, name in enumerate(("CT1", "CT2"), start=1):
        session.add(
            Assessment(
                offering_id=offering.id,
                name=name,
                assessment_type=AssessmentType.CT,
                max_marks=50,
                weightage=10,
                sequence_no=seq,
                is_published=True,
            )
        )
    session.commit()
    data = {"offering_id": offering.id, "teacher": teacher, "students": students}
    session.expunge_all()
    session.close()
    try:
        yield data
    finally:
        reset_recompute()
        cleanup = get_session_factory()()
        tables = ", ".join(
            t
            for t in cleanup.scalars(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
        )
        cleanup.execute(text(f"TRUNCATE {tables} CASCADE"))
        cleanup.commit()
        cleanup.close()


def _sheet(students) -> bytes:
    workbook = Workbook()
    workbook.active.append(["Register No", "CT1", "CT2"])
    for i, student in enumerate(students):
        workbook.active.append([student.register_number, 10 + i, "AB"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _counts(offering_id: uuid.UUID) -> tuple[int, int, str]:
    with get_session_factory()() as session:
        results = session.scalar(select(func.count()).select_from(AssessmentResult))
        confirms = session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "confirm")
        )
        batch = session.scalar(select(ImportBatch).where(ImportBatch.offering_id == offering_id))
        return results, confirms, batch.status.value


def test_failed_confirm_leaves_no_partial_results(committed: dict) -> None:
    app = create_app()  # real get_db: one session per request, rolled back on error
    headers = auth_headers(committed["teacher"])
    with TestClient(app, raise_server_exceptions=False) as client:
        upload = client.post(
            f"/api/v1/offerings/{committed['offering_id']}/imports",
            files={"file": ("m.xlsx", _sheet(committed["students"]))},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        batch_id = upload.json()["batch"]["id"]
        assert upload.json()["summary"]["will_create"] == 6

        calls: list[uuid.UUID] = []

        def fail_on_second(session: Session, assessment_id: uuid.UUID) -> None:
            calls.append(assessment_id)
            if len(calls) == 2:  # the first assessment's rows are already flushed by now
                raise RuntimeError("analytics crashed mid-import")

        set_recompute(fail_on_second)
        crashed = client.post(f"/api/v1/imports/{batch_id}/confirm", headers=headers)
        assert crashed.status_code == 500
        assert crashed.json()["error"]["code"] == "internal_error"
        assert len(calls) == 2
        assert _counts(committed["offering_id"]) == (0, 0, ImportStatus.PREVIEWED.value)

        reset_recompute()
        ok = client.post(f"/api/v1/imports/{batch_id}/confirm", headers=headers)
        assert ok.status_code == 200, ok.text
        assert _counts(committed["offering_id"]) == (6, 1, ImportStatus.COMMITTED.value)
