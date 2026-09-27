"""Reports: the model, the builders, and the three exports agreeing with each other.

The property that matters most is the last one. CSV, XLSX and PDF are built from a single
:class:`Report`, so "the three formats say the same thing" is checkable rather than hoped
for — `TestCrossFormatConsistency` reads a value out of all three and compares.

Everything else defends the same line the analytics layer draws: insufficient data stays
insufficient, absent stays absent, and nothing acquires a causal claim on its way out of the
system.
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from app.modules.analytics.core.contracts import Intervention
from app.modules.analytics.core.outputs import OBSERVATIONAL_CAVEAT
from app.modules.analytics.core.results import Unit, insufficient_measure
from app.modules.analytics.core.results import measure as make_measure
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import InterventionKind
from app.modules.reports import pdf
from app.modules.reports.builders import (
    attention_report,
    class_report,
    comparison_report,
    intervention_report,
    student_report,
)
from app.modules.reports.exporters import table_to_csv, to_csv, to_pdf, to_xlsx
from app.modules.reports.model import (
    INSUFFICIENT,
    NOT_EVALUATED,
    Cell,
    CellKind,
    Report,
    ReportKind,
    ReportMetadata,
    Section,
    Table,
    measure,
    missing,
    text,
)
from tests.analytics import builders as b
from tests.analytics import canonical as fx

STAMP = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)

FORBIDDEN = (
    "treatment effect",
    "causal",
    "effectiveness",
    "effective intervention",
    "ineffective",
    "proves",
    "proved",
    "resulted from",
    "will fail",
    "at risk of failing",
)
"""Claims a report may never make.

Matched on **word boundaries**: "proved" must not fire inside "improved", which is a
legitimate and required column value ("Target group rose", "improved by at least 5 pp").

