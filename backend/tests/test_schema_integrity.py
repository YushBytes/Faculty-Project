"""Schema integrity, read from the live migrated database rather than from the models.

`tests/test_migrations.py` already proves the chain has a single head, survives a full
down/up round trip, and matches the models. What is checked here is the part a model-to-metadata
comparison cannot see: that the constraints the design *relies on for correctness* are actually
present in PostgreSQL, with the delete rules and enum labels intended.

If any of these fails, the Python layer is the only thing standing between a bug and corrupt data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.analytics.core.results import Unit
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity, FlagStatus
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSource
from app.modules.analytics.core.vocabulary import (
    InterventionKind,
    InterventionStatus,
    StudentFindingCode,
)
from app.modules.attention.models import AttentionFlag
from app.modules.interventions.models import (
    Intervention,
    InterventionReason,
    InterventionStudent,
)
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.students.models import Student
from tests.conftest import StudentFactory

PHASE_10_TABLES = (
    "attention_flags",
    "interventions",
    "intervention_students",
    "intervention_reasons",
)

# Every enum type the schema declares, paired with the Python enum that is its source of truth.
ENUM_TYPES = {
    "attention_rule_code": AttentionRuleCode,
    "flag_severity": FlagSeverity,
    "flag_status": FlagStatus,
    "measure_unit": Unit,
    "threshold_key": ThresholdKey,
    "threshold_source": ThresholdSource,
    "intervention_kind": InterventionKind,
    "intervention_status": InterventionStatus,
    "student_finding_code": StudentFindingCode,
}


def fk_map(session: Session, table: str) -> dict[str, dict]:
    """``constrained column -> foreign key definition`` for one table."""
    return {
        ",".join(fk["constrained_columns"]): fk
        for fk in inspect(session.get_bind()).get_foreign_keys(table)
    }


class TestTablesAndKeys:
    def test_every_phase_10_table_exists(self, db_session: Session) -> None:
        tables = set(inspect(db_session.get_bind()).get_table_names())
        assert set(PHASE_10_TABLES) <= tables, f"missing: {set(PHASE_10_TABLES) - tables}"

    def test_primary_keys_are_what_the_design_relies_on(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        assert inspector.get_pk_constraint("attention_flags")["constrained_columns"] == ["id"]
        assert inspector.get_pk_constraint("interventions")["constrained_columns"] == ["id"]
        # The composite key *is* the "a student cannot be targeted twice" rule.
        assert sorted(
            inspector.get_pk_constraint("intervention_students")["constrained_columns"]
        ) == ["intervention_id", "student_id"]

    @pytest.mark.parametrize(
        "table,column,referred,ondelete",
        [
            ("attention_flags", "offering_id", "course_offerings", "RESTRICT"),
            ("attention_flags", "student_id", "students", "RESTRICT"),
            ("attention_flags", "triggered_by_assessment_id", "assessments", "SET NULL"),
            ("interventions", "offering_id", "course_offerings", "RESTRICT"),
            ("interventions", "recorded_by_id", "users", "SET NULL"),
            ("intervention_students", "intervention_id", "interventions", "CASCADE"),
            ("intervention_students", "student_id", "students", "RESTRICT"),
            ("intervention_reasons", "source_flag_id", "attention_flags", "SET NULL"),
        ],
    )
    def test_delete_rules_are_as_designed(
        self, db_session: Session, table: str, column: str, referred: str, ondelete: str
    ) -> None:
        keys = fk_map(db_session, table)
        assert column in keys, f"{table}.{column} has no foreign key"
        assert keys[column]["referred_table"] == referred
        assert (keys[column]["options"].get("ondelete") or "NO ACTION").upper() == ondelete

    def test_a_reason_is_keyed_to_the_target_not_just_to_the_intervention(
        self, db_session: Session
    ) -> None:
        """The composite FK is what makes "a reason names a target" a database guarantee."""
        composite = [
            fk
            for fk in inspect(db_session.get_bind()).get_foreign_keys("intervention_reasons")
            if sorted(fk["constrained_columns"]) == ["intervention_id", "student_id"]
        ]
        assert composite, "intervention_reasons has no composite key onto intervention_students"
        assert composite[0]["referred_table"] == "intervention_students"
        assert composite[0]["options"].get("ondelete", "").upper() == "CASCADE"


class TestIndexes:
    def test_the_dashboard_index_requested_as_d9_exists(self, db_session: Session) -> None:
        names = {ix["name"] for ix in inspect(db_session.get_bind()).get_indexes("attention_flags")}
        assert "ix_attention_flags_offering_id_status" in names

    def test_the_live_flag_uniqueness_is_a_partial_unique_index(self, db_session: Session) -> None:
        """Partial, so resolved history can accumulate while only one flag per rule stays live."""
        row = db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'attention_flags' AND indexname = :name"
            ),
            {"name": "uq_attention_flags_offering_id_student_id_rule_code_live"},
        ).scalar_one()
        assert "UNIQUE" in row.upper()
        assert "WHERE" in row.upper(), "the index must be partial, or history cannot exist"
        assert "resolved" in row

    @pytest.mark.parametrize(
        "table,column",
        [
            ("attention_flags", "student_id"),
            ("interventions", "offering_id"),
            ("intervention_students", "student_id"),
            ("intervention_reasons", "intervention_id"),
        ],
    )
    def test_every_foreign_key_read_path_is_indexed(
        self, db_session: Session, table: str, column: str
    ) -> None:
        indexed = {
            tuple(ix["column_names"]) for ix in inspect(db_session.get_bind()).get_indexes(table)
        }
        pk = tuple(inspect(db_session.get_bind()).get_pk_constraint(table)["constrained_columns"])
        assert any(columns and columns[0] == column for columns in indexed) or pk[:1] == (
            column,
        ), f"{table}.{column} is queried but not indexed"


class TestEnumsMatchPython:
    @pytest.mark.parametrize("type_name,enum", ENUM_TYPES.items(), ids=list(ENUM_TYPES))
    def test_the_database_labels_are_exactly_the_python_values(
        self, db_session: Session, type_name: str, enum: type
    ) -> None:
        labels = set(
            db_session.scalars(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :name"
                ),
                {"name": type_name},
            ).all()
        )
        assert labels == {member.value for member in enum}, (
            f"{type_name} has drifted from {enum.__name__}"
        )


class TestNullability:
    @pytest.mark.parametrize(
        "table,column",
        [
            ("attention_flags", "offering_id"),
            ("attention_flags", "student_id"),
            ("attention_flags", "rule_code"),
            ("attention_flags", "severity"),
            ("attention_flags", "status"),
            ("attention_flags", "actual_value"),
            ("attention_flags", "message"),
            ("attention_flags", "computed_at"),
            ("interventions", "offering_id"),
            ("interventions", "kind"),
            ("interventions", "status"),
            ("interventions", "after_sequence_no"),
        ],
    )
    def test_columns_the_design_depends_on_are_not_nullable(
        self, db_session: Session, table: str, column: str
    ) -> None:
        columns = {c["name"]: c for c in inspect(db_session.get_bind()).get_columns(table)}
        assert column in columns, f"{table}.{column} is missing"
        assert not columns[column]["nullable"], f"{table}.{column} should be NOT NULL"

    @pytest.mark.parametrize(
        "table,column",
        [
            ("attention_flags", "resolved_at"),
            ("attention_flags", "threshold_key"),
            ("attention_flags", "pass_mark_percent"),
            ("intervention_reasons", "rule_code"),
            ("intervention_reasons", "observed_value"),
            ("intervention_reasons", "source_flag_id"),
        ],
    )
    def test_columns_that_are_genuinely_optional_stay_nullable(
        self, db_session: Session, table: str, column: str
    ) -> None:
        """A NOT NULL here would force a fabricated value — the thing analytics must never do."""
        columns = {c["name"]: c for c in inspect(db_session.get_bind()).get_columns(table)}
        assert columns[column]["nullable"], f"{table}.{column} must be able to be absent"


class TestConstraintsActuallyBite:
    @pytest.fixture
    def student(
        self,
        db_session: Session,
        cse: Department,
        cse_offering: CourseOffering,
        make_student: StudentFactory,
    ) -> Student:
        section = db_session.get(Section, cse_offering.section_id)
        assert section is not None
        return make_student(cse, section, enroll_in=[cse_offering])

    def flag(self, offering_id: uuid.UUID, student_id: uuid.UUID, **overrides) -> AttentionFlag:
        values = {
            "offering_id": offering_id,
            "student_id": student_id,
            "rule_code": AttentionRuleCode.R1_LOW_PERFORMANCE,
            "severity": FlagSeverity.HIGH,
            "actual_value": 20,
            "actual_unit": Unit.PERCENT,
            "actual_n": 1,
            "pass_mark_percent": 50,
            "message": "probe",
            "computed_at": datetime.now(UTC),
        }
        values.update(overrides)
        return AttentionFlag(**values)

    def test_a_flag_with_no_stated_comparison_is_refused(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        db_session.add(
            self.flag(cse_offering.id, student.id, pass_mark_percent=None, threshold_key=None)
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_resolved_flag_must_carry_a_resolved_at(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        db_session.add(self.flag(cse_offering.id, student.id, status=FlagStatus.RESOLVED))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_blank_message_is_refused(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        db_session.add(self.flag(cse_offering.id, student.id, message="   "))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_negative_boundary_is_refused(
        self, db_session: Session, cse_offering: CourseOffering
    ) -> None:
        db_session.add(
            Intervention(
                offering_id=cse_offering.id,
                kind=InterventionKind.OTHER,
                status=InterventionStatus.COMPLETED,
                after_sequence_no=-1,
                note="probe",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_reason_for_a_student_who_is_not_a_target_is_refused(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        """The composite foreign key, doing the job the contract's validator also does."""
        intervention = Intervention(
            offering_id=cse_offering.id,
            kind=InterventionKind.OTHER,
            after_sequence_no=0,
            note="probe",
        )
        db_session.add(intervention)
        db_session.flush()
        db_session.add(
            InterventionReason(
                intervention_id=intervention.id, student_id=student.id, note="not a target"
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_deleting_an_intervention_cascades_to_its_targets_and_reasons(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        intervention = Intervention(
            offering_id=cse_offering.id,
            kind=InterventionKind.OTHER,
            after_sequence_no=0,
            note="probe",
        )
        db_session.add(intervention)
        db_session.flush()
        db_session.add(InterventionStudent(intervention_id=intervention.id, student_id=student.id))
        db_session.flush()
        db_session.add(
            InterventionReason(intervention_id=intervention.id, student_id=student.id, note="why")
        )
        db_session.flush()

        db_session.execute(
            text("DELETE FROM interventions WHERE id = :id"), {"id": intervention.id}
        )
        db_session.flush()
        assert (
            db_session.scalars(
                select(InterventionStudent).where(
                    InterventionStudent.intervention_id == intervention.id
                )
            ).all()
            == []
        )
        assert (
            db_session.scalars(
                select(InterventionReason).where(
                    InterventionReason.intervention_id == intervention.id
                )
            ).all()
            == []
        )

    def test_a_student_with_an_attention_flag_cannot_be_deleted(
        self, db_session: Session, cse_offering: CourseOffering, student: Student
    ) -> None:
        """RESTRICT: academic history is not silently removable underneath analytics."""
        db_session.add(self.flag(cse_offering.id, student.id))
        db_session.flush()
        with pytest.raises(IntegrityError):
            db_session.execute(text("DELETE FROM students WHERE id = :id"), {"id": student.id})
            db_session.flush()
