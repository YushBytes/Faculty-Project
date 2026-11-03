"""One offering's analytics, computed by the engine and materialised for aggregation.

``compute_summary`` runs the same engine functions the offering dashboard runs
(``cohort_profiles``, ``cohort_segments``, ``cohort_attention``, ``assessment_analytics`` and
the class statistics ``mean_percent`` / ``median_percent`` / ``pass_percent`` /
``completion_percent`` over the weighted course scores, exactly as ``class_health`` does) and
keeps the results — including each student's course score and each assessment's
percentages — so higher levels can pool them without recomputing anything a different way.

``SummaryStore`` keeps ``offering_summaries`` current. A row's ``fingerprint`` hashes
everything its numbers depend on (results, assessments, enrolments, the students' active
flags, the offering's pass mark and thresholds, department settings); a read that finds it
out of date recomputes first, and the C4 recompute hook refreshes it inside the write
transaction that changed the results.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.analytics.core.attention import (
    cohort_attention,
    students_requiring_attention,
)
from app.modules.analytics.core.class_health import cohort_course_scores, matrix_coverage
from app.modules.analytics.core.contracts import OfferingSnapshot
from app.modules.analytics.core.policy import assessed_percentages
from app.modules.analytics.core.profile import cohort_profiles
from app.modules.analytics.core.results import Measure
from app.modules.analytics.core.segmentation import cohort_segments
from app.modules.analytics.core.statistics import (
    assessment_analytics,
    completion_percent,
    mean_percent,
    median_percent,
    pass_percent,
    std_dev_percentage_points,
)
from app.modules.analytics.core.thresholds import ThresholdSet
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.assessments.models import Assessment, AssessmentResult
from app.modules.imports.validation import match_key
from app.modules.organization.models import Course, CourseOffering, DepartmentSetting
from app.modules.overview.models import OfferingSummary
from app.modules.students.models import Enrollment, EnrollmentStatus, Student

SUMMARY_VERSION = 3


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _measure(m: Measure | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "value": _num(m.value),
        "status": m.status.value,
        "n": m.n,
        "reason": m.reason if not m.is_ok else None,
    }


def compute_summary(
    snapshot: OfferingSnapshot, thresholds: ThresholdSet, *, stamp: datetime | None = None
) -> dict[str, Any]:
    """The engine's verdict on one offering, as JSON-safe data. Pure: no session."""
    stamp = stamp or datetime.now(UTC)
    profiles = cohort_profiles(snapshot, thresholds, generated_at=stamp)
    segments = cohort_segments(snapshot, thresholds, profiles=profiles, generated_at=stamp)
    attentions = cohort_attention(snapshot, thresholds, generated_at=stamp)
    scored = cohort_course_scores(profiles)
    scores = [score for _, score in scored]
    coverage = matrix_coverage(snapshot)
    pass_mark = snapshot.pass_mark_percent

    segment_of = {s.student.id: s for s in segments}
    flags_of = {a.student.id: a for a in attentions}
    students = []
    for profile in profiles:
        sid = profile.student.id
        wcs = profile.history.weighted_course_score
        seg = segment_of.get(sid)
        att = flags_of.get(sid)
        latest = profile.history.latest
        students.append(
            {
                "id": str(sid),
                "register_number": profile.student.register_no,
                "name": profile.student.name,
                "score": _num(wcs.value) if wcs.is_ok else None,
                "segment": seg.primary.value if seg and seg.primary.is_ok else None,
                "trend": (
                    profile.history.trend.label.value if profile.history.trend.label.is_ok else None
                ),
                "completion": _num(profile.history.completion_percent.value),
                "latest": _num(latest.percentage.value)
                if latest and latest.percentage.is_ok
                else None,
                "points": [
                    {"code": p.assessment_code, "seq": p.sequence_no, "pct": _num(p.percentage)}
                    for p in profile.history.points
                    if p.percentage is not None
                ],
                "flags": [f.rule_code.value for f in att.flags] if att else [],
                "severities": [f.severity.value for f in att.flags] if att else [],
            }
        )

    assessments = []
    for assessment in snapshot.ordered_assessments(published_only=True):
        analytics = assessment_analytics(snapshot, assessment, generated_at=stamp)
        pcts = assessed_percentages(snapshot, assessment)
        cov = analytics.coverage
        assessments.append(
            {
                "id": str(assessment.id),
                "name": assessment.code,
                "key": match_key(assessment.code),
                "sequence_no": assessment.sequence_no,
                "max_marks": _num(assessment.max_marks),
                "weightage": _num(assessment.weightage),
                "held_on": assessment.held_on.isoformat() if assessment.held_on else None,
                "mean": _measure(analytics.mean),
                "median": _measure(analytics.median),
                "std_dev": _measure(analytics.std_dev),
                "pass_percent": _measure(analytics.pass_percent),
                "completion_percent": _measure(analytics.completion_percent),
                "coverage": {
                    "assessed": cov.assessed,
                    "absent": cov.absent,
                    "exempt": cov.exempt,
                    "missing": cov.missing,
                },
                "percentages": [_num(p) for p in pcts],
                "passed": sum(1 for p in pcts if p >= pass_mark),
            }
        )

    rule_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    for entry in attentions:
        for flag in entry.flags:
            rule_counter[flag.rule_code.value] += 1
            severity_counter[flag.severity.value] += 1

    return {
        "version": SUMMARY_VERSION,
        "computed_at": stamp.isoformat(),
        "pass_mark": _num(pass_mark),
        "cohort_n": len(snapshot.active_students()),
        "published_assessments": len(assessments),
        "class_mean": _measure(mean_percent(scores)),
        "median": _measure(median_percent(scores)),
        "std_dev": _measure(std_dev_percentage_points(scores)),
        "pass_percent": _measure(pass_percent(scores, pass_mark)),
        "completion_percent": _measure(completion_percent(coverage)),
        "coverage": {
            "assessed": coverage.assessed,
            "absent": coverage.absent,
            "exempt": coverage.exempt,
            "missing": coverage.missing,
        },
        "scored": len(scores),
        "passed": sum(1 for s in scores if s >= pass_mark),
        "students_requiring_attention": len(students_requiring_attention(attentions)),
        "flagged_students": sum(1 for a in attentions if a.flags),
        "rules": dict(rule_counter),
        "severities": dict(severity_counter),
        "segments": dict(Counter(s["segment"] for s in students if s["segment"])),
        "trends": dict(Counter(s["trend"] for s in students if s["trend"])),
        "students": students,
        "assessments": assessments,
    }