"caused" is handled separately. It appears once, by design, inside the observational caveat —
"does not show that the intervention caused the change" — which is a denial of causation, not
a claim of it. `test_the_caveat_is_the_only_place_caused_appears` pins that.
"""


def says(body: str, phrase: str) -> bool:
    """Whether a body of text uses a phrase as words, not as a substring."""
    return re.search(rf"\b{re.escape(phrase)}\b", body) is not None


def thresholds(snapshot) -> ThresholdSet:  # noqa: ANN001
    return resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)


def canonical_class() -> Report:
    snapshot = fx.snapshot()
    return class_report(snapshot, thresholds(snapshot), generated_at=STAMP)


def an_intervention(snapshot, *, targets=(fx.S2, fx.S3, fx.S5), after: int = 2):  # noqa: ANN001
    return Intervention(
        id=uuid.UUID("11111111-2222-4333-8444-555555555555"),
        offering_id=snapshot.offering_id,
        student_ids=tuple(targets),
        kind=InterventionKind.REMEDIAL_SESSION,
        after_sequence_no=after,
        note="weekly remedial sessions",
    )


def csv_lines(report: Report) -> list[str]:
    return to_csv(report).decode("utf-8-sig").splitlines()


def sheet_values(report: Report, sheet_name: str) -> list[list[object]]:
    workbook = load_workbook(io.BytesIO(to_xlsx(report)))
    return [list(row) for row in workbook[sheet_name].iter_rows(values_only=True)]


def pdf_text(report: Report) -> str:
    """The text a reader sees, recovered from the content streams."""
    raw = to_pdf(report).decode("latin-1")
    return " ".join(re.findall(r"\((.*?)\) Tj", raw))


# --------------------------------------------------------------------------- the model


class TestCell:
    def test_a_missing_cell_carries_its_reason_and_no_number(self) -> None:
        cell = missing("only 1 completed assessment (minimum 2)")
        assert cell.is_missing
        assert cell.number is None
        assert cell.text == INSUFFICIENT
        assert "minimum 2" in (cell.note or "")

    def test_a_missing_cell_may_not_carry_a_number(self) -> None:
        with pytest.raises(ValidationError, match="absence is not a value"):
            Cell(text="insufficient data", number=Decimal(0), kind=CellKind.MISSING)

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
    def test_a_cell_cannot_hold_a_non_finite_number(self, bad: str) -> None:
        """Enforced by the field itself, so nothing downstream has to check again."""
        with pytest.raises(ValidationError, match="finite"):
            Cell(text="oops", number=Decimal(bad), kind=CellKind.NUMBER)

    def test_an_insufficient_measure_becomes_an_explained_absence(self) -> None:
        cell = measure(
            insufficient_measure(
                unit=Unit.PERCENT, n=1, minimum_n=2, reason="only 1 completed assessment"
            )
        )
        assert cell.text == INSUFFICIENT
        assert cell.number is None
        assert cell.note == "only 1 completed assessment"

    def test_an_unevaluated_measure_is_distinct_from_an_insufficient_one(self) -> None:
        """The Phase 5 distinction, carried into export."""
        assert measure(None).text == NOT_EVALUATED
        assert (
            measure(insufficient_measure(unit=Unit.PERCENT, n=0, minimum_n=1, reason="none")).text
            == INSUFFICIENT
        )

    def test_a_computed_measure_keeps_its_value_unit_and_n(self) -> None:
        cell = measure(make_measure(Decimal("62.40"), unit=Unit.PERCENT, n=5))
        assert cell.text == "62.40%"
        assert cell.number == Decimal("62.40")
        assert cell.kind is CellKind.PERCENT
        assert cell.note == "n = 5"

    def test_percentage_points_are_labelled_as_points(self) -> None:
        cell = measure(make_measure(Decimal("-4.00"), unit=Unit.PERCENTAGE_POINTS, n=5))
        assert cell.text == "-4.00 pp"
        assert cell.kind is CellKind.PERCENTAGE_POINTS


class TestTableAndReport:
    def test_a_row_must_match_its_headers(self) -> None:
        with pytest.raises(ValidationError, match="cells for"):
            Table(name="t", headers=("a", "b"), rows=((text("only one"),),))

    def test_table_names_must_be_unique(self) -> None:
        duplicate = Table(name="same", headers=("a",), rows=())
        with pytest.raises(ValidationError, match="duplicate table names"):
            Report(
                metadata=ReportMetadata(
                    kind=ReportKind.CLASS_SUMMARY, title="t", generated_at=STAMP
                ),
                sections=(
                    Section(title="one", tables=(duplicate,)),
                    Section(title="two", tables=(duplicate,)),
                ),
            )

    def test_a_report_must_be_stamped_with_a_real_instant(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            ReportMetadata(
                kind=ReportKind.CLASS_SUMMARY,
                title="t",
                generated_at=datetime(2026, 9, 27, 10, 0),
            )

    def test_metadata_omits_what_is_unset(self) -> None:
        described = dict(
            ReportMetadata(
                kind=ReportKind.ATTENTION, title="Attention", generated_at=STAMP
            ).describe()
        )
        assert described["Report"] == "Attention"
        assert "Course" not in described


# ------------------------------------------------------------------------- builders


class TestClassReport:
    def test_the_sections_and_tables_are_stable(self) -> None:
        report = canonical_class()
        assert [s.title for s in report.sections] == [
            "Summary",
            "Assessments",
            "Segments and distribution",
            "Attention",
        ]
        assert [t.name for t in report.tables] == [
            "Class summary",
            "Data coverage",
            "Assessments",
            "Segments",
            "Course score distribution",
            "Flags by severity",
            "Students by rule",
        ]

    def test_the_kpis_are_the_analytics_values(self) -> None:
        """57.36% is class_health's number; the report carries it, it does not recompute."""
        rows = {r[0].text: r[1] for r in canonical_class().table("Class summary").rows}
        assert rows["Class mean (weighted course score)"].text == "57.36%"
        assert rows["Median course score"].text == "55.00%"
        assert rows["Pass rate"].text == "85.71%"
        assert rows["Completion"].text == "85.00%"
        assert rows["Students in cohort"].text == "7"

    def test_assessments_are_in_sequence_order(self) -> None:
        table = canonical_class().table("Assessments")
        assert [row[0].text for row in table.rows] == ["CT1", "CT2", "FT1"]

    def test_an_assessment_row_carries_its_own_statistics(self) -> None:
        table = canonical_class().table("Assessments")
        ct1 = next(row for row in table.rows if row[0].text == "CT1")
        assert ct1[4].text == "63.67%", "mean"
        assert ct1[6].text == "23.96 pp", "std dev"
        assert "RA005" in ct1[9].text, "lowest names its student"

    def test_the_unpublished_assessment_is_not_reported(self) -> None:
        assert "QUIZ1" not in [row[0].text for row in canonical_class().table("Assessments").rows]

    def test_segments_and_attention_counts_are_carried(self) -> None:
        report = canonical_class()
        segments = {row[0].text: row[1].text for row in report.table("Segments").rows}
        assert segments == {"persistently_low": "3", "declining": "2", "high_performer": "1"}
        rules = {row[0].text: row[1].text for row in report.table("Students by rule").rows}
        assert rules["R1_LOW_PERFORMANCE"] == "2"
        assert sum(int(v) for v in rules.values()) == 11

    def test_an_unevaluated_attention_build_says_so_rather_than_showing_zero(self) -> None:
        """A class report built without attention must not read as "nobody needs help"."""
        snapshot = b.build_snapshot({"s1": (30, 30, 30)})
        from app.modules.analytics.core.class_health import class_health
        from app.modules.reports.builders import _coverage_table  # noqa: F401 - sanity

        health = class_health(
            snapshot, thresholds(snapshot), evaluate_attention=False, generated_at=STAMP
        )
        assert health.students_requiring_attention is None


