# ACADLYTICS — Analytics Specification

**Owner:** Agent 2 (analytics, intelligence, interventions, reporting)
**Status:** Phase 3 complete — F1–F13 implemented, composed into a student performance profile, and wired to the platform's real read interface (contract C3). Still to come: segmentation, the R1–R7 attention engine, class health, comparison/what-changed, interventions, insights, reports and the `/analytics/*` API.
**Last updated:** 2026-09-26
**Authority:** `docs/PROJECT_CONTEXT.md` (reduced-scope directive) wins over the blueprint wherever they disagree. This document refines, and never contradicts, §3, §4, §7 and §10 of that file.

---

## 1. What this layer is for

Every number this system shows must be traceable to **stored assessment data, a configured threshold and a named rule**. That is the product, not a nice-to-have: the system makes no predictions, assigns no risk scores and never explains *why* a student is struggling, so the only thing that makes it worth trusting is that each figure can be taken apart.

Four properties follow, and each one is enforced somewhere in code rather than asserted here:

| Property | How it is enforced |
|---|---|
| **Deterministic** | The core is a pure function of an `OfferingSnapshot`; no clock, no settings lookup, no database. `tests/analytics/test_architecture.py` fails the build on an import of `sqlalchemy`, `app.db`, `app.core.config` or `pydantic_settings`. |
| **Explainable** | Every contract in `core/outputs.py` carries an `Explanation`, and every measure carries its `n`, its unit and the threshold it was compared against, with that threshold's source. |
| **Testable** | Every formula takes plain data and returns plain data, so it is provable against a hand-computed fixture with no database. |
| **Reproducible** | `Decimal` throughout (never `float`), half-up rounding to 2 dp, deterministic fixture ids, and timezone-aware stamps. |

---

## 2. Architecture

```
FastAPI router  /api/v1/analytics/*          thin: auth, offering scope, serialisation
        |
        v
analytics service                            orchestration: snapshot -> engine -> response
        |                    \
        |                     \--> analytics engine (core/)   pure functions, no I/O
        v
repository                                   all SQL/ORM access
        |
        v
PostgreSQL 16
```

The engine hangs off the service rather than sitting under it: the service fetches **one** `OfferingSnapshot` through the `SnapshotSource` port and hands it to pure functions. There is no path from a formula to a session.

### Module map

```
app/modules/analytics/
    __init__.py         the layering, and the scope limits that are design decisions
    config.py           deployment threshold defaults, from settings   [Phase 1]
    schemas.py          API surface: re-exports the contracts          [Phase 1]
    services.py         the SnapshotSource and RecomputeHook ports     [Phase 1]
    repository.py       platform reads mapped onto the snapshot        [Phase 3]
    router.py           /api/v1/analytics/*                            [later]
    core/
        contracts.py    inputs: OfferingSnapshot, StudentRef, AssessmentRef, ResultRecord
        policy.py       the missing-data policy; StudentSeries
        thresholds.py   C5: every configurable threshold and its provenance
        rules.py        C9: the frozen R1-R7 attention-rule registry
        results.py      C10: Measure / Label, including insufficient data
        vocabulary.py   every categorical label and the set it came from
        outputs.py      the eleven contracts and their explainability payload
        statistics.py   F1, F3-F7: the primitives, and contract 1     [Phase 2]
        distribution.py F8: the histogram, and contract 6             [Phase 2]
        student.py      F2, F7, F10-F13, and contracts 2 and 3        [Phase 2]
        trends.py       F9: slope, method, classification; contract 4 [Phase 2]
```

**Still to come, one module per formula family:** `segmentation` (F17), `attention` (F18, the R1–R7 engine), `class_health` (F19), `comparison` (F15–F16), `interventions` (F20), `insights` (F21).

They are **not stubbed**. An empty module returning a plausible value is indistinguishable from a working one, and the whole point of this layer is that a caller can tell the difference between "no data" and "computed".

The primitives live in one place and nothing recomputes them: `statistics.arithmetic_mean`, `median_of`, `population_std_dev`, `value_range` and `quantize_percent` are the only implementations of that arithmetic in the codebase, and `policy.assessed_scores` is the only place the "who counts" filter is written.

### Why `schemas.py` re-exports instead of declaring

A second set of API models would mean every analytics value existed twice with a mapping between them — exactly where a rounded number, a dropped `n` or a lost insufficient-data status disappears. The core contracts are pydantic models with JSON-safe types, so FastAPI returns them directly and the OpenAPI document is generated from the same definitions the formulas produce. A test asserts `schemas.py` declares no classes of its own.

### Ownership boundary

Analytics reads academic data **through the platform's services and repositories** (README rule 4), never by querying platform tables. Faculty scope, PII limits and the audit trail are then enforced once, where the data lives. A missing query is requested from Agent 1, not written here. Agent 2 creates no ORM models and authors no migrations.

---

## 3. Inputs: the snapshot contract

Everything the engine computes comes from one object.

