"""Assessment results: missing-data policy, validation, audit, recompute hook, analytics read."""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.recompute import reset_recompute, set_recompute
from app.modules.assessments.models import AssessmentResult, ResultSource, ResultStatus
from app.modules.audit.models import AuditLog
from app.modules.organization.models import CourseOffering, Department
from app.modules.students.models import Enrollment, EnrollmentStatus
from app.modules.users.models import Role, User
from tests.conftest import AssessmentFactory, OrgFactory, StudentFactory, auth_headers


@pytest.fixture
def cohort(cse: Department, cse_offering: CourseOffering, make_student: StudentFactory):
    return [make_student(cse, enroll_in=[cse_offering]) for _ in range(4)]


@pytest.fixture
def ct1(cse_offering, make_assessment: AssessmentFactory):
    return make_assessment(cse_offering, "CT1", max_marks="50")


def _put(client, assessment, user, entries):
    return client.put(
        f"/api/v1/assessments/{assessment.id}/results",
        json={"results": entries},
        headers=auth_headers(user),
    )


def _stored(db: Session, assessment) -> dict:
    rows = db.scalars(
        select(AssessmentResult).where(AssessmentResult.assessment_id == assessment.id)
    )
    return {r.student_id: r for r in rows}


class TestMissingDataPolicy:
    def test_present_absent_exempt_stored_exactly(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        response = _put(
            client,
            ct1,
            faculty,
            [
                {"student_id": str(cohort[0].id), "score": 37.5},
                {"student_id": str(cohort[1].id), "status": "absent"},
                {"student_id": str(cohort[2].id), "status": "exempt"},
                {"register_number": cohort[3].register_number.lower(), "score": 0},
            ],
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"created": 4, "updated": 0, "unchanged": 0}
        stored = _stored(db_session, ct1)
        assert (stored[cohort[0].id].status, stored[cohort[0].id].score) == (
            ResultStatus.PRESENT,
            Decimal("37.50"),
        )
        assert (stored[cohort[1].id].status, stored[cohort[1].id].score) == (
            ResultStatus.ABSENT,
            None,
        )
        assert (stored[cohort[2].id].status, stored[cohort[2].id].score) == (
            ResultStatus.EXEMPT,
            None,
        )
        # An explicit 0 is a real score, distinct from absent.
        assert (stored[cohort[3].id].status, stored[cohort[3].id].score) == (
            ResultStatus.PRESENT,
            Decimal("0.00"),
        )
        assert stored[cohort[0].id].max_marks_snapshot == Decimal("50.00")
        assert stored[cohort[0].id].source is ResultSource.MANUAL

    def test_grid_shows_missing_and_percentages(
        self, client: TestClient, faculty: User, cohort, ct1
    ) -> None:
        _put(
            client,
            ct1,
            faculty,
            [
                {"student_id": str(cohort[0].id), "score": 37.5},
                {"student_id": str(cohort[1].id), "status": "absent"},
            ],
        )
        grid = client.get(
            f"/api/v1/assessments/{ct1.id}/results", headers=auth_headers(faculty)
        ).json()
        by_student = {r["student"]["id"]: r for r in grid["rows"]}
        assert by_student[str(cohort[0].id)]["result"]["percentage"] == 75.0
        assert by_student[str(cohort[1].id)]["state"] == "absent"
        assert by_student[str(cohort[1].id)]["result"]["percentage"] is None
        assert by_student[str(cohort[2].id)]["state"] == "missing"
        assert by_student[str(cohort[2].id)]["result"] is None
        assert grid["counts"] == {
            "present": 1,
            "absent": 1,
            "exempt": 0,
            "missing": 2,
            "enrolled": 4,
        }

    @pytest.mark.parametrize(
        ("entry", "message"),
        [
            ({}, "Give a score, or status"),
            ({"status": "present"}, "needs a score"),
            ({"status": "absent", "score": 0}, "must not have a score"),
            ({"status": "exempt", "score": 10}, "must not have a score"),
            ({"score": 50.01}, "above the maximum"),
        ],
    )
    def test_invalid_combinations_rejected(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session, entry, message
    ) -> None:
        response = _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), **entry}])
        assert response.status_code == 422
        detail = response.json()["error"]["details"][0]
        assert message in detail["message"]
        assert detail["loc"] == ["body", "results", 0, "score"]
        assert _stored(db_session, ct1) == {}

    @pytest.mark.parametrize("score", [-1, "12.345", "abc"])
    def test_malformed_scores(self, client: TestClient, faculty: User, cohort, ct1, score) -> None:
        response = _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": score}])
        assert response.status_code == 422

    def test_one_bad_entry_saves_nothing(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        response = _put(
            client,
            ct1,
            faculty,
            [
                {"student_id": str(cohort[0].id), "score": 40},
                {"student_id": str(cohort[1].id), "score": 99},
            ],
        )
        assert response.status_code == 422
        assert "nothing was saved" in response.json()["error"]["message"]
        assert _stored(db_session, ct1) == {}


class TestIdentityRules:
    def test_unknown_duplicate_and_not_enrolled(
        self, client: TestClient, faculty: User, cse, cohort, ct1, make_student
    ) -> None:
        outsider = make_student(cse)
        response = _put(
            client,
            ct1,
            faculty,
            [
                {"student_id": str(uuid.uuid4()), "score": 1},
                {"register_number": "RA0000000000000", "score": 1},
                {"student_id": str(cohort[0].id), "score": 1},
                {"register_number": cohort[0].register_number, "score": 2},
                {"student_id": str(outsider.id), "score": 1},
            ],
        )
        assert response.status_code == 422
        messages = [d["message"] for d in response.json()["error"]["details"]]
        assert any("Unknown student" in m for m in messages)
        assert any("Duplicate of entry 2" in m for m in messages)
        assert any("not enrolled" in m for m in messages)

    def test_exactly_one_identifier(self, client: TestClient, faculty: User, cohort, ct1) -> None:
        both = {"student_id": str(cohort[1].id), "register_number": cohort[1].register_number}
        for entry in (both, {"score": 1}):
            response = _put(client, ct1, faculty, [{**entry, "score": 1}])
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "validation_error"

    def test_dropped_student_new_result_blocked_existing_editable(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 20}])
        for student in cohort[:2]:
            enrollment = db_session.scalar(
                select(Enrollment).where(Enrollment.student_id == student.id)
            )
            enrollment.status = EnrollmentStatus.DROPPED
            enrollment.dropped_at = enrollment.enrolled_at
        db_session.flush()

        new = _put(client, ct1, faculty, [{"student_id": str(cohort[1].id), "score": 20}])
        assert new.status_code == 422 and "dropped" in new.json()["error"]["details"][0]["message"]
        edit = _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 25}])
        assert edit.status_code == 200 and edit.json()["updated"] == 1

        grid = client.get(
            f"/api/v1/assessments/{ct1.id}/results", headers=auth_headers(faculty)
        ).json()
        dropped_row = next(r for r in grid["rows"] if r["student"]["id"] == str(cohort[0].id))
        assert dropped_row["enrollment_status"] == "DROPPED" and dropped_row["state"] == "present"

    def test_out_of_scope_write_is_404(
        self, client: TestClient, make_user, cohort, ct1, db_session: Session
    ) -> None:
        stranger = make_user(Role.FACULTY, email="stranger@srmist.edu.in")
        response = _put(client, ct1, stranger, [{"student_id": str(cohort[0].id), "score": 1}])
        assert response.status_code == 404
        assert _stored(db_session, ct1) == {}


