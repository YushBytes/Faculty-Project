"""Import validation: a pure function from (staged sheet, platform snapshot) to a preview.

No database access here — the service builds a ``Snapshot`` and this module decides.
Preview and confirm run the same code, so what faculty saw is exactly what is written.

Levels
    error    blocks confirm (file-, column-, row- or cell-level)
    warning  surfaced; faculty decides (blank -> absent, name mismatch, overwrite, ...)
    info     recognised markers ("AB" -> absent), skipped empty rows
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

from app.core.tabular import IDENTITY_HEADERS, normalise_header
from app.modules.assessments.models import ResultStatus
from app.modules.imports.models import ImportFormat

# ---------------------------------------------------------------------------- vocabulary

IDENTITY = IDENTITY_HEADERS
NAME = ("full_name", "name", "student_name")
LONG_ASSESSMENT = ("assessment", "assessment_name", "exam", "test", "component")
LONG_SCORE = (
    "score",
    "marks",
    "mark",
    "marks_obtained",
    "obtained",
    "score_obtained",
    "obtained_mark",
    "obtained_marks",
    "mark_obtained",
)
LONG_MAX = ("max_score", "max_marks", "max", "out_of", "total_marks", "maximum", "max_mark")
LONG_PERCENT = ("percentage", "percent", "pct", "perc", "percentage_obtained")
LONG_STATUS = ("status", "attendance_status")
IGNORED = frozenset(
    (
        "s_no",
        "sno",
        "sl_no",
        "slno",
        "serial_no",
        "sr_no",
        "no",
        "email",
        "email_id",
        "section",
        "sec",
        "department",
        "dept",
        "batch",
        "program",
        "programme",
        "remarks",
        "remark",
        "total",
        "grade",
        "result",
        "rank",
        "attendance",
        "cgpa",
        "gpa",
        "date",
        "assessment_date",
        "exam_date",
        "course",
        "course_code",
        "offering",
    )
)
SINGLE_SCORE = (
    "score",
    "marks",
    "mark",
    "marks_obtained",
    "obtained",
    "obtained_mark",
    "obtained_marks",
    "mark_obtained",
)

ABSENT_MARKERS = frozenset(("AB", "A", "ABS", "ABSENT", "-", "--"))
EXEMPT_MARKERS = frozenset(("EX", "EXEMPT", "EXEMPTED"))
PRESENT_WORDS = frozenset(("PRESENT", "P"))
NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
PERCENT_TOLERANCE = Decimal("0.5")
NAME_MATCH_RATIO = 0.8
IGNORE = "ignore"


class Level(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Issue:
    level: Level
    code: str
    message: str
    column: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "code": self.code,
            "message": self.message,
            "column": self.column,
        }


def _err(code: str, message: str, column: str | None = None) -> Issue:
    return Issue(Level.ERROR, code, message, column)


def _warn(code: str, message: str, column: str | None = None) -> Issue:
    return Issue(Level.WARNING, code, message, column)


def _info(code: str, message: str, column: str | None = None) -> Issue:
    return Issue(Level.INFO, code, message, column)


class FileRejectedError(Exception):
    """File-blocking problems: the sheet cannot be staged at all."""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


# ---------------------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class AssessmentRef:
    id: uuid.UUID
    name: str
    max_marks: Decimal


@dataclass(frozen=True)
class StudentRef:
    id: uuid.UUID
    register_number: str
    full_name: str
    is_active: bool
    enrollment: str | None  # "ACTIVE", "DROPPED" or None (not enrolled in this offering)


@dataclass
class Snapshot:
    offering_label: str
    assessments: list[AssessmentRef]
    students: dict[str, StudentRef]  # register number -> student (only numbers in the file)
    cohort: list[StudentRef]  # active cohort, for "missing from file"
    existing: dict[tuple[uuid.UUID, uuid.UUID], tuple[ResultStatus, Decimal | None]]
    target_assessment_id: uuid.UUID | None = None
    duplicate_of: str | None = None  # description of an earlier committed import of this file
    # What the platform knows about the offering, to check a TLP file's own title block.
    course_code: str | None = None
    term_year: str | None = None
    term_semester: str | None = None
    faculty_codes: frozenset[str] = frozenset()
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Staged:
    file_format: ImportFormat
    headers: list[str]
    rows: list[dict[str, Any]]  # [{"row": n, "values": {...}}]
    column_mapping: dict[str, str] = field(default_factory=dict)
    fixes: dict[str, Any] = field(default_factory=dict)
    excluded_rows: list[int] = field(default_factory=list)
    skipped_empty_rows: list[int] = field(default_factory=list)


def fix_key(row: int, column: str) -> str:
    return f"{row}|{column}"


# ---------------------------------------------------------------------------- output


@dataclass
class ColumnInfo:
    header: str
    role: str  # identity | name | assessment | score | max | percentage | status | ignored
    assessment_id: uuid.UUID | None = None
    assessment_name: str | None = None
    mapped_by: str = "auto"  # auto | user
    issues: list[Issue] = field(default_factory=list)


@dataclass
class CellResult:
    column: str
    assessment_id: uuid.UUID | None
    assessment_name: str | None
    raw: str | None
    value: str | None  # after fixes
    fixed: bool
    status: ResultStatus | None
    score: Decimal | None
    issues: list[Issue] = field(default_factory=list)
    change: str | None = None  # create | update | unchanged


@dataclass
class RowResult:
    row: int
    register_number: str | None
    student_id: uuid.UUID | None
    student_name: str | None
    excluded: bool
    issues: list[Issue] = field(default_factory=list)
    cells: list[CellResult] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return any(i.level is Level.ERROR for i in self.issues) or any(
            i.level is Level.ERROR for c in self.cells for i in c.issues
        )


@dataclass
class Preview:
    file_format: ImportFormat
    columns: list[ColumnInfo]
    file_issues: list[Issue]
    rows: list[RowResult]
    missing_students: list[StudentRef]
    summary: dict[str, Any]
    # assessment id -> [(student id, status, score)] for every valid, non-excluded cell
    changes: dict[uuid.UUID, list[tuple[uuid.UUID, ResultStatus, Decimal | None]]]

    @property
    def can_confirm(self) -> bool:
        return self.summary["errors"] == 0 and self.summary["cells_to_write"] > 0


# ---------------------------------------------------------------------------- helpers


_PAREN = re.compile(r"\(([^)]*)\)")
_MAX_IN_TEXT = re.compile(r"(?:max(?:imum)?|out\s*of|/)\s*[:.]?\s*(\d+(?:\.\d+)?)", re.I)


def header_key(header: str) -> str:
    """'CT1 (max 50)' -> 'ct1', 'CT-1 /50' -> 'ct_1', 'Quiz 2 out of 10' -> 'quiz_2'."""
    text = _PAREN.sub(" ", header)
    text = re.sub(r"/\s*\d+(\.\d+)?\s*$", " ", text)
    text = re.sub(r"\b(out\s*of|max(imum)?)\b.*$", " ", text, flags=re.I)
    return normalise_header(text)


_ROMAN = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}


def match_key(text: str) -> str:
    """Key used to match a column or assessment name: separators ignored and a trailing
    Roman numeral read as a number, so 'FT-II', 'FT 2', 'ft2' and 'FT-2' are the same name
    (two assessments colliding here is ambiguous, never resolved by guessing).

    Only a numeral that is its own token after a word counts ('FT-I', 'LLJ II'), so words
    such as 'Viva' or 'Mix' are never read as numbers."""
    tokens = [t for t in header_key(text).split("_") if t]
    converted = [
        _ROMAN.get(token, token) if index > 0 and tokens[index - 1].isalpha() else token
        for index, token in enumerate(tokens)
    ]
    return "".join(converted)


def header_max(header: str) -> Decimal | None:
    match = _MAX_IN_TEXT.search(header)
    return Decimal(match.group(1)) if match else None


def normalise_register_number(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned or None


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z ]", "", re.sub(r"\s+", " ", value.lower())).strip()


def _to_decimal(raw: str) -> Decimal | None:
    if not NUMBER.match(raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _find(keys: dict[str, list[str]], aliases: tuple[str, ...]) -> list[str]:
    return [h for alias in aliases for h in keys.get(alias, [])]


# ---------------------------------------------------------------------------- structure


def check_headers(headers: list[str], rows: list[dict[str, Any]]) -> None:
    """Reject malformed header rows before staging (file-blocking)."""
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    for position, header in enumerate(headers, start=1):
        if header == "":
            has_data = any(r["values"].get("") not in (None, "") for r in rows)
            if has_data:
                issues.append(
                    _err("malformed_header", f"Column {position} has values but no header.")
                )
            continue
        folded = header.strip().lower()
        if folded in seen:
            issues.append(
                _err(
                    "duplicate_header",
                    f"Header '{header}' appears in columns {seen[folded]} and {position}.",
                    header,
                )
            )
        else:
            seen[folded] = position
    keys: dict[str, list[str]] = defaultdict(list)
    for header in headers:
        if header:
            keys[normalise_header(header)].append(header)
    identity = _find(keys, IDENTITY)
    if not identity:
        issues.append(
            _err(
                "missing_identity_column",
                "No register number column found. Add a column named 'Register No' "
                f"(also accepted: {', '.join(IDENTITY)}).",
            )
        )
    elif len(identity) > 1:
        issues.append(
            _err(
                "ambiguous_identity_column",
                f"Several columns look like the register number: {', '.join(identity)}.",
            )
        )
    if issues:
        raise FileRejectedError(issues)


def detect_format(headers: list[str]) -> ImportFormat:
    keys = {normalise_header(h) for h in headers if h}
    has_assessment = any(a in keys for a in LONG_ASSESSMENT)
    has_score = any(a in keys for a in LONG_SCORE)
    return ImportFormat.LONG if has_assessment and has_score else ImportFormat.WIDE


def map_columns(staged: Staged, snapshot: Snapshot) -> tuple[list[ColumnInfo], list[Issue]]:
    """Assign a role to every column. Assessment columns are matched by name; the user's
    mapping overrides win. Never guesses between two candidates."""
    by_key: dict[str, list[AssessmentRef]] = defaultdict(list)
    by_id = {a.id: a for a in snapshot.assessments}
    for assessment in snapshot.assessments:
        by_key[match_key(assessment.name)].append(assessment)
    target = by_id.get(snapshot.target_assessment_id) if snapshot.target_assessment_id else None

    columns: list[ColumnInfo] = []
    file_issues: list[Issue] = []
    for header in staged.headers:
        if header == "":
            columns.append(ColumnInfo(header, "ignored"))
            continue
        key = normalise_header(header)
        info = ColumnInfo(header, "ignored")
        override = staged.column_mapping.get(header)
        if key in IDENTITY:
            info.role = "identity"
        elif key in NAME:
            info.role = "name"
        elif staged.file_format is ImportFormat.LONG:
            for role, aliases in (
                ("assessment", LONG_ASSESSMENT),
                ("score", LONG_SCORE),
                ("max", LONG_MAX),
                ("percentage", LONG_PERCENT),
                ("status", LONG_STATUS),
            ):
                if key in aliases:
                    info.role = role
                    break
        elif override is not None:
            info.mapped_by = "user"
            if override != IGNORE:
                assessment = by_id.get(uuid.UUID(override))
                info.role = "assessment"
                if assessment is not None:
                    info.assessment_id, info.assessment_name = assessment.id, assessment.name
                else:
                    info.issues.append(
                        _err(
                            "missing_assessment_definition",
                            f"Column '{header}' is mapped to an assessment that no longer exists.",
                            header,
                        )
                    )
        elif target is not None and key in SINGLE_SCORE:
            info.role = "assessment"
            info.assessment_id, info.assessment_name = target.id, target.name
        elif target is not None and key in LONG_PERCENT:
            info.role = "percentage"  # checked against the score of the same row
        elif key in IGNORED or key in LONG_PERCENT:
            info.role = "ignored"
        else:
            info.role = "assessment"
            matches = by_key.get(match_key(header), [])
            if len(matches) == 1:
                info.assessment_id, info.assessment_name = matches[0].id, matches[0].name
            elif len(matches) > 1:
                names = ", ".join(a.name for a in matches)
                info.issues.append(
                    _err(
                        "ambiguous_column",
                        f"Column '{header}' matches several assessments ({names}); "
                        "map it explicitly.",
                        header,
                    )
                )
            else:
                known = ", ".join(a.name for a in snapshot.assessments) or "none defined"
                info.issues.append(
                    _err(
                        "missing_assessment_definition",
                        f"Column '{header}' does not match any assessment of "
                        f"{snapshot.offering_label} "
                        f"(defined: {known}). Create the assessment, map the column, or ignore it.",
                        header,
                    )
                )
        if info.role == "assessment" and info.assessment_id is not None:
            assessment = by_id[info.assessment_id]
            if target is not None and assessment.id != target.id:
                info.issues.append(
                    _err(
                        "wrong_assessment",
                        f"This import is for {target.name}; column '{header}' is "
                        f"{assessment.name}. "
                        "Ignore the column or import at offering level.",
                        header,
                    )
                )
            stated_max = header_max(header)
            if stated_max is not None and stated_max != assessment.max_marks:
                info.issues.append(
                    _err(
                        "max_mismatch",
                        f"Column '{header}' says max {stated_max}, but {assessment.name} has max "
                        f"{assessment.max_marks}.",
                        header,
                    )
                )
        columns.append(info)

    # Two columns feeding the same assessment is never resolved silently.
    feeding: dict[uuid.UUID, list[ColumnInfo]] = defaultdict(list)
    for info in columns:
        if info.role == "assessment" and info.assessment_id is not None:
            feeding[info.assessment_id].append(info)
    for group in feeding.values():
        if len(group) > 1:
            names = ", ".join(f"'{c.header}'" for c in group)
            for info in group:
                info.issues.append(
                    _err(
                        "duplicate_assessment_column",
                        f"Columns {names} all map to {info.assessment_name}; ignore all but one.",
                        info.header,
                    )
                )

    if staged.file_format is ImportFormat.WIDE and not any(c.role == "assessment" for c in columns):
        file_issues.append(_err("no_assessment_columns", "The sheet has no assessment columns."))
    if staged.file_format is ImportFormat.LONG and not any(c.role == "score" for c in columns):
        file_issues.append(_err("no_score_column", "The sheet has no score column."))
    return columns, file_issues


# ---------------------------------------------------------------------------- values


def interpret(
    raw: str | None,
    max_marks: Decimal,
    *,
    explicit_status: str | None = None,
    column: str | None = None,
) -> tuple[ResultStatus | None, Decimal | None, list[Issue]]:
    """Turn one raw cell into (status, score, issues). Blank is absent with a warning,
    never 0; unrecognised text is an error, never guessed."""
    text = (raw or "").strip()
    status_word = (explicit_status or "").strip().upper()
    issues: list[Issue] = []

    declared: ResultStatus | None = None
    if status_word:
        if status_word in ABSENT_MARKERS:
            declared = ResultStatus.ABSENT
        elif status_word in EXEMPT_MARKERS:
            declared = ResultStatus.EXEMPT
        elif status_word in PRESENT_WORDS:
            declared = ResultStatus.PRESENT
        else:
            return (
                None,
                None,
                [
                    _err(
                        "invalid_status",
                        f"Status '{explicit_status}' is not recognised "
                        "(use present, absent/AB, exempt/EX).",
                        column,
                    )
                ],
            )

    if text == "":
        if declared in (ResultStatus.ABSENT, ResultStatus.EXEMPT):
            return declared, None, []
        if declared is ResultStatus.PRESENT:
            return (
                None,
                None,
                [_err("missing_score", "Status is present but the score is blank.", column)],
            )
        return (
            ResultStatus.ABSENT,
            None,
            [
                _warn(
                    "blank_cell_absent",
                    "Blank cell — will be recorded as absent (not 0).",
                    column,
                )
            ],
        )

    upper = text.upper()
    if upper in ABSENT_MARKERS or upper in EXEMPT_MARKERS:
        status = ResultStatus.ABSENT if upper in ABSENT_MARKERS else ResultStatus.EXEMPT
        if declared not in (None, status):
            return (
                None,
                None,
                [
                    _err(
                        "conflicting_status",
                        f"'{text}' contradicts status '{explicit_status}'.",
                        column,
                    )
                ],
            )
        issues.append(
            _info(f"{status.value}_marker", f"'{text}' recorded as {status.value}.", column)
        )
        return status, None, issues

    score = _to_decimal(text)
    if score is None:
        return (
            None,
            None,
            [
                _err(
                    "invalid_number",
                    f"'{text}' is not a number or a recognised status (AB, -, EX).",
                    column,
                )
            ],
        )
    if declared in (ResultStatus.ABSENT, ResultStatus.EXEMPT):
        return (
            None,
            None,
            [
                _err(
                    "conflicting_status",
                    f"Score {text} given but status is '{explicit_status}'.",
                    column,
                )
            ],
        )
    if score.as_tuple().exponent < -2:
        return (
            None,
            None,
            [_err("too_many_decimals", f"'{text}' has more than 2 decimal places.", column)],
        )
    if score < 0:
        return None, None, [_err("score_below_zero", f"Score {text} is below 0.", column)]
    if score > max_marks:
        return (
            None,
            None,
            [_err("score_above_max", f"Score {text} is above the maximum {max_marks}.", column)],
        )
    return ResultStatus.PRESENT, score, issues


def check_percentage(
    raw: str | None,
    status: ResultStatus | None,
    score: Decimal | None,
    max_marks: Decimal,
    column: str | None,
) -> list[Issue]:
    text = (raw or "").strip()
    if not text:
        return []
    upper = text.upper()
    if upper in ABSENT_MARKERS or upper in EXEMPT_MARKERS:
        marker = ResultStatus.ABSENT if upper in ABSENT_MARKERS else ResultStatus.EXEMPT
        if status is marker:
            return []  # "Absent" in the % column of an absent row, as TLP reports print it
        return [
            _err(
                "impossible_percentage",
                f"Percentage says '{text}' but the mark is "
                f"{score if score is not None else 'blank'}.",
                column,
            )
        ]
    value = _to_decimal(text.rstrip("%").strip())
    if value is None or value < 0 or value > 100:
        return [
            _err("impossible_percentage", f"Percentage '{text}' is not between 0 and 100.", column)
        ]
    if status is not ResultStatus.PRESENT or score is None:
        return [
            _err("impossible_percentage", f"Percentage {text} given but there is no score.", column)
        ]
    expected = (score * 100 / max_marks).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if abs(expected - value) > PERCENT_TOLERANCE:
        return [
            _err(
                "impossible_percentage",
                f"Percentage {text} does not match {score}/{max_marks} = {expected}%.",
                column,
            )
        ]
    return []


# ---------------------------------------------------------------------------- TLP title block


def metadata_issues(snapshot: Snapshot, row_count: int, absent_count: int) -> list[Issue]:
    """Compare what a TLP file says about itself with the platform's records.

    Wrong course, wrong semester, wrong assessment or wrong maximum block the import: they
    mean the file is going to the wrong place. A faculty id that is not assigned here is a
    warning (the report may have been generated by a colleague). A strength that disagrees
    with the rows read means the file is incomplete and blocks.
    """
    meta = snapshot.source_metadata or {}
    if not meta:
        return []
    issues: list[Issue] = []
    by_id = {a.id: a for a in snapshot.assessments}
    target = by_id.get(snapshot.target_assessment_id) if snapshot.target_assessment_id else None
    code = meta.get("course_code")
    if code and snapshot.course_code and code.upper() != snapshot.course_code.upper():
        issues.append(
            _err(
                "course_mismatch",
                f"The file is for course {code}, but this is {snapshot.course_code}.",
            )
        )
    year, semester = meta.get("year"), meta.get("semester")
    if year and snapshot.term_year and year != snapshot.term_year:
        issues.append(
            _err(
                "term_mismatch",
                f"The file is for academic year {year}, but this offering is in "
                f"{snapshot.term_year}.",
            )
        )
    elif semester and snapshot.term_semester and semester != snapshot.term_semester:
        issues.append(
            _err(
                "term_mismatch",
                f"The file is for the {semester.lower()} semester, but this offering is in the "
                f"{snapshot.term_semester.lower()} semester.",
            )
        )
    test = meta.get("test_name")
    if test and target is not None and match_key(test) != match_key(target.name):
        issues.append(
            _err(
                "wrong_assessment",
                f"The file's test name is '{test}', but it is being imported into {target.name}.",
            )
        )
    component_max = meta.get("component_max")
    if component_max and target is not None and Decimal(component_max) != target.max_marks:
        issues.append(
            _err(
                "max_mismatch",
                f"The file's component maximum is {Decimal(component_max).normalize():f}, but "
                f"{target.name} is out of {target.max_marks.normalize():f}.",
            )
        )
    faculty = meta.get("faculty_code")
    if faculty and snapshot.faculty_codes and faculty not in snapshot.faculty_codes:
        issues.append(
            _warn(
                "faculty_mismatch",
                f"The report was generated by staff id {faculty} "
                f"({meta.get('faculty_name', 'unknown')}), who is not assigned to this offering.",
            )
        )
    strength = meta.get("total_strength")
    if strength is not None and int(Decimal(strength)) != row_count:
        issues.append(
            _err(
                "summary_mismatch",
                f"The report states a total strength of {int(Decimal(strength))} but "
                f"{row_count} student rows were read; the file may be incomplete.",
            )
        )
    absentees = meta.get("total_absentees")
    if absentees is not None and int(Decimal(absentees)) != absent_count:
        issues.append(
            _warn(
                "summary_mismatch",
                f"The report states {int(Decimal(absentees))} absentee(s); the rows contain "
                f"{absent_count}.",
            )
        )
    return issues


# ---------------------------------------------------------------------------- main


def validate(staged: Staged, snapshot: Snapshot) -> Preview:
    columns, file_issues = map_columns(staged, snapshot)
    identity = next(c.header for c in columns if c.role == "identity")
    name_col = next((c.header for c in columns if c.role == "name"), None)
    by_id = {a.id: a for a in snapshot.assessments}
    by_key: dict[str, list[AssessmentRef]] = defaultdict(list)
    for assessment in snapshot.assessments:
        by_key[match_key(assessment.name)].append(assessment)
    column_errors = any(i.level is Level.ERROR for c in columns for i in c.issues)
    names_in_cohort = Counter(_name_key(s.full_name) for s in snapshot.cohort)
    excluded = set(staged.excluded_rows)

    def value(row: dict[str, Any], column: str) -> tuple[str | None, str | None, bool]:
        original = row["values"].get(column)
        fix = staged.fixes.get(fix_key(row["row"], column))
        if fix is None:
            return original, original, False
        return original, fix["value"], True

    results: list[RowResult] = []
    for row in staged.rows:
        _, number_value, _ = value(row, identity)
        number = normalise_register_number(number_value)
        result = RowResult(
            row=row["row"],
            register_number=number,
            student_id=None,
            student_name=None,
            excluded=row["row"] in excluded,
        )
        results.append(result)
        if result.excluded:
            continue
        student = snapshot.students.get(number) if number else None
        if number is None:
            result.issues.append(
                _err("missing_register_number", "Register number is blank.", identity)
            )
        elif student is None:
            result.issues.append(
                _err("unknown_student", f"{number} is not a registered student.", identity)
            )
        elif student.enrollment is None:
            result.issues.append(
                _err(
                    "not_enrolled",
                    f"{number} is not enrolled in {snapshot.offering_label}.",
                    identity,
                )
            )
        if student is not None:
            result.student_id, result.student_name = student.id, student.full_name
            if name_col is not None:
                _, given, _ = value(row, name_col)
                if given and _name_key(given) != _name_key(student.full_name):
                    ratio = SequenceMatcher(
                        None, _name_key(given), _name_key(student.full_name)
                    ).ratio()
                    if names_in_cohort.get(_name_key(given)):
                        result.issues.append(
                            _err(
                                "conflicting_identity",
                                f"{number} belongs to '{student.full_name}', but '{given}' "
                                "is another "
                                "student in this offering.",
                                name_col,
                            )
                        )
                    elif ratio < NAME_MATCH_RATIO:
                        result.issues.append(
                            _warn(
                                "name_mismatch",
                                f"Name '{given}' differs from the register "
                                f"('{student.full_name}').",
                                name_col,
                            )
                        )

        # Build the (assessment, raw value) cells of this row.
        if staged.file_format is ImportFormat.WIDE:
            for info in columns:
                if info.role != "assessment":
                    continue
                original, current, fixed = value(row, info.header)
                result.cells.append(
                    CellResult(
                        column=info.header,
                        assessment_id=info.assessment_id,
                        assessment_name=info.assessment_name,
                        raw=original,
                        value=current,
                        fixed=fixed,
                        status=None,
                        score=None,
                    )
                )
        else:
            assessment_col = next((c.header for c in columns if c.role == "assessment"), None)
            score_col = next((c.header for c in columns if c.role == "score"), None)
            _, assessment_text, _ = (
                value(row, assessment_col) if assessment_col else (None, None, False)
            )
            original, current, fixed = value(row, score_col) if score_col else (None, None, False)
            cell = CellResult(
                column=score_col or "",
                assessment_id=None,
                assessment_name=None,
                raw=original,
                value=current,
                fixed=fixed,
                status=None,
                score=None,
            )
            matches = by_key.get(match_key(assessment_text or ""), []) if assessment_text else []
            if not assessment_text:
                cell.issues.append(
                    _err("missing_assessment_name", "Assessment name is blank.", assessment_col)
                )
            elif len(matches) != 1:
                cell.issues.append(
                    _err(
                        "missing_assessment_definition" if not matches else "ambiguous_column",
                        f"'{assessment_text}' does not match exactly one assessment of "
                        f"{snapshot.offering_label}.",
                        assessment_col,
                    )
                )
            else:
                cell.assessment_id, cell.assessment_name = matches[0].id, matches[0].name
                if snapshot.target_assessment_id and matches[0].id != snapshot.target_assessment_id:
                    cell.issues.append(
                        _err(
                            "wrong_assessment",
                            f"Row is for {matches[0].name}, not the assessment being imported.",
                            assessment_col,
                        )
                    )
            result.cells.append(cell)

        for cell in result.cells:
            if cell.issues or cell.assessment_id is None:
                continue
            assessment = by_id[cell.assessment_id]
            explicit_status = None
            if staged.file_format is ImportFormat.LONG:
                status_col = next((c.header for c in columns if c.role == "status"), None)
                max_col = next((c.header for c in columns if c.role == "max"), None)
                if status_col:
                    explicit_status = value(row, status_col)[1]
                if max_col:
                    stated = value(row, max_col)[1]
                    stated_max = _to_decimal((stated or "").strip()) if stated else None
                    if stated and (stated_max is None or stated_max != assessment.max_marks):
                        cell.issues.append(
                            _err(
                                "max_mismatch",
                                f"Max '{stated}' does not match {assessment.name} max "
                                f"{assessment.max_marks}.",
                                max_col,
                            )
                        )
                        continue
            status, score, issues = interpret(
                cell.value,
                assessment.max_marks,
                explicit_status=explicit_status,
                column=cell.column,
            )
            cell.status, cell.score = status, score
            cell.issues.extend(issues)
            pct_col = next((c.header for c in columns if c.role == "percentage"), None)
            if pct_col is not None and status is not None:
                cell.issues.extend(
                    check_percentage(
                        value(row, pct_col)[1],
                        status,
                        score,
                        assessment.max_marks,
                        pct_col,
                    )
                )
            if (
                student is not None
                and status is not None
                and (student.id, assessment.id) not in snapshot.existing
                and (student.enrollment == "DROPPED" or not student.is_active)
            ):
                cell.issues.append(
                    _err(
                        "dropped_student",
                        f"{student.register_number} has dropped the offering or is inactive; new "
                        "results cannot be added.",
                        cell.column,
                    )
                )

    # Duplicate students (wide) / duplicate (student, assessment) pairs (long): all copies fail.
    active_rows = [r for r in results if not r.excluded and r.register_number]
    if staged.file_format is ImportFormat.WIDE:
        by_number: dict[str, list[RowResult]] = defaultdict(list)
        for r in active_rows:
            by_number[r.register_number].append(r)
        for group in by_number.values():
            if len(group) > 1:
                rows = ", ".join(str(r.row) for r in group)
                for r in group:
                    r.issues.append(
                        _err(
                            "duplicate_student_row", f"{r.register_number} appears in rows {rows}."
                        )
                    )
    else:
        by_pair: dict[tuple[str, uuid.UUID], list[tuple[RowResult, CellResult]]] = defaultdict(list)
        for r in active_rows:
            for c in r.cells:
                if c.assessment_id:
                    by_pair[(r.register_number, c.assessment_id)].append((r, c))
        for group in by_pair.values():
            if len(group) > 1:
                rows = ", ".join(str(r.row) for r, _ in group)
                for r, c in group:
                    c.issues.append(
                        _err(
                            "duplicate_student_row",
                            f"{r.register_number} has {c.assessment_name} in rows {rows}.",
                            c.column,
                        )
                    )

    # Decide what each valid cell would do.
    changes: dict[uuid.UUID, list[tuple[uuid.UUID, ResultStatus, Decimal | None]]] = defaultdict(
        list
    )
    counts = Counter()
    for r in results:
        if r.excluded:
            continue
        row_blocked = any(i.level is Level.ERROR for i in r.issues)
        for c in r.cells:
            for issue in c.issues:
                counts[issue.code] += 1
            if row_blocked or column_errors or c.status is None or c.assessment_id is None:
                continue
            if any(i.level is Level.ERROR for i in c.issues) or r.student_id is None:
                continue
            existing = snapshot.existing.get((r.student_id, c.assessment_id))
            if existing is None:
                c.change = "create"
            elif existing == (c.status, c.score):
                c.change = "unchanged"
            else:
                c.change = "update"
            counts[f"change_{c.change}"] += 1
            if c.change != "unchanged":
                changes[c.assessment_id].append((r.student_id, c.status, c.score))

    in_file = {r.student_id for r in results if r.student_id and not r.excluded}
    missing = [s for s in snapshot.cohort if s.id not in in_file]
    global_issues = list(file_issues)
    global_issues.extend(
        metadata_issues(
            snapshot,
            row_count=len(staged.rows),
            absent_count=sum(
                1
                for r in results
                for c in r.cells
                if c.status is ResultStatus.ABSENT and (c.raw or "").strip()
            ),
        )
    )
    if missing:
        global_issues.append(
            _warn(
                "missing_from_file",
                f"{len(missing)} enrolled student(s) are not in the file; "
                "their results stay as they are.",
            )
        )
    if counts["change_update"]:
        global_issues.append(
            _warn(
                "will_overwrite",
                f"{counts['change_update']} existing result(s) will be updated; "
                "old values are kept "
                "in the audit log.",
            )
        )
    if snapshot.duplicate_of:
        global_issues.append(_warn("duplicate_file", snapshot.duplicate_of))
    if staged.skipped_empty_rows:
        global_issues.append(
            _info(
                "empty_rows_skipped",
                f"Skipped empty rows: {', '.join(map(str, staged.skipped_empty_rows[:20]))}"
                + (" ..." if len(staged.skipped_empty_rows) > 20 else ""),
            )
        )

    all_issues = (
        global_issues
        + [i for c in columns for i in c.issues]
        + [i for r in results for i in r.issues]
        + [i for r in results for c in r.cells for i in c.issues]
    )
    level_counts = Counter(i.level for i in all_issues)
    rows_with_errors = sum(1 for r in results if not r.excluded and r.has_error)
    summary = {
        "total_rows": len(results),
        "excluded_rows": sum(1 for r in results if r.excluded),
        "rows_with_errors": rows_with_errors,
        "matched_students": len(in_file),
        "not_found": sum(1 for r in results for i in r.issues if i.code == "unknown_student"),
        "not_enrolled": sum(1 for r in results for i in r.issues if i.code == "not_enrolled"),
        "duplicates": sum(
            1
            for r in results
            for i in [*r.issues, *(x for c in r.cells for x in c.issues)]
            if i.code == "duplicate_student_row"
        ),
        "blank_cells": counts["blank_cell_absent"],
        "absent_markers": counts["absent_marker"],
        "exempt_markers": counts["exempt_marker"],
        "exceeds_max": counts["score_above_max"],
        "invalid_values": counts["invalid_number"]
        + counts["too_many_decimals"]
        + counts["score_below_zero"]
        + counts["invalid_status"],
        "missing_students": len(missing),
        "will_create": counts["change_create"],
        "will_update": counts["change_update"],
        "unchanged": counts["change_unchanged"],
        "cells_to_write": counts["change_create"] + counts["change_update"],
        "errors": level_counts[Level.ERROR],
        "warnings": level_counts[Level.WARNING],
        "infos": level_counts[Level.INFO],
        "duplicate_file": bool(snapshot.duplicate_of),
    }
    summary["can_confirm"] = summary["errors"] == 0 and summary["cells_to_write"] > 0
    return Preview(
        file_format=staged.file_format,
        columns=columns,
        file_issues=global_issues,
        rows=results,
        missing_students=missing,
        summary=summary,
        changes=dict(changes),
    )