| Type | Holds | Notes |
|---|---|---|
| `OfferingSnapshot` | `offering_id`, `pass_mark_percent`, `assessments`, `students`, `results` | Self-validating: no duplicate ids, no duplicate `sequence_no`, no result pointing at a student or assessment outside the snapshot, no score above `max_marks`. |
| `StudentRef` | `id`, `register_no`, `name?`, `is_active` | Deliberately minimal — analytics never needs contact details, so PII cannot travel into logs or reports through this layer. |
| `AssessmentRef` | `id`, `code`, `sequence_no`, `max_marks`, `weightage`, `held_on?`, `is_published` | Order comes from `sequence_no`, never from `held_on`: real faculty data often has no dates. |
| `ResultRecord` | `student_id`, `assessment_id`, `status`, `score?` | **A score exists only when `status == present`.** Enforced by a validator, so an absent row can never arrive carrying `0`. |

`pass_mark_percent` comes from the offering (`course_offerings.pass_mark_percent`), never from a constant. Unpublished assessments are excluded by default: a faculty member who has created but not published an assessment has not told students it counts, and including it would distort completion and trends.

---

## 4. Missing-data rules

```
ABSENT != 0     MISSING != 0     NOT ASSESSED != 0     EXEMPT != 0
```

Three states are **stored**; two are **derived**. `missing` and `incomplete` are the *absence* of data and must never be added to the database enum.

| State | Representation | In a mean? | Counts as assessed? | In the completion denominator? |
|---|---|---|---|---|
| `ASSESSED` (`present`) | row, score not null | **yes** | yes | yes |
| `ABSENT` | row, score null | no | no | **yes** |
| `EXEMPT` | row, score null | no | no | **no** |
| `MISSING` | **no row exists** | no | no | **yes** |
| *incomplete* | derived shape of a whole series | n/a | n/a | reduces completion % |

The pair that matters: two students who sat the same two of three papers have **different** completion figures if one was exempt and one was absent. Exemption is not a failure to turn up, and counting it as one manufactures a problem a teacher would then act on.

Implementation: `core/policy.py` — `classify()` maps a stored status (or `None`) onto a `DerivedState`; `SeriesPoint` carries a percentage **only** in the `ASSESSED` state; `StudentSeries` exposes `completed_count` and `completion_denominator` so no caller recounts. `DataCoverage` (in `core/outputs.py`) carries the four counts on every group output and is validated against the series it ships with.

---

## 5. Insufficient data

Insufficient data is an **outcome, not an error** — a 200 response, never a 4xx, never a fabricated `0`, never a label the data does not support.

```jsonc
{ "status": "insufficient_data", "value": null, "n": 1, "minimum_n": 2,
  "reason": "only 1 completed assessment (minimum 2)" }
```

Rules:

1. Every `Measure` and `Label` carries `n`. A reason is **required** when the status is `insufficient_data` (enforced by a validator).
2. `NaN` and `±Infinity` may never leave analytics. `Decimal` has its own `NaN`, so the guard checks `is_finite()` rather than trusting the type.
3. **No vocabulary contains `insufficient_data`.** The directive lists "Insufficient Data" as a trend and as a segment; expressing it as a *value* would collide with the status above and force every consumer to special-case one member of each enum. A trend that cannot be classified is `Label(status=insufficient_data, value=null)`, and the UI renders the words from the status. Tested in `test_vocabulary.py`.

### Sample-size gates

| Gate | Default | Applies to |
|---|---|---|
| `min_group_n` | 5 | any group statistic that would be *labelled* (class health verdicts, segment counts as a cohort claim) |
| `min_trend_points` | 2 | trend classification, sharp decline |
| `min_consistency_points` | 3 | consistency / volatility |
| `min_outcome_group_n` | 3 | **each** of the target and peer groups in an intervention outcome |

A mean over 3 students is still computed and returned with `n = 3`; what the gate withholds is the *label* ("this class is performing poorly"), because that is the part that misleads at small n.

---

## 6. Configuration

No academic threshold is hard-coded at a call site. A rule asks for a value and gets back the number **and its provenance**, so an explanation can say "50%, set for this offering" rather than just "50%".

### Resolution order (contract C5)

```
offering override  ->  department setting  ->  deployment setting  ->  built-in default
   (stored JSONB)      (stored settings row)   (ANALYTICS_* env)      (THRESHOLD_DEFAULTS)
        |                      |                        \                    /
   OFFERING_OVERRIDE    DEPARTMENT_SETTING                  SYSTEM_DEFAULT
```

The last two both report `system_default`: to a faculty member "the system default" is one thing however it was set. What an explanation must distinguish is whether *their* offering or department changed the number.

The **pass mark is not in this table**. It is a first-class column on the offering and is passed in, never defaulted — institutions differ and the platform's 40% is not a universal standard.

### Keys

Directive name → implemented key. Every key is a `ThresholdKey` member, an `AnalyticsSettings` field, and a stored-override key **under the same spelling**; a test asserts the three sets are identical.