# ------------------------------------------------------------------ store


def _max_text(column) -> Any:
    return func.coalesce(cast(func.max(column), String), literal(""))


class SummaryStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def fingerprints(self, offering_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """A hash of everything an offering's numbers depend on, for many offerings at once."""
        if not offering_ids:
            return {}
        ids = list(offering_ids)
        results = dict(
            self._session.execute(
                select(
                    Assessment.offering_id,
                    func.count(AssessmentResult.student_id).cast(String)
                    + ":"
                    + _max_text(AssessmentResult.updated_at),
                )
                .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.id)
                .where(Assessment.offering_id.in_(ids))
                .group_by(Assessment.offering_id)
            ).all()
        )
        assessments = dict(
            self._session.execute(
                select(
                    Assessment.offering_id,
                    func.count().cast(String) + ":" + _max_text(Assessment.updated_at),
                )
                .where(Assessment.offering_id.in_(ids))
                .group_by(Assessment.offering_id)
            ).all()
        )
        enrolments = dict(
            self._session.execute(
                select(
                    Enrollment.offering_id,
                    func.count().cast(String)
                    + ":"
                    + func.count().filter(Enrollment.status == EnrollmentStatus.ACTIVE).cast(String)
                    + ":"
                    + _max_text(Enrollment.enrolled_at)
                    + ":"
                    + _max_text(Enrollment.dropped_at)
                    + ":"
                    + _max_text(Student.updated_at),
                )
                .join(Student, Student.id == Enrollment.student_id)
                .where(Enrollment.offering_id.in_(ids))
                .group_by(Enrollment.offering_id)
            ).all()
        )
        offerings = {
            row[0]: row[1:]
            for row in self._session.execute(
                select(
                    CourseOffering.id,
                    CourseOffering.updated_at,
                    Course.department_id,
                )
                .join(Course, Course.id == CourseOffering.course_id)
                .where(CourseOffering.id.in_(ids))
            ).all()
        }
        settings = dict(
            self._session.execute(
                select(
                    DepartmentSetting.department_id, _max_text(DepartmentSetting.updated_at)
                ).group_by(DepartmentSetting.department_id)
            ).all()
        )
        out = {}
        for oid in ids:
            updated, department = offerings.get(oid, (None, None))
            parts = (
                str(SUMMARY_VERSION),
                str(updated),
                results.get(oid, ""),
                assessments.get(oid, ""),
                enrolments.get(oid, ""),
                settings.get(department, ""),
            )
            out[oid] = hashlib.sha256("|".join(parts).encode()).hexdigest()
        return out

    def refresh(self, offering_id: uuid.UUID, *, fingerprint: str | None = None) -> dict:
        """Recompute one offering and upsert its row. Does not commit."""
        loaded = AnalyticsRepository(self._session).context_for_offering(offering_id, actor=None)
        data = compute_summary(loaded.snapshot, loaded.thresholds)
        if fingerprint is None:
            self._session.flush()
            fingerprint = self.fingerprints([offering_id])[offering_id]
        statement = insert(OfferingSummary).values(
            offering_id=offering_id, fingerprint=fingerprint, data=data, computed_at=func.now()
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[OfferingSummary.offering_id],
                set_={"fingerprint": fingerprint, "data": data, "computed_at": func.now()},
            )
        )
        return data

    def ensure(
        self, offering_ids: list[uuid.UUID], *, commit: bool = True
    ) -> dict[uuid.UUID, dict]:
        """Current summaries for these offerings, recomputing any that are out of date."""
        if not offering_ids:
            return {}
        wanted = self.fingerprints(offering_ids)
        stored = {
            row.offering_id: row
            for row in self._session.scalars(
                select(OfferingSummary).where(OfferingSummary.offering_id.in_(offering_ids))
            )
        }
        out: dict[uuid.UUID, dict] = {}
        stale = False
        for oid in offering_ids:
            row = stored.get(oid)
            if row is not None and row.fingerprint == wanted[oid]:
                out[oid] = row.data
            else:
                out[oid] = self.refresh(oid, fingerprint=wanted[oid])
                stale = True
        if stale and commit:
            self._session.commit()
        return out
