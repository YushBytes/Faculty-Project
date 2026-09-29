"""What an SRM TLP mark report says about itself.

The title block names the test, academic year, component maximum, course and faculty; the
summary block states the strength, absentees, failures, pass mark, pass percentage and the
mark-range distribution. None of it is written anywhere — the platform's own records stay
the source of truth — but it is exactly what lets the importer check that a file is being
imported into the right place (course, semester, assessment, maximum) and that it arrived
complete (strength = rows read).

Parsing is by labelled pattern ("Test Name : FP-I"), so a line that is missing is simply
absent from the result, never guessed.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_PATTERNS: dict[str, re.Pattern[str]] = {
    "test_name": re.compile(r"test\s*name\s*:\s*(.+?)(?:\s+-\s+academic\s+year|$)", re.I),
    "academic_year": re.compile(
        r"academic\s*year\s*:\s*(AY\s*[\d]{4}\s*-\s*\d{2}(?:\s*-\s*(?:ODD|EVEN))?)", re.I
    ),
    "component_max": re.compile(r"component\s*max\.?\s*marks?\s*:\s*(\d+(?:\.\d+)?)", re.I),
    "format": re.compile(r"format\s+(TLP\s*\d+)", re.I),
    "report_date": re.compile(r"report\s*date\s*:\s*([0-9A-Za-z-/ ]+)", re.I),
    "total_strength": re.compile(r"total\s*strength\s*:?\s*(\d+)", re.I),
    "total_absentees": re.compile(r"total\s*absentees\s*:?\s*(\d+)", re.I),
    "total_failures": re.compile(r"total\s*no\.?\s*of\s*failures\s*:?\s*(\d+)", re.I),
    "pass_mark_percent": re.compile(r"pass\s*mark\s*:?\s*(\d+(?:\.\d+)?)\s*%", re.I),
    "pass_percentage": re.compile(r"pass\s*percentage\s*:?\s*(\d+(?:\.\d+)?)", re.I),
}
_COURSE = re.compile(
    r"(?P<code>\d{2}[A-Z]{2,4}\d{3}[A-Z])\s*\((?P<name>[^)]+)\)\s*handled\s+by\s+(?P<faculty>.+?)\s*\((?P<fid>[A-Za-z0-9-]+)\)",
    re.I,
)
_RANGE = re.compile(r"(?<![\d.])(\d{1,3})\s*-\s*(\d{1,3})\s+(\d+)(?![\d.])")
_NUMERIC = frozenset(
    (
        "component_max",
        "total_strength",
        "total_absentees",
        "total_failures",
        "pass_mark_percent",
        "pass_percentage",
    )
)


def parse_academic_year(value: str | None) -> tuple[str | None, str | None]:
    """'AY2025-26-EVEN' -> ('2025-26', 'EVEN')."""
    if not value:
        return None, None
    match = re.search(r"(\d{4})\s*-\s*(\d{2})(?:\s*-\s*(ODD|EVEN))?", value, re.I)
    if not match:
        return None, None
    semester = match.group(3).upper() if match.group(3) else None
    return f"{match.group(1)}-{match.group(2)}", semester


def parse_metadata(preamble: list[str], trailer: list[str]) -> dict[str, Any]:
    """Labelled facts from the title and summary blocks. Empty when the file has neither."""
    text_lines = [*preamble, *trailer]
    if not text_lines:
        return {}
    found: dict[str, Any] = {}
    for line in text_lines:
        for key, pattern in _PATTERNS.items():
            if key in found:
                continue
            match = pattern.search(line)
            if match:
                value = match.group(1).strip()
                if key in _NUMERIC:
                    try:
                        found[key] = str(Decimal(value))
                    except InvalidOperation:
                        continue
                else:
                    found[key] = re.sub(r"\s+", "", value) if key == "academic_year" else value
        course = _COURSE.search(line)
        if course and "course_code" not in found:
            found["course_code"] = course.group("code").upper()
            found["course_name"] = course.group("name").strip()
            found["faculty_name"] = course.group("faculty").strip()
            found["faculty_code"] = course.group("fid").strip()
    ranges = []
    for line in trailer:
        for low, high, count in _RANGE.findall(line):
            ranges.append({"range": f"{int(low)}-{int(high)}", "students": int(count)})
    if ranges:
        found["ranges"] = ranges
    year, semester = parse_academic_year(found.get("academic_year"))
    if year:
        found["year"] = year
    if semester:
        found["semester"] = semester
    if preamble and any("srm" in line.lower() for line in preamble):
        found.setdefault("institution", next(line for line in preamble if "srm" in line.lower()))
    return found


def is_tlp(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("test_name") or metadata.get("course_code"))
