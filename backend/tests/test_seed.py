"""The demo dataset contains every pattern promised to the analytics layer (contract C11)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessments.models import Assessment, AssessmentResult
from app.modules.assessments.service import OfferingResultsService
from app.modules.organization.models import Course, CourseOffering, Section
from app.modules.students.models import Enrollment, EnrollmentStatus, Student
from app.seed import SeedError, seed_demo


@pytest.fixture
def report(db_session: Session):
    return seed_demo(db_session, password="Demo@2026pass")


def _offering(db: Session, course: str, section: str) -> CourseOffering:
    return db.scalar(
        select(CourseOffering)
        .join(Course, Course.id == CourseOffering.course_id)
        .join(Section, Section.id == CourseOffering.section_id)
        .where(Course.code == course, Section.name == section)
    )


def _series(db: Session, offering: CourseOffering) -> dict[str, list]:
    data = OfferingResultsService(db).unscoped(offering.id)
    names = {a.id: a.name for a in data.assessments}
    by_student: dict[str, dict[str, object]] = {}
    number_of = {s.id: s.register_number for s in data.students}
    for r in data.results:
        value = r.percentage if r.status.value == "present" else r.status.value
        by_student.setdefault(number_of[r.student_id], {})[names[r.assessment_id]] = value
    return {n: [cells.get(k) for k in ("CT1", "CT2", "CT3")] for n, cells in by_student.items()}


def test_counts_and_accounts(report, db_session: Session) -> None:
    assert report.students == 60 and len(report.offerings) == 4
    assert set(report.users.values()) == {"ADMIN", "HOD", "FACULTY"}
    assert all(email.endswith("@acadlytics.dev") for email in report.users)


def test_embedded_patterns(report, db_session: Session) -> None:
    series = _series(db_session, _offering(db_session, "21CSC201J", "A1"))
    p = lambda n: series[f"RA251100301{n:04d}"]  # noqa: E731

    assert p(1) == [Decimal("90"), Decimal("92"), Decimal("88")]
    assert p(2)[0] > p(2)[1] > p(2)[2] and p(2)[0] - p(2)[2] >= 20  # steady decline
    assert p(3)[2] - (p(3)[0] + p(3)[1]) / 2 <= -15  # sharp drop vs previous mean
    assert p(4)[0] < p(4)[1] < p(4)[2]  # improving
    assert all(v < 50 for v in p(5))  # persistently low (pass 50)
    for n in (6, 7, 8):
        assert all(abs(v - 50) <= 5 for v in p(n))  # borderline cluster
    assert p(9)[1] == "absent" and p(10)[1] == "exempt"
    assert p(11) == [Decimal("65"), None, None]  # single assessment; the rest missing
    assert max(p(12)) - min(p(12)) >= 40  # volatile


def test_small_cohort_unpublished_dropped_inactive(report, db_session: Session) -> None:
    small = OfferingResultsService(db_session).unscoped(_offering(db_session, "21CSC202J", "C1").id)
    assert len(small.students) == 4
    assert [a.name for a in small.assessments] == ["CT1", "CT2", "CT3"]  # FT1 unpublished

    ft1_results = db_session.scalars(
        select(AssessmentResult).join(Assessment).where(Assessment.name == "FT1")
    ).all()
    assert ft1_results == []

    dropped = db_session.scalar(
        select(Enrollment).where(Enrollment.status == EnrollmentStatus.DROPPED)
    )
    assert dropped is not None
    kept = db_session.scalars(
        select(AssessmentResult).where(AssessmentResult.student_id == dropped.student_id)
    ).all()
    assert kept  # history kept
    assert db_session.scalar(select(Student).where(Student.is_active.is_(False))) is not None


def test_refuses_non_empty_database(report, db_session: Session) -> None:
    with pytest.raises(SeedError):
        seed_demo(db_session, password="x" * 12)