| Directive name | Key / settings field / env var (`ANALYTICS_…`) | Default | Unit | Used by |
|---|---|---|---|---|
| `PASS_PERCENT` | *(not a threshold)* `course_offerings.pass_mark_percent` | 40.00 | percent | R2, R3, R7, pass %, borderline |
| `LOW_PERFORMANCE_THRESHOLD` | `low_performance_percent` | 50 | percent | R1, Persistently Low |
| — | `high_performance_percent` | 75 | percent | High Performer segment |
| `REPEATED_LOW_COUNT` | `repeated_low_count` | 3 | count | R3 |
| `SHARP_DECLINE_THRESHOLD` | `decline_drop_pp` | 15 | pp | R4 |
| `TREND_DELTA` | `trend_delta_pp` | 5 | pp/assessment | trend, R5 |
| — | `low_completion_percent` | 75 | percent | R6 |
| `BORDERLINE_MARGIN` | `borderline_band_pp` | 5 | pp | R7, Borderline segment |
| `IMPROVEMENT_THRESHOLD` | `improvement_delta_pp` | 5 | pp | most improved, Improving segment, outcome label |
| — | `min_group_n` | 5 | count | group-statistic gate |
| — | `min_trend_points` | 2 | count | trend gate |
| — | `min_consistency_points` | 3 | count | consistency gate |
| — | `min_outcome_group_n` | 3 | count | outcome gate |

`high_performance_percent` was added because the High Performer segment needs a boundary, and the alternative is a hard-coded 75 inside the segmentation module. Magnitudes (`decline_drop_pp`, `trend_delta_pp`, `borderline_band_pp`, `improvement_delta_pp`) are stored **positive**; the rule applies the direction.

Validation is shared by all four layers: percentages must be 0–100, magnitudes positive, counts whole and ≥ 1, everything finite. A bad environment variable or a bad stored override fails loudly rather than silently producing a nonsensical threshold. Unknown keys in a stored document are **ignored and reported** in `ThresholdSet.ignored_keys` — a newer configuration must not break an older deployment, but a typo must stay visible.

---

## 7. Output contracts

All eleven are frozen pydantic models in `core/outputs.py`, reject unknown fields, carry an `Explanation`, and (except `ScoreDistribution`, which its container stamps) carry a timezone-aware `generated_at`.

| # | Contract | Answers | Key fields |
|---|---|---|---|
| 1 | `AssessmentAnalytics` | how did the class do in this assessment? | `mean`, `median`, `std_dev`, `lowest`/`highest` (with the student), `pass_percent`, `completion_percent`, `distribution`, `coverage` |
| 2 | `StudentAssessmentPerformance` | how did this student do in this assessment? | `state`, `score?`, `percentage`, `difference_from_class_mean`, `meets_pass_mark?` |
| 3 | `StudentPerformanceHistory` | what is this student's story in this offering? | `points` (every published assessment, gaps included), `weighted_course_score`, `completion_percent`, `consistency_std_dev`, `volatility_range`, `trend`, `latest` |
| 4 | `StudentTrend` | which way are they moving? | `label`, `slope`, `method`, `points_used`, `percentages_used`, `threshold` |
| 5 | `ClassHealth` | how is this offering doing? | `class_mean`, `median`, `pass_percent`, `completion_percent`, `students_requiring_attention`, `segment_counts`, `flag_counts`, `latest_assessment` |
| 6 | `ScoreDistribution` | how are the scores spread? | `bins` (the canonical ten), `n`, `coverage` |
| 7 | `StudentSegment` | what one thing should a teacher act on? | `primary` + `factors` (everything else that is true, with evidence) |
| 8 | `AttentionFlag` | which rule fired, and on what evidence? | `rule_code`, `severity`, `status`, `actual`, `threshold?`, `pass_mark_percent?`, `reference_assessments`, `message` |
| 9 | `ChangeAnalysis` | what did the latest assessment change? | `from`/`to_assessment`, `intersection_n`, `class_mean_change`, `pass_percent_change`, `groups` (counts **with their members**), `new_flags` |
| 10 | `InterventionOutcome` | what was observed after the action? | `baseline_assessments`, `follow_up_assessment`, `target`, `peers`, `net_change`, `label` |
| 11 | `GeneratedInsight` | what is the one sentence? | `scope`, `subject_id?`, `code`, `text`, `severity?`, evidence in the explanation |

### The explainability payload

```
Explanation
    narrative            one or two sentences, stating values and thresholds
    formula              the arithmetic in symbols
    evidence[]           named facts: "CT2", "48.00", percent, note
    thresholds[]         ResolvedThreshold: key, value, source
    pass_mark_percent    when the rule compared against it
    assessments_used[]   codes, in contributing order
    caveats[]            warnings that must be read with the number
```

### Invariants enforced by validators, not by convention

