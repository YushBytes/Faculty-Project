"""Scope reports (faculty, section, course, coordinator, academic head, department,
institution) in CSV, XLSX and a presentation PDF.

Built **from the same overview object the dashboard renders** — one aggregation, laid out
three ways — so a dashboard that says 72.4 % and the report downloaded from it cannot disagree.
Conclusions are sentences over measured values only: which assessment moved most, which
groups sit highest and lowest, how complete the data is. Nothing causal, no scores invented.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.reports.exporters import to_csv, to_xlsx
from app.modules.reports.model import (
    Cell,
    CellKind,
    Report,
    ReportKind,
    ReportMetadata,
    Section,
    Table,
    count,
    missing,
    percent,
    text,
)

INSTITUTION = "SRM Institute of Science and Technology"
KINDS = ("summary", "attention", "comparison")
RULE_NAMES = {
    "R1_LOW_PERFORMANCE": "Low performance",
    "R2_FAILED_LATEST": "Below pass mark in latest assessment",
    "R3_REPEATED_LOW": "Repeated low performance",
    "R4_SHARP_DECLINE": "Sharp decline",
    "R5_DECLINING_TREND": "Declining trend",
    "R6_LOW_COMPLETION": "Low completion",
    "R7_BORDERLINE": "Borderline",
}


def _pct(m: dict[str, Any] | None) -> Cell:
    if not m or m.get("value") is None:
        return missing((m or {}).get("reason") or "no value was computed")
    return percent(Decimal(str(m["value"])).quantize(Decimal("0.01")))


def _fmt(m: dict[str, Any] | None) -> str:
    if not m or m.get("value") is None:
        return "insufficient data"
    return f"{m['value']:.2f}%"


def title_for(overview: dict[str, Any], role: str) -> str:
    crumbs = overview["scope"]["crumbs"]
    last = crumbs[-1] if crumbs else None
    if last:
        return {
            "department": f"Department Performance Report — {last['label']}",
            "course": f"Course Report — {last['label']}",
            "coordinator": f"Course Coordinator Report — {last['label']}",
            "faculty": f"Faculty Report — {last['label']}",
            "section": f"Section Report — {last['label']}",
            "offering": f"Class Report — {last['label']}",
        }[last["kind"]]
    return {
        "ADMIN": "Institution Performance Report",
        "HOD": "Department Performance Report",
        "ACADEMIC_HEAD": "Academic Portfolio Report",
        "COURSE_COORDINATOR": "Course Coordinator Report",
        "FACULTY": "Faculty Report",
    }[role]


def conclusions(overview: dict[str, Any]) -> list[str]:
    """Plain statements of measured values, in a fixed order."""
    k, counts, lines = overview["kpis"], overview["counts"], []
    if k["average"]["value"] is None:
        return ["No published assessment results are available for this scope and period."]
    lines.append(
        f"The average weighted course score is {_fmt(k['average'])} across {k['scored']} "
        f"student course scores (median {_fmt(k['median'])}), from {counts['offerings']} "
        f"class(es) in {counts['sections']} section(s)."
    )
    lines.append(
        f"{_fmt(k['pass_percent'])} of students with a course score are at or above their pass "
        f"mark; {k['failed']} are below it. {k['not_scored']} enrolled student(s) have no course "
        "score yet and are not counted as failures."
    )
    if k["completion_percent"]["value"] is not None:
        lines.append(
            f"Assessment completion is {_fmt(k['completion_percent'])} "
            f"({k['coverage'].get('absent', 0)} absent, {k['coverage'].get('missing', 0)} "
            f"missing, {k['coverage'].get('exempt', 0)} exempt sittings)."
        )
    moves = [t for t in overview["trend"] if t["change"] is not None]
    if moves:
        biggest = max(moves, key=lambda t: abs(t["change"]))
        direction = "rose" if biggest["change"] > 0 else "fell"
        lines.append(
            f"The largest movement between consecutive assessments: the mean {direction} by "
            f"{abs(biggest['change']):.2f} percentage points to {_fmt(biggest['mean'])} at "
            f"{biggest['name']}."
        )
    for label, rows in (
        ("section", overview["comparisons"]["sections"]),
        ("faculty member", overview["comparisons"]["faculty"]),
        ("course", overview["comparisons"]["courses"]),
    ):
        ranked = [r for r in rows if r["average"]["value"] is not None]
        if len(ranked) >= 2:
            hi = max(ranked, key=lambda r: r["average"]["value"])
            lo = min(ranked, key=lambda r: r["average"]["value"])
            lines.append(
                f"Across {len(ranked)} {label}s the average ranges from {_fmt(lo['average'])} "
                f"({lo['label']}) to {_fmt(hi['average'])} ({hi['label']})."
            )
    if k["attention_students"]:
        lines.append(
            f"{k['attention_students']} student(s) meet the attention escalation rule; "
            f"{k['flagged_students']} have at least one attention flag."
        )
    lines.append(
        "These are observed measurements. They describe what happened, not why; differences "
        "between groups can reflect paper difficulty, cohort and timing as well as teaching."
    )
    return lines


def _comparison_table(name: str, rows: list[dict], first: str) -> Table:
    return Table(
        name=name,
        headers=(
            first,
            "Sections",
            "Students scored",
            "Average",
            "Median",
            "Pass %",
            "Completion",
            "Attention",
        ),
        rows=tuple(
            (
                text(r["label"]),
                count(r["sections"]),
                count(r["scored"]),
                _pct(r["average"]),
                _pct(r["median"]),
                _pct(r["pass_percent"]),
                _pct(r["completion_percent"]),
                count(r["attention_students"]),
            )
            for r in rows
        ),
    )


def build(
    overview: dict[str, Any], *, kind: str, role: str, generated_at: datetime | None = None
) -> Report:
    stamp = generated_at or datetime.now(UTC)
    k = overview["kpis"]
    sections: list[Section] = []
    kpi_rows = (
        (text("Students (distinct)"), count(overview["counts"]["students"])),
        (text("Sections"), count(overview["counts"]["sections"])),
        (text("Courses"), count(overview["counts"]["courses"])),
        (text("Faculty"), count(overview["counts"]["faculty"])),
        (text("Average course score"), _pct(k["average"])),
        (text("Median course score"), _pct(k["median"])),
        (text("Standard deviation (pp)"), _pct(k["std_dev"])),
        (text("Pass %"), _pct(k["pass_percent"])),
        (text("Below pass mark %"), _pct(k["fail_percent"])),
        (text("Completion %"), _pct(k["completion_percent"])),
        (text("Students requiring attention"), count(k["attention_students"])),
    )
    sections.append(
        Section(
            title="Summary",
            summary=" ".join(conclusions(overview)),
            tables=(Table(name="Key measures", headers=("Measure", "Value"), rows=kpi_rows),),
            notes=(
                "Averages are over each student's weighted course score in each class; absent, "
                "exempt and missing results are never counted as zero.",
            ),
        )
    )
    if kind in ("summary", "comparison"):
        sections.append(
            Section(
                title="Assessment analysis",
                tables=(
                    Table(
                        name="Assessments",
                        headers=(
                            "Assessment",
                            "Classes",
                            "Mean",
                            "Median",
                            "Pass %",
                            "Completion",
                            "Change (pp)",
                        ),
                        rows=tuple(
                            (
                                text(t["name"]),
                                count(t["offerings"]),
                                _pct(t["mean"]),
                                _pct(t["median"]),
                                _pct(t["pass_percent"]),
                                _pct(t["completion_percent"]),
                                Cell(
                                    text=f"{t['change']:+.2f}",
                                    number=Decimal(str(t["change"])),
                                    kind=CellKind.PERCENTAGE_POINTS,
                                )
                                if t["change"] is not None
                                else missing("first assessment in scope", shown="—"),
                            )
                            for t in overview["trend"]
                        ),
                    ),
                    Table(
                        name="Mark ranges",
                        headers=("Range (%)", "Students"),
                        rows=tuple((text(r["range"]), count(r["count"])) for r in k["srm_ranges"]),
                    ),
                ),
            )
        )
        comparisons = overview["comparisons"]
        tables = []
        if len(comparisons["courses"]) > 1 or kind == "comparison":
            tables.append(_comparison_table("Courses", comparisons["courses"], "Course"))
        tables.append(_comparison_table("Sections", comparisons["sections"], "Section"))
        tables.append(_comparison_table("Faculty", comparisons["faculty"], "Faculty"))
        if len(comparisons["semesters"]) > 1:
            tables.append(_comparison_table("Semesters", comparisons["semesters"], "Semester"))
        sections.append(
            Section(
                title="Comparisons",
                tables=tuple(tables),
                notes=(
                    "Faculty figures are the classes each person teaches; a co-taught class counts "
                    "for each teacher. They measure student results, not teaching quality.",
                ),
            )
        )
    if kind in ("summary", "attention"):
        rules = k["rules"]
        student_rows = []
        for group, label in (
            ("bottom", "Lowest course score"),
            ("declining", "Declining"),
            ("borderline", "Borderline"),
        ):
            for s in overview["students"][group]:
                student_rows.append(
                    (
                        text(label),
                        text(s["register_number"]),
                        text(s["name"]),
                        text(s["offering"]),
                        _pct({"value": s["score"]}),
                        text(", ".join(RULE_NAMES.get(f, f) for f in s["flags"]) or "—"),
                    )
                )
        sections.append(
            Section(
                title="Attention",
                tables=(
                    Table(
                        name="Attention rules",
                        headers=("Rule", "Students flagged"),
                        rows=tuple(
                            (text(RULE_NAMES.get(r, r)), count(n)) for r, n in sorted(rules.items())
                        ),
                    ),
                    Table(
                        name="Students to review",
                        headers=("List", "Register No", "Name", "Class", "Course score", "Flags"),
                        rows=tuple(student_rows),
                    ),
                ),
                notes=(
                    "Attention flags are deterministic rules on recorded marks, not predictions.",
                ),
            )
        )
    activity = overview["activity"]
    sections.append(
        Section(
            title="Data and activity",
            tables=(
                Table(
                    name="Activity",
                    headers=("Measure", "Value"),
                    rows=(
                        (text("Confirmed imports"), count(activity["confirmed_imports"])),
                        (text("Interventions recorded"), count(activity["interventions"])),
                        (text("Published assessments"), count(overview["counts"]["assessments"])),
                    ),
                ),
            ),
        )
    )
    crumbs = overview["scope"]["crumbs"]
    return Report(
        metadata=ReportMetadata(
            kind=ReportKind.CLASS_SUMMARY,
            title=title_for(overview, role),
            generated_at=stamp,
            course_code=next((c["label"] for c in crumbs if c["kind"] == "course"), None),
            section_name=next((c["label"] for c in crumbs if c["kind"] == "section"), None),
            term_code=overview["period"],
            subject=" / ".join([overview["scope"]["root"], *(c["label"] for c in crumbs)]),
        ),
        sections=tuple(sections),
    )


# ------------------------------------------------------------------ presentation PDF

NAVY = "#12284C"
ACCENT = "#0F766E"
MUTED = "#64748B"
LINE = "#E2E8F0"
SERIES = ["#0F766E", "#2563EB", "#D97706", "#7C3AED", "#DC2626", "#0891B2"]


def to_pdf(report: Report, overview: dict[str, Any]) -> bytes:
    from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )
    from reportlab.platypus import Table as RLTable

    c = colors.HexColor
    styles = {
        "title": ParagraphStyle(
            "t", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=c(NAVY)
        ),
        "sub": ParagraphStyle(
            "s", fontName="Helvetica", fontSize=10.5, leading=14, textColor=c(MUTED)
        ),
        "h": ParagraphStyle(
            "h",
            fontName="Helvetica-Bold",
            fontSize=13.5,
            leading=18,
            textColor=c(NAVY),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "b",
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=c("#1E293B"),
            alignment=TA_LEFT,
        ),
        "note": ParagraphStyle(
            "n", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=c(MUTED)
        ),
        "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10),
    }
    k = overview["kpis"]
    meta = report.metadata
    buffer = io.BytesIO()

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(c(NAVY))
        canvas.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(15 * mm, A4[1] - 9 * mm, "ACADLYTICS")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm, INSTITUTION)
        canvas.setFillColor(c(MUTED))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(
            15 * mm,
            10 * mm,
            f"{meta.title} · {overview['period']} · "
            f"generated {meta.generated_at:%d %b %Y %H:%M} UTC",
        )
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=meta.title,
        author="ACADLYTICS",
        subject=meta.subject or "",
    )
    width = A4[0] - 30 * mm
    story: list = [
        Paragraph(meta.title, styles["title"]),
        Spacer(1, 3),
        Paragraph(f"{INSTITUTION} · {meta.subject or ''}", styles["sub"]),
        Paragraph(
            f"{overview['period']} · Generated {meta.generated_at:%d %B %Y, %H:%M} UTC",
            styles["sub"],
        ),
        Spacer(1, 10),
    ]

    # KPI tiles
    tiles = [
        ("Average", _fmt(k["average"])),
        ("Median", _fmt(k["median"])),
        ("Pass %", _fmt(k["pass_percent"])),
        ("Completion", _fmt(k["completion_percent"])),
        ("Students", f"{overview['counts']['students']:,}"),
        ("Sections", str(overview["counts"]["sections"])),
        ("Faculty", str(overview["counts"]["faculty"])),
        ("Attention", str(k["attention_students"])),
    ]
    tile_cells = [
        [
            Paragraph(
                f"<font size=7.5 color='{MUTED}'>{label.upper()}</font><br/>"
                f"<font size=15 color='{NAVY}'><b>{value}</b></font>",
                styles["body"],
            )
            for label, value in tiles[i : i + 4]
        ]
        for i in (0, 4)
    ]
    grid = RLTable(tile_cells, colWidths=[width / 4] * 4, rowHeights=[16 * mm, 16 * mm])
    grid.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, c(LINE)),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, c(LINE)),
                ("BACKGROUND", (0, 0), (-1, -1), c("#F8FAFC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [grid, Spacer(1, 10), Paragraph("Summary", styles["h"])]
    for line in conclusions(overview):
        story.append(Paragraph(f"• {line}", styles["body"]))
    story.append(Spacer(1, 6))

    def chart_title(d: Drawing, label: str) -> None:
        d.add(
            String(
                0, d.height - 12, label, fontName="Helvetica-Bold", fontSize=10, fillColor=c(NAVY)
            )
        )

    trend = [t for t in overview["trend"] if t["mean"]["value"] is not None]
    if len(trend) >= 1:
        d = Drawing(width, 62 * mm)
        chart_title(d, "Assessment trend — mean % and pass %")
        lc = HorizontalLineChart()
        lc.x, lc.y, lc.width, lc.height = 28, 22, width - 50, 62 * mm - 50
        lc.data = [
            [t["mean"]["value"] for t in trend],
            [t["pass_percent"]["value"] or 0 for t in trend],
        ]
        lc.categoryAxis.categoryNames = [t["name"] for t in trend]
        lc.categoryAxis.labels.fontSize = 7.5
        lc.valueAxis.valueMin, lc.valueAxis.valueMax, lc.valueAxis.valueStep = 0, 100, 20
        lc.valueAxis.labels.fontSize = 7.5
        lc.valueAxis.gridStrokeColor = c(LINE)
        lc.valueAxis.visibleGrid = 1
        for i, colour in enumerate((ACCENT, "#2563EB")):
            lc.lines[i].strokeColor = c(colour)
            lc.lines[i].strokeWidth = 2
        d.add(lc)
        d.add(String(width - 150, d.height - 12, "— mean %", fontSize=8, fillColor=c(ACCENT)))
        d.add(String(width - 90, d.height - 12, "— pass %", fontSize=8, fillColor=c("#2563EB")))
        story.append(KeepTogether([d, Spacer(1, 6)]))

    d = Drawing(width, 58 * mm)
    chart_title(d, "Distribution of course scores (SRM mark ranges)")
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 28, 20, width * 0.55, 58 * mm - 45
    bc.data = [[r["count"] for r in k["srm_ranges"]]]
    bc.categoryAxis.categoryNames = [r["range"] for r in k["srm_ranges"]]
    bc.categoryAxis.labels.fontSize = 7.5
    bc.valueAxis.valueMin = 0
    bc.valueAxis.labels.fontSize = 7.5
    bc.bars[0].fillColor = c(ACCENT)
    bc.barWidth = 10
    d.add(bc)
    if k["scored"]:
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = width * 0.70, 12, 42 * mm, 42 * mm
        pie.data = [max(k["passed"], 0), max(k["failed"], 0), max(k["not_scored"], 0)]
        pie.labels = [f"Pass {k['passed']}", f"Below {k['failed']}", f"No score {k['not_scored']}"]
        pie.slices.strokeColor = colors.white
        for i, colour in enumerate((ACCENT, "#DC2626", "#CBD5E1")):
            pie.slices[i].fillColor = c(colour)
            pie.slices[i].fontSize = 7
        d.add(pie)
    story.append(KeepTogether([d, Spacer(1, 4)]))

    comparisons = overview["comparisons"]
    group = comparisons["sections"] if len(comparisons["sections"]) > 1 else comparisons["faculty"]
    ranked = sorted(
        (r for r in group if r["average"]["value"] is not None), key=lambda r: r["average"]["value"]
    )
    if len(ranked) >= 2:
        shown = ranked if len(ranked) <= 24 else ranked[:12] + ranked[-12:]
        height = max(50 * mm, len(shown) * 5.2 * mm + 20 * mm)
        d = Drawing(width, height)
        noun = "Sections" if group is comparisons["sections"] else "Faculty"
        chart_title(
            d,
            f"{noun} — average course score %"
            + (" (lowest and highest 12)" if len(ranked) > 24 else ""),
        )
        hb = HorizontalBarChart()
        hb.x, hb.y, hb.width, hb.height = 90, 10, width - 110, height - 30
        hb.data = [[r["average"]["value"] for r in shown]]
        hb.categoryAxis.categoryNames = [r["label"][:22] for r in shown]
        hb.categoryAxis.labels.fontSize = 7
        hb.valueAxis.valueMin, hb.valueAxis.valueMax, hb.valueAxis.valueStep = 0, 100, 20
        hb.valueAxis.labels.fontSize = 7
        hb.bars[0].fillColor = c("#2563EB")
        d.add(hb)
        story.append(Spacer(1, 8))
        story.append(d)

    # Tables from the report model (the same rows the CSV/XLSX contain)
    story.append(PageBreak())
    for section in report.sections:
        story.append(Paragraph(section.title, styles["h"]))
        for table in section.tables:
            if table.is_empty:
                continue
            data = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in table.headers]] + [
                [Paragraph(cell.text, styles["cell"]) for cell in row] for row in table.rows
            ]
            t = RLTable(
                data, repeatRows=1, colWidths=[width / len(table.headers)] * len(table.headers)
            )
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), c("#EEF2F7")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, c(LINE)),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c("#FAFBFC")]),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story += [Paragraph(table.name, styles["body"]), Spacer(1, 3), t, Spacer(1, 8)]
        for note in section.notes:
            story.append(Paragraph(f"Note: {note}", styles["note"]))
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buffer.getvalue()


def export(report: Report, overview: dict[str, Any], export_format: str) -> tuple[bytes, str]:
    if export_format == "csv":
        return to_csv(report), "text/csv; charset=utf-8"
    if export_format == "xlsx":
        return to_xlsx(report), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return to_pdf(report, overview), "application/pdf"
