"""Intervention persistence over the API: authorisation, validation and the reason trail.

Scope comes from the platform (``OfferingAccess``), so an offering the caller cannot view is a
404 and its existence is never disclosed. A target who is not enrolled here is a 422: the
offering was found, the request is simply wrong about who is in it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.analytics.core.rules import AttentionRuleCode, FlagStatus
from app.modules.attention.models import AttentionFlag
from app.modules.interventions.models import Intervention, InterventionStudent
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.users.models import Role, User
from tests.conftest import (
    AssessmentFactory,
    OrgFactory,
    StudentFactory,
    UserFactory,
    auth_headers,
)

LOW_SCORE = "10"
HIGH_SCORE = "45"


class Setup:
    def __init__(
        self, offering: CourseOffering, struggling: uuid.UUID, thriving: uuid.UUID
    ) -> None:
        self.offering = offering
        self.struggling = struggling
        self.thriving = thriving

    @property
    def url(self) -> str:
        return f"/api/v1/offerings/{self.offering.id}/interventions"


@pytest.fixture
def setup(
    client: TestClient,
    db_session: Session,
    cse_offering: CourseOffering,
    cse: Department,
    faculty: User,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
) -> Setup:
    """An offering with results recorded, so real attention flags exist to cite as reasons."""
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    struggling = make_student(cse, section, enroll_in=[cse_offering])
    thriving = make_student(cse, section, enroll_in=[cse_offering])
    assessment = make_assessment(cse_offering, "CT1", max_marks="50")
    response = client.put(
        f"/api/v1/assessments/{assessment.id}/results",
        json={
            "results": [
                {"student_id": str(struggling.id), "score": LOW_SCORE},
                {"student_id": str(thriving.id), "score": HIGH_SCORE},
            ]
        },
        headers=auth_headers(faculty),
    )
    assert response.status_code == 200, response.text
    return Setup(cse_offering, struggling.id, thriving.id)


def live_flag(session: Session, student_id: uuid.UUID, rule: AttentionRuleCode) -> AttentionFlag:
    flag = session.scalar(
        select(AttentionFlag).where(
            AttentionFlag.student_id == student_id,
            AttentionFlag.rule_code == rule,
            AttentionFlag.status != FlagStatus.RESOLVED,
        )
    )
    assert flag is not None, f"expected a live {rule.value} flag for the fixture student"
    return flag


def body(setup: Setup, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "student_ids": [str(setup.struggling)],
        "kind": "remedial_session",
        "after_sequence_no": 1,
        "note": "Ran an extra tutorial on the first two units.",
    }
    payload.update(overrides)
    return payload


class TestCreate:
    def test_faculty_of_the_offering_can_record_one(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(setup.url, json=body(setup), headers=auth_headers(faculty))
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["student_ids"] == [str(setup.struggling)]
        assert created["kind"] == "remedial_session"
        assert created["status"] == "completed", "the default: a recorded action has happened"
        assert created["recorded_by_id"] == str(faculty.id)
        assert created["after_sequence_no"] == 1

    def test_it_is_persisted_with_its_targets(
        self, client: TestClient, db_session: Session, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url,
            json=body(setup, student_ids=[str(setup.struggling), str(setup.thriving)]),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 201, response.text
        stored = db_session.scalars(select(Intervention)).all()
        assert len(stored) == 1
        targets = db_session.scalars(
            select(InterventionStudent.student_id).where(
                InterventionStudent.intervention_id == stored[0].id
            )
        ).all()
        assert set(targets) == {setup.struggling, setup.thriving}

    def test_admin_and_hod_may_record_one(
        self, client: TestClient, setup: Setup, admin: User, hod: User
    ) -> None:
        for actor in (admin, hod):
            response = client.post(setup.url, json=body(setup), headers=auth_headers(actor))
            assert response.status_code == 201, f"{actor.role}: {response.text}"


class TestReasonTrail:
    def test_a_reason_freezes_the_flag_it_names(
        self, client: TestClient, db_session: Session, setup: Setup, faculty: User
    ) -> None:
        flag = live_flag(db_session, setup.struggling, AttentionRuleCode.R1_LOW_PERFORMANCE)
        response = client.post(
            setup.url,
            json=body(
                setup,
                note=None,
                reasons=[{"student_id": str(setup.struggling), "flag_id": str(flag.id)}],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 201, response.text

        reason = response.json()["reasons"][0]
        assert reason["rule_code"] == AttentionRuleCode.R1_LOW_PERFORMANCE.value
        assert reason["source_flag_id"] == str(flag.id)
        assert reason["observed"]["value"] == pytest.approx(float(flag.actual_value), abs=0.01)
        assert reason["observed"]["status"] == "ok"
        assert reason["threshold"]["value"] == pytest.approx(float(flag.threshold_value), abs=0.01)
        assert reason["note"] == flag.message, "the flag's sentence, so the reason reads as one"

    def test_the_frozen_value_survives_the_flag_being_resolved(
        self, client: TestClient, db_session: Session, setup: Setup, faculty: User
    ) -> None:
        """Recomputing later must not rewrite what the teacher saw when they acted."""
        flag = live_flag(db_session, setup.struggling, AttentionRuleCode.R1_LOW_PERFORMANCE)
        observed_then = float(flag.actual_value)
        response = client.post(
            setup.url,
            json=body(
                setup,
                note=None,
                reasons=[{"student_id": str(setup.struggling), "flag_id": str(flag.id)}],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 201, response.text

        # Read the timestamp first: the create() above committed, so the instance is expired and
        # touching a column now would autoflush a half-resolved row -- which the
        # ck_attention_flags_resolved_at_matches_status constraint rightly refuses.
        stamp = flag.computed_at
        flag.status = FlagStatus.RESOLVED
        flag.resolved_at = stamp
        db_session.flush()

        listed = client.get(setup.url, headers=auth_headers(faculty))
        assert listed.status_code == 200, listed.text
        reason = listed.json()["items"][0]["reasons"][0]
        assert reason["observed"]["value"] == pytest.approx(observed_then, abs=0.01)
        assert reason["rule_code"] == AttentionRuleCode.R1_LOW_PERFORMANCE.value

    def test_a_rule_code_cannot_be_asserted_directly(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        """An analytics reason must trace to a rule that actually fired, not to a claim."""
        response = client.post(
            setup.url,
            json=body(
                setup,
                reasons=[
                    {
                        "student_id": str(setup.struggling),
                        "rule_code": "R1_LOW_PERFORMANCE",
                        "note": "made it up",
                    }
                ],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text

    def test_a_flag_belonging_to_another_student_is_refused(
        self, client: TestClient, db_session: Session, setup: Setup, faculty: User
    ) -> None:
        flag = live_flag(db_session, setup.struggling, AttentionRuleCode.R1_LOW_PERFORMANCE)
        response = client.post(
            setup.url,
            json=body(
                setup,
                student_ids=[str(setup.thriving)],
                note=None,
                reasons=[{"student_id": str(setup.thriving), "flag_id": str(flag.id)}],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text
        assert "flag" in response.json()["error"]["message"].lower()

    def test_an_unknown_flag_is_refused(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url,
            json=body(
                setup,
                note=None,
                reasons=[{"student_id": str(setup.struggling), "flag_id": str(uuid.uuid4())}],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text

    def test_a_finding_reason_needs_no_flag(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url,
            json=body(
                setup,
                note=None,
                reasons=[{"student_id": str(setup.struggling), "finding": "repeated_low"}],
            ),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 201, response.text
        assert response.json()["reasons"][0]["finding"] == "repeated_low"


class TestValidation:
    def test_targets_may_not_be_empty(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url, json=body(setup, student_ids=[]), headers=auth_headers(faculty)
        )
        assert response.status_code == 422, response.text

    def test_a_target_may_not_be_listed_twice(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url,
            json=body(setup, student_ids=[str(setup.struggling), str(setup.struggling)]),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text

    def test_a_student_outside_the_offering_is_refused(
        self,
        client: TestClient,
        setup: Setup,
        cse: Department,
        make_student: StudentFactory,
        faculty: User,
    ) -> None:
        outsider = make_student(cse)
        response = client.post(
            setup.url,
            json=body(setup, student_ids=[str(outsider.id)]),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text
        assert "not active enrolments" in response.json()["error"]["message"]

    def test_an_intervention_must_say_why(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url, json=body(setup, note=None), headers=auth_headers(faculty)
        )
        assert response.status_code == 422, response.text

    def test_a_reason_may_not_name_a_student_who_is_not_a_target(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url,
            json=body(setup, reasons=[{"student_id": str(setup.thriving), "note": "not a target"}]),
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text

    def test_an_unknown_kind_is_refused(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url, json=body(setup, kind="mind_reading"), headers=auth_headers(faculty)
        )
        assert response.status_code == 422, response.text

    def test_a_negative_boundary_is_refused(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.post(
            setup.url, json=body(setup, after_sequence_no=-1), headers=auth_headers(faculty)
        )
        assert response.status_code == 422, response.text

    def test_a_boundary_of_zero_is_allowed(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        """Nothing had been sat yet: a legitimate window, not a missing value."""
        response = client.post(
            setup.url, json=body(setup, after_sequence_no=0), headers=auth_headers(faculty)
        )
        assert response.status_code == 201, response.text


class TestAuthorisation:
    def test_an_unauthenticated_request_is_rejected(self, client: TestClient, setup: Setup) -> None:
        assert client.get(setup.url).status_code == 401
        assert client.post(setup.url, json=body(setup)).status_code == 401

    def test_faculty_outside_the_offering_get_404_not_403(
        self, client: TestClient, setup: Setup, make_user: UserFactory
    ) -> None:
        """Existence is not disclosed: out of scope reads exactly like does not exist."""
        stranger = make_user(Role.FACULTY, email="stranger@srmist.edu.in")
        assert client.get(setup.url, headers=auth_headers(stranger)).status_code == 404
        posted = client.post(setup.url, json=body(setup), headers=auth_headers(stranger))
        assert posted.status_code == 404

    def test_an_hod_of_another_department_gets_404(
        self,
        client: TestClient,
        setup: Setup,
        make_user: UserFactory,
        ece: Department,
    ) -> None:
        other_hod = make_user(Role.HOD, email="hod.ece@srmist.edu.in", department=ece)
        assert client.get(setup.url, headers=auth_headers(other_hod)).status_code == 404

    def test_a_nonexistent_offering_is_404(self, client: TestClient, faculty: User) -> None:
        url = f"/api/v1/offerings/{uuid.uuid4()}/interventions"
        assert client.get(url, headers=auth_headers(faculty)).status_code == 404

    def test_faculty_cannot_record_into_another_offering(
        self,
        client: TestClient,
        setup: Setup,
        org: OrgFactory,
        cse: Department,
        term,
        make_user: UserFactory,
        make_student: StudentFactory,
    ) -> None:
        stranger = make_user(Role.FACULTY, email="other.faculty@srmist.edu.in")
        theirs = org.offering(org.course(cse), org.section(cse), term, faculty=[stranger])
        their_student = make_student(cse, enroll_in=[theirs])
        response = client.post(
            setup.url,
            json=body(setup, student_ids=[str(their_student.id)]),
            headers=auth_headers(stranger),
        )
        assert response.status_code == 404, "the offering, not the student, decides visibility"


class TestReads:
    def test_listing_is_paged_and_scoped_to_the_offering(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        for _ in range(3):
            assert (
                client.post(setup.url, json=body(setup), headers=auth_headers(faculty)).status_code
                == 201
            )
        response = client.get(setup.url, params={"limit": 2}, headers=auth_headers(faculty))
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2
        assert all(item["offering_id"] == str(setup.offering.id) for item in page["items"])

    def test_a_student_listing_shows_only_their_own(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        assert (
            client.post(setup.url, json=body(setup), headers=auth_headers(faculty)).status_code
            == 201
        )
        assert (
            client.post(
                setup.url,
                json=body(setup, student_ids=[str(setup.thriving)]),
                headers=auth_headers(faculty),
            ).status_code
            == 201
        )

        response = client.get(
            f"/api/v1/offerings/{setup.offering.id}/students/{setup.struggling}/interventions",
            headers=auth_headers(faculty),
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 1
        assert page["items"][0]["student_ids"] == [str(setup.struggling)]

    def test_a_student_outside_the_offering_is_refused_on_read(
        self,
        client: TestClient,
        setup: Setup,
        cse: Department,
        make_student: StudentFactory,
        faculty: User,
    ) -> None:
        outsider = make_student(cse)
        response = client.get(
            f"/api/v1/offerings/{setup.offering.id}/students/{outsider.id}/interventions",
            headers=auth_headers(faculty),
        )
        assert response.status_code == 422, response.text

    def test_a_status_filter_narrows_the_listing(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        assert (
            client.post(
                setup.url, json=body(setup, status="planned"), headers=auth_headers(faculty)
            ).status_code
            == 201
        )
        assert (
            client.post(setup.url, json=body(setup), headers=auth_headers(faculty)).status_code
            == 201
        )
        response = client.get(
            setup.url, params={"intervention_status": "planned"}, headers=auth_headers(faculty)
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1


class TestOutcomes:
    def test_outcomes_are_measured_from_stored_interventions(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        assert (
            client.post(
                setup.url, json=body(setup, after_sequence_no=0), headers=auth_headers(faculty)
            ).status_code
            == 201
        )
        response = client.get(f"{setup.url}/outcomes", headers=auth_headers(faculty))
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["outcomes"]) == 1
        assert payload["outcomes"][0]["offering_id"] == str(setup.offering.id)

    def test_an_offering_with_none_recorded_is_an_empty_answer_not_an_error(
        self, client: TestClient, setup: Setup, faculty: User
    ) -> None:
        response = client.get(f"{setup.url}/outcomes", headers=auth_headers(faculty))
        assert response.status_code == 200, response.text
        assert response.json()["outcomes"] == []

    def test_outcomes_are_out_of_scope_for_a_stranger(
        self, client: TestClient, setup: Setup, make_user: UserFactory
    ) -> None:
        stranger = make_user(Role.FACULTY, email="nosy@srmist.edu.in")
        response = client.get(f"{setup.url}/outcomes", headers=auth_headers(stranger))
        assert response.status_code == 404


class TestNoFlagFabrication:
    def test_there_is_no_endpoint_that_creates_an_attention_flag(self, client: TestClient) -> None:
        """Flags are materialised state owned by the recompute hook, never client-created."""
        spec = client.get("/openapi.json").json()
        writable = {
            path
            for path, ops in spec["paths"].items()
            if "attention" in path and {"post", "put", "patch", "delete"} & set(ops)
        }
        assert writable == set(), f"attention must not be writable over HTTP: {writable}"
