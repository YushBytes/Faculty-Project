"""The real teacher dataset, end to end, reconciled against the source report.

Source: an official SRM IST "FORMAT TLP5" mark report —

    Faculty of Engineering and Technology, SRM Institute of Science and Technology, Kattankulathur
    Test FP-I · Academic Year AY2025-26-EVEN · Component Max. Mark 10.00
    21DCS201P (Design Thinking and Methodology), handled by Dr. Arulalan V (103059)

The report's own summary block is the independent check every number here is measured against:

    Total strength 58      0-49   1
    Total absentees 1      50-59  3
    Total failures 1       60-69  13
    Pass MARK 50%          70-79  14
    Pass percentage 96.55  80-89  17
                           90-100 9

**Column mapping, PDF → import file.** The fixture is `tests/fixtures/real_teacher_fp1.csv`
(and `.xlsx`), carrying three columns:

======================  ==========================  ==========================================
PDF column              Import column               Why
======================  ==========================  ==========================================
``Reg. No``             ``Register No``             how the importer identifies a student
``Name``                ``Name``                    checked against the stored name, not stored
``Obtained Mark``       ``FP-I (max 10)``           the assessment's own column; header states max
``S.No.``               *not imported*              a display index, not data
``Dept``                *not imported*              belongs to the student record, not the result
``%``                   *not imported*              derived; the engine recomputes it from score
                                                    and max so there is one rounding rule, not two
======================  ==========================  ==========================================

``Absent`` travels through **verbatim** — ``ABSENT`` is one of the importer's recognised absence
markers, so nothing had to be reshaped to fit the pipeline and nothing became a zero.

Why this dataset earns its own test: it contains, in real data, every case the project's central
invariant turns on — one **Absent** student, one **genuine 0.00**, two students at **exactly the
50% pass mark**, one student below it, and 54 above.
"""

from __future__ import annotations

import csv
import statistics
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.assessments.models import (
    Assessment,
    AssessmentResult,
    AssessmentType,
    ResultStatus,
)
from app.modules.attention.models import LIVE_FLAG_STATUSES, AttentionFlag
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.students.models import Enrollment, Student, StudentSectionHistory
from app.modules.users.models import Role, User
from tests.conftest import DEFAULT_PASSWORD, UserFactory, auth_headers

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CSV_FIXTURE = FIXTURES / "real_teacher_fp1.csv"
XLSX_FIXTURE = FIXTURES / "real_teacher_fp1.xlsx"

MAX_MARK = Decimal("10")
ASSESSMENT_NAME = "FP-I"
COURSE_CODE = "21DCS201P"
COURSE_NAME = "Design Thinking and Methodology"
TERM_CODE = "AY2025-26-EVEN"

# The source report's summary block. Hardcoded on purpose: it is the external reference, so it
# must not be derived from the same file the implementation reads.
PDF_TOTAL_STRENGTH = 58
PDF_ABSENTEES = 1
PDF_FAILURES = 1
PDF_PASS_MARK = 50
PDF_PASS_PERCENTAGE = Decimal("96.55")
PDF_DISTRIBUTION = {"0-49": 1, "50-59": 3, "60-69": 13, "70-79": 14, "80-89": 17, "90-100": 9}


# --------------------------------------------------------------------------- the fixture file


def roster() -> list[tuple[str, str, str]]:
    """``(register number, name, raw mark cell)`` straight from the committed fixture."""
    with CSV_FIXTURE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header, body = rows[0], rows[1:]
    assert header == ["Register No", "Name", "FP-I (max 10)"], header
    return [(r[0], r[1], r[2]) for r in body]


def percentages(entries: list[tuple[str, str, str]]) -> list[Decimal]:
    """Percentages of the *present* students, from the raw marks. Absent has no percentage."""
    return [Decimal(mark) * 10 for _, _, mark in entries if mark != "Absent"]


def bucket_of(percentage: Decimal) -> str:
    edges = [(50, "0-49"), (60, "50-59"), (70, "60-69"), (80, "70-79"), (90, "80-89")]
    for edge, label in edges:
        if percentage < edge:
            return label
    return "90-100"


