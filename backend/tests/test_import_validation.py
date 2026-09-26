"""The import validation engine, tested as a pure function (no database).

One test per validation rule from the Agent 1 brief and blueprint §13.2.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.assessments.models import ResultStatus
from app.modules.imports.models import ImportFormat
from app.modules.imports.validation import (
    AssessmentRef,
    FileRejectedError,
    Snapshot,
    Staged,
    StudentRef,
    check_headers,
    detect_format,
    fix_key,
    header_key,
    header_max,
    interpret,
    validate,
)

CT1 = AssessmentRef(uuid.uuid4(), "CT1", Decimal("50"))
CT2 = AssessmentRef(uuid.uuid4(), "CT2", Decimal("50"))
FT1 = AssessmentRef(uuid.uuid4(), "FT1", Decimal("100"))


def student(
    n: int, name: str, enrollment: str | None = "ACTIVE", active: bool = True
) -> StudentRef:
    return StudentRef(uuid.uuid4(), f"RA25{n:011d}", name, active, enrollment)


ASHA = student(1, "Asha Rao")
VIKRAM = student(2, "Vikram Singh")
MEERA = student(3, "Meera Iyer")
COHORT = [ASHA, VIKRAM, MEERA]


def snapshot(**overrides) -> Snapshot:
    values = dict(
        offering_label="21CSC201J / A1 / 2026-ODD",
        assessments=[CT1, CT2, FT1],
        students={s.register_number: s for s in COHORT},
        cohort=COHORT,
        existing={},
    )
    values.update(overrides)
    return Snapshot(**values)


def staged(headers: list[str], *rows: list, fmt: ImportFormat | None = None, **extra) -> Staged:
    return Staged(
        file_format=fmt or detect_format(headers),
        headers=headers,
        rows=[
            {"row": i + 2, "values": dict(zip(headers, r, strict=True))} for i, r in enumerate(rows)
        ],
        **extra,
    )


def codes(preview) -> set[str]:
    found = {i.code for i in preview.file_issues}
    found |= {i.code for c in preview.columns for i in c.issues}
    for row in preview.rows:
        found |= {i.code for i in row.issues}
        found |= {i.code for c in row.cells for i in c.issues}
    return found


def cell(preview, row: int, column: str):
    r = next(r for r in preview.rows if r.row == row)
    return next(c for c in r.cells if c.column == column)


# ------------------------------------------------------------------------ happy path


def test_wide_sheet_maps_columns_and_values() -> None:
    preview = validate(
        staged(
            ["Reg No", "Name", "CT1 (max 50)", "ct2", "Remarks"],
            [ASHA.register_number, "Asha Rao", "45", "AB", "good"],
            [VIKRAM.register_number.lower(), "Vikram Singh", "12.5", "EX", ""],
            [MEERA.register_number, "Meera Iyer", "0", "", None],
        ),
        snapshot(),
    )
    assert preview.file_format is ImportFormat.WIDE
    roles = {c.header: (c.role, c.assessment_name) for c in preview.columns}
    assert roles == {
        "Reg No": ("identity", None),
        "Name": ("name", None),
        "CT1 (max 50)": ("assessment", "CT1"),
        "ct2": ("assessment", "CT2"),
        "Remarks": ("ignored", None),
    }
    assert (cell(preview, 2, "CT1 (max 50)").status, cell(preview, 2, "CT1 (max 50)").score) == (
        ResultStatus.PRESENT,
        Decimal("45"),
    )
    assert cell(preview, 2, "ct2").status is ResultStatus.ABSENT
    assert cell(preview, 3, "ct2").status is ResultStatus.EXEMPT
    zero = cell(preview, 4, "CT1 (max 50)")
    assert (zero.status, zero.score) == (ResultStatus.PRESENT, Decimal("0"))
    blank = cell(preview, 4, "ct2")
    assert (blank.status, blank.score) == (ResultStatus.ABSENT, None)
    assert [i.code for i in blank.issues] == ["blank_cell_absent"]
    assert preview.summary["errors"] == 0 and preview.summary["can_confirm"]
    assert preview.summary["will_create"] == 6 and preview.summary["blank_cells"] == 1
    assert len(preview.changes[CT1.id]) == 3


def test_long_sheet() -> None:
    preview = validate(
        staged(
            [
                "Register No",
                "Student Name",
                "Assessment",
                "Score",
                "Max Score",
                "Percentage",
                "Status",
            ],
            [ASHA.register_number, "Asha Rao", "CT1", "40", "50", "80", ""],
            [ASHA.register_number, "Asha Rao", "FT1", "", "100", "", "Absent"],
            [VIKRAM.register_number, "Vikram Singh", "ct1", "25", "", "50%", "present"],
        ),
        snapshot(),
    )
    assert preview.file_format is ImportFormat.LONG
    assert preview.summary["errors"] == 0, codes(preview)
    assert cell(preview, 3, "Score").status is ResultStatus.ABSENT
    assert {a for a in preview.changes} == {CT1.id, FT1.id}


# ------------------------------------------------------------------------ file level


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        (["Name", "CT1"], "missing_identity_column"),
        (["Reg No", "Register Number", "CT1"], "ambiguous_identity_column"),
        (["Reg No", "CT1", "ct1 "], "duplicate_header"),
    ],
)
def test_file_blocking_headers(headers: list[str], code: str) -> None:
    with pytest.raises(FileRejectedError) as exc:
        check_headers(headers, [])
    assert code in {i.code for i in exc.value.issues}


def test_header_without_name_but_with_data_rejected() -> None:
    with pytest.raises(FileRejectedError) as exc:
        check_headers(["Reg No", ""], [{"row": 2, "values": {"Reg No": "RA1", "": "45"}}])
    assert exc.value.issues[0].code == "malformed_header"


def test_missing_assessment_definition_blocks_everything() -> None:
    preview = validate(
        staged(["Reg No", "CT1", "CT3"], [ASHA.register_number, "40", "30"]), snapshot()
    )
    assert "missing_assessment_definition" in codes(preview)
    assert preview.summary["errors"] == 1 and not preview.summary["can_confirm"]
    assert preview.changes == {}  # a column problem blocks the whole import


def test_mapping_resolves_unknown_column() -> None:
    sheet = staged(["Reg No", "Cycle Test II"], [ASHA.register_number, "40"])
    sheet.column_mapping = {"Cycle Test II": str(CT2.id)}
    preview = validate(sheet, snapshot())
    assert preview.summary["errors"] == 0 and preview.columns[1].mapped_by == "user"
    sheet.column_mapping = {"Cycle Test II": "ignore"}
    ignored = validate(sheet, snapshot())
    assert "no_assessment_columns" in codes(ignored)


def test_duplicate_assessment_column() -> None:
    preview = validate(
        staged(["Reg No", "CT1", "CT-1"], [ASHA.register_number, "40", "41"]),
        snapshot(assessments=[CT1]),
    )
    assert "duplicate_assessment_column" in codes(preview)


def test_ambiguous_column_mapping() -> None:
    twin = AssessmentRef(uuid.uuid4(), "CT 1", Decimal("50"))
    preview = validate(
        staged(["Reg No", "ct1"], [ASHA.register_number, "40"]),
        snapshot(assessments=[CT1, twin]),
    )
    assert "ambiguous_column" in codes(preview)


def test_header_max_must_match() -> None:
    preview = validate(staged(["Reg No", "CT1 (max 60)"], [ASHA.register_number, "40"]), snapshot())
    assert "max_mismatch" in codes(preview)


def test_single_assessment_import() -> None:
    preview = validate(
        staged(["Reg No", "Marks", "CT2"], [ASHA.register_number, "40", "10"]),
        snapshot(target_assessment_id=CT1.id),
    )
    marks = next(c for c in preview.columns if c.header == "Marks")
    assert marks.assessment_id == CT1.id
    assert "wrong_assessment" in codes(preview)


# ------------------------------------------------------------------------ row level


def test_unknown_not_enrolled_and_blank_register_numbers() -> None:
    outsider = student(9, "Outsider", enrollment=None)
    preview = validate(
        staged(
            ["Reg No", "CT1"],
            ["RA0000000000001", "40"],
            [outsider.register_number, "40"],
            ["", "40"],
        ),
        snapshot(
            students={**{s.register_number: s for s in COHORT}, outsider.register_number: outsider}
        ),
    )
    assert {"unknown_student", "not_enrolled", "missing_register_number"} <= codes(preview)
    assert preview.summary["not_found"] == 1 and preview.summary["not_enrolled"] == 1


def test_duplicate_student_rows_flag_every_copy() -> None:
    preview = validate(
        staged(
            ["Reg No", "CT1"],
            [ASHA.register_number, "40"],
            [VIKRAM.register_number, "30"],
            [ASHA.register_number.lower(), "41"],
        ),
        snapshot(),
    )
    flagged = [
        r.row for r in preview.rows if any(i.code == "duplicate_student_row" for i in r.issues)
    ]
    assert flagged == [2, 4]
    assert CT1.id in preview.changes and len(preview.changes[CT1.id]) == 1  # Vikram only


def test_duplicate_pair_in_long_sheet() -> None:
    preview = validate(
        staged(
            ["Reg No", "Assessment", "Score"],
            [ASHA.register_number, "CT1", "40"],
            [ASHA.register_number, "ct1", "41"],
            [ASHA.register_number, "CT2", "41"],
        ),
        snapshot(),
    )
    assert preview.summary["duplicates"] == 2
    assert list(preview.changes) == [CT2.id]


def test_conflicting_identity_vs_name_mismatch() -> None:
    preview = validate(
        staged(
            ["Reg No", "Name", "CT1"],
            [ASHA.register_number, "Vikram Singh", "40"],  # another student's name
            [VIKRAM.register_number, "Ravi Kumar", "30"],  # just different
            [MEERA.register_number, "meera  iyer.", "20"],  # formatting only
        ),
        snapshot(),
    )
    by_row = {r.row: {i.code for i in r.issues} for r in preview.rows}
    assert by_row == {2: {"conflicting_identity"}, 3: {"name_mismatch"}, 4: set()}


def test_dropped_student_cannot_get_new_results() -> None:
    dropped = student(5, "Dropped", enrollment="DROPPED")
    preview = validate(
        staged(["Reg No", "CT1"], [dropped.register_number, "40"]),
        snapshot(students={dropped.register_number: dropped}),
    )
    assert "dropped_student" in codes(preview)


def test_excluded_rows_are_skipped() -> None:
    sheet = staged(["Reg No", "CT1"], [ASHA.register_number, "400"], [VIKRAM.register_number, "40"])
    sheet.excluded_rows = [2]
    preview = validate(sheet, snapshot())
    assert preview.summary["errors"] == 0 and preview.summary["excluded_rows"] == 1
    assert [c[0] for c in preview.changes[CT1.id]] == [VIKRAM.id]


# ------------------------------------------------------------------------ cell level


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("twelve", "invalid_number"),
        ("12,5", "invalid_number"),
        ("1e3", "invalid_number"),
        ("12.345", "too_many_decimals"),
        ("-1", "score_below_zero"),
        ("50.01", "score_above_max"),
    ],
)
def test_bad_values(raw: str, code: str) -> None:
    status, score, issues = interpret(raw, Decimal("50"))
    assert (status, score) == (None, None)
    assert [i.code for i in issues] == [code]


@pytest.mark.parametrize("raw", ["AB", "ab", "A", "-", "Absent"])
def test_absent_markers(raw: str) -> None:
    status, score, issues = interpret(raw, Decimal("50"))
    assert (status, score) == (ResultStatus.ABSENT, None)
    assert issues[0].level.value == "info"


def test_status_column_rules() -> None:
    assert interpret("", Decimal("50"), explicit_status="exempt")[0] is ResultStatus.EXEMPT
    assert interpret("", Decimal("50"), explicit_status="present")[2][0].code == "missing_score"
    assert (
        interpret("30", Decimal("50"), explicit_status="absent")[2][0].code == "conflicting_status"
    )
    assert interpret("30", Decimal("50"), explicit_status="sick")[2][0].code == "invalid_status"


@pytest.mark.parametrize(
    ("score", "percentage", "ok"),
    [
        ("40", "80", True),
        ("40", "80.4", True),
        ("40", "75", False),
        ("40", "120", False),
        ("", "50", False),
        ("40", "abc", False),
    ],
)
def test_impossible_percentage(score: str, percentage: str, ok: bool) -> None:
    preview = validate(
        staged(
            ["Reg No", "Assessment", "Score", "Percentage"],
            [ASHA.register_number, "CT1", score, percentage],
        ),
        snapshot(),
    )
    assert ("impossible_percentage" not in codes(preview)) is ok


def test_long_max_column_must_match() -> None:
    preview = validate(
        staged(
            ["Reg No", "Assessment", "Score", "Max Marks"],
            [ASHA.register_number, "CT1", "40", "60"],
        ),
        snapshot(),
    )
    assert "max_mismatch" in codes(preview)


# ------------------------------------------------------------------------ fixes & warnings


def test_fix_turns_blank_into_explicit_zero() -> None:
    sheet = staged(["Reg No", "CT1"], [ASHA.register_number, None])
    assert cell(validate(sheet, snapshot()), 2, "CT1").status is ResultStatus.ABSENT
    sheet.fixes = {fix_key(2, "CT1"): {"value": "0"}}
    fixed = cell(validate(sheet, snapshot()), 2, "CT1")
    assert (fixed.status, fixed.score, fixed.fixed, fixed.raw) == (
        ResultStatus.PRESENT,
        Decimal("0"),
        True,
        None,
    )


def test_overwrite_unchanged_and_missing_students() -> None:
    existing = {
        (ASHA.id, CT1.id): (ResultStatus.PRESENT, Decimal("40")),
        (VIKRAM.id, CT1.id): (ResultStatus.PRESENT, Decimal("10")),
    }
    preview = validate(
        staged(["Reg No", "CT1"], [ASHA.register_number, "40"], [VIKRAM.register_number, "11"]),
        snapshot(existing=existing, duplicate_of="Imported before."),
    )
    s = preview.summary
    assert (s["unchanged"], s["will_update"], s["will_create"], s["missing_students"]) == (
        1,
        1,
        0,
        1,
    )
    assert {"will_overwrite", "missing_from_file", "duplicate_file"} <= codes(preview)
    assert preview.changes == {CT1.id: [(VIKRAM.id, ResultStatus.PRESENT, Decimal("11"))]}


def test_nothing_to_write_cannot_confirm() -> None:
    existing = {(ASHA.id, CT1.id): (ResultStatus.ABSENT, None)}
    preview = validate(
        staged(["Reg No", "CT1"], [ASHA.register_number, "AB"]), snapshot(existing=existing)
    )
    assert preview.summary["errors"] == 0 and preview.summary["can_confirm"] is False


def test_header_helpers() -> None:
    assert header_key("CT1 (max 50)") == "ct1"
    assert header_key("CT-1 /50") == "ct_1"
    assert header_key("Quiz 2 out of 10") == "quiz_2"
    assert header_max("CT1 (max 50)") == Decimal("50")
    assert header_max("Quiz / 10") == Decimal("10")
    assert header_max("CT1") is None
