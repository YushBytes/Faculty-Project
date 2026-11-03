"""Reading an SRM "FORMAT TLP5" mark report PDF into rows.

A TLP5 PDF is text, not an image: a title block, one header line
(``S.No. Reg. No Name Dept Obtained Mark %``), one line per student and a summary block.
This reads the text layer line by line and turns it into the same raw rows a spreadsheet
gives — title lines as one-cell rows, then the header, then six cells per student, then the
summary lines — so the rest of the pipeline (header detection, trailer, validation, staging)
is exactly the spreadsheet path.

It is deliberately strict. Every line between the header and the summary block must match
the student-line pattern; a line that does not is an error naming the line, never a row
silently dropped or a column guessed. A PDF without the TLP header line is rejected with a
message asking for the Excel/CSV export instead. Scanned (image-only) PDFs have no text
layer and are rejected the same way.
"""

from __future__ import annotations

import io
import re

from app.core.errors import BusinessRuleError
from app.core.tabular import UnsupportedFileError

HEADER = ["S.No.", "Reg. No", "Name", "Dept", "Obtained Mark", "%"]
_HEADER_LINE = re.compile(
    r"^s\.?\s*no\.?\s+reg\.?\s*no\.?\s+name\s+dept\.?\s+obtained\s+marks?\s+%\s*$", re.I
)
_MARK = r"(?:\d+(?:\.\d+)?|absent|ab|abs|exempt|ex|-{1,2})"
_STUDENT_LINE = re.compile(
    rf"^(?P<sno>\d+)\s+(?P<reg>[A-Za-z0-9]{{5,20}})\s+(?P<name>.+?)\s+(?P<dept>[A-Za-z&.]{{2,12}})"
    rf"\s+(?P<mark>{_MARK})\s+(?P<pct>{_MARK})$",
    re.I,
)
_TRAILER = (
    "total strength",
    "total absentees",
    "range of marks",
    "signature of",
    "report date",
    "pass mark",
    "pass percentage",
)
MAX_PAGES = 60


class PdfNotTlpError(UnsupportedFileError):
    pass


def _dedouble(line: str) -> str:
    """Bold title text is often drawn twice ("FFAACCUULLTTYY"); undo it for the title only."""
    words = line.split(" ")
    fixed = []
    for word in words:
        if (
            len(word) >= 4
            and len(word) % 2 == 0
            and all(word[i] == word[i + 1] for i in range(0, len(word), 2))
        ):
            fixed.append(word[::2])
        else:
            fixed.append(word)
    return " ".join(fixed)


def pdf_lines(content: bytes) -> list[str]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise PdfNotTlpError("PDF import is not available on this server.") from exc
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise PdfNotTlpError(f"The PDF has more than {MAX_PAGES} pages.")
            lines: list[str] = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines.extend(line.strip() for line in text.splitlines() if line.strip())
    except PdfNotTlpError:
        raise
    except Exception as exc:  # pdfminer raises a zoo of exception types for bad input
        raise PdfNotTlpError("The file could not be read as a PDF.") from exc
    return lines


def read_tlp_pdf(content: bytes) -> list[list[str | None]]:
    lines = pdf_lines(content)
    if not lines:
        raise PdfNotTlpError(
            "The PDF has no text layer (a scanned image?). Upload the Excel/CSV export instead."
        )
    header_at = next((i for i, line in enumerate(lines) if _HEADER_LINE.match(line)), None)
    if header_at is None:
        raise PdfNotTlpError(
            "Only SRM TLP-format PDF mark reports can be read (a table headed 'S.No. Reg. No "
            "Name Dept Obtained Mark %'). Upload the Excel/CSV export for other layouts."
        )
    rows: list[list[str | None]] = [[_dedouble(line)] for line in lines[:header_at]]
    rows.append(list(HEADER))
    problems: list[str] = []
    in_trailer = False
    for number, line in enumerate(lines[header_at + 1 :], start=header_at + 2):
        lowered = line.lower()
        if in_trailer or any(marker in lowered for marker in _TRAILER):
            in_trailer = True
            rows.append([line])
            continue
        if _HEADER_LINE.match(line):  # repeated on a new page
            continue
        match = _STUDENT_LINE.match(line)
        if match is None:
            problems.append(f"line {number}: '{line[:80]}'")
            continue
        rows.append([match.group(k) for k in ("sno", "reg", "name", "dept", "mark", "pct")])
    if problems:
        raise BusinessRuleError(
            "Some lines of the TLP PDF could not be read as student rows; nothing was guessed. "
            "Upload the Excel/CSV export instead, or correct the PDF.",
            details=[{"loc": ["file"], "message": p} for p in problems[:50]],
        )
    return rows
