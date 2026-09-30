"""Scoped, aggregated analytics for every level of the hierarchy — one implementation.

The same ``overview`` answers "what is happening across the institution" for the
Administrator and "what is happening in my classes" for a faculty member: the *scope* differs
(``visible_offerings`` in ``organization/scope.py``, then the caller's filters), the analytics
do not. Every number comes from ``offering_summaries`` (the engine's output per offering)
pooled by ``aggregate.py``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.modules.attention.models import AttentionFlag
from app.modules.audit.models import AuditLog
from app.modules.imports.models import ImportBatch, ImportStatus
from app.modules.interventions.models import Intervention, InterventionStudent
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseCoordinator,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.organization.scope import (
    coordinated_course_ids,
    visible_offerings,
)
from app.modules.overview import aggregate
from app.modules.overview.aggregate import Item, OfferingMeta
from app.modules.overview.summary import SummaryStore
from app.modules.students.models import Enrollment, EnrollmentStatus, Student
from app.modules.users.models import Role, User

Period = Literal["ODD", "EVEN", "YEAR"]


@dataclass(frozen=True)
class Filters:
    academic_year: str | None = None
    semester: Period | None = None
    term_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    faculty_id: uuid.UUID | None = None
    coordinator_id: uuid.UUID | None = None
    offering_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in self.__dict__.items()}


class InsightsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = SummaryStore(session)

    # ------------------------------------------------------------ period

    def resolve_period(self, filters: Filters) -> tuple[Filters, list[AcademicTerm], str]:
        """Which terms a request covers. Default: the current term. ``YEAR`` = both semesters
        of the academic year (offerings are per term, so nothing is counted twice)."""
        terms = list(self._session.scalars(select(AcademicTerm).order_by(AcademicTerm.start_date)))
        current = next((t for t in terms if t.is_current), terms[-1] if terms else None)
        if filters.offering_id is not None:
            # One class: its own term, whatever period is selected elsewhere.
            term_id = self._session.scalar(
                select(CourseOffering.term_id).where(CourseOffering.id == filters.offering_id)
            )
            chosen = [t for t in terms if t.id == term_id]
            if not chosen:
                raise NotFoundError("Course offering not found.")
            return (
                Filters(
                    **{
                        **filters.__dict__,
                        "academic_year": chosen[0].academic_year,
                        "semester": chosen[0].semester.value if chosen[0].semester else "YEAR",
                    }
                ),
                chosen,
                chosen[0].name,
            )
        if filters.term_id is not None:
            chosen = [t for t in terms if t.id == filters.term_id]
            if not chosen:
                raise NotFoundError("Academic term not found.")
            return filters, chosen, chosen[0].name
        year = filters.academic_year or (current.academic_year if current else None)
        semester = filters.semester or (
            current.semester.value if current and current.semester else "YEAR"
        )
        in_year = [t for t in terms if t.academic_year == year]
        if semester == "YEAR":
            chosen, label = in_year, f"Academic year {year}"
        else:
            chosen = [t for t in in_year if t.semester and t.semester.value == semester]
            label = f"{semester.title()} semester {year}"
        return (
            Filters(**{**filters.__dict__, "academic_year": year, "semester": semester}),
            chosen,
            label,
        )

    # ------------------------------------------------------------ scope

    def items(self, filters: Filters, *, actor: User) -> tuple[list[Item], Filters, str]:
        resolved, terms, period = self.resolve_period(filters)
        metas = self._metas(resolved, [t.id for t in terms], actor)
        summaries = self._store.ensure([uuid.UUID(m.id) for m in metas])
        items = [Item(meta=m, data=summaries[uuid.UUID(m.id)]) for m in metas]
        return items, resolved, period

    def _metas(self, f: Filters, term_ids: list[uuid.UUID], actor: User) -> list[OfferingMeta]:
        query = (
            select(CourseOffering, Course, Section, AcademicTerm, Department)
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .join(AcademicTerm, AcademicTerm.id == CourseOffering.term_id)
            .join(Department, Department.id == Course.department_id)
            .where(visible_offerings(actor), CourseOffering.term_id.in_(term_ids))
        )
        if f.department_id:
            query = query.where(Course.department_id == f.department_id)
        if f.course_id:
            query = query.where(CourseOffering.course_id == f.course_id)
        if f.section_id:
            query = query.where(CourseOffering.section_id == f.section_id)
        if f.offering_id:
            query = query.where(CourseOffering.id == f.offering_id)
        if f.faculty_id:
            query = query.where(
                CourseOffering.id.in_(
                    select(OfferingFaculty.offering_id).where(
                        OfferingFaculty.user_id == f.faculty_id
                    )
                )
            )
        if f.coordinator_id:
            query = query.where(
                CourseOffering.course_id.in_(coordinated_course_ids(f.coordinator_id))
            )
        rows = self._session.execute(
            query.order_by(Course.code, Section.name, AcademicTerm.start_date)
        ).all()
        ids = [row[0].id for row in rows]
        faculty: dict[uuid.UUID, list[tuple[str, str]]] = defaultdict(list)
        for oid, uid, name in self._session.execute(
            select(OfferingFaculty.offering_id, User.id, User.full_name)
            .join(User, User.id == OfferingFaculty.user_id)
            .where(OfferingFaculty.offering_id.in_(ids))
            .order_by(User.full_name)
        ):
            faculty[oid].append((str(uid), name))
        coordinators: dict[uuid.UUID, list[tuple[str, str]]] = defaultdict(list)
        for cid, uid, name in self._session.execute(
            select(CourseCoordinator.course_id, User.id, User.full_name)
            .join(User, User.id == CourseCoordinator.user_id)
            .where(CourseCoordinator.course_id.in_({row[1].id for row in rows}))
            .order_by(User.full_name)
        ):
            coordinators[cid].append((str(uid), name))
        return [
            OfferingMeta(
                id=str(o.id),
                course_id=str(c.id),
                course_code=c.code,
                course_name=c.name,
                course_type=c.course_type.value if c.course_type else None,
                department_id=str(d.id),
                department_code=d.code,
                department_name=d.name,
                section_id=str(s.id),
                section_name=s.name,
                batch_year=s.batch_year,
                term_id=str(t.id),
                term_code=t.code,
                term_name=t.name,
                academic_year=t.academic_year,
                semester=t.semester.value if t.semester else None,
                is_current=t.is_current,
                pass_percent=float(o.pass_percent),
                faculty=tuple(faculty[o.id]),
                coordinators=tuple(coordinators[c.id]),
            )
            for o, c, s, t, d in rows
        ]

    # ------------------------------------------------------------ overview

    def overview(self, filters: Filters, *, actor: User) -> dict[str, Any]:
        items, resolved, period = self.items(filters, actor=actor)
        ids = [uuid.UUID(i.meta.id) for i in items]
        single_course = len({i.meta.course_id for i in items}) == 1
        # Rows of the heat maps: sections within one course, courses otherwise.
        row_key = (
            (lambda i: (i.meta.section_id, i.meta.section_name))
            if single_course
            else (lambda i: (i.meta.course_id, f"{i.meta.course_code} {i.meta.course_name}"))
        )
        comparisons = {
            "courses": aggregate.group(
                items,
                lambda i: [(i.meta.course_id, i.meta.course_code)],
                extra=lambda _, m: {
                    "name": m[0].meta.course_name,
                    "course_type": m[0].meta.course_type,
                    "coordinators": [n for _, n in m[0].meta.coordinators],
                    "faculty": len({f for x in m for f, _ in x.meta.faculty}),
                },
            ),
            "sections": aggregate.group(
                items,
                lambda i: [(i.meta.section_id, i.meta.section_name)],
                extra=lambda _, m: {"batch_year": m[0].meta.batch_year},
            ),
            "faculty": aggregate.group(
                items,
                lambda i: list(i.meta.faculty),
                extra=lambda _, m: {"course_codes": sorted({x.meta.course_code for x in m})},
            ),
            "semesters": aggregate.group(items, lambda i: [(i.meta.term_id, i.meta.term_name)]),
            "departments": aggregate.group(
                items,
                lambda i: [(i.meta.department_id, i.meta.department_code)],
                extra=lambda _, m: {"name": m[0].meta.department_name},
            ),
        }
        return {
            "scope": self._scope_label(resolved, items, actor),
            "period": period,
            "filters": resolved.as_dict(),
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": self._counts(ids, items),
            "kpis": aggregate.pooled_kpis(items),
            "trend": aggregate.assessment_trend(items),
            "course_trends": [
                {
                    "course_id": c["id"],
                    "course_code": c["label"],
                    "points": c["trend"],
                }
                for c in comparisons["courses"]
            ],
            "comparisons": comparisons,
            "heatmap": aggregate.heatmap(items, row_key),
            "attention_matrix": aggregate.attention_matrix(items, row_key),
            "heatmap_rows": "sections" if single_course else "courses",
            "students": aggregate.student_lists(items),
            "activity": self._activity(ids, actor),
        }

    def offerings(self, filters: Filters, *, actor: User) -> dict[str, Any]:
        """Every offering in scope with its headline measures (the section table)."""
        items, resolved, period = self.items(filters, actor=actor)
        rows = []
        for item in items:
            row = aggregate.compact([item])
            m = item.meta
            rows.append(
                {
                    "id": m.id,
                    "course_id": m.course_id,
                    "course_code": m.course_code,
                    "course_name": m.course_name,
                    "section_id": m.section_id,
                    "section_name": m.section_name,
                    "term_code": m.term_code,
                    "term_name": m.term_name,
                    "semester": m.semester,
                    "faculty": [{"id": i, "name": n} for i, n in m.faculty],
                    "coordinators": [{"id": i, "name": n} for i, n in m.coordinators],
                    "published_assessments": item.data["published_assessments"],
                    **row,
                }
            )
        return {"period": period, "filters": resolved.as_dict(), "items": rows, "total": len(rows)}

    def assessment(self, filters: Filters, key: str, *, actor: User) -> dict[str, Any]:
        """One assessment name (e.g. FT-II) across every offering in scope."""
        items, resolved, period = self.items(filters, actor=actor)
        with_it = [i for i in items if any(a["key"] == key for a in i.data["assessments"])]
        if not with_it:
            raise NotFoundError("No assessment with that name in scope.")
        trend = aggregate.assessment_trend(items)
        position = next(index for index, t in enumerate(trend) if t["key"] == key)
        sections = []
        for item in with_it:
            a = next(a for a in item.data["assessments"] if a["key"] == key)
            sections.append(
                {
                    "offering_id": item.meta.id,
                    "assessment_id": a["id"],
                    "label": item.meta.label,
                    "section_name": item.meta.section_name,
                    "faculty": [n for _, n in item.meta.faculty],
                    "mean": a["mean"],
                    "median": a["median"],
                    "pass_percent": a["pass_percent"],
                    "completion_percent": a["completion_percent"],
                    "coverage": a["coverage"],
                    "max_marks": a["max_marks"],
                }
            )
        return {
            "period": period,
            "filters": resolved.as_dict(),
            "assessment": trend[position],
            "previous": trend[position - 1] if position > 0 else None,
            "sections": sorted(sections, key=lambda s: s["label"]),
            "faculty": aggregate.group(
                [
                    Item(
                        meta=i.meta,
                        data={
                            **i.data,
                            "assessments": [a for a in i.data["assessments"] if a["key"] == key],
                        },
                    )
                    for i in with_it
                ],
                lambda i: list(i.meta.faculty),
            ),
        }

    # ------------------------------------------------------------ lists across offerings

    def attention(
        self,
        filters: Filters,
        *,
        actor: User,
        rule: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        items, resolved, period = self.items(filters, actor=actor)
        ids = [uuid.UUID(i.meta.id) for i in items]
        labels = {uuid.UUID(i.meta.id): i.meta for i in items}
        query = (
            select(AttentionFlag, Student)
            .join(Student, Student.id == AttentionFlag.student_id)
            .where(AttentionFlag.offering_id.in_(ids), AttentionFlag.status != "resolved")
        )
        if rule:
            query = query.where(AttentionFlag.rule_code == rule)
        if severity:
            query = query.where(AttentionFlag.severity == severity)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        severity_rank = case(
            (AttentionFlag.severity == "high", 0), (AttentionFlag.severity == "medium", 1), else_=2
        )
        rows = self._session.execute(
            query.order_by(severity_rank, AttentionFlag.rule_code, Student.register_number)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "period": period,
            "filters": resolved.as_dict(),
            "total": total,
            "summary": aggregate.pooled_kpis(items)["rules"],
            "severities": aggregate.pooled_kpis(items)["severities"],
            "items": [
                {
                    "id": str(flag.id),
                    "rule_code": flag.rule_code.value,
                    "severity": flag.severity.value,
                    "status": flag.status.value,
                    "message": flag.message,
                    "actual_value": float(flag.actual_value),
                    "actual_unit": flag.actual_unit.value,
                    "threshold_value": float(flag.threshold_value)
                    if flag.threshold_value is not None
                    else None,
                    "assessments": list(flag.reference_assessments or []),
                    "computed_at": flag.computed_at.isoformat(),
                    "student": {
                        "id": str(student.id),
                        "register_number": student.register_number,
                        "name": student.full_name,
                    },
                    "offering_id": str(flag.offering_id),
                    "offering": labels[flag.offering_id].label,
                    "faculty": [n for _, n in labels[flag.offering_id].faculty],
                }
                for flag, student in rows
            ],
        }

    def interventions(
        self, filters: Filters, *, actor: User, limit: int, offset: int
    ) -> dict[str, Any]:
        items, resolved, period = self.items(filters, actor=actor)
        ids = [uuid.UUID(i.meta.id) for i in items]
        labels = {uuid.UUID(i.meta.id): i.meta for i in items}
        query = select(Intervention).where(Intervention.offering_id.in_(ids))
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            self._session.scalars(
                query.order_by(Intervention.created_at.desc()).limit(limit).offset(offset)
            )
        )
        students = defaultdict(list)
        for iid, sid, reg, name in self._session.execute(
            select(
                InterventionStudent.intervention_id,
                Student.id,
                Student.register_number,
                Student.full_name,
            )
            .join(Student, Student.id == InterventionStudent.student_id)
            .where(InterventionStudent.intervention_id.in_([r.id for r in rows]))
        ):
            students[iid].append({"id": str(sid), "register_number": reg, "name": name})
        recorders = {
            u.id: u.full_name
            for u in self._session.scalars(
                select(User).where(
                    User.id.in_({r.recorded_by_id for r in rows if r.recorded_by_id})
                )
            )
        }
        by_status = dict(
            self._session.execute(
                select(Intervention.status, func.count())
                .where(Intervention.offering_id.in_(ids))
                .group_by(Intervention.status)
            ).all()
        )
        return {
            "period": period,
            "filters": resolved.as_dict(),
            "total": total,
            "by_status": {k.value: v for k, v in by_status.items()},
            "items": [
                {
                    "id": str(r.id),
                    "offering_id": str(r.offering_id),
                    "offering": labels[r.offering_id].label,
                    "kind": r.kind.value,
                    "status": r.status.value,
                    "after_sequence_no": r.after_sequence_no,
                    "recorded_on": r.recorded_on.isoformat() if r.recorded_on else None,
                    "note": r.note,
                    "students": students[r.id],
                    "recorded_by": recorders.get(r.recorded_by_id),
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------ helpers

    def _counts(self, ids: list[uuid.UUID], items: list[Item]) -> dict[str, int]:
        students = self._session.scalar(
            select(func.count(distinct(Enrollment.student_id))).where(
                Enrollment.offering_id.in_(ids), Enrollment.status == EnrollmentStatus.ACTIVE
            )
        )
        faculty = self._session.scalar(
            select(func.count(distinct(OfferingFaculty.user_id))).where(
                OfferingFaculty.offering_id.in_(ids)
            )
        )
        course_ids = {uuid.UUID(i.meta.course_id) for i in items}
        coordinators = self._session.scalar(
            select(func.count(distinct(CourseCoordinator.user_id))).where(
                CourseCoordinator.course_id.in_(course_ids)
            )
        )
        return {
            "departments": len({i.meta.department_id for i in items}),
            "courses": len(course_ids),
            "sections": len({i.meta.section_id for i in items}),
            "offerings": len(items),
            "students": students or 0,
            "faculty": faculty or 0,
            "coordinators": coordinators or 0,
            "assessments": sum(i.data["published_assessments"] for i in items),
        }

    def _activity(self, ids: list[uuid.UUID], actor: User) -> dict[str, Any]:
        imports = self._session.execute(
            select(ImportBatch, User.full_name)
            .outerjoin(User, User.id == ImportBatch.uploaded_by_id)
            .where(ImportBatch.offering_id.in_(ids))
            .order_by(ImportBatch.created_at.desc())
            .limit(8)
        ).all()
        offering_labels = {
            o.id: f"{c.code} · {s.name}"
            for o, c, s in self._session.execute(
                select(CourseOffering, Course, Section)
                .join(Course, Course.id == CourseOffering.course_id)
                .join(Section, Section.id == CourseOffering.section_id)
                .where(CourseOffering.id.in_({b.offering_id for b, _ in imports}))
            )
        }
        import_counts = dict(
            self._session.execute(
                select(ImportBatch.status, func.count())
                .where(ImportBatch.offering_id.in_(ids))
                .group_by(ImportBatch.status)
            ).all()
        )
        interventions = self._session.scalar(
            select(func.count()).where(Intervention.offering_id.in_(ids))
        )
        audit = []
        if actor.role in (Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD):
            audit_query = select(AuditLog, User.full_name).outerjoin(
                User, User.id == AuditLog.actor_id
            )
            if actor.role is not Role.ADMIN:
                audit_query = audit_query.where(AuditLog.offering_id.in_(ids))
            audit = [
                {
                    "action": log.action,
                    "entity": log.entity,
                    "actor": name,
                    "at": log.created_at.isoformat(),
                }
                for log, name in self._session.execute(
                    audit_query.order_by(AuditLog.created_at.desc()).limit(8)
                ).all()
            ]
        return {
            "imports": [
                {
                    "id": str(b.id),
                    "file_name": b.file_name,
                    "status": b.status.value,
                    "offering": offering_labels.get(b.offering_id),
                    "offering_id": str(b.offering_id),
                    "by": name,
                    "at": (b.committed_at or b.created_at).isoformat(),
                    "created": (b.summary or {}).get("created"),
                    "updated": (b.summary or {}).get("updated"),
                }
                for b, name in imports
            ],
            "import_counts": {k.value: v for k, v in import_counts.items()},
            "confirmed_imports": import_counts.get(ImportStatus.COMMITTED, 0),
            "interventions": interventions or 0,
            "audit": audit,
        }

    def _scope_label(self, f: Filters, items: list[Item], actor: User) -> dict[str, Any]:
        """What the page is looking at, for headers and breadcrumbs."""
        crumbs = []
        if f.department_id and items:
            crumbs.append(
                {
                    "kind": "department",
                    "id": str(f.department_id),
                    "label": items[0].meta.department_code,
                }
            )
        if f.course_id and items:
            crumbs.append(
                {
                    "kind": "course",
                    "id": str(f.course_id),
                    "label": f"{items[0].meta.course_code} {items[0].meta.course_name}",
                }
            )
        if f.coordinator_id:
            user = self._session.get(User, f.coordinator_id)
            crumbs.append(
                {
                    "kind": "coordinator",
                    "id": str(f.coordinator_id),
                    "label": user.full_name if user else "Coordinator",
                }
            )
        if f.faculty_id:
            user = self._session.get(User, f.faculty_id)
            crumbs.append(
                {
                    "kind": "faculty",
                    "id": str(f.faculty_id),
                    "label": user.full_name if user else "Faculty",
                }
            )
        if f.section_id:
            section = self._session.get(Section, f.section_id)
            crumbs.append(
                {
                    "kind": "section",
                    "id": str(f.section_id),
                    "label": f"Section {section.name}" if section else "Section",
                }
            )
        if f.offering_id and items:
            crumbs.append(
                {"kind": "offering", "id": str(f.offering_id), "label": items[0].meta.label}
            )
        role_scope = {
            Role.ADMIN: "Institution",
            Role.HOD: "Department",
            Role.ACADEMIC_HEAD: "Academic portfolio",
            Role.COURSE_COORDINATOR: "My courses",
            Role.FACULTY: "My classes",
        }[actor.role]
        return {"root": role_scope, "crumbs": crumbs}


def filters_from(**values: Any) -> Filters:
    semester = values.get("semester")
    if semester and semester not in ("ODD", "EVEN", "YEAR"):
        raise BusinessRuleError("semester must be ODD, EVEN or YEAR.")
    return Filters(**values)
