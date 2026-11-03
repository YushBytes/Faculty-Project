"""Database-level guarantees for the academic structure."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.db.repository import write_guard
from app.modules.organization.models import AcademicTerm, CourseOffering, Department
from tests.conftest import OrgFactory


def _term(code: str, *, current: bool = False, start=date(2026, 7, 1), end=date(2026, 12, 1)):
    return AcademicTerm(
        code=code,
        name=code,
        academic_year="2026-27",
        start_date=start,
        end_date=end,
        is_current=current,
    )


def test_single_current_term_enforced(db_session: Session) -> None:
    db_session.add_all([_term("T1", current=True), _term("T2", current=True)])
    with pytest.raises(IntegrityError, match="uq_academic_terms_single_current"):
        db_session.flush()


def test_many_non_current_terms_allowed(db_session: Session) -> None:
    db_session.add_all([_term("T1"), _term("T2"), _term("T3")])
    db_session.flush()


def test_term_dates_ordered(db_session: Session) -> None:
    db_session.add(_term("T1", start=date(2026, 7, 1), end=date(2026, 7, 1)))
    with pytest.raises(IntegrityError, match="ck_academic_terms_dates_ordered"):
        db_session.flush()


def test_pass_percent_range(db_session: Session, org: OrgFactory, cse: Department, term) -> None:
    offering = CourseOffering(
        course_id=org.course(cse).id,
        section_id=org.section(cse).id,
        term_id=term.id,
        pass_percent=Decimal("100.5"),
    )
    db_session.add(offering)
    with pytest.raises(IntegrityError, match="ck_course_offerings_pass_percent_range"):
        db_session.flush()


def test_lowercase_codes_rejected_by_database(db_session: Session) -> None:
    db_session.add(Department(code="cse", name="x"))
    with pytest.raises(IntegrityError, match="ck_departments_code_upper"):
        db_session.flush()


class TestWriteGuard:
    def test_conflict_is_translated_and_session_stays_usable(
        self, db_session: Session, cse: Department
    ) -> None:
        with (
            pytest.raises(ConflictError, match="exists"),
            write_guard(db_session, conflict="CSE exists"),
        ):
            db_session.add(Department(code="CSE", name="dup"))

        # The failed insert is discarded; the session keeps working.
        codes = db_session.scalars(select(Department.code)).all()
        assert codes == ["CSE"]

    def test_check_violation_is_business_rule(self, db_session: Session) -> None:
        with pytest.raises(BusinessRuleError), write_guard(db_session):
            db_session.add(_term("BAD", start=date(2026, 7, 2), end=date(2026, 7, 1)))

    def test_delete_in_use_restored(
        self, db_session: Session, cse: Department, org: OrgFactory
    ) -> None:
        org.course(cse)
        with pytest.raises(ConflictError), write_guard(db_session, in_use="in use"):
            db_session.delete(cse)
        assert db_session.get(Department, cse.id) is not None