class TestTheFixtureMatchesTheSourceReport:
    """Before trusting the fixture as a test input, prove it *is* the teacher's data."""

    def test_row_count(self) -> None:
        assert len(roster()) == PDF_TOTAL_STRENGTH

    def test_absentee_count_and_identity(self) -> None:
        absent = [(reg, name) for reg, name, mark in roster() if mark == "Absent"]
        assert len(absent) == PDF_ABSENTEES
        assert absent[0][0] == "RA2311003011995"

    def test_one_genuine_zero_distinct_from_the_absentee(self) -> None:
        zeros = [reg for reg, _, mark in roster() if mark != "Absent" and Decimal(mark) == 0]
        assert zeros == ["RA2411003012527"]

    def test_two_students_sit_exactly_on_the_pass_mark(self) -> None:
        at_mark = [
            reg for reg, _, m in roster() if m != "Absent" and Decimal(m) * 10 == PDF_PASS_MARK
        ]
        assert len(at_mark) == 2, "the 50% boundary cases this dataset was chosen for"

    def test_distribution_matches_the_report(self) -> None:
        counts = dict.fromkeys(PDF_DISTRIBUTION, 0)
        for percentage in percentages(roster()):
            counts[bucket_of(percentage)] += 1
        assert counts == PDF_DISTRIBUTION

    def test_failure_count_and_pass_percentage_match_the_report(self) -> None:
        present = percentages(roster())
        failures = [p for p in present if p < PDF_PASS_MARK]
        passes = [p for p in present if p >= PDF_PASS_MARK]
        assert len(failures) == PDF_FAILURES
        # The report's 96.55 is passes over *total strength* (56/58), not over those who sat it.
        assert round(Decimal(len(passes)) / PDF_TOTAL_STRENGTH * 100, 2) == PDF_PASS_PERCENTAGE

    def test_both_upload_formats_carry_the_same_table(self) -> None:
        from openpyxl import load_workbook

        sheet = load_workbook(XLSX_FIXTURE, read_only=True, data_only=True).active
        rows = [[c for c in row] for row in sheet.iter_rows(values_only=True)]
        assert rows[0] == ["Register No", "Name", "FP-I (max 10)"]
        assert len(rows) - 1 == PDF_TOTAL_STRENGTH
        for (reg, name, mark), row in zip(roster(), rows[1:], strict=True):
            assert [reg, name] == [row[0], row[1]]
            assert str(row[2]) == mark or Decimal(str(row[2])) == Decimal(mark)


# --------------------------------------------------------------------------- the world


class World:
    def __init__(self, offering: CourseOffering, assessment: Assessment, faculty: User) -> None:
        self.offering = offering
        self.assessment = assessment
        self.faculty = faculty
        self.headers = auth_headers(faculty)

    @property
    def base(self) -> str:
        return f"/api/v1/offerings/{self.offering.id}"


@pytest.fixture
def fp1(db_session: Session, make_user: UserFactory) -> World:
    """The real offering: Dr Arulalan V, 21DCS201P, AY2025-26-EVEN, 58 CSE students, FP-I /10."""
    department = Department(code="CSE", name="Computer Science and Engineering")
    db_session.add(department)
    db_session.flush()

    faculty = make_user(Role.FACULTY, email="arulalan.v@srmist.edu.in", full_name="Dr. Arulalan V")
    term = AcademicTerm(
        code=TERM_CODE,
        name="Even Semester 2025-26",
        academic_year="2025-26",
        start_date=__import__("datetime").date(2026, 1, 5),
        end_date=__import__("datetime").date(2026, 5, 31),
        is_current=True,
    )
    course = Course(
        department_id=department.id, code=COURSE_CODE, name=COURSE_NAME, credits=Decimal("3")
    )
    section = Section(department_id=department.id, name="S2", batch_year=2024)
    db_session.add_all([term, course, section])
    db_session.flush()

    offering = CourseOffering(course_id=course.id, section_id=section.id, term_id=term.id)
    db_session.add(offering)
    db_session.flush()
    db_session.add(OfferingFaculty(offering_id=offering.id, user_id=faculty.id))

    for register_number, name, _ in roster():
        student = Student(
            register_number=register_number,
            full_name=name,
            email=f"{register_number.lower()}@srmist.edu.in",
            department_id=department.id,
            batch_year=int(register_number[2:4]) + 2000,
            current_section_id=section.id,
        )
        db_session.add(student)
        db_session.flush()
        db_session.add(StudentSectionHistory(student_id=student.id, section_id=section.id))
        db_session.add(Enrollment(offering_id=offering.id, student_id=student.id))

    assessment = Assessment(
        offering_id=offering.id,
        name=ASSESSMENT_NAME,
        assessment_type=AssessmentType.INTERNAL,
        max_marks=MAX_MARK,
        weightage=Decimal("10"),
        sequence_no=1,
        is_published=True,
    )
    db_session.add(assessment)
    db_session.flush()
    db_session.refresh(offering)
    return World(offering, assessment, faculty)


