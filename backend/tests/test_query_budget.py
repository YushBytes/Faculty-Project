"""Query-count smoke tests: the shape of the read path, not its speed.

This is deliberately **not** a benchmark. A wall-clock number measured on a laptop against a
container proves nothing about production, so nothing here asserts a latency target. What it does
assert is the property that actually causes dashboards to fall over: that the number of SQL
statements a read issues does **not grow with the size of the cohort**. An N+1 is a shape bug, and
shape is measurable reliably even on a laptop.

Timings are printed for information (run with ``-s``) and never asserted.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import (
    Assessment,
    AssessmentResult,
    AssessmentType,
    ResultSource,
    ResultStatus,
)
from app.modules.organization.models import AcademicTerm, CourseOffering, Department
from app.modules.students.models import Enrollment, Student, StudentSectionHistory
from app.modules.users.models import User
from tests.conftest import OrgFactory, auth_headers

SMALL = 5
LARGE = 30
ASSESSMENTS = 4
MAX_MARKS = Decimal("50")

# A generous ceiling. The point is to catch a regression from "a few queries" to "one per
# student", not to pin the exact number, which legitimately shifts as features are added.
QUERY_CEILING = 40


class Counter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)

    def summary(self, limit: int = 3) -> str:
        from collections import Counter as Tally

        tally = Tally(s.split("\n")[0][:70] for s in self.statements)
        return "; ".join(f"{n}x {sql}" for sql, n in tally.most_common(limit))


@contextmanager
def counting(session: Session) -> Iterator[Counter]:
    """Count every statement executed on this session's connection."""
    counter = Counter()
    connection = session.get_bind()

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ANN202
        counter.statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield counter
    finally:
        event.remove(connection, "before_cursor_execute", record)


def build_offering(
    session: Session,
    org: OrgFactory,
    department: Department,
    term: AcademicTerm,
    faculty: User,
    *,
    students: int,
) -> tuple[CourseOffering, list[Student]]:
    """A realistic offering: a cohort, several published assessments, a full result matrix.

    Rows are inserted directly rather than through the API: this test is about the *read* path, and
    driving the writes over HTTP would spend its time in the recompute hook instead.
    """
    section = org.section(department)
    offering = org.offering(org.course(department), section, term, faculty=[faculty])
    # Both fixtures build cohorts inside one transaction, so each needs its own identifier space.
    # Uppercase: ck_students_register_number_format allows only ^[A-Z0-9]{5,20}$.
    token = uuid.uuid4().hex[:6].upper()

    cohort: list[Student] = []
    for index in range(students):
        student = Student(
            register_number=f"RA{token}{index:07d}",
            full_name=f"Student {index}",
            email=f"budget-{token.lower()}-{index}@srmist.edu.in",
            department_id=department.id,
            batch_year=2025,
            current_section_id=section.id,
        )
        session.add(student)
        session.flush()
        session.add(StudentSectionHistory(student_id=student.id, section_id=section.id))
        session.add(Enrollment(offering_id=offering.id, student_id=student.id))
        cohort.append(student)
    session.flush()

    for sequence in range(1, ASSESSMENTS + 1):
        assessment = Assessment(
            offering_id=offering.id,
            name=f"CT{sequence}",
            assessment_type=AssessmentType.CT,
            max_marks=MAX_MARKS,
            weightage=Decimal("25"),
            sequence_no=sequence,
            is_published=True,
        )
        session.add(assessment)
        session.flush()
        for index, student in enumerate(cohort):
            # A deterministic spread so some students are flagged and some are not.
            score = Decimal((index * 7 + sequence * 3) % 50)
            session.add(
                AssessmentResult(
                    student_id=student.id,
                    assessment_id=assessment.id,
                    score=score,
                    status=ResultStatus.PRESENT,
                    max_marks_snapshot=MAX_MARKS,
                    source=ResultSource.MANUAL,
                )
            )
    session.flush()
    return offering, cohort


@pytest.fixture
def small(
    db_session: Session, org: OrgFactory, cse: Department, term: AcademicTerm, faculty: User
) -> tuple[CourseOffering, list[Student]]:
    return build_offering(db_session, org, cse, term, faculty, students=SMALL)


@pytest.fixture
def large(
    db_session: Session, org: OrgFactory, cse: Department, term: AcademicTerm, faculty: User
) -> tuple[CourseOffering, list[Student]]:
    return build_offering(db_session, org, cse, term, faculty, students=LARGE)


def measure(
    client: TestClient, session: Session, actor: User, path: str
) -> tuple[int, float, Counter]:
    with counting(session) as counter:
        started = time.perf_counter()
        response = client.get(path, headers=auth_headers(actor))
        elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    return counter.count, elapsed, counter


