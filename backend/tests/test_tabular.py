"""File parsing used by every importer: raw strings in, nothing coerced to numbers or zero."""

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.core.errors import BusinessRuleError
from app.core.tabular import (
    FileType,
    UnsupportedFileError,
    normalise_header,
    read_table,
    safe_file_name,
)


def xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_csv_keeps_raw_strings_and_blanks_as_none() -> None:
    table = read_table("m.csv", b"Reg No,Mark\nRA001,007\nRA002,\nRA003,AB\n")
    assert table.file_type is FileType.CSV
    assert table.headers == ["Reg No", "Mark"]
    assert [r["Mark"] for r in table.rows] == ["007", None, "AB"]
    assert table.row_numbers == [2, 3, 4]


def test_csv_semicolon_and_bom() -> None:
    table = read_table("m.csv", "﻿Reg;Name\nRA1;Asha\n".encode())
    assert table.headers == ["Reg", "Name"] and table.rows == [{"Reg": "RA1", "Name": "Asha"}]


def test_xlsx_integers_not_floats_and_row_numbers() -> None:
    content = xlsx([[None], ["Reg", "Mark"], ["RA1", 45], ["RA2", 12.5], [None, None], ["RA3", 0]])
    table = read_table("m.xlsx", content)
    assert table.file_type is FileType.XLSX
    assert [r["Mark"] for r in table.rows] == ["45", "12.5", "0"]
    assert table.row_numbers == [3, 4, 6]
    assert table.skipped_empty_rows == [5]


def test_values_outside_header_rejected() -> None:
    with pytest.raises(BusinessRuleError, match="Row 2"):
        read_table("m.csv", b"A,B\n1,2,3\n")


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("m.pdf", b"%PDF-1.7", "could not be read as a PDF"),
        ("m.pages", b"not a spreadsheet", "Unsupported file type"),
        ("m.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "Legacy .xls"),
        ("m.csv", b"\xff\xfe\x00bad", "not valid UTF-8"),
        ("m.docx", b"PK\x03\x04rest", "not an .xlsx"),
    ],
)
def test_unsupported_files(name: str, content: bytes, message: str) -> None:
    with pytest.raises(UnsupportedFileError, match=message):
        read_table(name, content)


def test_corrupt_xlsx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")
    with pytest.raises(UnsupportedFileError, match="could not be read"):
        read_table("m.xlsx", buffer.getvalue())


def test_empty_and_headerless() -> None:
    with pytest.raises(BusinessRuleError, match="empty"):
        read_table("m.csv", b"")
    with pytest.raises(BusinessRuleError, match="no header"):
        read_table("m.csv", b"\n,\n")


def test_normalise_header() -> None:
    assert normalise_header(" Reg. No ") == "reg_no"
    assert normalise_header("CT-1 (50)") == "ct_1_50"


# ---------------------------------------------------------------- size limits (boundaries)


def _csv(rows: int, columns: int = 3) -> bytes:
    header = ["register_number", "name", "marks"] + [f"extra_{i}" for i in range(columns - 3)]
    lines = [",".join(header)]
    lines += [
        ",".join([f"RA{i:013d}", f"Student {i}", "10"] + [""] * (columns - 3)) for i in range(rows)
    ]
    return ("\n".join(lines) + "\n").encode()


def test_exactly_max_rows_is_accepted() -> None:
    from app.core.tabular import MAX_ROWS

    assert len(read_table("m.csv", _csv(MAX_ROWS)).rows) == MAX_ROWS


def test_one_row_over_the_limit_is_refused() -> None:
    from app.core.tabular import MAX_ROWS

    with pytest.raises(BusinessRuleError, match="Too many rows"):
        read_table("m.csv", _csv(MAX_ROWS + 1))


def test_exactly_max_columns_is_accepted_and_one_more_refused() -> None:
    from app.core.tabular import MAX_COLUMNS

    assert len(read_table("m.csv", _csv(2, columns=MAX_COLUMNS)).headers) == MAX_COLUMNS
    with pytest.raises(BusinessRuleError, match="Too many columns"):
        read_table("m.csv", _csv(2, columns=MAX_COLUMNS + 1))


def test_oversized_file_is_refused_before_parsing() -> None:
    from app.core.tabular import MAX_UPLOAD_BYTES

    with pytest.raises(BusinessRuleError, match="larger than"):
        read_table("m.csv", b"x" * (MAX_UPLOAD_BYTES + 1))


@pytest.mark.parametrize(
    ("sent", "recorded"),
    [
        ("marks.csv", "marks.csv"),
        ("DSA_FJ-II_A1.xlsx", "DSA_FJ-II_A1.xlsx"),
        ("../../etc/passwd.csv", "passwd.csv"),
        ("C:\\Users\\x\\Desktop\\OS_FT2.xlsx", "OS_FT2.xlsx"),
        ("re\x00port\r\n.csv", "report.csv"),
        ("  spaced name.csv  ", "spaced name.csv"),
        ("..", "upload"),
        ("dir/", "upload"),
        ("", "upload"),
        (None, "upload"),
        ("a" * 300 + ".csv", "a" * 255),
    ],
)
def test_safe_file_name_keeps_only_the_last_segment(sent: str | None, recorded: str) -> None:
    assert safe_file_name(sent) == recorded