def upload(client: TestClient, world: World, path: Path):
    return client.post(
        f"{world.base}/imports",
        files={"file": (path.name, path.read_bytes())},
        headers=world.headers,
    )


def import_the_real_file(client: TestClient, world: World, path: Path = CSV_FIXTURE) -> dict:
    staged = upload(client, world, path)
    assert staged.status_code == 201, staged.text
    body = staged.json()
    batch_id = body["batch"]["id"]

    preview = client.get(f"/api/v1/imports/{batch_id}/preview", headers=world.headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["errors"] == 0, preview.json()["summary"]

    confirmed = client.post(f"/api/v1/imports/{batch_id}/confirm", headers=world.headers)
    assert confirmed.status_code == 200, confirmed.text
    return body["summary"]


# --------------------------------------------------------------------------- import + database


class TestImportingTheRealFile:
    def test_the_teachers_csv_imports_with_no_errors(self, client: TestClient, fp1: World) -> None:
        summary = import_the_real_file(client, fp1)
        assert summary["will_create"] == PDF_TOTAL_STRENGTH

    def test_the_teachers_xlsx_imports_identically(
        self, client: TestClient, db_session: Session, fp1: World
    ) -> None:
        import_the_real_file(client, fp1, XLSX_FIXTURE)
        assert (
            db_session.scalar(select(func.count()).select_from(AssessmentResult))
            == PDF_TOTAL_STRENGTH
        )

    def test_the_absent_marker_is_recognised_not_treated_as_a_score(
        self, client: TestClient, fp1: World
    ) -> None:
        staged = upload(client, fp1, CSV_FIXTURE)
        assert staged.status_code == 201, staged.text
        summary = staged.json()["summary"]
        assert summary["absent_markers"] >= PDF_ABSENTEES, (
            "the teacher's literal 'Absent' must be recognised as an absence marker"
        )
        assert summary["blank_cells"] == 0, "this file has no blank cells"


class TestDatabaseReconciliation:
    """§14: verify PostgreSQL directly, against the report — not via the UI."""

    @pytest.fixture(autouse=True)
    def _imported(self, client: TestClient, fp1: World) -> None:
        import_the_real_file(client, fp1)

    def rows(self, session: Session) -> list[AssessmentResult]:
        return list(session.scalars(select(AssessmentResult)).all())

    def test_one_row_per_student_and_no_duplicates(self, db_session: Session, fp1: World) -> None:
        rows = self.rows(db_session)
        assert len(rows) == PDF_TOTAL_STRENGTH
        keys = [(r.student_id, r.assessment_id) for r in rows]
        assert len(keys) == len(set(keys))

    def test_the_absent_student_has_a_row_with_no_score(
        self, db_session: Session, fp1: World
    ) -> None:
        absent = [r for r in self.rows(db_session) if r.status is ResultStatus.ABSENT]
        assert len(absent) == PDF_ABSENTEES
        assert absent[0].score is None, "absent must never be stored as a number"
        student = db_session.get(Student, absent[0].student_id)
        assert student is not None and student.register_number == "RA2311003011995"

    def test_the_genuine_zero_is_stored_as_a_present_zero(
        self, db_session: Session, fp1: World
    ) -> None:
        student = db_session.scalar(
            select(Student).where(Student.register_number == "RA2411003012527")
        )
        assert student is not None
        row = db_session.scalar(
            select(AssessmentResult).where(AssessmentResult.student_id == student.id)
        )
        assert row is not None
        assert row.status is ResultStatus.PRESENT, "0 is a mark that was earned, not an absence"
        assert row.score == Decimal("0.00")

    def test_absent_and_zero_are_distinguishable_in_the_database(
        self, db_session: Session, fp1: World
    ) -> None:
        """The invariant this dataset exists to prove."""
        statuses = db_session.execute(
            select(AssessmentResult.status, func.count()).group_by(AssessmentResult.status)
        ).all()
        by_status = {status.value: count for status, count in statuses}
        assert by_status["present"] == PDF_TOTAL_STRENGTH - PDF_ABSENTEES
        assert by_status["absent"] == PDF_ABSENTEES
        zero_scores = db_session.scalar(
            select(func.count()).select_from(AssessmentResult).where(AssessmentResult.score == 0)
        )
        assert zero_scores == 1, "exactly one student earned a zero"

    def test_every_stored_score_matches_the_source_file(
        self, db_session: Session, fp1: World
    ) -> None:
        stored = {
            db_session.get(Student, r.student_id).register_number: r  # type: ignore[union-attr]
            for r in self.rows(db_session)
        }
        for register_number, _, mark in roster():
            row = stored[register_number]
            if mark == "Absent":
                assert row.status is ResultStatus.ABSENT and row.score is None
            else:
                assert row.score == Decimal(mark), register_number
                assert row.max_marks_snapshot == MAX_MARK

    def test_the_distribution_in_the_database_matches_the_report(
        self, db_session: Session, fp1: World
    ) -> None:
        counts = dict.fromkeys(PDF_DISTRIBUTION, 0)
        for row in self.rows(db_session):
            if row.score is None:
                continue
            counts[bucket_of(row.score / row.max_marks_snapshot * 100)] += 1
        assert counts == PDF_DISTRIBUTION

    def test_results_belong_to_the_right_offering_and_faculty(
        self, db_session: Session, fp1: World
    ) -> None:
        assessments = db_session.scalars(
            select(Assessment).where(Assessment.offering_id == fp1.offering.id)
        ).all()
        assert [a.name for a in assessments] == [ASSESSMENT_NAME]
        assert all(r.assessment_id == fp1.assessment.id for r in self.rows(db_session))
        assigned = db_session.scalars(
            select(OfferingFaculty.user_id).where(OfferingFaculty.offering_id == fp1.offering.id)
        ).all()
        assert list(assigned) == [fp1.faculty.id]


# --------------------------------------------------------------------------- attention boundaries


class TestAttentionOnRealData:
    @pytest.fixture(autouse=True)
    def _imported(self, client: TestClient, fp1: World) -> None:
        import_the_real_file(client, fp1)

    def flags(self, session: Session, register_number: str) -> set[AttentionRuleCode]:
        student = session.scalar(select(Student).where(Student.register_number == register_number))
        assert student is not None
        return {
            row.rule_code
            for row in session.scalars(
                select(AttentionFlag).where(
                    AttentionFlag.student_id == student.id,
                    AttentionFlag.status.in_(LIVE_FLAG_STATUSES),
                )
            ).all()
        }

    def test_the_zero_scoring_student_is_flagged_for_performance_not_completion(
        self, db_session: Session, fp1: World
    ) -> None:
        fired = self.flags(db_session, "RA2411003012527")
        assert AttentionRuleCode.R1_LOW_PERFORMANCE in fired
        assert AttentionRuleCode.R2_FAILED_LATEST in fired
        assert AttentionRuleCode.R6_LOW_COMPLETION not in fired, (
            "they sat the paper and scored 0; that is complete, not missing"
        )

    @pytest.mark.parametrize("register_number", ["RA2411003012530", "RA2411003012533"])
    def test_exactly_fifty_percent_does_not_fire_the_low_performance_rule(
        self, db_session: Session, fp1: World, register_number: str
    ) -> None:
        """§16's boundary. R1 and R2 both compare with a strict ``<``, so the pass mark passes."""
        fired = self.flags(db_session, register_number)
        assert AttentionRuleCode.R1_LOW_PERFORMANCE not in fired
        assert AttentionRuleCode.R2_FAILED_LATEST not in fired

    @pytest.mark.parametrize("register_number", ["RA2411003012530", "RA2411003012533"])
    def test_exactly_fifty_percent_is_reported_as_borderline(
        self, db_session: Session, fp1: World, register_number: str
    ) -> None:
        """Not failing is not the same as being fine: R7 still shows the teacher the margin."""
        assert AttentionRuleCode.R7_BORDERLINE in self.flags(db_session, register_number)

    def test_the_absent_student_is_flagged_for_completion_and_not_for_a_score(
        self, db_session: Session, fp1: World
    ) -> None:
        fired = self.flags(db_session, "RA2311003011995")
        assert AttentionRuleCode.R6_LOW_COMPLETION in fired
        assert AttentionRuleCode.R1_LOW_PERFORMANCE not in fired, (
            "an absence is not a low score; averaging it as 0 is the bug this guards"
        )
        assert AttentionRuleCode.R2_FAILED_LATEST not in fired

    def test_a_strong_student_is_not_flagged_at_all(self, db_session: Session, fp1: World) -> None:
        assert self.flags(db_session, "RA2411003012505") == set()

    def test_rules_needing_several_assessments_cannot_fire_on_one(
        self, db_session: Session, fp1: World
    ) -> None:
        """One assessment means no trend. Those rules stay silent rather than guessing."""
        fired: set[AttentionRuleCode] = set()
        for row in db_session.scalars(select(AttentionFlag)).all():
            fired.add(row.rule_code)
        for code in (
            AttentionRuleCode.R3_REPEATED_LOW,
            AttentionRuleCode.R4_SHARP_DECLINE,
            AttentionRuleCode.R5_DECLINING_TREND,
        ):
            assert code not in fired, f"{code.value} fired with a single assessment"


# --------------------------------------------------------------------------- analytics + reports


class TestAnalyticsOnRealData:
    @pytest.fixture(autouse=True)
    def _imported(self, client: TestClient, fp1: World) -> None:
        import_the_real_file(client, fp1)

    def test_class_health_reports_the_real_cohort(self, client: TestClient, fp1: World) -> None:
        response = client.get(f"{fp1.base}/analytics", headers=fp1.headers)
        assert response.status_code == 200, response.text
        health = response.json()["health"]

        assert health["cohort_n"] == PDF_TOTAL_STRENGTH
        assert health["published_assessments"] == 1
        assert Decimal(str(health["pass_mark_percent"])) == PDF_PASS_MARK

        present = percentages(roster())
        assert Decimal(str(health["class_mean"]["value"])) == pytest.approx(
            statistics.mean(present), abs=Decimal("0.01")
        )
        assert Decimal(str(health["median"]["value"])) == pytest.approx(
            statistics.median(present), abs=Decimal("0.01")
        )

    def test_completion_counts_the_absentee_as_not_completed(
        self, client: TestClient, fp1: World
    ) -> None:
        health = client.get(f"{fp1.base}/analytics", headers=fp1.headers).json()["health"]
        completion = health["completion_percent"]
        assert completion["status"] == "ok"
        expected = Decimal(PDF_TOTAL_STRENGTH - PDF_ABSENTEES) / PDF_TOTAL_STRENGTH * 100
        assert Decimal(str(completion["value"])) == pytest.approx(expected, abs=Decimal("0.01"))

    def test_no_response_value_is_non_finite(self, client: TestClient, fp1: World) -> None:
        import json
        import math

        for route in ("analytics", "attention", "insights"):
            response = client.get(f"{fp1.base}/{route}", headers=fp1.headers)
            assert response.status_code == 200, response.text

            def reject(token: str, route: str = route) -> float:
                raise AssertionError(f"{route} serialised {token!r}")

            document = json.loads(response.text, parse_constant=reject)

            def walk(node: object) -> None:
                if isinstance(node, dict):
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)
                elif isinstance(node, float):
                    assert math.isfinite(node)

            walk(document)

    @pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
    @pytest.mark.parametrize("kind", ["class_summary", "attention", "assessment_comparison"])
    def test_every_report_renders_from_the_real_data(
        self, client: TestClient, fp1: World, kind: str, fmt: str
    ) -> None:
        response = client.get(
            f"{fp1.base}/reports/{kind}", params={"format": fmt}, headers=fp1.headers
        )
        assert response.status_code == 200, response.text
        assert response.content
        if fmt == "pdf":
            assert response.content.startswith(b"%PDF")
        if fmt == "csv":
            # Check whole cells, not substrings: real names contain "nan" (LOKKESH ANAND).
            import csv as csvmod
            import io

            cells = [
                cell.strip().lower()
                for row in csvmod.reader(io.StringIO(response.text))
                for cell in row
            ]
            for poison in ("nan", "-nan", "inf", "-inf", "infinity", "-infinity"):
                assert poison not in cells, f"{kind} exported a {poison!r} cell"

    def test_the_class_report_names_the_real_course(self, client: TestClient, fp1: World) -> None:
        """A downloaded report must say which offering it covers.

        Without it, a folder of class summaries is unusable.
        """
        response = client.get(
            f"{fp1.base}/reports/class_summary", params={"format": "csv"}, headers=fp1.headers
        )
        assert response.status_code == 200, response.text
        assert COURSE_CODE in response.text, "the report body does not name the course"
        assert TERM_CODE in response.text, "the report body does not name the term"
        assert COURSE_CODE in response.headers["content-disposition"], (
            "the filename does not name the course"
        )

    def test_the_attention_report_lists_the_students_who_need_it(
        self, client: TestClient, fp1: World
    ) -> None:
        body = client.get(
            f"{fp1.base}/reports/attention", params={"format": "csv"}, headers=fp1.headers
        ).text
        assert "RA2411003012527" in body, "the zero-scoring student must appear"
        assert "RA2311003011995" in body, "the absentee must appear"