| Contract | Refuses to be built when |
|---|---|
| `StudentAssessmentPerformance` | a non-assessed state carries a score, a percentage, or a `meets_pass_mark` verdict |
| `StudentTrend` | the difficulty caveat is missing; a classified trend has no `method`; fewer than two percentages are quoted; points and percentages do not line up |
| `StudentPerformanceHistory` | `coverage` disagrees with the series it ships with |
| `ScoreDistribution` | the bins are not the canonical ten; counts do not sum to `n`; `n` is not the assessed count (binning an absence would put it in 0–9) |
| `StudentSegment` | the primary segment is not among the satisfied factors; an insufficient-data segment lists factors |
| `AttentionFlag` | the message predicts or asserts a cause; neither a threshold nor the pass mark is quoted; the value that fired it could not be computed |
| `ChangeAnalysis` | the difficulty caveat is missing; a change is reported with no earlier assessment to compare against |
| `InterventionOutcome` | the observational caveat is missing; the narrative claims causation; the follow-up is also a baseline; there is no baseline |
| `GeneratedInsight` | the text predicts or asserts a cause; there is no evidence; a student-scoped insight does not name its student |
| all | `generated_at` is naive |

**Forbidden wording** (`FORBIDDEN_PHRASES`) is screened in flag messages and insight text — the only free-text that reaches a teacher: *will fail, at risk of failing, high risk, risk score, likely to fail, predicts, prediction, forecast, caused by, because the student, due to lack of*. The list is about claims, not tone: "below the pass mark in three consecutive assessments" is a fact and passes.

**Mandatory caveats.** `DIFFICULTY_CAVEAT` on anything comparing assessments (RISK-10 — a harder paper makes a whole cohort look like it is declining) and `OBSERVATIONAL_CAVEAT` on every intervention outcome (a change observed after an action is not a change caused by it).

---

## 8. Planned formulas (Phase 4)

All arithmetic in `Decimal`; percentages to 2 dp, half-up. `P_a` is a student's percentage in assessment `a`; `w_a` its weightage.

| # | Output | Formula | Gate / notes |
|---|---|---|---|
| F1 | Assessment percentage | `P = 100 * score / max_marks` | `max_marks <= 0` is a data error, not a 0% |
| F2 | Weighted course score | `W = Σ(P_a · w_a) / Σ(w_a)` over **completed** assessments only | future assessments cannot drag a student down |
| F3 | Group mean / median | over **assessed** students only | `n` and excluded states always reported |
| F4 | Standard deviation | **population** σ over the same set | sample σ is wrong here: the cohort is the population |
| F5 | Min / max | lowest and highest `P`, each with its student | `ExtremeScore` |
| F6 | Pass % | `100 · #{P ≥ pass_mark} / assessed` | denominator is *assessed*, not cohort; absence is reported by F7 instead |
| F7 | Completion % | `100 · assessed / (assessed + absent + missing)` | exempt excluded from the denominator |
| F8 | Histogram | ten bins `0-9 … 90-100`, last inclusive of 100 | assessed only; counts must sum to `n` |
| F9 | Trend | `n < 2` → insufficient; `n == 2` → `P[-1] − P[-2]`; `n ≥ 3` → least-squares slope over position index, in pp per assessment. `slope ≥ +trend_delta_pp` → Improving; `≤ −trend_delta_pp` → Declining; else Stable | `method` names which was used |
| F10 | Sharp decline | `drop = P_latest − mean(P over earlier completed)`; fires when `drop ≤ −decline_drop_pp` | needs ≥ 2 completed |
| F11 | Repeated low | `k` consecutive completed assessments with `P < pass_mark` | `k = repeated_low_count`; consecutive over *completed* points |
| F12 | Borderline | `|W − pass_mark| ≤ borderline_band_pp` | band inclusive both sides |
| F13 | Consistency / volatility | population σ of the student's `P` series, plus `range = max − min` | needs ≥ `min_consistency_points` |
| F14 | Most improved | `Δ = P_to − P_from`, both **present**; qualifies when `Δ ≥ improvement_delta_pp` | states both assessments |
| F15 | Assessment comparison | mean/median/pass %/completion deltas between two assessments over the **cohort intersection** | `intersection_n` stated; difficulty caveat |
| F16 | What changed | class-mean delta, counts crossing the pass mark each way, new sharp declines, new flags — **each count with its member list** | difficulty caveat |
| F17 | Segmentation | Persistently Low (`W ≤ low_performance_percent`, or F11 fired) · Declining (F9 Declining or F10) · Borderline (F12) · Improving (F9 Improving) · High Performer (`W ≥ high_performance_percent`) · Stable (none of the above). Primary = first satisfied in `SEGMENT_PRIORITY` | a student may satisfy several; all travel as `factors` |
| F18 | Attention | R1–R7 (§9) over one student's series | escalation rule in §9 |
| F19 | Class health | aggregation of the above; nothing recomputed a second way | group labels gated on `min_group_n` |
| F20 | Intervention outcome | `net = target.change − peers.change`, each group `post_mean − pre_mean`, over students assessed in **both** baseline and follow-up | both groups gated on `min_outcome_group_n`; observational caveat |
| F21 | Insights | fixed template per `InsightCode`, filled from the outputs above | no LLM; evidence required |

