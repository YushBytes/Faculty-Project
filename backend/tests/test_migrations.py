"""Migration integrity: runs from an empty database, is reversible, and matches the models."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, make_url
from sqlalchemy.engine import Engine

from app.db.models import Base
from tests.conftest import TEST_DATABASE_URL, alembic_config, drop_database, recreate_database

SCRATCH_URL = make_url(TEST_DATABASE_URL).set(database="acadlytics_migration_test")
SCRATCH = SCRATCH_URL.render_as_string(hide_password=False)


@pytest.fixture
def scratch_engine() -> Iterator[Engine]:
    recreate_database(SCRATCH)
    eng = create_engine(SCRATCH)
    yield eng
    eng.dispose()
    drop_database(SCRATCH)


def _current_revision(eng: Engine) -> str | None:
    with eng.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_single_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config(SCRATCH)).get_heads()
    assert len(heads) == 1, f"Multiple Alembic heads: {heads}"


def test_upgrade_from_empty_downgrade_and_reupgrade(scratch_engine: Engine) -> None:
    cfg = alembic_config(SCRATCH)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")
    assert _current_revision(scratch_engine) == head

    command.downgrade(cfg, "base")
    assert _current_revision(scratch_engine) is None
    leftover = set(inspect(scratch_engine).get_table_names()) - {"alembic_version"}
    assert leftover == set(), f"Downgrade left tables behind: {leftover}"

    command.upgrade(cfg, "head")
    assert _current_revision(scratch_engine) == head


def test_models_match_migrations(engine: Engine) -> None:
    """Fails if a model changed without a matching migration."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations are out of sync: {diff}"
