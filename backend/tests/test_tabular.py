"""File parsing used by every importer: raw strings in, nothing coerced to numbers or zero."""

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.core.errors import BusinessRuleError
from app.core.tabular import FileType, UnsupportedFileError, normalise_header, read_table


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