### Implementation notes (settled in Phase 2)

Questions the formula table above left open, and the answer the code now holds. Each is a real choice, so it is written down rather than left to be re-derived from the source.

| Question | Decision | Why |
|---|---|---|
| What is the x-axis of the trend fit? | The student's position among their **completed** assessments, 1..n — not `sequence_no` | Otherwise a gap changes the slope of the points either side of it, and two students with different absences get slopes on different axes. The unit says what this means: pp *per completed assessment*. |
| Is "repeated low" the longest run or the current one? | The **trailing** run, counted back from the most recent completed assessment | A student who was below the pass mark three times and has since recovered is not in that state now; a rule saying otherwise would keep raising a flag about a problem that has passed. |
| Standard deviation of one value? | Insufficient data, gated at `n >= 2` (`MIN_STD_DEV_POINTS`, not configurable) | Population σ of one value is 0, which is true and useless. A student's *consistency* is gated higher, at `min_consistency_points` (3). |
| Who wins a tie for highest/lowest? | The **first** student in the snapshot's cohort order | Stable across runs, so two renderings of the same report name the same student. |
| Which mean does `difference_from_class_mean` use? | The published, two-decimal mean | The subtraction a reader can check is the one between the two numbers they can see. |
| Marks in explanation text | Normalised to two decimals for display; the stored value in the contract is untouched | Imported marks arrive variously as `45` and `50.00`; "45 of 50.00 marks" reads like a bug. |
| Weights on a series | `SeriesPoint` carries `weightage` (default 1) | F2 is a student-level formula and must be computable from a series alone; otherwise every caller has to hold the snapshot too. |
| What is "latest performance"? | The most recent assessment the student was actually **assessed** in | "Latest" means the last time there was a performance. The gaps after it are still visible in `points`. |
| All weights zero? | Equal weighting, with `UNWEIGHTED_CAVEAT` on the explanation and the narrative reading "Course score (unweighted)" | **Revised in Phase 3.** The platform's default weightage is 0, so "nothing configured" is the ordinary state of a real offering, not an error. Withholding a course score from every such class would be useless rather than careful; counting assessments equally is the *absence* of a weighting, and it is said out loud. A zero-weight assessment among weighted ones still simply does not count. |
| Whole cohort exempt? | Completion is insufficient data, **not** 0% | A completion percentage with no denominator is not zero completion. |
| Group statistics below `min_group_n`? | Computed and returned with their `n` | The gate withholds *labels*, not numbers — see §5. Labels arrive with segmentation and class health. |

A guard worth naming: any function taking both a snapshot and a `ThresholdSet` rejects a set resolved against a different pass mark. Quoting one pass mark in an explanation while applying another in the arithmetic is the most misleading thing this layer could do, so it fails loudly instead.

### Student performance intelligence (Phase 3)

`core/profile.py` composes the Phase 2 measures into contract 12, `StudentPerformanceProfile`. It **computes nothing of its own** — a test asserts every field equals the Phase 2 function it came from, so the profile and a bare measure cannot drift apart.

| Field | Source | Note |
|---|---|---|
| `history` | `student.student_performance_history` (contract 3) | the series with its gaps, course score, completion, consistency, volatility, trend |
| `latest` | the most recent **assessed** assessment | "latest performance" means the last time there was one; the missing tail is still visible in `points` |
| `previous` | the one before it, skipping absences | |
| `change_from_previous` | `student.latest_change` | percentage **points**, never a percentage change |
| `historical_average` | `student.prior_average` | the mean of the work **before** the latest, per F10's definition of prior history |
| `change_from_historical_average` | `student.decline_against_earlier_mean` (F10) | signed |
| `trend` | `history.trend` (F9) | one trend, computed once |
| `findings` | F10, F11, F14 evaluated against their thresholds | see below |

**Findings are not flags.** A `StudentFinding` says what the numbers do; an `AttentionFlag` says someone should act, with a severity and a lifecycle. The attention engine will read the same measures. `detected` is three-valued: `None` means the condition could not be evaluated (too few completed assessments) and is **not** the same answer as `False` — "no sharp decline" about a student with one result would be a claim the data does not support.

| Finding | Condition | Threshold |
|---|---|---|
| `sharp_decline` | latest minus the mean of earlier completed, at or below `-decline_drop_pp` | `decline_drop_pp` |
| `repeated_low` | trailing run below the pass mark, at or above `repeated_low_count` | `repeated_low_count` + the offering's pass mark |
| `improvement` | latest minus previous, at or above `improvement_delta_pp` | `improvement_delta_pp` |

Improvement is a fact about one student. Ranking students against each other ("most improved") is a cohort question and belongs to the class-intelligence phase.

### Reading real data (Phase 3)

`repository.py` is the only file in the intelligence layer that knows the platform's schema, and it is split so the risky half needs no database:

