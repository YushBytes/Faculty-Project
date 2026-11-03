"""Serialising a :class:`Report` to CSV and XLSX. No calculation, anywhere.

Both exporters walk the report's sections and tables in the order the builder produced
them, so two runs of the same report are byte-identical and the two formats hold the same
values. Neither knows what a weighted course score is, and neither should: if an exporter
ever needs to work something out, the report model was missing a field.

**Conventions**, chosen here because the project had none for export:

===================  ==========================================================
numbers              exactly as analytics rendered them, two decimal places;
                     CSV writes the display text, XLSX writes a real number so a
                     spreadsheet can sum a column
percentages          ``62.40%`` in text; the bare number in a spreadsheet cell,
                     with the unit in the column header
missing values       the word (``insufficient data``, ``not evaluated``,
                     ``absent``), never blank and never ``0``
reasons              a ``… (note)`` suffix in CSV, a cell comment-style adjacent
                     "Note" column in XLSX where the table carries notes
dates                ISO-8601
line endings         ``\\r\\n``, per RFC 4180, so Excel reads the file correctly
encoding             UTF-8 with a BOM, so Excel opens non-ASCII names correctly
===================  ==========================================================

``NaN`` and ``Infinity`` cannot reach either exporter: the analytics layer rejects them at
construction, and ``Cell.number`` is a pydantic ``Decimal`` field, which refuses a non-finite
value outright.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from app.modules.reports import pdf
from app.modules.reports.model import Cell, CellKind, Report, Table

CSV_LINE_ENDING = "\r\n"
UTF8_BOM = "﻿"

MAX_SHEET_NAME = 31
"""Excel's limit. Longer names are truncated, and uniqueness is preserved explicitly."""


def cell_text(cell: Cell) -> str:
    """What a cell reads as in a flat format, reason included.

    The note matters most exactly where the value is absent: "insufficient data" on its own
    tells a reader nothing, while "insufficient data (only 1 completed assessment (minimum
    2))" tells them what to do about it.
    """
    if cell.is_missing and cell.note:
        return f"{cell.text} ({cell.note})"
    return cell.text


# ----------------------------------------------------------------------------- CSV


def _csv_rows(report: Report) -> Iterator[Sequence[str]]:
    """The whole report as flat rows: metadata, then each table under its own banner.

    One file holds every section, because a report is one thing and a faculty member who
    downloads "the attention report" should not receive five files. Each table is preceded
    by a ``# Table: <name>`` banner so the parts stay findable, and a consumer who wants
    only one table can split on it.
    """
    for name, value in report.metadata.describe():
        yield (f"# {name}", value)

    for section in report.sections:
        yield ()
        yield ("# Section", section.title)
        if section.summary:
            yield ("# Summary", section.summary)
        for note in section.notes:
            yield ("# Note", note)
        for table in section.tables:
            yield ()
            yield ("# Table", table.name)
            yield tuple(table.headers)
            for row in table.rows:
                yield tuple(cell_text(cell) for cell in row)


