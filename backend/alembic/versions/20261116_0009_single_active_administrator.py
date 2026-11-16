"""At most one active Administrator, enforced by the database.

The application already refuses a second active ADMIN (users/service.py counts before it
writes), but a count-then-write check cannot stop two transactions that run at the same moment
while there is no Administrator — two API processes bootstrapping an empty database, or the
bootstrap racing ``create-admin``. This partial unique index makes the second commit fail;
``write_guard`` turns that into the same 409 the service already returns.

Only the index is added. No row is read-modified or deleted: if the data already holds more
than one active Administrator, the upgrade stops with an explanation instead of choosing one.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WHERE = "role = 'ADMIN' AND is_active"


def upgrade() -> None:
    active_admins = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM users WHERE role = 'ADMIN' AND is_active")
    )
    if active_admins and active_admins > 1:
        raise RuntimeError(
            f"{active_admins} active Administrator accounts exist; exactly one is allowed. "
            "Deactivate the extra accounts (keeping the intended Administrator) and run the "
            "migration again. Nothing was changed."
        )
    op.create_index(
        "uq_users_single_active_admin",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text(WHERE),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_users_single_active_admin",
        table_name="users",
        postgresql_where=sa.text(WHERE),
    )