- `snapshot_from_offering_results(OfferingResults) -> OfferingSnapshot` — **pure**, unit-tested field by field;
- `AnalyticsRepository` — one call to `OfferingResultsService` (contract C3) plus one to `SettingsService`, then the mapper. No logic of its own.

Mapping decisions worth knowing:

| From the platform | Into the snapshot | Why |
|---|---|---|
| `assessments.name` | `AssessmentRef.code` | the platform has no separate code; the label is free text up to 100 characters, so `code` accepts it verbatim rather than upper-casing and truncating it |
| `results.percentage` | **not carried** | analytics recomputes from `score` and `max_marks`, so there is one rounding rule in the system |
| `max_marks_snapshot` | checked against the assessment's `max_marks` | the platform guarantees these agree; if they ever do not, the denominator is ambiguous and the read fails loudly rather than guessing |
| `enrollment_status` + `is_active` | `StudentRef.is_active` | both must hold: a dropped student keeps their results as history but is not in the cohort a class statistic is over |
| `offering.pass_percent` | `pass_mark_percent` | never a constant |
| `offering.config`, department `settings` | the C5 override layers | unknown keys are ignored and reported in `ignored_keys`, so a newer configuration cannot break an older deployment |

`SnapshotSource` (in `services.py`) changed shape in Phase 3 for two reasons: the session belongs to the implementation (decision D-001, as every platform service does it), and scope needs the **actor** — `actor=None` is the unscoped system path for the recompute hook and must never be reached from a request.

**Segment priority** is `PERSISTENTLY_LOW → DECLINING → BORDERLINE → IMPROVING → HIGH_PERFORMER → STABLE` — ordered by what a teacher would act on, not by how good the news is. Improving outranks High Performer because it is the one to reinforce; Stable is last because it is the absence of anything to do.

---

## 9. Attention rules (contract C9 — frozen)

These codes are canonical and **must not be renumbered**: the blueprint used the same R-numbers for different rules, so drift would make a stored `rule_code` mean two things.

| Code | Rule | Compares against | Severity |
|---|---|---|---|
| `R1_LOW_PERFORMANCE` | weighted course score below threshold | `low_performance_percent` (50) | High |
| `R2_FAILED_LATEST` | latest completed assessment below pass | **the offering's pass mark** | Medium |
| `R3_REPEATED_LOW` | `k` consecutive completed below pass | `repeated_low_count` (3) + pass mark | High |
| `R4_SHARP_DECLINE` | latest vs mean of earlier | `decline_drop_pp` (15) | Medium |
| `R5_DECLINING_TREND` | slope at or below the negative threshold | `trend_delta_pp` (5) | Low |
| `R6_LOW_COMPLETION` | completion below threshold | `low_completion_percent` (75) | Medium |
| `R7_BORDERLINE` | within the band either side of the pass mark | `borderline_band_pp` (5) + pass mark | Low |

**Requires academic attention** when any High rule fires, or at least two Medium rules fire. Low rules are informational alone: being borderline is worth showing a teacher, but it is not by itself a call to act.

Message style — state the value, the threshold and the assessments; never predict, never invent a cause:

> Latest assessment 42%. Configured low-performance threshold 50%. Below 50% in 3 consecutive assessments (CT1 46%, CT2 48%, FT1 42%).

Flags have a lifecycle (`open` → `acknowledged` / `resolved`). Analytics only raises; faculty acknowledge and resolve.

---

## 10. Sample payloads

Generated from the real models, not hand-written.

### A classified trend

Emitted by `trends.trend_for()` for student S2 of the canonical fixture (80, 60, 40).

```json
{
  "generated_at": "2026-09-26T10:30:00Z",
  "offering_id": "00000000-0000-4000-8000-000000000001",
  "student_id": "00000000-0000-4000-8000-0000000000b2",
  "label": { "status": "ok", "n": 3, "minimum_n": 2, "reason": null,
             "value": "declining", "vocabulary": "trend" },
  "slope": { "status": "ok", "n": 3, "minimum_n": 2, "reason": null,
             "value": -20.0, "unit": "percentage_points_per_assessment" },
  "method": "least_squares",
  "points_used": ["CT1", "CT2", "FT1"],
  "percentages_used": [80.0, 60.0, 40.0],
  "threshold": { "key": "trend_delta_pp", "value": 5.0, "source": "system_default" },
  "explanation": {
    "narrative": "Least-squares slope across 3 completed assessments: -20.00 pp per assessment (CT1 80.00%, CT2 60.00%, FT1 40.00%). Classified declining against a threshold of 5 pp per assessment.",
    "formula": "n < min_trend_points -> insufficient; n == 2 -> P[-1] - P[-2]; n >= 3 -> least-squares slope over positions 1..n",
    "evidence": [
      { "name": "CT1", "value": "80.00", "unit": "percent", "note": null },
      { "name": "CT2", "value": "60.00", "unit": "percent", "note": null },
      { "name": "FT1", "value": "40.00", "unit": "percent", "note": null },
      { "name": "Method", "value": "least_squares", "unit": null,
        "note": "least-squares fit over the completed series" }
    ],
    "thresholds": [{ "key": "trend_delta_pp", "value": 5.0, "source": "system_default" }],
    "pass_mark_percent": null,
    "assessments_used": ["CT1", "CT2", "FT1"],
    "caveats": ["Assessments are not equated for difficulty: a harder paper lowers percentages across the cohort, so a change between assessments is not by itself evidence about the students."]
  }
}
```

