"""Uploading TLP reports into an empty platform: the report alone sets up the semester,
course, section, students, faculty login and test, and only its own data ends up stored."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import Assessment, AssessmentResult, ResultStatus
from app.modules.imports.provision import admission_year, section_from_file_name
from app.modules.imports.tlp_writer import TlpHeader, TlpRow, to_csv, to_pdf, to_xlsx
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    CourseType,
    OfferingFaculty,
    Section,
    Semester,
)
from app.modules.students.models import Enrollment, Student
from app.modules.users.models import Role, User
from tests.conftest import auth_headers

API = "/api/v1"
WRITERS = {"xlsx": to_xlsx, "csv": to_csv, "pdf": to_pdf}


def header(**overrides) -> TlpHeader:
    values = dict(
        test_name="FJ-III",
        academic_year="AY2025-26-EVEN",
        component_max=Decimal("15"),
        course_code="21CSC201J",
        course_name="Data Structures and Algorithms",
        faculty_name="Dr. Kavya Iyer",
        faculty_code="902049",
    )
    values.update(overrides)
    return TlpHeader(**values)


def students(start: int, marks=("12.5", None, "7", "15", "10")) -> list[TlpRow]:
    names = ["ANANYA RAO", "BHARATH K", "CHITRA MENON", "DEEPAK SINGH", "ESHA PATEL"]
    return [
        TlpRow(f"RA24110030{start + i:05d}", names[i % len(names)], Decimal(m) if m else None)
        for i, m in enumerate(marks)
    ]


def upload(client: TestClient, user: User, files, sections=None):
    # A rejected file rolls its own transaction back; make sure the test's users survive it.
    Session.object_session(user).commit()
    data = {"sections": __import__("json").dumps(sections)} if sections else None
    r = client.post(
        f"{API}/tlp-uploads",
        files=[("files", (name, content)) for name, content in files],
        data=data,
        headers=auth_headers(user),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_section_is_read_from_the_file_name() -> None:
    assert section_from_file_name("DSA_FJ-III_A1.xlsx") == "A1"
    assert section_from_file_name("CSE sec B2 FT2.pdf") == "B2"
    assert section_from_file_name("section-N6.csv") == "N6"
    assert section_from_file_name("21CSC201J_FJ3_K12.xlsx") == "K12"
    assert section_from_file_name("FJ3_FT2.xlsx") is None  # assessment names, not sections
    assert section_from_file_name("report.pdf") is None
    assert section_from_file_name("A1_vs_A2.csv") is None  # two candidates: ask
    assert admission_year("RA2411003010001") == 2024


@pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
def test_first_report_sets_up_everything_and_stores_only_its_data(
    client: TestClient, db_session: Session, hod: User, fmt: str
) -> None:
    rows = students(1)
    body = upload(client, hod, [(f"DSA_FJ-III_A1.{fmt}", WRITERS[fmt](header(), rows))])
    result = body["files"][0]
    assert result["status"] in ("valid", "warning"), result
    assert result["section_name"] == "A1" and result["assessment_name"] == "FJ-III"
    created = result["created"]
    assert created["term"] == "AY2025-26-EVEN"
    assert created["course"] == "21CSC201J Data Structures and Algorithms"
    assert created["section"] == "A1 (batch 2024)"
    assert created["students"] == 5 and created["enrolments"] == 5
    assert created["faculty"]["email"] == "902049@srmist.edu.in"
    assert created["assessment"] == "FJ-III (out of 15)"
    assert "ids" not in created

    course = db_session.scalar(select(Course).where(Course.code == "21CSC201J"))
    assert course.course_type is CourseType.JOINT
    term = db_session.scalar(select(AcademicTerm))
    assert term.semester is Semester.EVEN and term.is_current
    offering = db_session.scalar(select(CourseOffering))
    teacher = db_session.scalar(select(User).where(User.employee_code == "902049"))
    assert teacher.role is Role.FACULTY and teacher.full_name == "Dr. Kavya Iyer"
    assert db_session.scalar(
        select(OfferingFaculty).where(
            OfferingFaculty.offering_id == offering.id, OfferingFaculty.user_id == teacher.id
        )
    )
    assert {s.full_name for s in db_session.scalars(select(Student))} == {r.name for r in rows}
    assessment = db_session.scalar(select(Assessment))
    assert assessment.max_marks == Decimal("15") and not assessment.is_published

    confirmed = client.post(
        f"{API}/tlp-uploads/{body['group_id']}/confirm", headers=auth_headers(hod)
    ).json()
    assert confirmed["files"][0]["status"] == "confirmed"
    written = {r.student.register_number: r for r in db_session.scalars(select(AssessmentResult))}
    assert written[rows[0].register_number].score == Decimal("12.5")
    absent = written[rows[1].register_number]
    assert absent.status is ResultStatus.ABSENT and absent.score is None  # never 0

    login = client.post(
        f"{API}/auth/login",
        json={"email": "902049@srmist.edu.in", "password": "Faculty@2026"},
    )
    assert login.status_code == 200, login.text


def test_later_reports_reuse_what_exists(client: TestClient, db_session: Session, hod) -> None:
    rows = students(1)
    first = upload(client, hod, [("DSA_A1.xlsx", to_xlsx(header(), rows))])
    client.post(f"{API}/tlp-uploads/{first['group_id']}/confirm", headers=auth_headers(hod))

    # Another course, file name without a section: the students' section is known.
    os_header = header(course_code="21CSC202J", course_name="Operating Systems")
    second = upload(client, hod, [("os_marks.csv", to_csv(os_header, rows))])
    result = second["files"][0]
    assert result["status"] in ("valid", "warning")
    assert result["section_name"] == "A1"
    assert "5 of 5 register numbers are already in section A1" in result["routed_by"]
    assert "students" not in result["created"] and "section" not in result["created"]
    assert db_session.scalar(select(func.count()).select_from(Student)) == 5
    assert db_session.scalar(select(func.count()).select_from(Section)) == 1
    assert db_session.scalar(select(func.count()).select_from(User)) == 2  # hod + faculty

    # The next test of the same class adds an assessment, nothing else.
    third = upload(client, hod, [("a.xlsx", to_xlsx(header(test_name="FJ-II"), rows))])
    assert third["files"][0]["created"] == {"assessment": "FJ-II (out of 15)"}
    names = [
        a.name for a in db_session.scalars(select(Assessment).order_by(Assessment.sequence_no))
    ]
    assert names[:2] == ["FJ-II", "FJ-III"]  # SRM teaching order, not upload order


def test_unknown_section_is_asked_for_then_used(
    client: TestClient, db_session: Session, hod
) -> None:
    content = to_xlsx(header(), students(1))
    body = upload(client, hod, [("marks.xlsx", content)])
    assert body["files"][0]["status"] == "needs_section"
    assert db_session.scalar(select(func.count()).select_from(Student)) == 0  # nothing kept

    body = upload(client, hod, [("marks.xlsx", content)], sections={"marks.xlsx": "sec b3"})
    result = body["files"][0]
    assert result["status"] in ("valid", "warning") and result["section_name"] == "B3"


def test_file_name_that_contradicts_the_students_is_rejected(
    client: TestClient, db_session: Session, hod
) -> None:
    rows = students(1)
    first = upload(client, hod, [("DSA_A1.xlsx", to_xlsx(header(), rows))])
    client.post(f"{API}/tlp-uploads/{first['group_id']}/confirm", headers=auth_headers(hod))
    wrong = upload(client, hod, [("DSA_FJ-II_A2.xlsx", to_xlsx(header(test_name="FJ-II"), rows))])
    result = wrong["files"][0]
    assert result["status"] == "rejected"
    assert "says section A2" in result["message"] and "A1" in result["message"]
    assert db_session.scalar(select(func.count()).select_from(Section)) == 1


def test_discarding_an_upload_removes_what_it_set_up(
    client: TestClient, db_session: Session, hod
) -> None:
    body = upload(client, hod, [("DSA_A1.xlsx", to_xlsx(header(), students(1)))])
    batch_id = body["files"][0]["batch_id"]
    r = client.post(f"{API}/imports/{batch_id}/discard", headers=auth_headers(hod))
    assert r.status_code == 200, r.text
    for model in (Student, Enrollment, Section, Course, CourseOffering, AcademicTerm, Assessment):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0, model
    assert db_session.scalar(select(User).where(User.employee_code == "902049")) is None


def test_discard_keeps_what_other_uploads_use(client: TestClient, db_session: Session, hod):
    rows = students(1)
    first = upload(client, hod, [("DSA_A1.xlsx", to_xlsx(header(), rows))])
    client.post(f"{API}/tlp-uploads/{first['group_id']}/confirm", headers=auth_headers(hod))
    os_header = header(course_code="21CSC202J", course_name="Operating Systems")
    second = upload(client, hod, [("os.xlsx", to_xlsx(os_header, rows))])
    client.post(
        f"{API}/imports/{second['files'][0]['batch_id']}/discard", headers=auth_headers(hod)
    )
    assert db_session.scalar(select(func.count()).select_from(Student)) == 5
    assert db_session.scalar(select(Course).where(Course.code == "21CSC202J")) is None
    assert db_session.scalar(select(Course).where(Course.code == "21CSC201J")) is not None


def test_existing_student_records_are_not_overwritten(
    client: TestClient, db_session: Session, hod
) -> None:
    rows = students(1)
    upload(client, hod, [("DSA_A1.xlsx", to_xlsx(header(), rows))])
    renamed = [TlpRow(r.register_number, "SOMEONE ELSE", r.mark) for r in rows]
    os_header = header(course_code="21CSC202J", course_name="Operating Systems")
    upload(client, hod, [("os.xlsx", to_xlsx(os_header, renamed))])
    assert {s.full_name for s in db_session.scalars(select(Student))} == {r.name for r in rows}


def test_faculty_may_set_up_only_their_own_class(
    client: TestClient, db_session: Session, make_user, cse
) -> None:
    teacher = make_user(Role.FACULTY, department=cse)
    teacher.employee_code = "905555"
    db_session.flush()
    someone_else = upload(client, teacher, [("A1.xlsx", to_xlsx(header(), students(1)))])
    assert someone_else["files"][0]["status"] == "rejected"
    assert db_session.scalar(select(func.count()).select_from(Course)) == 0
    own = upload(
        client, teacher, [("A1.xlsx", to_xlsx(header(faculty_code="905555"), students(1)))]
    )
    assert own["files"][0]["status"] in ("valid", "warning")
