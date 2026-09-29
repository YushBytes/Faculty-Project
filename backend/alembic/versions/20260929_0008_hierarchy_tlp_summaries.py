"""Institutional hierarchy, SRM course/assessment vocabulary, TLP metadata, summaries.

* roles ACADEMIC_HEAD and COURSE_COORDINATOR; ``course_coordinators``; one active HOD and one
  active Academic Head per department; staff ``employee_code`` and ``designation``
* ``academic_terms.semester`` (ODD/EVEN) and ``courses.course_type`` (SRM T/J/P/L/M)
* SRM assessment families (FJ, FL, FP, FM, LLT, LLJ, PBL, VIVA, PRACTICAL)
* ``import_batches.source_metadata`` / ``upload_group_id`` for TLP files
* ``offering_summaries`` (materialised engine output) and ``generated_reports`` (history)

New enum values are added outside the migration transaction: PostgreSQL does not allow a
value added in a transaction to be used (here, by the partial index) before it commits.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29 17:26:22.670639
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_ROLES = ("ACADEMIC_HEAD", "COURSE_COORDINATOR")
OLD_ROLES = ("ADMIN", "HOD", "FACULTY")
NEW_TYPES = ("FJ", "FL", "FP", "FM", "LLT", "LLJ", "PBL", "VIVA", "PRACTICAL")
OLD_TYPES = ("CT", "FT", "QUIZ", "ASSIGNMENT", "LAB", "INTERNAL", "OTHER")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_ROLES:
            op.execute(f"ALTER TYPE user_role ADD VALUE IF NOT EXISTS '{value}' BEFORE 'FACULTY'")
        for value in NEW_TYPES:
            op.execute(
                f"ALTER TYPE assessment_type ADD VALUE IF NOT EXISTS '{value}' BEFORE 'QUIZ'"
            )
    sa.Enum("ODD", "EVEN", name="semester").create(op.get_bind(), checkfirst=True)
    sa.Enum("T", "J", "P", "L", "M", name="course_type").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "course_coordinators",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"],
            ["users.id"],
            name=op.f("fk_course_coordinators_assigned_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_course_coordinators_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_course_coordinators_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("course_id", "user_id", name=op.f("pk_course_coordinators")),
    )
    op.create_index(
        op.f("ix_course_coordinators_user_id"), "course_coordinators", ["user_id"], unique=False
    )
    op.create_table(
        "generated_reports",
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("export_format", sa.String(length=8), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["generated_by_id"],
            ["users.id"],
            name=op.f("fk_generated_reports_generated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_reports")),
    )
    op.create_index(
        op.f("ix_generated_reports_generated_by_id_created_at"),
        "generated_reports",
        ["generated_by_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "offering_summaries",
        sa.Column("offering_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["offering_id"],
            ["course_offerings.id"],
            name=op.f("fk_offering_summaries_offering_id_course_offerings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("offering_id", name=op.f("pk_offering_summaries")),
    )
    op.add_column(
        "academic_terms",
        sa.Column(
            "semester",
            postgresql.ENUM("ODD", "EVEN", name="semester", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "courses",
        sa.Column(
            "course_type",
            postgresql.ENUM("T", "J", "P", "L", "M", name="course_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("import_batches", sa.Column("upload_group_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_import_batches_upload_group_id"),
        "import_batches",
        ["upload_group_id"],
        unique=False,
    )
    op.add_column("users", sa.Column("employee_code", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("designation", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_users_department_head",
        "users",
        ["department_id", "role"],
        unique=True,
        postgresql_where=sa.text("role IN ('HOD', 'ACADEMIC_HEAD') AND is_active"),
    )
    op.create_unique_constraint(op.f("uq_users_employee_code"), "users", ["employee_code"])
    op.create_check_constraint(
        op.f("ck_users_department_role_has_department"),
        "users",
        "role NOT IN ('ACADEMIC_HEAD', 'COURSE_COORDINATOR') OR department_id IS NOT NULL",
    )


def _shrink_enum(type_name: str, table: str, column: str, keep: tuple[str, ...]) -> None:
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_old")
    values = ", ".join(f"'{v}'" for v in keep)
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({values})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name} "
        f"USING {column}::text::{type_name}"
    )
    op.execute(f"DROP TYPE {type_name}_old")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_department_role_has_department"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_employee_code"), "users", type_="unique")
    op.drop_index(
        "uq_users_department_head",
        table_name="users",
        postgresql_where=sa.text("role IN ('HOD', 'ACADEMIC_HEAD') AND is_active"),
    )
    op.drop_column("users", "designation")
    op.drop_column("users", "employee_code")
    op.drop_index(op.f("ix_import_batches_upload_group_id"), table_name="import_batches")
    op.drop_column("import_batches", "upload_group_id")
    op.drop_column("import_batches", "source_metadata")
    op.drop_column("courses", "course_type")
    op.drop_column("academic_terms", "semester")
    op.drop_table("offering_summaries")
    op.drop_index(
        op.f("ix_generated_reports_generated_by_id_created_at"), table_name="generated_reports"
    )
    op.drop_table("generated_reports")
    op.drop_index(op.f("ix_course_coordinators_user_id"), table_name="course_coordinators")
    op.drop_table("course_coordinators")
    sa.Enum(name="semester").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="course_type").drop(op.get_bind(), checkfirst=True)
    # Removed roles fall back to FACULTY; removed assessment families to OTHER.
    op.execute(
        "UPDATE users SET role = 'FACULTY' WHERE role::text IN ('ACADEMIC_HEAD', 'COURSE_COORDINATOR')"
    )
    op.execute(
        "UPDATE assessments SET assessment_type = 'OTHER' WHERE assessment_type::text IN ("
        + ", ".join(f"'{v}'" for v in NEW_TYPES)
        + ")"
    )
    op.drop_constraint(op.f("ck_users_hod_has_department"), "users", type_="check")
    _shrink_enum("user_role", "users", "role", OLD_ROLES)
    op.create_check_constraint(
        op.f("ck_users_hod_has_department"), "users", "role <> 'HOD' OR department_id IS NOT NULL"
    )
    _shrink_enum("assessment_type", "assessments", "assessment_type", OLD_TYPES)
