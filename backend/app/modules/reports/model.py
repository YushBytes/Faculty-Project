"""What a report *is*, before anyone decides what it looks like.

A report here is data, not a document: metadata, then sections, each holding rows of typed
cells. CSV, XLSX and PDF all serialise this same object, which is what makes "the three
formats agree" a property the tests can actually check rather than a promise.

    analytics contracts  ->  Report (this module)  ->  csv / xlsx / pdf bytes

Nothing in this module computes anything. A :class:`Cell` is a value that analytics already
produced, carried with enough context to render it honestly in three different places:

``text``
    the canonical display string — what CSV writes and PDF prints.
``number``
    the same value as a ``Decimal`` when it is one, so XLSX can store a real number and a
    spreadsheet can sum a column. ``None`` when there is no number, which is **not** zero.
``note``
    why there is no number, when there is not. An insufficient measure carries its reason
    here, so the shortfall survives export instead of turning into an empty cell.

That three-part shape is the whole design. It is why an absent result exports as "absent"
rather than 0, and why "insufficient data: only 1 completed assessment (minimum 2)" reaches
the reader in all three formats.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import JsonDecimal
from app.modules.analytics.core.results import Label, Measure, Unit

NOT_EVALUATED = "not evaluated"
"""A build did not look. Distinct from insufficient data, which means it looked and could
not answer — the distinction Phase 5 exists to preserve, carried into the exports."""

INSUFFICIENT = "insufficient data"
"""Analytics looked and could not answer. Never rendered as 0, blank or "no change"."""


class CellKind(StrEnum):
    """What a cell holds, so an exporter can format it without guessing.

    Formatting differs between the three outputs — a spreadsheet wants a real number, a PDF
    wants a string — but the *meaning* is fixed here, once.
    """

    TEXT = "text"
    NUMBER = "number"
    PERCENT = "percent"
    PERCENTAGE_POINTS = "percentage_points"
    COUNT = "count"
    DATE = "date"
    MISSING = "missing"
    """No value, with a reason: insufficient data, not evaluated, absent, exempt."""


class Cell(BaseModel):
    """One value in a report, ready to be written three different ways."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    number: JsonDecimal | None = None
    kind: CellKind = CellKind.TEXT
    note: str | None = None

    @model_validator(mode="after")
    def _a_missing_cell_has_no_number(self) -> Self:
        if self.kind is CellKind.MISSING and self.number is not None:
            raise ValueError(
                f"a missing cell carries a number ({self.number}); absence is not a value"
            )
        return self

    @property
    def is_missing(self) -> bool:
        return self.kind is CellKind.MISSING


def text(value: object, *, note: str | None = None) -> Cell:
    """A plain string cell."""
    return Cell(text=str(value), kind=CellKind.TEXT, note=note)


def count(value: int, *, note: str | None = None) -> Cell:
    return Cell(text=str(value), number=Decimal(value), kind=CellKind.COUNT, note=note)


def percent(value: Decimal, *, note: str | None = None) -> Cell:
    """A percentage that analytics already computed, shown with its sign."""
    return Cell(text=f"{value}%", number=value, kind=CellKind.PERCENT, note=note)


def missing(reason: str, *, shown: str = INSUFFICIENT) -> Cell:
    """A value that does not exist, and the reason it does not.

    The reason is the point. "Insufficient data" alone tells a reader nothing about what was
    missing; the note carries the shortfall analytics already worded.
    """
    return Cell(text=shown, kind=CellKind.MISSING, note=reason)


_UNIT_KIND = {
    Unit.PERCENT: CellKind.PERCENT,
    Unit.PERCENTAGE_POINTS: CellKind.PERCENTAGE_POINTS,
    Unit.PERCENTAGE_POINTS_PER_ASSESSMENT: CellKind.PERCENTAGE_POINTS,
    Unit.COUNT: CellKind.COUNT,
    Unit.MARKS: CellKind.NUMBER,
}

_UNIT_SUFFIX = {
    Unit.PERCENT: "%",
    Unit.PERCENTAGE_POINTS: " pp",
    Unit.PERCENTAGE_POINTS_PER_ASSESSMENT: " pp/assessment",
}


def measure(value: Measure | None, *, absent: str = NOT_EVALUATED) -> Cell:
    """A :class:`Measure`, insufficiency and all.

    ``None`` means the analytic was never run — ``absent`` says so — while a measure whose
    status is insufficient exports as :data:`INSUFFICIENT` plus its own reason. The two are
    different answers and stay different in every format.
    """
    if value is None:
        return missing(
            "this analytic was not evaluated for this report; it is not a finding of zero",
            shown=absent,
        )
    if not value.is_ok or value.value is None:
        return missing(value.reason or "no value was computed")
    suffix = _UNIT_SUFFIX.get(value.unit, "")
    return Cell(
        text=f"{value.value}{suffix}",
        number=value.value,
        kind=_UNIT_KIND.get(value.unit, CellKind.NUMBER),
        note=f"n = {value.n}" if value.n else None,
    )