class TestReadsDoNotScaleWithTheCohort:
    @pytest.mark.parametrize("route", ["analytics", "attention", "insights"])
    def test_query_count_is_the_same_for_five_students_and_thirty(
        self,
        client: TestClient,
        db_session: Session,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
        large: tuple[CourseOffering, list[Student]],
        route: str,
    ) -> None:
        small_offering, small_cohort = small
        large_offering, large_cohort = large

        few, few_seconds, _ = measure(
            client, db_session, faculty, f"/api/v1/offerings/{small_offering.id}/{route}"
        )
        many, many_seconds, detail = measure(
            client, db_session, faculty, f"/api/v1/offerings/{large_offering.id}/{route}"
        )

        print(
            f"\n{route}: {SMALL} students -> {few} queries in {few_seconds * 1000:.0f} ms | "
            f"{LARGE} students -> {many} queries in {many_seconds * 1000:.0f} ms"
        )
        assert many == few, (
            f"{route} issues more SQL for a bigger cohort ({few} -> {many}), which is an N+1. "
            f"Most frequent statements: {detail.summary()}"
        )
        assert many <= QUERY_CEILING, f"{route} issues {many} queries; ceiling is {QUERY_CEILING}"

    def test_a_student_read_does_not_query_per_classmate(
        self,
        client: TestClient,
        db_session: Session,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
        large: tuple[CourseOffering, list[Student]],
    ) -> None:
        small_offering, small_cohort = small
        large_offering, large_cohort = large
        few, _, _ = measure(
            client,
            db_session,
            faculty,
            f"/api/v1/offerings/{small_offering.id}/students/{small_cohort[0].id}/analytics",
        )
        many, _, detail = measure(
            client,
            db_session,
            faculty,
            f"/api/v1/offerings/{large_offering.id}/students/{large_cohort[0].id}/analytics",
        )
        assert many == few, f"per-student analytics scales with the cohort: {detail.summary()}"

    @pytest.mark.parametrize("kind", ["class_summary", "attention", "assessment_comparison"])
    def test_report_building_does_not_scale_in_queries(
        self,
        client: TestClient,
        db_session: Session,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
        large: tuple[CourseOffering, list[Student]],
        kind: str,
    ) -> None:
        few, _, _ = measure(
            client,
            db_session,
            faculty,
            f"/api/v1/offerings/{small[0].id}/reports/{kind}?format=csv",
        )
        many, _, detail = measure(
            client,
            db_session,
            faculty,
            f"/api/v1/offerings/{large[0].id}/reports/{kind}?format=csv",
        )
        assert many == few, f"{kind} report scales with the cohort: {detail.summary()}"


class TestInterventionReadsAreBatched:
    def test_listing_interventions_costs_the_same_for_one_as_for_many(
        self,
        client: TestClient,
        db_session: Session,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
    ) -> None:
        """Targets and reasons are read per page, not per intervention."""
        offering, cohort = small
        url = f"/api/v1/offerings/{offering.id}/interventions"

        created = client.post(
            url,
            json={
                "student_ids": [str(cohort[0].id)],
                "kind": "academic_support",
                "after_sequence_no": 1,
                "note": "first",
            },
            headers=auth_headers(faculty),
        )
        assert created.status_code == 201, created.text
        one, _, _ = measure(client, db_session, faculty, url)

        for student in cohort[1:]:
            response = client.post(
                url,
                json={
                    "student_ids": [str(student.id)],
                    "kind": "academic_support",
                    "after_sequence_no": 1,
                    "note": "another",
                },
                headers=auth_headers(faculty),
            )
            assert response.status_code == 201, response.text
        several, _, detail = measure(client, db_session, faculty, url)

        assert several == one, (
            f"listing interventions costs more as they accumulate: {one} -> {several}. "
            f"{detail.summary()}"
        )

    def test_outcome_measurement_is_one_read_per_offering(
        self,
        client: TestClient,
        db_session: Session,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
    ) -> None:
        offering, cohort = small
        for student in cohort:
            response = client.post(
                f"/api/v1/offerings/{offering.id}/interventions",
                json={
                    "student_ids": [str(student.id)],
                    "kind": "remedial_session",
                    "after_sequence_no": 1,
                    "note": "measured",
                },
                headers=auth_headers(faculty),
            )
            assert response.status_code == 201, response.text

        count, elapsed, detail = measure(
            client, db_session, faculty, f"/api/v1/offerings/{offering.id}/interventions/outcomes"
        )
        print(
            f"\noutcomes: {len(cohort)} interventions -> {count} queries in {elapsed * 1000:.0f} ms"
        )
        assert count <= QUERY_CEILING, (
            f"measuring {len(cohort)} interventions took {count} queries: {detail.summary()}"
        )


class TestRecomputeIsBounded:
    def test_recompute_reads_one_offering_regardless_of_how_many_exist(
        self,
        db_session: Session,
        org: OrgFactory,
        cse: Department,
        term: AcademicTerm,
        faculty: User,
        small: tuple[CourseOffering, list[Student]],
    ) -> None:
        """Scope check as a query-shape property: other offerings are never touched."""
        from app.modules.analytics.recompute import recompute_offering

        offering, _ = small
        assessment = db_session.scalars(
            select(Assessment).where(Assessment.offering_id == offering.id)
        ).first()
        assert assessment is not None

        # A second, larger offering that the recompute must ignore entirely.
        other, _ = build_offering(db_session, org, cse, term, faculty, students=LARGE)

        with counting(db_session) as counter:
            recompute_offering(db_session, offering.id, assessment.id)

        joined = " ".join(counter.statements)
        assert str(other.id) not in joined
        print(f"\nrecompute: {counter.count} queries for one offering")
        assert counter.count <= QUERY_CEILING, (
            f"recompute issued {counter.count} queries: {counter.summary()}"
        )