### The same shape when there is only one assessment (contract C10)

```json
{
  "label": { "status": "insufficient_data", "n": 1, "minimum_n": 2,
             "reason": "only 1 completed assessment (minimum 2)",
             "value": null, "vocabulary": "trend" },
  "slope": { "status": "insufficient_data", "n": 1, "minimum_n": 2,
             "reason": "only 1 completed assessment (minimum 2)",
             "value": null, "unit": "percentage_points_per_assessment" },
  "method": null,
  "points_used": ["CT1"],
  "percentages_used": [50.0]
}
```

### An absent result — never a zero

```json
{
  "state": "absent",
  "score": null,
  "max_marks": 50.0,
  "percentage": { "status": "insufficient_data", "n": 0, "minimum_n": 1,
                  "reason": "recorded absent for CT2; an absent result is not a score of 0",
                  "value": null, "unit": "percent" },
  "difference_from_class_mean": { "status": "insufficient_data", "n": 0, "minimum_n": 1,
                  "reason": "no percentage to compare: the student was absent",
                  "value": null, "unit": "percentage_points" },
  "meets_pass_mark": null,
  "explanation": {
    "narrative": "Recorded absent for CT2. The student is counted in the completion denominator and excluded from every mean.",
    "evidence": [{ "name": "Recorded status", "value": "absent", "unit": null,
                   "note": "stored, not derived" }]
  }
}
```

### An attention flag (R3)

```json
{
  "rule_code": "R3_REPEATED_LOW",
  "severity": "high",
  "status": "open",
  "actual": { "status": "ok", "n": 3, "minimum_n": 3, "reason": null,
              "value": 3.0, "unit": "count" },
  "threshold": { "key": "repeated_low_count", "value": 3.0, "source": "system_default" },
  "pass_mark_percent": 40.0,
  "reference_assessments": ["CT1", "CT2", "FT1"],
  "message": "Below the 40% pass mark in 3 consecutive assessments (CT1 38%, CT2 36%, FT1 34%). Configured threshold: 3 consecutive assessments."
}
```

### A generated insight

```json
{
  "scope": "offering",
  "subject_id": null,
  "code": "class_mean_moved",
  "text": "Class mean fell 4.50 pp from CT1 (62.00%) to CT2 (57.50%), across the 58 students assessed in both.",
  "severity": "medium",
  "explanation": {
    "formula": "mean(P_CT2) - mean(P_CT1) over students assessed in both",
    "evidence": [
      { "name": "CT1 mean", "value": "62.00", "unit": "percent" },
      { "name": "CT2 mean", "value": "57.50", "unit": "percent" },
      { "name": "Cohort intersection", "value": "58", "unit": "count" }
    ]
  }
}
```

---

## 11. Edge cases

The matrix Phase 4 must satisfy. Fixtures for every row already exist (§12).

| Case | Required behaviour |
|---|---|
| No students, no assessments | every output returns insufficient data with `n = 0`; nothing raises |
| One student | student analytics work; every group statistic refuses to label |
| Cohort below `min_group_n` | mean returned with its `n`; class-level *labels* withheld |
| One completed assessment | no trend, no consistency, no sharp decline; weighted score = that percentage |
| Exactly two completed | trend by two-point delta, `method = two_point_delta`; still no consistency |
| Student with no rows at all | stays in the cohort; completion 0%; no mean, no segment, no trend |
| Whole cohort absent for an assessment | mean is insufficient data, **not** 0%; completion 0% |
| Absent vs exempt | same papers sat, different completion denominators |
| All students pass / all fail | pass % 100 / 0 — a real answer, not a gate |
| Identical scores | σ = 0, range 0, trend Stable; no division by zero |
| Slope exactly at ±`trend_delta_pp` | classified (comparison is `≥` / `≤`), not Stable |
| Score exactly on the pass mark | passes (`P ≥ pass_mark`) **and** is Borderline (band inclusive) |
| `max_marks = 0` | data error, raises; never a 0% |
| Unpublished assessment | excluded from every default statistic |
| Inactive student | excluded from cohort statistics; own history still readable |
| Pass mark ≠ 40 (e.g. 50) | every pass/borderline answer moves; nothing is hard-coded |
| Threshold overridden per offering | value **and** `source` change in the explanation |
| Unknown key in stored config | ignored, reported in `ignored_keys`, nothing breaks |
| Intervention with a 2-student peer group | outcome withheld: `min_outcome_group_n` applies to both sides |
| Follow-up assessment absent for a target student | that student is in neither the pre nor post mean; `n` shows it |