def to_csv(report: Report) -> bytes:
    """The report as UTF-8 CSV with a BOM and RFC 4180 line endings."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=CSV_LINE_ENDING, quoting=csv.QUOTE_MINIMAL)
    for row in _csv_rows(report):
        writer.writerow(row)
    return (UTF8_BOM + buffer.getvalue()).encode("utf-8")


def table_to_csv(table: Table) -> bytes:
    """One table on its own, for a caller that wants a single machine-readable grid."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=CSV_LINE_ENDING, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(table.headers)
    for row in table.rows:
        writer.writerow(tuple(cell_text(cell) for cell in row))
    return (UTF8_BOM + buffer.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------- XLSX

_NUMBER_FORMAT = {
    CellKind.PERCENT: "0.00",
    CellKind.PERCENTAGE_POINTS: "+0.00;-0.00;0.00",
    CellKind.NUMBER: "0.00",
    CellKind.COUNT: "0",
}
"""Percentages are stored as the number analytics computed (62.40), not as Excel's 0.624 —
the unit lives in the header, and a reader comparing the sheet with the PDF sees the same
digits. Percentage points show their sign, because a movement's direction is the point."""


def _sheet_names(report: Report) -> dict[str, str]:
    """A unique, ≤31-character sheet name per table, derived deterministically."""
    used: set[str] = set()
    names: dict[str, str] = {}
    for table in report.tables:
        base = table.name[:MAX_SHEET_NAME]
        candidate = base
        suffix = 2
        while candidate in used:
            trimmed = base[: MAX_SHEET_NAME - len(str(suffix)) - 1]
            candidate = f"{trimmed} {suffix}"
            suffix += 1
        used.add(candidate)
        names[table.name] = candidate
    return names


def to_xlsx(report: Report) -> bytes:
    """The report as a workbook: a cover sheet, then one sheet per table.

    Values are written as numbers where they are numbers, so the sheet is usable rather than
    a picture of a report — but nothing is computed here, and there are no formulas: a
    formula would be a second source of truth that could disagree with the analytics.
    """
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Report"
    _write_cover(cover, report)

    names = _sheet_names(report)
    for section in report.sections:
        for table in section.tables:
            sheet = workbook.create_sheet(names[table.name])
            _write_table(sheet, table, section_title=section.title, notes=section.notes)

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _write_cover(sheet: object, report: Report) -> None:
    """Metadata and each section's prose, as label/value pairs."""
    bold = Font(bold=True)
    cursor = 1
    cursor = _put(sheet, cursor, ("Report", report.metadata.title), bold_first=True)
    for name, value in report.metadata.describe():
        if name == "Report":
            continue  # already written as the banner above
        cursor = _put(sheet, cursor, (name, value))
    cursor += 1
    for section in report.sections:
        cursor = _put(sheet, cursor, ("Section", section.title), bold_first=True)
        if section.summary:
            cursor = _put(sheet, cursor, ("Summary", section.summary))
        for note in section.notes:
            cursor = _put(sheet, cursor, ("Note", note))
        cursor += 1
    del bold
    _fit(sheet, widths=(30, 100))


def _put(sheet: object, row: int, values: Sequence[object], *, bold_first: bool = False) -> int:
    """Write one row at an explicit index and return the next one.

    Explicit rather than ``append`` plus ``max_row``: an empty ``append`` is a no-op in
    openpyxl, which silently makes every subsequent row overwrite the same one.
    """
    for column, value in enumerate(values, start=1):
        target = sheet.cell(row=row, column=column)  # type: ignore[attr-defined]
        target.value = value
        if bold_first and column == 1:
            target.font = Font(bold=True)
    return row + 1


def _write_table(sheet: object, table: Table, *, section_title: str, notes: Sequence[str]) -> None:
    """A titled grid: section, table name, headers, then every row in order."""
    cursor = 1
    cursor = _put(sheet, cursor, (section_title,), bold_first=True)
    cursor = _put(sheet, cursor, (table.name,))
    cursor += 1

    header_row = cursor
    cursor = _put(sheet, cursor, table.headers)
    for column in range(1, len(table.headers) + 1):
        sheet.cell(row=header_row, column=column).font = Font(bold=True)  # type: ignore[attr-defined]

    for row in table.rows:
        for column, cell in enumerate(row, start=1):
            target = sheet.cell(row=cursor, column=column)  # type: ignore[attr-defined]
            if cell.number is not None and cell.kind is not CellKind.TEXT:
                target.value = float(cell.number)
                target.number_format = _NUMBER_FORMAT.get(cell.kind, "0.00")
            else:
                target.value = cell_text(cell)
            target.alignment = Alignment(wrap_text=False)
        cursor += 1

    if notes:
        cursor += 1
        for note in notes:
            cursor = _put(sheet, cursor, ("Note", note))

    _fit(sheet, widths=tuple(_column_width(table, index) for index in range(len(table.headers))))


def _column_width(table: Table, index: int) -> int:
    longest = len(table.headers[index])
    for row in table.rows:
        longest = max(longest, len(cell_text(row[index])))
    return min(max(longest + 2, 12), 60)


def _fit(sheet: object, *, widths: Sequence[int]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- PDF


def to_pdf(report: Report) -> bytes:
    """The report as a readable A4 document.

    The same sections, summaries, tables and notes as the other two formats, laid out for a
    person rather than a spreadsheet. Notes are printed in full: the observational caveat and
    the coverage statements are part of the report, and a PDF that dropped them to save a
    line would be the one format where the reader is most likely to take a number at face
    value.
    """
    document = pdf.Document()
    document.line(report.metadata.title, size=pdf.TITLE_SIZE, bold=True)
    for name, value in report.metadata.describe():
        document.line(f"{name}: {value}")

    for section in report.sections:
        document.heading(section.title)
        if section.summary:
            document.paragraph(section.summary)
        for table in section.tables:
            document.blank()
            document.line(table.name, bold=True)
            document.table(
                table.headers,
                [[cell_text(cell) for cell in row] for row in table.rows],
            )
        for note in section.notes:
            document.blank()
            document.paragraph(f"Note: {note}")

    return pdf.render(document)
