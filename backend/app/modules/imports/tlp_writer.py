"""Writing SRM "FORMAT TLP5" mark reports (xlsx, csv, pdf).

Used to produce the demo upload files and test fixtures in exactly the layout the importer
receives from the institution: title block, table, summary block. The summary is computed the
way the TLP report computes it (absentees in the pass-percentage denominator), which is why
it is only ever *compared* with the platform's analytics, never used as one.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from openpyxl import Workbook
from openpyxl.styles import Font

RANGES = ((0, 49), (50, 59), (60, 69), (70, 79), (80, 89), (90, 100))


@dataclass(frozen=True)
class TlpHeader:
    test_name: str
    academic_year: str  # "AY2025-26-EVEN"
    component_max: Decimal
    course_code: str
    course_name: str
    faculty_name: str
    faculty_code: str
    department: str = "CSE"
    report_date: str = "09-May-26"
    pass_mark_percent: int = 50


@dataclass(frozen=True)
class TlpRow:
    register_number: str
    name: str
    mark: Decimal | None  # None = Absent


def _pct(mark: Decimal, maximum: Decimal) -> Decimal:
    return (mark * 100 / maximum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _summary(header: TlpHeader, rows: list[TlpRow]) -> tuple[list[str], list[str]]:
    present = [r for r in rows if r.mark is not None]
    pcts = [_pct(r.mark, header.component_max) for r in present]
    failures = sum(1 for p in pcts if p < header.pass_mark_percent)
    absentees = len(rows) - len(present)
    passed = len(present) - failures
    pass_pct = (Decimal(passed) * 100 / len(rows)).quantize(Decimal("0.01")) if rows else Decimal(0)
    left = [
        f"Total strength {len(rows)}",
        f"Total absentees {absentees}",
        f"Total no. of failures {failures}",
        f"Pass MARK {header.pass_mark_percent}%",
        f"Pass percentage {pass_pct}",
    ]
    right = []
    for low, high in RANGES:
        count = sum(1 for p in pcts if low <= p < high + 1)
        right.append(f"{low}-{high} {count}")
    return left, right


def _title(header: TlpHeader) -> list[str]:
    return [
        "FACULTY OF ENGINEERING AND TECHNOLOGY",
        "SRM Institute of Science and Technology, Kattankulathur",
        "FORMAT TLP5",
        f"Test Name : {header.test_name} - Academic Year : {header.academic_year}",
        f"Component Max. Mark: {header.component_max:.2f} Marks",
        f"{header.course_code}({header.course_name}) handled by "
        f"{header.faculty_name}({header.faculty_code})",
    ]


def _cells(header: TlpHeader, index: int, row: TlpRow) -> list[str]:
    if row.mark is None:
        mark, pct = "Absent", "Absent"
    else:
        mark, pct = f"{row.mark:.2f}", f"{_pct(row.mark, header.component_max):.2f}"
    return [str(index), row.register_number, row.name, header.department, mark, pct]


COLUMNS = ["S.No.", "Reg. No", "Name", "Dept", "Obtained Mark", "%"]


def to_xlsx(header: TlpHeader, rows: list[TlpRow]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "TLP5"
    for line in _title(header):
        sheet.append([line])
    sheet.append(COLUMNS)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    for index, row in enumerate(rows, start=1):
        sheet.append(_cells(header, index, row))
    left, right = _summary(header, rows)
    sheet.append([])
    sheet.append([left[0], "", "Range of marks", "No.of students"])
    for i in range(max(len(left) - 1, len(right))):
        label = left[i + 1] if i + 1 < len(left) else ""
        rng = right[i].rsplit(" ", 1) if i < len(right) else ["", ""]
        sheet.append([label, "", rng[0], rng[1]])
    sheet.append(["SIGNATURE OF STAFF"])
    sheet.append(["SIGNATURE OF HOD"])
    sheet.append([f"Report Date:{header.report_date}"])
    sheet.column_dimensions["B"].width = 20
    sheet.column_dimensions["C"].width = 32
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def to_csv(header: TlpHeader, rows: list[TlpRow]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for line in _title(header):
        writer.writerow([line])
    writer.writerow(COLUMNS)
    for index, row in enumerate(rows, start=1):
        writer.writerow(_cells(header, index, row))
    left, right = _summary(header, rows)
    writer.writerow([f"{left[0]} Range of marks No.of students"])
    for i in range(max(len(left) - 1, len(right))):
        label = left[i + 1] if i + 1 < len(left) else ""
        writer.writerow([f"{label} {right[i] if i < len(right) else ''}".strip()])
    writer.writerow(["SIGNATURE OF STAFF"])
    writer.writerow(["SIGNATURE OF HOD"])
    writer.writerow([f"Report Date:{header.report_date}"])
    return out.getvalue().encode("utf-8")


def to_pdf(header: TlpHeader, rows: list[TlpRow]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    def line(text: str, *, bold: bool = False, size: int = 9) -> None:
        nonlocal y
        if y < 50:
            pdf.showPage()
            y = height - 50
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(40, y, text)
        y -= size + 5

    for index, text in enumerate(_title(header)):
        line(text, bold=index < 3, size=11 if index < 3 else 9)
    y -= 4
    line("S.No. Reg. No Name Dept Obtained Mark %", bold=True)
    for index, row in enumerate(rows, start=1):
        line(" ".join(_cells(header, index, row)))
    left, right = _summary(header, rows)
    y -= 4
    line(f"{left[0]} Range of marks No.of students")
    for i in range(max(len(left) - 1, len(right))):
        label = left[i + 1] if i + 1 < len(left) else ""
        line(f"{label} {right[i] if i < len(right) else ''}".strip())
    line("SIGNATURE OF STAFF")
    line("SIGNATURE OF HOD")
    line(f"Report Date:{header.report_date}")
    pdf.save()
    return buffer.getvalue()