---

## 12. Test foundation

```
tests/analytics/
    __init__.py       no database, no HTTP client, no root-conftest fixtures — by design
    conftest.py       snapshot / threshold / scenario fixtures, and a fixed clock
    canonical.py      one rich eight-student cohort, hand-computed
    builders.py       scenario builders, one awkward condition each
    test_architecture.py test_contracts.py test_policy.py test_results.py
    test_rules.py     test_thresholds.py test_vocabulary.py test_outputs.py
    test_config.py    test_builders.py
```

If a test in this package ever needs a session, a formula has reached into the database and the layering has been broken.

**`canonical.py`** — eight students over CT1/CT2/FT1 plus an unpublished quiz, pass mark 40, divisors chosen so every percentage is exact: high performer, steady decline, sharp drop (earlier mean 89 → 50), borderline at the mark, persistently low, absent-then-exempt, single-assessment, and an inactive student.

**`builders.py`** — `build_snapshot()` takes a table of **percentages** (`max_marks` defaults to 100, so a cell of 60 is exactly 60.00%) where each cell is a number or `ABSENT` / `EXEMPT` / `MISSING`; a `MISSING` cell produces **no row at all**. Ids are `uuid5`-derived, so scenarios are reproducible.

| Builder | Isolates |
|---|---|
| `single_student` | n = 1: student analytics work, group statistics must refuse |
| `small_class` | n = 3 (< `min_group_n`) with exactly 2 points (= `min_trend_points`): the two gates are independent |
| `multi_assessment_class` | 4 assessments (one unpublished), an absence mid-series, a student who stops sitting |
| `missing_results` | gaps, including a student with no row anywhere |
| `absent_students` | absent vs exempt denominators; a wholly absent student |
| `improving_students` | slopes +10, **exactly +5**, +2, and a two-point series |
| `declining_students` | slopes −10, **exactly −5**, −2, plus a 39 pp cliff |
| `borderline_students` | on the mark, inside the band, on its edge, outside |
| `volatile_students` | identical means, σ of 27.61 / 0.00 / 1.58 |
| `empty_offering` | no students, no assessments |

`test_builders.py` reads every scenario back through the policy layer and asserts it still contains what its name claims — a drifted fixture would let every test built on it pass while proving something else.

---

## 13. Pending platform dependencies

Phase 1 is complete **against the data that exists**. These are needed before the matching analytics can run on real data, and all are requests to Agent 1 (`docs/PROJECT_CONTEXT.md` §12), not work Agent 2 may do:

| Dependency | Blocks | Current state |
|---|---|---|
| `assessments` table (`max_marks`, `weightage`, `sequence_no`, `is_published`) — D1 | every analytic on real data | not yet migrated |
| `assessment_results` (nullable `score` + `status`) — D2 | every analytic on real data | not yet migrated |
| `course_offerings.config` JSONB — D3 | the offering-override layer | `pass_mark_percent` exists; `config` does not, so the layer resolves empty |
| department `settings` table — D4 | the department layer | does not exist; resolves empty |
| `interventions`, `intervention_students` — D5 | contract 10 | not yet migrated |
| `attention_flags` — D6 | flag persistence and history | not yet migrated |
| cohort read method — D8 | `SnapshotSource` implementation | Phase 4 |
| seed dataset with the C11 patterns — D11 | end-to-end verification | not yet delivered |

The resolver already accepts both stored override layers, so when D3 and D4 land only the adapter changes — no rule does.

---

## 14. What Phase 1 delivered, and what is next

**Phase 1 delivered:** the module structure; the eleven contracts with their explainability payload and enforced invariants; the vocabularies; the configuration system (13 keys, four-layer resolution, provenance, validation); the missing-data policy as executable rules; the insufficient-data shape (C10); the frozen rule registry (C9); and the `SnapshotSource` / `RecomputeHook` ports (C4/U1 signature agreed).

**Phase 2 delivered:** F1–F13 — the statistical primitives, per-assessment group statistics (contract 1), the histogram (contract 6), student metrics and history (contracts 2 and 3), and trends (contract 4). 535 pure tests, every canonical expectation hand-computed and quoted in the test that asserts it.

**Phase 3 delivered:** contract 12 (`StudentPerformanceProfile`) composing the Phase 2 measures into one student's history, comparisons, trend and findings; `StudentFinding` with its three-valued verdict; and `repository.py`, the pure mapper plus thin repository that reads real stored data through contract C3. 644 pure tests.

**Next — Phase 4 (class intelligence):** segmentation (F17), class health (F19) and comparison / what-changed (F15–F16), all reading the measures below them rather than recomputing.

**Then:** the R1–R7 attention engine (F18) and the `recompute` hook it fills (C4); interventions and observed outcomes (F20); deterministic insights (F21); then the `/analytics/*` routers with `OfferingAccess` scope on every endpoint.
