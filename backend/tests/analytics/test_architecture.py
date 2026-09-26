"""Structural guarantees that reviews miss but a test can hold.

Two things are enforced here.

*The analytics core stays database-independent.* It is easy to reach for a session when a
query would be convenient, and the cost only shows up later, when a formula can no longer be
tested without a database and the same read exists in two places with two access rules. The
import scan below makes that a build failure rather than a habit.

*No question-level or topic-level tables appear.* The blueprint specifies topic analytics, a
question-to-topic weighted mapping and a difficulty index in convincing detail, and none of
it is supportable: the data does not exist. The schema check keeps that decision visible
instead of letting a future phase quietly reintroduce the tables and, with them, analytics
that would have to invent their inputs.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODULE_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules" / "analytics"
CORE_DIR = MODULE_DIR / "core"

FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy",
    "alembic",
    "psycopg",
    "app.db",
    "fastapi",
    "starlette",
)

FORBIDDEN_TABLES = frozenset(
    {
        "questions",
        "question_topics",
        "topics",
        "marks",
        "student_topic_summary",
        "student_question_marks",
    }
)


def _core_modules() -> list[pathlib.Path]:
    modules = sorted(CORE_DIR.glob("*.py"))
    assert modules, f"no analytics core modules found under {CORE_DIR}"
    return modules


def _imported_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


class TestCoreIsDatabaseIndependent:
    @pytest.mark.parametrize("path", _core_modules(), ids=lambda p: p.name)
    def test_module_imports_nothing_database_bound(self, path: pathlib.Path) -> None:
        offenders = sorted(
            name for name in _imported_names(path) if name.startswith(FORBIDDEN_IMPORT_PREFIXES)
        )
        assert not offenders, (
            f"{path.name} imports {offenders}. The analytics core must stay pure: read "
            "academic data through the platform's services in the service layer instead."
        )

    @pytest.mark.parametrize("path", _core_modules(), ids=lambda p: p.name)
    def test_module_imports_no_orm_models(self, path: pathlib.Path) -> None:
        offenders = sorted(
            name
            for name in _imported_names(path)
            if name.startswith("app.modules.") and name.endswith(".models")
        )
        assert not offenders, (
            f"{path.name} imports ORM models {offenders}. The core consumes the contracts in "
            "core.contracts; an adapter maps models onto them."
        )

    def test_importing_the_core_does_not_pull_in_sqlalchemy(self) -> None:
        """A transitive import would defeat the scan above."""
        import subprocess
        import sys

        probe = (
            "import sys; import app.modules.analytics.core as c; "
            "assert 'sqlalchemy' not in sys.modules, "
            "'importing the analytics core pulled in sqlalchemy'; print('clean')"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(pathlib.Path(__file__).resolve().parents[2]),
        )
        assert result.returncode == 0, result.stderr
        assert "clean" in result.stdout


class TestCoreOwnsNoConfiguration:
    """Settings reach the core as arguments, never as a lookup.

    A formula that reads an environment variable cannot be proved against a fixture: its
    answer depends on the machine it runs on. The deployment's defaults are resolved once,
    in ``app.modules.analytics.config``, and handed to the core as data.
    """

    @pytest.mark.parametrize("path", _core_modules(), ids=lambda p: p.name)
    def test_core_module_reads_no_settings(self, path: pathlib.Path) -> None:
        offenders = sorted(
            name
            for name in _imported_names(path)
            if name.startswith(("pydantic_settings", "app.core.config", "os"))
            or name == "app.modules.analytics.config"
        )
        assert not offenders, (
            f"{path.name} imports {offenders}. Thresholds are resolved in analytics/config.py "
            "and passed in; the core must stay deterministic given its inputs."
        )


class TestTheApiSurfaceIsNotASecondCopy:
    """``schemas.py`` re-exports the contracts; it does not declare parallel models.

    Two sets of response models means a mapping between them, and that mapping is exactly
    where an ``n``, a unit or an insufficient-data status goes missing.
    """

    def test_schemas_declares_no_models_of_its_own(self) -> None:
        tree = ast.parse((MODULE_DIR / "schemas.py").read_text(encoding="utf-8"))
        declared = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        assert not declared, (
            f"schemas.py declares {declared}. Response models live in core/outputs.py so the "
            "OpenAPI document and the formulas cannot drift apart."
        )

    def test_every_contract_is_exported(self) -> None:
        from app.modules.analytics import schemas
        from app.modules.analytics.core.outputs import ANALYTICS_CONTRACTS

        missing = [c.__name__ for c in ANALYTICS_CONTRACTS if c.__name__ not in schemas.__all__]
        assert not missing, f"contracts absent from the API surface: {missing}"


class TestNoQuestionOrTopicSchema:
    def test_no_question_or_topic_tables_are_registered(self) -> None:
        """Reduced scope: assessment-level data only. See docs/PROJECT_CONTEXT.md section 3."""
        from app.db.models import Base

        present = FORBIDDEN_TABLES & set(Base.metadata.tables)
        assert not present, (
            f"question/topic-level tables found: {sorted(present)}. Analytics on this data "
            "was excluded because the data does not exist; adding the tables without real "
            "data support would mean inventing their contents."
        )

    def test_analytics_core_mentions_no_question_or_topic_field(self) -> None:
        from app.modules.analytics.core import contracts

        fields = {
            name
            for model in (
                contracts.AssessmentRef,
                contracts.ResultRecord,
                contracts.OfferingSnapshot,
                contracts.StudentRef,
            )
            for name in model.model_fields
        }
        assert not {f for f in fields if "question" in f or "topic" in f}