class TestOverwriteAudit:
    def test_update_keeps_old_value_in_audit(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 30}])
        same = _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 30}])
        assert same.json() == {"created": 0, "updated": 0, "unchanged": 1}

        changed = _put(
            client, ct1, faculty, [{"student_id": str(cohort[0].id), "status": "absent"}]
        )
        assert changed.json() == {"created": 0, "updated": 1, "unchanged": 0}
        logs = db_session.scalars(
            select(AuditLog).where(AuditLog.entity == "assessment_result")
        ).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.action == "update" and log.actor_id == faculty.id
        assert log.old_value["score"] == "30.00" and log.old_value["status"] == "present"
        assert log.new_value["score"] is None and log.new_value["status"] == "absent"
        assert log.offering_id == ct1.offering_id

    def test_delete_result_is_audited_and_becomes_missing(
        self, client: TestClient, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 30}])
        url = f"/api/v1/assessments/{ct1.id}/results/{cohort[0].id}"
        assert client.delete(url, headers=auth_headers(faculty)).status_code == 204
        assert client.delete(url, headers=auth_headers(faculty)).status_code == 404
        assert _stored(db_session, ct1) == {}
        log = db_session.scalar(select(AuditLog).where(AuditLog.action == "delete"))
        assert log.old_value["score"] == "30.00"


class TestRecomputeHook:
    @pytest.fixture
    def calls(self):
        seen: list[tuple[uuid.UUID, int]] = []

        def spy(session: Session, assessment_id: uuid.UUID) -> None:
            # Runs inside the writer's transaction: the new rows are already visible.
            count = session.scalar(
                text("SELECT count(*) FROM assessment_results WHERE assessment_id = :a"),
                {"a": assessment_id},
            )
            seen.append((assessment_id, count))

        set_recompute(spy)
        yield seen
        reset_recompute()

    def test_called_once_per_write_with_rows_visible(
        self, client: TestClient, faculty: User, cohort, ct1, calls
    ) -> None:
        _put(
            client,
            ct1,
            faculty,
            [
                {"student_id": str(cohort[0].id), "score": 30},
                {"student_id": str(cohort[1].id), "score": 31},
            ],
        )
        assert calls == [(ct1.id, 2)]
        _put(client, ct1, faculty, [{"student_id": str(cohort[0].id), "score": 30}])  # no change
        assert len(calls) == 1
        client.delete(
            f"/api/v1/assessments/{ct1.id}/results/{cohort[1].id}", headers=auth_headers(faculty)
        )
        assert calls[-1] == (ct1.id, 1)

    def test_hook_failure_aborts_the_write(
        self, faculty: User, cohort, ct1, db_session: Session
    ) -> None:
        from app.modules.assessments.schemas import ResultEntry
        from app.modules.assessments.service import AssessmentService

        def broken(session: Session, assessment_id: uuid.UUID) -> None:
            raise RuntimeError("analytics failed")

        set_recompute(broken)
        try:
            with pytest.raises(RuntimeError):
                AssessmentService(db_session).upsert_results(
                    ct1.id,
                    [ResultEntry(student_id=cohort[0].id, score=Decimal("5"))],
                    actor=faculty,
                )
        finally:
            reset_recompute()
        # The exception happened before commit; the request's session is rolled back by get_db.

    def test_admin_recompute_runs_hook_for_each_assessment(
        self, client: TestClient, admin: User, faculty: User, cse_offering, make_assessment, calls
    ) -> None:
        make_assessment(cse_offering, "CT1")
        make_assessment(cse_offering, "CT2")
        url = f"/api/v1/admin/recompute?offering_id={cse_offering.id}"
        response = client.post(url, headers=auth_headers(admin))
        assert response.json()["assessments_recomputed"] == 2 and len(calls) == 2
        assert client.post(url, headers=auth_headers(faculty)).status_code == 403


