"""Pooling offering summaries into a course, faculty, coordinator, department or institution.

Pure functions over ``offering_summaries`` data. Every statistic is the analytics engine's own
function applied to the pooled values the offerings already produced:

    average / median / spread   ``mean_percent`` / ``median_percent`` /
                                ``std_dev_percentage_points`` over every student's weighted
                                course score in scope (one value per student per offering)
    pass %                      students at or above their offering's pass mark / students
                                with a course score (the engine's rule; absent is not a fail)
    completion %                ``completion_percent`` over the pooled result matrix
    assessment trend            per assessment name (FT-I, FT-II, ...), the pooled
                                percentages of every assessed student
    distribution                ``bin_percentages`` over the pooled course scores

So at a single offering these reproduce the offering dashboard exactly, and at every level
above it they are the same definitions over more students — never an average of averages.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.analytics.core.distribution import bin_percentages
from app.modules.analytics.core.outputs import DataCoverage
from app.modules.analytics.core.results import Measure
from app.modules.analytics.core.statistics import (
    completion_percent,
    mean_percent,
    median_percent,
    quantize_percent,
    std_dev_percentage_points,
)

SRM_RANGES = ((0, 49), (50, 59), (60, 69), (70, 79), (80, 89), (90, 100))
POOLED_BASIS = "every (student, published assessment) in the selected offerings"


@dataclass(frozen=True)
class OfferingMeta:
    id: str
    course_id: str
    course_code: str
    course_name: str
    course_type: str | None
    department_id: str
    department_code: str
    department_name: str
    section_id: str
    section_name: str
    batch_year: int
    term_id: str
    term_code: str
    term_name: str
    academic_year: str
    semester: str | None
    is_current: bool
    pass_percent: float
    faculty: tuple[tuple[str, str], ...] = ()
    coordinators: tuple[tuple[str, str], ...] = ()

    @property
    def label(self) -> str:
        return f"{self.course_code} · {self.section_name}"


@dataclass
class Item:
    meta: OfferingMeta
    data: dict[str, Any]


@dataclass
class _Pool:
    scores: list[Decimal] = field(default_factory=list)
    passed: int = 0
    cohort: int = 0
    coverage: Counter = field(default_factory=Counter)


def _m(measure: Measure) -> dict[str, Any]:
    return {
        "value": float(measure.value) if measure.value is not None else None,
        "status": measure.status.value,
        "n": measure.n,
        "reason": None if measure.is_ok else measure.reason,
    }


def _ratio(numerator: int, denominator: int, *, reason: str) -> dict[str, Any]:
    if denominator == 0:
        return {"value": None, "status": "insufficient_data", "n": 0, "reason": reason}
    value = quantize_percent(Decimal(100 * numerator) / Decimal(denominator))
    return {"value": float(value), "status": "ok", "n": denominator, "reason": None}


def _coverage(counter: Counter) -> DataCoverage:
    return DataCoverage(
        assessed=counter["assessed"],
        absent=counter["absent"],
        exempt=counter["exempt"],
        missing=counter["missing"],
        basis=POOLED_BASIS,
    )


def pooled_kpis(items: Sequence[Item], *, light: bool = False) -> dict[str, Any]:
    pool = _Pool()
    rules: Counter = Counter()
    severities: Counter = Counter()
    segments: Counter = Counter()
    trends: Counter = Counter()
    attention = flagged = 0
    for item in items:
        data = item.data
        pool.cohort += data["cohort_n"]
        pool.passed += data["passed"]
        pool.scores.extend(
            Decimal(str(s["score"])) for s in data["students"] if s["score"] is not None
        )
        pool.coverage.update(data["coverage"])
        rules.update(data["rules"])
        severities.update(data["severities"])
        segments.update(data["segments"])
        trends.update(data["trends"])
        attention += data["students_requiring_attention"]
        flagged += data["flagged_students"]
    scored = len(pool.scores)
    return {
        "offerings": len(items),
        "enrolments": pool.cohort,
        "scored": scored,
        "passed": pool.passed,
        "failed": scored - pool.passed,
        "not_scored": pool.cohort - scored,
        "average": _m(mean_percent(pool.scores)),
        "median": _m(median_percent(pool.scores)),
        "std_dev": None if light else _m(std_dev_percentage_points(pool.scores)),
        "pass_percent": _ratio(pool.passed, scored, reason="no student has a course score yet"),
        "fail_percent": _ratio(
            scored - pool.passed, scored, reason="no student has a course score yet"
        ),
        "completion_percent": (
            _m(completion_percent(_coverage(pool.coverage)))
            if sum(pool.coverage.values())
            else {
                "value": None,
                "status": "insufficient_data",
                "n": 0,
                "reason": "no published assessment in scope",
            }
        ),
        "coverage": dict(pool.coverage),
        "attention_students": attention,
        "flagged_students": flagged,
        "rules": dict(rules),
        "severities": dict(severities),
        "segments": dict(segments),
        "trends": dict(trends),
        "distribution": []
        if light
        else [
            {"range": f"{b.lower}-{b.upper}", "count": b.count, "share": float(b.share_percent)}
            for b in bin_percentages(pool.scores)
        ],
        "srm_ranges": [
            {
                "range": f"{low}-{high}",
                "count": sum(1 for s in pool.scores if low <= s < high + 1),
            }
            for low, high in SRM_RANGES
        ],
    }


def assessment_trend(items: Sequence[Item], *, light: bool = False) -> list[dict[str, Any]]:
    """Pooled statistics per assessment name, in teaching order, with the change from the
    previous one — the spikes and drops a coordinator looks for."""
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        for a in item.data["assessments"]:
            bucket = buckets.setdefault(
                a["key"],
                {
                    "key": a["key"],
                    "name": a["name"],
                    "sequence": a["sequence_no"],
                    "pcts": [],
                    "passed": 0,
                    "coverage": Counter(),
                    "offerings": 0,
                    "max_marks": set(),
                },
            )
            bucket["sequence"] = min(bucket["sequence"], a["sequence_no"])
            bucket["pcts"].extend(Decimal(str(p)) for p in a["percentages"])
            bucket["passed"] += a["passed"]
            bucket["coverage"].update(a["coverage"])
            bucket["offerings"] += 1
            bucket["max_marks"].add(a["max_marks"])
    ordered = sorted(buckets.values(), key=lambda b: (b["sequence"], b["name"]))
    out = []
    previous = None
    for bucket in ordered:
        mean = mean_percent(bucket["pcts"])
        if light:  # comparison rows and heat maps need only the mean
            entry = {"key": bucket["key"], "name": bucket["name"], "mean": _m(mean), "change": None}
            if (
                previous is not None
                and previous["mean"]["value"] is not None
                and mean.value is not None
            ):
                entry["change"] = round(float(mean.value) - previous["mean"]["value"], 2)
            out.append(entry)
            previous = entry
            continue
        entry = {
            "key": bucket["key"],
            "name": bucket["name"],
            "sequence": bucket["sequence"],
            "offerings": bucket["offerings"],
            "max_marks": sorted(m for m in bucket["max_marks"] if m is not None),
            "mean": _m(mean),
            "median": _m(median_percent(bucket["pcts"])),
            "std_dev": _m(std_dev_percentage_points(bucket["pcts"])),
            "pass_percent": _ratio(
                bucket["passed"], len(bucket["pcts"]), reason="nobody was assessed"
            ),
            "completion_percent": _m(completion_percent(_coverage(bucket["coverage"])))
            if sum(bucket["coverage"].values())
            else None,
            "coverage": dict(bucket["coverage"]),
            "distribution": [
                {"range": f"{b.lower}-{b.upper}", "count": b.count}
                for b in bin_percentages(bucket["pcts"])
            ],
            "change": None,
        }
        if previous is not None and entry["mean"]["value"] is not None:
            prev = previous["mean"]["value"]
            if prev is not None:
                entry["change"] = round(entry["mean"]["value"] - prev, 2)
        out.append(entry)
        previous = entry
    return out


def compact(items: Sequence[Item]) -> dict[str, Any]:
    """A comparison row: the headline measures plus the assessment means for a sparkline."""
    kpis = pooled_kpis(items, light=True)
    trend = assessment_trend(items, light=True)
    return {
        "offerings": kpis["offerings"],
        "enrolments": kpis["enrolments"],
        "scored": kpis["scored"],
        "average": kpis["average"],
        "median": kpis["median"],
        "pass_percent": kpis["pass_percent"],
        "fail_percent": kpis["fail_percent"],
        "completion_percent": kpis["completion_percent"],
        "attention_students": kpis["attention_students"],
        "trend": [{"key": t["key"], "name": t["name"], "mean": t["mean"]["value"]} for t in trend],
        "latest_change": next(
            (t["change"] for t in reversed(trend) if t["change"] is not None), None
        ),
    }


def group(
    items: Sequence[Item],
    key: Callable[[Item], Iterable[tuple[str, str]]],
    *,
    extra: Callable[[str, list[Item]], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compare groups of offerings. ``key`` yields (id, label) pairs, so an offering taught
    by two faculty counts for both."""
    groups: dict[str, list[Item]] = defaultdict(list)
    labels: dict[str, str] = {}
    for item in items:
        for gid, label in key(item):
            groups[gid].append(item)
            labels[gid] = label
    rows = []
    for gid, members in groups.items():
        row = {"id": gid, "label": labels[gid], **compact(members)}
        row["sections"] = len({m.meta.section_id for m in members})
        row["courses"] = len({m.meta.course_id for m in members})
        if extra:
            row.update(extra(gid, members))
        rows.append(row)
    rows.sort(key=lambda r: r["label"])
    return rows


