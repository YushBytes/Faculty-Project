"""Aggregated analytics across the hierarchy: consistency with the offering engine, scope,
freshness after new results, reports and the workspace."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.assessments.models import AssessmentResult, ResultSource, ResultStatus
from app.modules.organization.models import CourseCoordinator, Semester
from app.modules.users.models import Role
from tests.conftest import auth_headers

API = "/api/v1"


def _results(db: Session, assessment, rows) -> None:
    for student, score in rows:
        db.add(
            AssessmentResult(
                student_id=student.id,
                assessment_id=assessment.id,
                score=None if score is None else Decimal(score),
                status=ResultStatus.PRESENT if score is not None else ResultStatus.ABSENT,
                max_marks_snapshot=assessment.max_marks,
                source=ResultSource.MANUAL,
            )
        )
    db.flush()


@pytest.fixture
def world(db_session: Session, org, cse, term, make_user, make_student, make_assessment):
    term.semester = Semester.ODD
    t1 = make_user(Role.FACULTY, department=cse, full_name="Teacher One")
    t2 = make_user(Role.FACULTY, department=cse, full_name="Teacher Two")
    coord = make_user(Role.COURSE_COORDINATOR, department=cse)
    dsa, os_ = org.course(cse, "21CSC201J"), org.course(cse, "21CSC202J")
    db_session.add(CourseCoordinator(course_id=dsa.id, user_id=coord.id))
    a1, a2 = org.section(cse, "A1"), org.section(cse, "A2")
    o1 = org.offering(dsa, a1, term, [t1])
    o2 = org.offering(dsa, a2, term, [t2])
    o3 = org.offering(os_, a1, term, [t2])
    s1 = [make_student(cse, a1, enroll_in=[o1, o3]) for _ in range(5)]
    s2 = [make_student(cse, a2, enroll_in=[o2]) for _ in range(5)]
    for offering, students, marks in (
        (o1, s1, [("40", "35"), ("30", "32"), ("20", "18"), ("45", "44"), ("25", None)]),
        (o2, s2, [("48", "46"), ("22", "12"), ("35", "38"), ("40", "41"), ("15", "20")]),
        (o3, s1, [("30", "35"), ("40", "45"), ("20", "25"), ("35", "30"), ("45", "40")]),
    ):
        ct1 = make_assessment(offering, "FT-I", max_marks="50", weightage="30")
        ct2 = make_assessment(offering, "FT-II", max_marks="50", weightage="30")
        _results(db_session, ct1, [(s, m[0]) for s, m in zip(students, marks, strict=True)])
        _results(db_session, ct2, [(s, m[1]) for s, m in zip(students, marks, strict=True)])
    return {"t1": t1, "t2": t2, "coord": coord, "o1": o1, "o2": o2, "o3": o3, "dsa": dsa, "s1": s1}


def test_single_offering_matches_the_offering_dashboard(client: TestClient, world) -> None:
    headers = auth_headers(world["t1"])
    offering = world["o1"]
    engine = client.get(f"{API}/offerings/{offering.id}/analytics", headers=headers).json()
    pooled = client.get(
        f"{API}/insights/overview", params={"offering_id": str(offering.id)}, headers=headers
    ).json()
    health, kpis = engine["health"], pooled["kpis"]
    assert kpis["average"]["value"] == health["class_mean"]["value"]
    assert kpis["median"]["value"] == health["median"]["value"]
    assert kpis["pass_percent"]["value"] == health["pass_percent"]["value"]
    assert kpis["completion_percent"]["value"] == health["completion_percent"]["value"]
    assert kpis["attention_students"] == engine["attention"]["students_requiring_attention"]


def test_scope_and_comparisons(client: TestClient, world, hod, admin) -> None:
    def overview(user, **params):
        r = client.get(f"{API}/insights/overview", params=params, headers=auth_headers(user))
        assert r.status_code == 200, r.text
        return r.json()

    assert overview(world["t1"])["counts"]["offerings"] == 1
    assert overview(world["t2"])["counts"]["offerings"] == 2
    coord = overview(world["coord"])
    assert coord["counts"]["offerings"] == 2 and coord["counts"]["courses"] == 1
    assert {r["label"] for r in coord["comparisons"]["faculty"]} == {"Teacher One", "Teacher Two"}
    assert coord["heatmap_rows"] == "sections"
    assert [c["name"] for c in coord["heatmap"]["columns"]] == ["FT-I", "FT-II"]
    department = overview(hod)
    assert department["counts"]["offerings"] == 3 and department["counts"]["courses"] == 2
    # Section A1 pools both of its courses.
    a1 = next(r for r in department["comparisons"]["sections"] if r["label"] == "A1")
    assert a1["offerings"] == 2
    # Absent is not a zero: the absent FT-II sitting shows in coverage, not the mean.
    assert department["kpis"]["coverage"]["absent"] == 1
    assert overview(admin)["counts"]["departments"] == 1
    # A faculty filter outside your scope simply finds nothing.
    assert overview(world["t1"], faculty_id=str(world["t2"].id))["counts"]["offerings"] == 0


def test_summaries_refresh_after_new_results(
    client: TestClient, db_session: Session, world, make_assessment
) -> None:
    headers = auth_headers(world["t1"])
    before = client.get(f"{API}/insights/overview", headers=headers).json()
    ft3 = make_assessment(world["o1"], "FT-III", max_marks="50", weightage="40")
    r = client.put(
        f"{API}/assessments/{ft3.id}/results",
        json={"results": [{"student_id": str(s.id), "score": "10"} for s in world["s1"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    after = client.get(f"{API}/insights/overview", headers=headers).json()
    assert [t["name"] for t in after["trend"]] == ["FT-I", "FT-II", "FT-III"]
    assert after["kpis"]["average"]["value"] < before["kpis"]["average"]["value"]
    assert after["trend"][-1]["change"] < 0


@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "csv"])
def test_scope_report_downloads_and_is_recorded(client: TestClient, world, fmt) -> None:
    headers = auth_headers(world["coord"])
    r = client.get(
        f"{API}/insights/report",
        params={"format": fmt, "course_id": str(world["dsa"].id)},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    if fmt == "pdf":
        assert r.content.startswith(b"%PDF")
    elif fmt == "csv":
        assert "Average course score" in r.text and "Teacher One" in r.text
    history = client.get(f"{API}/insights/reports/history", headers=headers).json()
    assert history[0]["format"] == fmt and history[0]["title"].startswith("Course Report")


def test_report_numbers_match_the_dashboard(client: TestClient, world, hod) -> None:
    headers = auth_headers(hod)
    dashboard = client.get(f"{API}/insights/overview", headers=headers).json()
    csv_text = client.get(f"{API}/insights/report", params={"format": "csv"}, headers=headers).text
    assert f"{dashboard['kpis']['average']['value']:.2f}%" in csv_text


def test_assessment_attention_interventions_lists(client: TestClient, world, hod) -> None:
    headers = auth_headers(hod)
    r = client.get(f"{API}/insights/assessments/ft2", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["sections"]) == 3 and r.json()["previous"]["name"] == "FT-I"
    assert client.get(f"{API}/insights/attention", headers=headers).status_code == 200
    assert client.get(f"{API}/insights/interventions", headers=headers).status_code == 200


def test_student_overview_is_scoped(client: TestClient, world) -> None:
    student = world["s1"][0]
    r = client.get(f"{API}/insights/students/{student.id}", headers=auth_headers(world["t2"]))
    assert r.status_code == 200
    assert [c["course_code"] for c in r.json()["classes"]] == ["21CSC202J"]  # only t2's class
    r = client.get(f"{API}/insights/students/{student.id}", headers=auth_headers(world["t1"]))
    assert [c["course_code"] for c in r.json()["classes"]] == ["21CSC201J"]


def test_workspace_describes_each_role(client: TestClient, world, admin) -> None:
    ws = client.get(f"{API}/me/workspace", headers=auth_headers(world["coord"])).json()
    assert ws["user"]["role"] == "COURSE_COORDINATOR"
    assert [c["code"] for c in ws["coordinated_courses"]] == ["21CSC201J"]
    assert ws["capabilities"]["assign_faculty"] and not ws["capabilities"]["manage_users"]
    ws = client.get(f"{API}/me/workspace", headers=auth_headers(world["t2"])).json()
    assert len(ws["teaching"]) == 2 and not ws["capabilities"]["compare_faculty"]
    ws = client.get(f"{API}/me/workspace", headers=auth_headers(admin)).json()
    assert ws["capabilities"]["manage_departments"] and ws["institution"].startswith("SRM")