def label(value: Label | None, *, absent: str = NOT_EVALUATED) -> Cell:
    """A :class:`Label`, which is a word rather than a number."""
    if value is None:
        return missing("this analytic was not evaluated for this report", shown=absent)
    if not value.is_ok or value.value is None:
        return missing(value.reason or "no label was assigned")
    return Cell(text=value.value, kind=CellKind.TEXT, note=f"n = {value.n}" if value.n else None)


class Table(BaseModel):
    """Rows of cells under fixed headers.

    Column order is the header order and row order is the row order: both are decided by the
    builder that made the table, and neither is re-sorted downstream. Every exporter walks
    them as given, so a report rendered twice is identical and a report rendered three ways
    lines up.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    headers: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[Cell, ...], ...] = ()

    @model_validator(mode="after")
    def _rows_match_the_headers(self) -> Self:
        for index, row in enumerate(self.rows):
            if len(row) != len(self.headers):
                raise ValueError(
                    f"table {self.name!r} row {index} has {len(row)} cells for "
                    f"{len(self.headers)} headers"
                )
        return self

    @property
    def is_empty(self) -> bool:
        return not self.rows


class Section(BaseModel):
    """One part of a report: a heading, optional prose, and optional tables.

    ``notes`` carries the things that must travel with the numbers — data coverage, the
    observational caveat, an explanation of what was not evaluated. They are part of the
    report, not decoration, and every exporter is required to render them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    summary: str | None = None
    tables: tuple[Table, ...] = ()
    notes: tuple[str, ...] = ()


class ReportKind(StrEnum):
    """The report types this layer produces. One per question a faculty member asks."""

    CLASS_SUMMARY = "class_summary"
    STUDENT_PERFORMANCE = "student_performance"
    ATTENTION = "attention"
    ASSESSMENT_COMPARISON = "assessment_comparison"
    INTERVENTION_OUTCOME = "intervention_outcome"


class OfferingIdentity(BaseModel):
    """How a report names the offering it is about, for a human reader.

    The platform's own read already carries these labels; they are threaded through so a
    downloaded file says which course, section and term it covers. Without them two class
    summaries are indistinguishable once they are sitting in a folder.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    course_code: str | None = None
    section_name: str | None = None
    term_code: str | None = None


class ReportMetadata(BaseModel):
    """Who and what the report is about, and when it was made.

    Deliberately academic-only: an offering, a course, a section, a term, a student's
    register number. No user ids, no tokens, no internal identifiers beyond the offering's
    own — a report leaves the system, and everything in it should be something a faculty
    member could read aloud in a meeting.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ReportKind
    title: str = Field(min_length=1)
    generated_at: datetime
    offering_id: str | None = None
    course_code: str | None = None
    section_name: str | None = None
    term_code: str | None = None
    subject: str | None = None
    """What the report is *of*: a student's register number, an assessment code, and so on."""

    @model_validator(mode="after")
    def _stamped_with_a_real_instant(self) -> Self:
        stamp = self.generated_at
        if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
            raise ValueError("generated_at must be timezone-aware")
        return self

    def describe(self) -> tuple[tuple[str, str], ...]:
        """The metadata as label/value pairs, in a fixed order, omitting what is unset."""
        pairs = (
            ("Report", self.title),
            ("Course", self.course_code),
            ("Section", self.section_name),
            ("Term", self.term_code),
            ("Subject", self.subject),
            ("Generated", self.generated_at.isoformat(timespec="seconds")),
        )
        return tuple((name, value) for name, value in pairs if value)


class Report(BaseModel):
    """A complete report: metadata and sections, in the order they should be read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: ReportMetadata
    sections: tuple[Section, ...] = ()

    @property
    def tables(self) -> tuple[Table, ...]:
        return tuple(table for section in self.sections for table in section.tables)

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(note for section in self.sections for note in section.notes)

    def table(self, name: str) -> Table | None:
        return next((table for table in self.tables if table.name == name), None)

    @model_validator(mode="after")
    def _table_names_are_unique(self) -> Self:
        names = [table.name for table in self.tables]
        if len(names) != len(set(names)):
            raise ValueError(
                f"duplicate table names {sorted(names)}: a workbook cannot hold two sheets "
                "with the same name, and a reader cannot tell them apart"
            )
        return self


def rows_of(table: Table | None) -> Sequence[tuple[Cell, ...]]:
    """A table's rows, or nothing when the table is absent."""
    return table.rows if table else ()
