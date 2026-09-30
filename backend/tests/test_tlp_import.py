"""SRM TLP mark reports through the real import pipeline: xlsx, csv and pdf, single-section
and multi-file uploads, title-block verification and routing."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessments.models import AssessmentResult, ResultStatus
from app.modules.imports.tlp_writer import TlpHeader, TlpRow, to_csv, to_pdf, to_xlsx
from app.modules.imports.validation import match_key
from app.modules.organization.models import CourseCoordinator, Semester
from app.modules.users.models import Role
from tests.conftest import auth_headers

API = "/api/v1"
WRITERS = {"xlsx": to_xlsx, "csv": to_csv, "pdf": to_pdf}


def header(**overrides) -> TlpHeader:
    values = dict(
        test_name="FT-II",
        academic_year="AY2026-27-ODD",
        component_max=Decimal("15"),
        course_code="21CSC201J",
        course_name="Data Structures and Algorithms",
        faculty_name="Dr. Priya Nair",
        faculty_code="900101",
    )
    values.update(overrides)
    return TlpHeader(**values)


@pytest.fixture
def world(db_session: Session, org, cse, term, make_user, make_student, make_assessment):
    term.semester = Semester.ODD
    teacher = make_user(Role.FACULTY, department=cse)
    teacher.employee_code = "900101"
    coord = make_user(Role.COURSE_COORDINATOR, department=cse)
    dsa = org.course(cse, "21CSC201J")
    db_session.add(CourseCoordinator(course_id=dsa.id, user_id=coord.id))
    sections = [org.section(cse, name) for name in ("A1", "A2")]
    offerings = [org.offering(dsa, s, term, [teacher]) for s in sections]
    students = {}
    for offering, section in zip(offerings, sections, strict=True):
        make_assessment(offering, "FT-I", max_marks="5", weightage="5")
        make_assessment(offering, "FT-2", max_marks="15", weightage="15")
        students[section.name] = [
            make_student(cse, section, enroll_in=[offering]) for _ in range(4)
        ]
    db_session.flush()
    return {
        "teacher": teacher,
        "coord": coord,
        "offerings": offerings,
        "students": students,
        "course": dsa,
    }


def roster(students, marks=("12.5", None, "0", "15")) -> list[TlpRow]:
    return [
        TlpRow(s.register_number, s.full_name.upper(), Decimal(m) if m is not None else None)
        for s, m in zip(students, marks, strict=True)
    ]


def test_roman_and_arabic_numerals_are_the_same_name() -> None:
    assert match_key("FT-II") == match_key("FT 2") == match_key("ft2") == "ft2"
    assert match_key("LLJ-I") == "llj1"
    assert match_key("Report and Viva") == "reportandviva"  # no word is read as a numeral
    assert match_key("PBL-III (20)") == "pbl3"


@pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
def test_single_section_tlp_upload_confirms_exact_values(
    client: TestClient, db_session: Session, world, fmt: str
) -> None:
    offering = world["offerings"][0]
    students = world["students"]["A1"]
    content = WRITERS[fmt](header(), roster(students))
    r = client.post(
        f"{API}/offerings/{offering.id}/imports",
        files={"file": (f"A1_FT2.{fmt}", content)},
        headers=auth_headers(world["teacher"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Routed to FT-2 by the report's own test name, with its title block kept.
    assert body["batch"]["source_metadata"]["test_name"] == "FT-II"
    assert body["batch"]["source_metadata"]["total_strength"] == "4"
    assert body["summary"]["errors"] == 0, body["file_issues"]
    roles = {c["header"]: c["role"] for c in body["columns"]}
    assert roles["Obtained Mark"] == "assessment" and roles["%"] == "percentage"
    assert roles["S.No."] == roles["Dept"] == "ignored"

    r = client.post(
        f"{API}/imports/{body['batch']['id']}/confirm", headers=auth_headers(world["teacher"])
    )
    assert r.status_code == 200, r.text
    stored = {
        res.student_id: (res.status, res.score)
        for res in db_session.scalars(select(AssessmentResult))
    }
    assert stored[students[0].id] == (ResultStatus.PRESENT, Decimal("12.50"))
    assert stored[students[1].id] == (ResultStatus.ABSENT, None)  # Absent, never 0
    assert stored[students[2].id] == (ResultStatus.PRESENT, Decimal("0.00"))  # a real zero


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"component_max": Decimal("20")}, "max_mismatch"),
        ({"course_code": "21CSC202J"}, "course_mismatch"),
        ({"academic_year": "AY2026-27-EVEN"}, "term_mismatch"),
        ({"academic_year": "AY2024-25-ODD"}, "term_mismatch"),
    ],
)
def test_title_block_must_agree_with_the_platform(
    client: TestClient, world, overrides, code
) -> None:
    offering = world["offerings"][0]
    content = to_xlsx(header(**overrides), roster(world["students"]["A1"]))
    r = client.post(
        f"{API}/offerings/{offering.id}/imports",
        files={"file": ("x.xlsx", content)},
        headers=auth_headers(world["teacher"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert code in {i["code"] for i in body["file_issues"] if i["level"] == "error"}
    assert body["summary"]["can_confirm"] is False
    confirm = client.post(
        f"{API}/imports/{body['batch']['id']}/confirm", headers=auth_headers(world["teacher"])
    )
    assert confirm.status_code == 422


def test_truncated_report_is_detected_from_its_own_summary(client: TestClient, world) -> None:
    offering = world["offerings"][0]
    content = to_xlsx(header(), roster(world["students"]["A1"]))
    # Remove one student row but keep the summary that says 4.
    from io import BytesIO

    from openpyxl import load_workbook

    book = load_workbook(BytesIO(content))
    book.active.delete_rows(9)
    out = BytesIO()
    book.save(out)
    r = client.post(
        f"{API}/offerings/{offering.id}/imports",
        files={"file": ("x.xlsx", out.getvalue())},
        headers=auth_headers(world["teacher"]),
    )
    codes = {i["code"] for i in r.json()["file_issues"] if i["level"] == "error"}
    assert "summary_mismatch" in codes


def test_unknown_test_name_is_rejected_with_the_reason(client: TestClient, world) -> None:
    offering = world["offerings"][0]
    content = to_csv(header(test_name="FT-IV"), roster(world["students"]["A1"]))
    r = client.post(
        f"{API}/offerings/{offering.id}/imports",
        files={"file": ("x.csv", content)},
        headers=auth_headers(world["teacher"]),
    )
    assert r.status_code == 422
    assert "FT-IV" in r.json()["error"]["message"]


def test_coordinator_multi_file_upload_routes_stages_and_confirms(
    client: TestClient, db_session: Session, world, make_student, cse
) -> None:
    a1, a2 = world["students"]["A1"], world["students"]["A2"]
    strangers = [make_student(cse) for _ in range(4)]  # enrolled nowhere
    files = [
        ("A1_FT2.xlsx", to_xlsx(header(), roster(a1))),
        ("A2_FT2.pdf", to_pdf(header(), roster(a2, ("10", "11", "9.5", "14")))),
        ("copy_of_A1.xlsx", to_xlsx(header(), roster(a1))),  # identical bytes -> skipped
        ("unknown.csv", to_csv(header(), roster(strangers))),
        ("not_a_report.csv", b"hello,world\n1,2\n"),
    ]
    headers = auth_headers(world["coord"])
    r = client.post(
        f"{API}/tlp-uploads",
        files=[("files", (name, content)) for name, content in files],
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    status = {f["file_name"]: f for f in body["files"]}
    assert status["A1_FT2.xlsx"]["section_name"] == "A1"
    assert status["A2_FT2.pdf"]["section_name"] == "A2"
    assert status["A1_FT2.xlsx"]["assessment_name"] == "FT-2"
    assert status["A1_FT2.xlsx"]["status"] in ("valid", "warning")
    assert "4 of 4" in status["A2_FT2.pdf"]["routed_by"]
    assert status["copy_of_A1.xlsx"]["status"] == "skipped"
    assert status["unknown.csv"]["status"] == "rejected"
    assert status["not_a_report.csv"]["status"] == "rejected"
    assert body["counts"]["total"] == 5

    confirmed = client.post(f"{API}/tlp-uploads/{body['group_id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert {f["status"] for f in confirmed.json()["files"]} == {"confirmed"}
    written = db_session.scalars(select(AssessmentResult)).all()
    assert len(written) == 8

    again = client.get(f"{API}/tlp-uploads/{body['group_id']}", headers=headers)
    assert again.status_code == 200 and again.json()["counts"]["confirmed"] == 2


def test_faculty_cannot_route_into_sections_outside_their_scope(
    client: TestClient, world, make_user, cse
) -> None:
    outsider = make_user(Role.FACULTY, department=cse)
    content = to_xlsx(header(), roster(world["students"]["A1"]))
    r = client.post(
        f"{API}/tlp-uploads",
        files=[("files", ("A1.xlsx", content))],
        headers=auth_headers(outsider),
    )
    assert r.status_code == 201
    assert r.json()["files"][0]["status"] == "rejected"


def test_apply_srm_scheme_is_idempotent(client: TestClient, db_session, org, cse, term, faculty):
    dt = org.course(cse, "21DCS201P")
    dt.course_type = None
    from app.modules.organization.models import CourseType

    dt.course_type = CourseType.PROJECT
    offering = org.offering(dt, org.section(cse, "S2"), term, [faculty])
    headers = auth_headers(faculty)
    r = client.post(f"{API}/offerings/{offering.id}/assessments/apply-scheme", headers=headers)
    assert r.status_code == 200, r.text
    names = [a["name"] for a in r.json()["items"]]
    assert names == ["FP-I", "PBL-I", "PBL-II", "FP-II", "PBL-III", "Report and Viva Voce"]
    assert float(r.json()["weightage_total"]) == 100
    fp1 = r.json()["items"][0]
    assert float(fp1["max_marks"]) == 10  # the TLP "Component Max. Mark"
    again = client.post(f"{API}/offerings/{offering.id}/assessments/apply-scheme", headers=headers)
    assert len(again.json()["items"]) == 6


def test_correcting_a_mark_supersedes_the_files_percentage(client: TestClient, world) -> None:
    offering = world["offerings"][0]
    rows = roster(world["students"]["A1"])
    rows[0] = TlpRow(rows[0].register_number, rows[0].name, Decimal("17"))  # above max 15
    headers = auth_headers(world["teacher"])
    r = client.post(
        f"{API}/offerings/{offering.id}/imports",
        files={"file": ("x.xlsx", to_xlsx(header(), rows))},
        headers=headers,
    ).json()
    assert r["summary"]["errors"] >= 1
    batch = r["batch"]["id"]
    row = next(x["row"] for x in r["rows"] if x["cells"] and x["cells"][0]["raw"] == "17.00")
    fixed = client.post(
        f"{API}/imports/{batch}/fix",
        json={"fixes": [{"row": row, "column": "Obtained Mark", "value": "14"}]},
        headers=headers,
    ).json()
    assert fixed["summary"]["errors"] == 0 and fixed["summary"]["can_confirm"] is True