def heatmap(items: Sequence[Item], key: Callable[[Item], tuple[str, str]]) -> dict[str, Any]:
    """Rows (a grouping) x columns (assessment names) -> pooled mean %."""
    trend = assessment_trend(items)
    columns = [{"key": t["key"], "name": t["name"]} for t in trend]
    groups: dict[str, list[Item]] = defaultdict(list)
    labels: dict[str, str] = {}
    for item in items:
        gid, label = key(item)
        groups[gid].append(item)
        labels[gid] = label
    rows = []
    for gid, members in sorted(groups.items(), key=lambda kv: labels[kv[0]]):
        values = {t["key"]: t["mean"]["value"] for t in assessment_trend(members, light=True)}
        rows.append({"id": gid, "label": labels[gid], "values": values})
    return {"columns": columns, "rows": rows}


def attention_matrix(
    items: Sequence[Item], key: Callable[[Item], tuple[str, str]]
) -> dict[str, Any]:
    """Rows (a grouping) x attention rules -> students flagged."""
    groups: dict[str, Counter] = defaultdict(Counter)
    labels: dict[str, str] = {}
    cohort: Counter = Counter()
    for item in items:
        gid, label = key(item)
        labels[gid] = label
        groups[gid].update(item.data["rules"])
        cohort[gid] += item.data["cohort_n"]
    rules = sorted({r for c in groups.values() for r in c})
    return {
        "rules": rules,
        "rows": [
            {"id": gid, "label": labels[gid], "cohort": cohort[gid], "values": dict(c)}
            for gid, c in sorted(groups.items(), key=lambda kv: labels[kv[0]])
        ],
    }


def student_lists(items: Sequence[Item], *, limit: int = 12) -> dict[str, list[dict]]:
    entries = []
    for item in items:
        for s in item.data["students"]:
            entries.append(
                {
                    **{
                        k: s[k]
                        for k in (
                            "id",
                            "register_number",
                            "name",
                            "score",
                            "segment",
                            "trend",
                            "latest",
                        )
                    },
                    "flags": s["flags"],
                    "offering_id": item.meta.id,
                    "offering": item.meta.label,
                    "pass_mark": item.data["pass_mark"],
                }
            )
    scored = [e for e in entries if e["score"] is not None]
    by_score = sorted(scored, key=lambda e: (-e["score"], e["register_number"]))
    return {
        "top": by_score[:limit],
        "bottom": list(reversed(by_score[-limit:])) if by_score else [],
        "borderline": [e for e in by_score if e["segment"] == "borderline"][:limit],
        "improving": [e for e in by_score if e["trend"] == "improving"][:limit],
        "declining": sorted(
            (e for e in scored if e["trend"] == "declining"), key=lambda e: e["score"]
        )[:limit],
        "persistently_low": [e for e in reversed(by_score) if e["segment"] == "persistently_low"][
            :limit
        ],
    }