class TestOfferingResultsRead:
    def test_matrix_contents_and_filters(
        self,
        client: TestClient,
        faculty: User,
        cse,
        cse_offering,
        make_assessment,
        make_student,
        db_session: Session,
    ) -> None:
        ct1 = make_assessment(cse_offering, "CT1", max_marks="50")
        draft = make_assessment(cse_offering, "CT2", published=False)
        active = make_student(cse, enroll_in=[cse_offering])
        inactive = make_student(cse, enroll_in=[cse_offering], is_active=False)
        _put(client, ct1, faculty, [{"student_id": str(active.id), "score": 45}])
        db_session.add(
            AssessmentResult(
                student_id=inactive.id,
                assessment_id=ct1.id,
                status=ResultStatus.PRESENT,
                score=Decimal("10"),
                max_marks_snapshot=Decimal("50"),
                source=ResultSource.MANUAL,
            )
        )
        db_session.flush()

        url = f"/api/v1/offerings/{cse_offering.id}/results"
        body = client.get(url, headers=auth_headers(faculty)).json()
        assert body["offering"]["pass_percent"] == 50.0 and body["offering"]["config"] == {}
        assert [a["name"] for a in body["assessments"]] == ["CT1"]
        assert [s["id"] for s in body["students"]] == [str(active.id)]
        assert body["results"] == [
            {
                "student_id": str(active.id),
                "assessment_id": str(ct1.id),
                "status": "present",
                "score": 45.0,
                "max_marks_snapshot": 50.0,
                "percentage": 90.0,
            }
        ]

        everything = client.get(
            url,
            params={"published_only": False, "include_dropped": True},
            headers=auth_headers(faculty),
        ).json()
        assert {a["id"] for a in everything["assessments"]} == {str(ct1.id), str(draft.id)}
        assert len(everything["students"]) == 2 and len(everything["results"]) == 2

    def test_scope(self, client: TestClient, make_user, org: OrgFactory, ece, term) -> None:
        other = org.offering(org.course(ece), org.section(ece), term)
        stranger = make_user(Role.FACULTY, email="stranger@srmist.edu.in")
        response = client.get(
            f"/api/v1/offerings/{other.id}/results", headers=auth_headers(stranger)
        )
        assert response.status_code == 404

    def test_percentage_rounding(self) -> None:
        from app.modules.assessments.service import percentage

        assert percentage(Decimal("1"), Decimal("3")) == Decimal("33.33")
        assert percentage(Decimal("2"), Decimal("3")) == Decimal("66.67")
        assert percentage(None, Decimal("3")) is None


class TestDatabaseConstraints:
    def _row(self, student, assessment, **overrides) -> AssessmentResult:
        values = dict(
            student_id=student.id,
            assessment_id=assessment.id,
            status=ResultStatus.PRESENT,
            score=Decimal("10"),
            max_marks_snapshot=Decimal("50"),
            source=ResultSource.MANUAL,
        )
        return AssessmentResult(**{**values, **overrides})

    @pytest.mark.parametrize(
        "overrides",
        [
            {"status": ResultStatus.ABSENT},  # absent with a score
            {"status": ResultStatus.EXEMPT, "score": Decimal("0")},
            {"score": None},  # present without a score
            {"score": Decimal("50.5")},  # above snapshot max
            {"score": Decimal("-1")},
        ],
    )
    def test_rejects_inconsistent_rows(self, db_session: Session, cohort, ct1, overrides) -> None:
        db_session.add(self._row(cohort[0], ct1, **overrides))
        with pytest.raises(IntegrityError, match="ck_assessment_results"):
            db_session.flush()

    def test_one_result_per_student_and_assessment(self, db_session: Session, cohort, ct1) -> None:
        db_session.add(self._row(cohort[0], ct1))
        db_session.flush()
        db_session.expunge_all()
        db_session.add(self._row(cohort[0], ct1))
        with pytest.raises(IntegrityError, match="pk_assessment_results"):
            db_session.flush()