class TestStudentReport:
    def report(self, student=fx.S5, **kwargs) -> Report:  # noqa: ANN001
        snapshot = fx.snapshot()
        return student_report(snapshot, student, thresholds(snapshot), generated_at=STAMP, **kwargs)

    def test_the_history_keeps_every_assessment_including_the_gaps(self) -> None:
        table = self.report(fx.S6).table("Assessment history")
        assert [row[0].text for row in table.rows] == ["CT1", "CT2", "FT1"]
        assert [row[1].text for row in table.rows] == ["absent", "exempt", "assessed"]

    def test_an_absent_result_exports_as_absent_never_as_zero(self) -> None:
        table = self.report(fx.S6).table("Assessment history")
        absent = next(row for row in table.rows if row[1].text == "absent")
        assert absent[2].is_missing, "score"
        assert absent[2].number is None
        assert "not a score of 0" in (absent[2].note or "")
        assert absent[4].is_missing, "percentage"

    def test_an_exempt_result_exports_as_exempt(self) -> None:
        table = self.report(fx.S6).table("Assessment history")
        exempt = next(row for row in table.rows if row[1].text == "exempt")
        assert exempt[2].is_missing
        assert "exempt" in (exempt[2].note or "")

    def test_a_missing_result_exports_as_missing(self) -> None:
        table = self.report(fx.S7).table("Assessment history")
        assert [row[1].text for row in table.rows] == ["assessed", "missing", "missing"]

    def test_the_summary_carries_the_profile_values(self) -> None:
        rows = {row[0].text: row[1] for row in self.report(fx.S5).table("Student summary").rows}
        assert rows["Weighted course score"].text == "33.00%"
        assert rows["Completion"].text == "100.00%"
        assert rows["Trend"].text == "stable"
        assert rows["Segment"].text == "persistently_low"

    def test_an_unclassifiable_trend_is_explained_not_blanked(self) -> None:
        rows = {row[0].text: row[1] for row in self.report(fx.S7).table("Student summary").rows}
        trend = rows["Trend"]
        assert trend.is_missing
        assert "minimum 2" in (trend.note or "")

    def test_findings_that_could_not_be_evaluated_say_so(self) -> None:
        table = self.report(fx.S7).table("Findings")
        decline = next(row for row in table.rows if row[0].text == "sharp_decline")
        assert decline[1].is_missing
        assert decline[1].text == INSUFFICIENT

    def test_attention_flags_appear_in_rule_order(self) -> None:
        table = self.report(fx.S5).table("Flags")
        assert [row[0].text for row in table.rows] == [
            "R1_LOW_PERFORMANCE",
            "R2_FAILED_LATEST",
            "R3_REPEATED_LOW",
        ]

    def test_interventions_appear_when_the_student_is_targeted(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(
            snapshot,
            fx.S5,
            thresholds(snapshot),
            interventions=[an_intervention(snapshot)],
            generated_at=STAMP,
        )
        assert report.table("Interventions") is not None
        assert report.table("Observed outcomes") is not None
        assert OBSERVATIONAL_CAVEAT in report.notes

    def test_an_untargeted_student_gets_no_intervention_section(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(
            snapshot,
            fx.S1,
            thresholds(snapshot),
            interventions=[an_intervention(snapshot)],
            generated_at=STAMP,
        )
        assert report.table("Interventions") is None


class TestAttentionReport:
    def report(self) -> Report:
        snapshot = fx.snapshot()
        return attention_report(snapshot, thresholds(snapshot), generated_at=STAMP)

    def test_the_canonical_totals(self) -> None:
        rows = {row[0].text: row[1].text for row in self.report().table("Attention summary").rows}
        assert rows["Total flags"] == "11"
        assert rows["Flagged students"] == "6"
        assert rows["Students requiring attention"] == "2"

    def test_every_flag_is_a_row_with_its_evidence(self) -> None:
        table = self.report().table("Flags by student")
        assert len(table.rows) == 11
        headers = table.headers
        assert "Threshold source" in headers
        assert "Explanation" in headers

    def test_overlapping_flags_are_all_preserved(self) -> None:
        """S5 fires three rules and appears three times, never collapsed to one reason."""
        rows = [r for r in self.report().table("Flags by student").rows if "RA005" in r[0].text]
        assert [row[2].text for row in rows] == [
            "R1_LOW_PERFORMANCE",
            "R2_FAILED_LATEST",
            "R3_REPEATED_LOW",
        ]

    def test_flags_are_not_reordered_by_severity(self) -> None:
        """R1 (high), R2 (medium), R3 (high): severity order would move R3 up."""
        rows = [r for r in self.report().table("Flags by student").rows if "RA005" in r[0].text]
        assert [row[3].text for row in rows] == ["high", "medium", "high"]

    def test_students_appear_in_cohort_order(self) -> None:
        seen = [row[0].text[:5] for row in self.report().table("Flags by student").rows]
        assert seen == sorted(seen), "register-number order, stable across runs"

    def test_threshold_and_its_source_are_exported(self) -> None:
        row = next(
            r
            for r in self.report().table("Flags by student").rows
            if r[2].text == "R1_LOW_PERFORMANCE"
        )
        assert row[5].text == "50"
        assert row[6].text == "system_default"

    def test_r2_quotes_the_pass_mark_rather_than_a_threshold(self) -> None:
        row = next(
            r
            for r in self.report().table("Flags by student").rows
            if r[2].text == "R2_FAILED_LATEST"
        )
        assert "pass mark" in row[5].text

    def test_students_with_no_flags_are_listed_with_their_reason(self) -> None:
        table = self.report().table("Students with no flags")
        assert [row[0].text[:5] for row in table.rows] == ["RA001"]
        assert "No attention rule fired" in table.rows[0][1].text


class TestComparisonReport:
    def report(self) -> Report:
        snapshot = fx.snapshot()
        return comparison_report(snapshot, thresholds(snapshot), generated_at=STAMP)

    def test_the_movements_are_the_analytics_values(self) -> None:
        rows = {row[0].text: row[1] for row in self.report().table("Movements").rows}
        assert rows["Class mean"].text == "-10.20 pp"
        assert rows["Pass rate"].text == "0.00 pp"

    def test_the_endpoints_name_both_assessments(self) -> None:
        table = self.report().table("Assessments compared")
        assert [row[1].text for row in table.rows] == ["CT2", "FT1"]

    def test_students_who_moved_are_named(self) -> None:
        table = self.report().table("Students who moved")
        declined = next(row for row in table.rows if "Declined" in row[0].text)
        assert declined[1].text == "2"
        assert "RA002" in declined[2].text and "RA003" in declined[2].text

    def test_the_difficulty_caveat_travels_with_the_comparison(self) -> None:
        assert any("difficulty" in note for note in self.report().notes)

    def test_a_first_assessment_reports_no_change_rather_than_zero(self) -> None:
        snapshot = b.build_snapshot({"s1": (60,), "s2": (70,)})
        report = comparison_report(snapshot, thresholds(snapshot), generated_at=STAMP)
        rows = {row[0].text: row[1] for row in report.table("Movements").rows}
        assert rows["Class mean"].is_missing
        assert "first published assessment" in (rows["Class mean"].note or "")


class TestInterventionReport:
    def report(self) -> Report:
        snapshot = fx.snapshot()
        return intervention_report(
            snapshot, [an_intervention(snapshot)], thresholds(snapshot), generated_at=STAMP
        )

    def test_the_outcome_row_carries_both_groups(self) -> None:
        table = self.report().table("Observed outcomes")
        assert table.headers[6] == "Target change"
        assert table.headers[9] == "Observed difference in change"
        assert len(table.rows) == 1

    def test_the_observational_caveat_is_on_the_report(self) -> None:
        assert OBSERVATIONAL_CAVEAT in self.report().notes

    def test_the_headers_never_say_effectiveness(self) -> None:
        for table in self.report().tables:
            for header in table.headers:
                assert "effect" not in header.lower()
                assert "success" not in header.lower()

    def test_an_unmeasurable_outcome_is_explained(self) -> None:
        snapshot = fx.snapshot()
        report = intervention_report(
            snapshot,
            [an_intervention(snapshot, after=3)],
            thresholds(snapshot),
            generated_at=STAMP,
        )
        row = report.table("Observed outcomes").rows[0]
        assert row[2].is_missing, "follow-up"
        assert "no assessment has been held" in (row[2].note or "")


# ------------------------------------------------------------------------ exporters


class TestCsv:
    def test_headers_and_rows_are_written_in_order(self) -> None:
        lines = csv_lines(canonical_class())
        start = lines.index("# Table,Class summary")
        assert lines[start + 1] == "Metric,Value,Note"
        assert lines[start + 2].startswith("Students in cohort,7,")

    def test_the_file_starts_with_a_bom_for_excel(self) -> None:
        assert to_csv(canonical_class()).startswith("﻿".encode())

    def test_line_endings_are_rfc_4180(self) -> None:
        assert b"\r\n" in to_csv(canonical_class())

    def test_a_missing_value_exports_as_words_with_its_reason(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(snapshot, fx.S7, thresholds(snapshot), generated_at=STAMP)
        body = to_csv(report).decode("utf-8-sig")
        assert INSUFFICIENT in body
        assert "minimum 2" in body

    def test_no_nan_or_infinity_reaches_the_file(self) -> None:
        for report in _every_report():
            body = to_csv(report).decode("utf-8-sig")
            assert "NaN" not in body
            assert "Infinity" not in body
            assert "inf," not in body

    def test_no_python_object_repr_leaks(self) -> None:
        for report in _every_report():
            body = to_csv(report).decode("utf-8-sig")
            assert "object at 0x" not in body
            assert "Decimal(" not in body
            assert "UUID(" not in body

    def test_repeated_export_is_byte_identical(self) -> None:
        report = canonical_class()
        assert to_csv(report) == to_csv(report)

    def test_a_single_table_can_be_exported_alone(self) -> None:
        table = canonical_class().table("Assessments")
        lines = table_to_csv(table).decode("utf-8-sig").splitlines()
        assert lines[0].startswith("Assessment,Max marks")
        assert len(lines) == len(table.rows) + 1


class TestXlsx:
    def test_the_workbook_has_a_cover_and_one_sheet_per_table(self) -> None:
        report = canonical_class()
        workbook = load_workbook(io.BytesIO(to_xlsx(report)))
        assert workbook.sheetnames[0] == "Report"
        assert len(workbook.sheetnames) == len(report.tables) + 1
        assert "Class summary" in workbook.sheetnames

    def test_sheet_names_stay_within_excels_limit(self) -> None:
        for report in _every_report():
            workbook = load_workbook(io.BytesIO(to_xlsx(report)))
            for name in workbook.sheetnames:
                assert len(name) <= 31

    def test_numbers_are_written_as_numbers(self) -> None:
        """So a reader can sum a column, rather than receiving a picture of one."""
        rows = sheet_values(canonical_class(), "Class summary")
        cohort = next(row for row in rows if row and row[0] == "Students in cohort")
        assert cohort[1] == 7
        assert isinstance(cohort[1], (int, float))

    def test_a_percentage_keeps_the_analytics_digits(self) -> None:
        rows = sheet_values(canonical_class(), "Class summary")
        mean = next(row for row in rows if row and row[0] == "Class mean (weighted course score)")
        assert mean[1] == pytest.approx(57.36)

    def test_a_missing_value_is_words_not_an_empty_cell(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(snapshot, fx.S7, thresholds(snapshot), generated_at=STAMP)
        rows = sheet_values(report, "Student summary")
        trend = next(row for row in rows if row and row[0] == "Trend")
        assert isinstance(trend[1], str)
        assert INSUFFICIENT in trend[1]

    def test_row_order_matches_the_report(self) -> None:
        report = canonical_class()
        rows = sheet_values(report, "Assessments")
        codes = [row[0] for row in rows if row and row[0] in {"CT1", "CT2", "FT1"}]
        assert codes == ["CT1", "CT2", "FT1"]

    def test_the_workbook_contains_no_formulas(self) -> None:
        """A formula would be a second source of truth that could disagree with analytics."""
        workbook = load_workbook(io.BytesIO(to_xlsx(canonical_class())))
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                for value in row:
                    assert not (isinstance(value, str) and value.startswith("="))

    def test_every_report_produces_a_readable_workbook(self) -> None:
        for report in _every_report():
            workbook = load_workbook(io.BytesIO(to_xlsx(report)))
            assert workbook.sheetnames


class TestPdf:
    def test_the_file_is_a_well_formed_pdf(self) -> None:
        raw = to_pdf(canonical_class())
        assert raw.startswith(b"%PDF-1.4")
        assert raw.rstrip().endswith(b"%%EOF")
        assert b"xref" in raw and b"trailer" in raw

    def test_the_cross_reference_offset_is_correct(self) -> None:
        """A wrong offset makes the file unopenable in a strict reader."""
        raw = to_pdf(canonical_class())
        offset = int(re.search(rb"startxref\s+(\d+)", raw).group(1))
        assert raw[offset : offset + 4] == b"xref"

    def test_long_reports_paginate(self) -> None:
        raw = to_pdf(attention_report(fx.snapshot(), thresholds(fx.snapshot()), generated_at=STAMP))
        assert len(re.findall(rb"/Type /Page[^s]", raw)) >= 2

    def test_the_title_and_metadata_are_printed(self) -> None:
        body = pdf_text(canonical_class())
        assert "Class summary" in body
        assert "Generated" in body

    def test_the_sections_are_printed(self) -> None:
        body = pdf_text(canonical_class())
        for title in ("Summary", "Assessments", "Segments and distribution"):
            assert title in body

    def test_the_numbers_reach_the_page(self) -> None:
        body = pdf_text(canonical_class())
        assert "57.36" in body
        assert "85.71" in body

    def test_insufficient_data_is_worded_on_the_page(self) -> None:
        snapshot = fx.snapshot()
        body = pdf_text(student_report(snapshot, fx.S7, thresholds(snapshot), generated_at=STAMP))
        assert INSUFFICIENT in body

    def test_the_observational_caveat_reaches_the_page(self) -> None:
        snapshot = fx.snapshot()
        report = intervention_report(
            snapshot, [an_intervention(snapshot)], thresholds(snapshot), generated_at=STAMP
        )
        body = pdf_text(report)
        assert "Observed change only" in body
        assert "does not show that the intervention caused" in body

    def test_no_forbidden_causal_wording_is_printed(self) -> None:
        for report in _every_report():
            body = pdf_text(report).lower()
            for banned in FORBIDDEN:
                assert not says(body, banned), f"{banned!r} printed in {report.metadata.title}"

    def test_repeated_export_is_byte_identical(self) -> None:
        report = canonical_class()
        assert to_pdf(report) == to_pdf(report)

    def test_parentheses_in_data_do_not_corrupt_the_file(self) -> None:
        """Unescaped parens would end the PDF string early and break the document."""
        document = pdf.Document()
        document.line("a (tricky) value with \\ backslash")
        raw = pdf.render(document)
        assert rb"\(tricky\)" in raw
        assert raw.rstrip().endswith(b"%%EOF")

    def test_long_words_are_broken_rather_than_running_off_the_page(self) -> None:
        lines = pdf.wrap("x" * 400)
        assert len(lines) > 1
        assert all(len(line) <= 140 for line in lines)


# --------------------------------------------------------------- cross-format agreement


class TestCrossFormatConsistency:
    """The same source analytics must mean the same thing in all three formats."""

    @pytest.mark.parametrize(
        ("metric", "expected"),
        [
            ("Class mean (weighted course score)", "57.36"),
            ("Median course score", "55.00"),
            ("Pass rate", "85.71"),
            ("Completion", "85.00"),
        ],
    )
    def test_a_kpi_reads_the_same_in_csv_xlsx_and_pdf(self, metric: str, expected: str) -> None:
        report = canonical_class()

        csv_row = next(
            line
            for line in csv_lines(report)
            if line.startswith(f"{metric},") or line.startswith(f'"{metric}",')
        )
        assert expected in csv_row

        xlsx_row = next(
            row for row in sheet_values(report, "Class summary") if row and row[0] == metric
        )
        # XLSX stores a number, so 55.00 arrives as 55: compare numerically, not by text.
        assert float(xlsx_row[1]) == pytest.approx(float(expected))

        assert expected in pdf_text(report)

    def test_the_attention_totals_agree_across_formats(self) -> None:
        report = attention_report(fx.snapshot(), thresholds(fx.snapshot()), generated_at=STAMP)
        assert "Total flags,11" in "\n".join(csv_lines(report))
        rows = sheet_values(report, "Attention summary")
        assert next(r for r in rows if r and r[0] == "Total flags")[1] == 11
        assert "11" in pdf_text(report)

    def test_every_table_row_count_matches_across_csv_and_xlsx(self) -> None:
        report = canonical_class()
        for table in report.tables:
            csv_body = table_to_csv(table).decode("utf-8-sig").splitlines()
            assert len(csv_body) == len(table.rows) + 1
            sheet = sheet_values(report, table.name)
            data_rows = [row for row in sheet if row and row[0] not in (None, table.name, "Note")]
            assert len(data_rows) >= len(table.rows)

    def test_an_absent_result_is_absent_in_all_three(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(snapshot, fx.S6, thresholds(snapshot), generated_at=STAMP)
        assert "absent" in "\n".join(csv_lines(report))
        assert any(
            "absent" in str(value)
            for row in sheet_values(report, "Assessment history")
            for value in row
            if value
        )
        assert "absent" in pdf_text(report)

    def test_no_format_ever_turns_a_gap_into_a_zero(self) -> None:
        snapshot = fx.snapshot()
        report = student_report(snapshot, fx.S6, thresholds(snapshot), generated_at=STAMP)
        history = report.table("Assessment history")
        absent = next(row for row in history.rows if row[1].text == "absent")
        assert absent[2].number is None
        sheet = sheet_values(report, "Assessment history")
        absent_sheet = next(row for row in sheet if row and row[1] == "absent")
        assert absent_sheet[2] != 0


class TestDeterminismAndSafety:
    def test_the_same_report_renders_identically_every_time(self) -> None:
        for report in _every_report():
            assert to_csv(report) == to_csv(report)
            assert to_pdf(report) == to_pdf(report)

    def test_row_order_follows_the_snapshots_cohort_order(self) -> None:
        """The documented rule, stated as a test so it cannot drift.

        Report order *is* snapshot order — reversing the cohort reverses the rows. That is
        the deterministic contract, not an accident: the snapshot decides who comes first
        (the platform returns students by register number), and the report does not re-sort.
        """
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(update={"students": tuple(reversed(snapshot.students))})
        forwards = attention_report(snapshot, thresholds(snapshot), generated_at=STAMP)
        backwards = attention_report(reordered, thresholds(reordered), generated_at=STAMP)

        def students(report: Report) -> list[str]:
            return [row[0].text[:5] for row in report.table("Flags by student").rows]

        assert students(forwards) == sorted(students(forwards))
        assert students(backwards) == sorted(students(backwards), reverse=True)
        assert set(students(forwards)) == set(students(backwards)), "same students either way"

    def test_the_same_snapshot_always_renders_the_same_bytes(self) -> None:
        snapshot = fx.snapshot()
        first = attention_report(snapshot, thresholds(snapshot), generated_at=STAMP)
        second = attention_report(fx.snapshot(), thresholds(fx.snapshot()), generated_at=STAMP)
        assert to_csv(first) == to_csv(second)
        assert to_pdf(first) == to_pdf(second)

    def test_no_report_exposes_a_secret_or_an_internal_identifier(self) -> None:
        for report in _every_report():
            body = to_csv(report).decode("utf-8-sig").lower()
            for secret in ("password", "token", "jwt", "secret", "postgresql://", "traceback"):
                assert secret not in body

    def test_no_forbidden_causal_wording_in_any_export(self) -> None:
        for report in _every_report():
            for body in (
                to_csv(report).decode("utf-8-sig").lower(),
                pdf_text(report).lower(),
            ):
                for banned in FORBIDDEN:
                    assert not says(body, banned), f"{banned!r} in {report.metadata.title}"

    def test_the_caveat_is_the_only_place_caused_appears(self) -> None:
        snapshot = fx.snapshot()
        report = intervention_report(
            snapshot, [an_intervention(snapshot)], thresholds(snapshot), generated_at=STAMP
        )
        body = to_csv(report).decode("utf-8-sig")
        for line in body.splitlines():
            if "caused" in line:
                assert "does not show that the intervention caused" in line

    @pytest.mark.parametrize("scenario", sorted(b.SCENARIOS))
    def test_every_scenario_exports_in_all_three_formats(self, scenario: str) -> None:
        snapshot = b.SCENARIOS[scenario]()
        if not snapshot.ordered_assessments():
            pytest.skip("no published assessment to report on")
        report = class_report(snapshot, thresholds(snapshot), generated_at=STAMP)
        assert to_csv(report)
        assert to_xlsx(report)
        assert to_pdf(report).startswith(b"%PDF")


def _every_report() -> list[Report]:
    """One of each report type, for the sweeps."""
    snapshot = fx.snapshot()
    resolved = thresholds(snapshot)
    return [
        class_report(snapshot, resolved, generated_at=STAMP),
        student_report(snapshot, fx.S5, resolved, generated_at=STAMP),
        attention_report(snapshot, resolved, generated_at=STAMP),
        comparison_report(snapshot, resolved, generated_at=STAMP),
        intervention_report(snapshot, [an_intervention(snapshot)], resolved, generated_at=STAMP),
    ]