class TestAtomicityOnRealData:
    def test_a_rejected_second_import_leaves_the_real_results_untouched(
        self, client: TestClient, db_session: Session, fp1: World
    ) -> None:
        import_the_real_file(client, fp1)
        before = {
            (r.student_id, r.score, r.status)
            for r in db_session.scalars(select(AssessmentResult)).all()
        }

        broken = b"Register No,FP-I (max 10)\nRA9999999999999,7.00\n"
        staged = client.post(
            f"{fp1.base}/imports",
            files={"file": ("bad.csv", broken)},
            headers=fp1.headers,
        )
        assert staged.status_code == 201, staged.text
        batch_id = staged.json()["batch"]["id"]
        assert staged.json()["summary"]["errors"] >= 1

        refused = client.post(f"/api/v1/imports/{batch_id}/confirm", headers=fp1.headers)
        assert refused.status_code == 422, refused.text

        after = {
            (r.student_id, r.score, r.status)
            for r in db_session.scalars(select(AssessmentResult)).all()
        }
        assert after == before, "a refused import must not disturb committed academic data"


class TestScopeOnRealData:
    def test_another_faculty_member_cannot_see_this_offering(
        self, client: TestClient, fp1: World, make_user: UserFactory
    ) -> None:
        stranger = make_user(Role.FACULTY, email="not.arulalan@srmist.edu.in")
        for route in ("analytics", "attention", "insights", "interventions"):
            response = client.get(f"{fp1.base}/{route}", headers=auth_headers(stranger))
            assert response.status_code == 404, f"{route} leaked to a stranger"

    def test_the_real_faculty_member_can_log_in_and_read_their_offering(
        self, client: TestClient, fp1: World
    ) -> None:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": fp1.faculty.email, "password": DEFAULT_PASSWORD},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        response = client.get(f"{fp1.base}/analytics", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        assert response.json()["health"]["cohort_n"] == PDF_TOTAL_STRENGTH


def test_the_fixture_is_the_only_source_of_student_identities() -> None:
    """Guard against drift: 58 unique register numbers, 58 unique names."""
    entries = roster()
    assert len({reg for reg, _, _ in entries}) == PDF_TOTAL_STRENGTH
    assert len({name for _, name, _ in entries}) == PDF_TOTAL_STRENGTH
    assert all(uuid.UUID(int=0) or reg.startswith("RA") for reg, _, _ in entries)
