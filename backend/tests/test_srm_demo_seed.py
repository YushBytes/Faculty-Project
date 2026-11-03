"""The SRM demo institution: deterministic, the full hierarchy, real pipeline history."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.demo.srm import seed_srm
from app.modules.imports.models import ImportBatch, ImportStatus
from app.modules.interventions.models import Intervention
from app.modules.organization.models import CourseCoordinator, Section
from app.modules.overview.models import OfferingSummary
from app.modules.users.models import Role, User


def test_small_srm_institution(db_session: Session) -> None:
    report = seed_srm(
        db_session,
        password="Demo@2026pass",
        sections=8,
        write_demo_files=False,
        progress=lambda *_: None,
    )
    roles = {
        role: db_session.scalar(select(func.count()).select_from(User).where(User.role == role))
        for role in Role
    }
    assert roles[Role.ADMIN] == roles[Role.HOD] == roles[Role.ACADEMIC_HEAD] == 1
    assert roles[Role.COURSE_COORDINATOR] == 6
    assert db_session.scalar(select(func.count()).select_from(CourseCoordinator)) == 6
    assert db_session.scalar(select(func.count()).select_from(Section)) == 8
    # Every class has its engine summary; DSA FJ-II arrived through real TLP imports.
    assert (
        db_session.scalar(select(func.count()).select_from(OfferingSummary))
        == report.offerings
        == 48
    )
    committed = db_session.scalars(
        select(ImportBatch).where(ImportBatch.status == ImportStatus.COMMITTED)
    ).all()
    assert len(committed) == report.imports == 8
    assert all(b.source_metadata["test_name"] == "FJ-II" for b in committed)
    assert db_session.scalar(select(func.count()).select_from(Intervention)) == report.interventions
    assert all(email.endswith("@acadlytics.dev") for email in report.accounts)
