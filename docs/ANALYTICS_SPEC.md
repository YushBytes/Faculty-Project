# ACADLYTICS — Analytics Specification

**Owner:** Agent 2 (analytics, intelligence, interventions, reporting)
**Status:** Phase 10 complete — **F1–F21 implemented and served over `/api/v1`**, with CSV/XLSX/PDF downloads, and the deferred persistence delivered: `attention_flags` (D6), `interventions` / `intervention_students` / `intervention_reasons` (D5), migration `0007`, and the real C4 recompute.
**Last updated:** 2026-09-29
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
    service.py          application service: one read, one computation [Phase 9]
    router.py           the /api/v1 endpoints                          [Phase 9]
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
| — | `cohort_shift_pp` | 5 | pp | class-mean, pass-rate, participation and spread movement (F16) |
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
| 12 | `StudentPerformanceProfile` | how is this student doing over time? | `history`, `latest`/`previous`, `change_from_previous`, `historical_average`, `findings` |
| 13 | `AssessmentComparison` | how did the same students move between two assessments? | `intersection_n`, the five deltas, both assessments' own analytics |
| 14 | `StudentAttention` | which rules did this student fire, and does that need acting on? | `flags` (R1→R7), `requires_attention` (derived), `highest_severity` |
| 15 | `InterventionOutcomeSummary` | what do several interventions look like together? | `measurable`, mean/median observed change, `improved`/`declined`/`unchanged` |
| 11 | `GeneratedInsight` *(filled in Phase 8)* | what is the one sentence? | `code`, `scope`, `subject_id?`, `text`, evidence and threshold provenance |

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

| What is "the class mean"? | The mean of the students' **weighted course scores**; the latest paper's mean stays in `latest_assessment` | They answer different questions and differ materially (canonical: 57.36 against 53.50). Mixing them is the easiest way to make a dashboard quietly wrong. |
| Cohort completion: students or cells? | Cells — every `(student, assessment)` the cohort was required to sit | A class where everyone missed one paper and a class where a quarter sat nothing are different situations; counting students reports them identically. |
| Is participation measured over the intersection? | No, over the whole active cohort | "Did fewer students turn up" is a question about everyone, not about the ones who turned up. |
| One movement threshold or four? | One, `cohort_shift_pp` | Whether a movement is worth telling a teacher about should not depend on which of the four numbers moved. |
| What makes a decline "new"? | F10 true at the later assessment and not at the earlier one, via `policy.series_up_to` | "New" is a claim about two states; a student already declining last time has not newly declined. |
| Is Stable the fallback? | No. A student with no classifiable trend and no other segment is **unclassified** | Stable says "nothing to act on", which needs a known-flat trend. Falling through would turn "we do not know" into "all is well". |
| Are attention counts insufficient data? | No — `None`/empty, meaning "not evaluated" | "We did not look" and "we looked and the data was thin" are different statements, and only the second is about the students. |
| Does the borderline band overlap the low band? | With a pass mark of 40 and a low threshold of 50, yes: every borderline student is also persistently low, so borderline is never primary. At the platform's default pass mark of 50 they separate | A consequence of configuration, not of code; pinned by a test so it stays visible. |
| Snapshot result lookup | `OfferingSnapshot.result_for` is backed by a `functools.cached_property` index | It was a linear scan called `n × m` times over `n × m` rows; a 300 × 10 cohort now builds in ~33 ms. Frozen, hashable and equality semantics are unchanged, and the index is never serialised. |

| Is R1 strict or inclusive? | **Strict** (`<`), per C9's "below" — while F17's Persistently Low is inclusive (`<=`) on the same threshold | Both are explicitly specified. A score of exactly the threshold is segmented low and unflagged; a test pins the difference. |
| What does `flag_counts` count? | **Flags**, by severity. `rule_counts` counts **students** | 3 High flags held by 2 students are both true and different numbers; a dashboard needs to know which it is showing. |
| Do overlapping rules collapse? | No. Every fired rule is kept, ordered R1→R7 | Each names a different fact. The ordering is determinism, not priority — C9 ranks no rule above another. |
| Where does the attention verdict live? | `StudentAttention`, which **derives** it in a validator | Computing it in callers is how two views of the same student end up disagreeing. |
| Attention on a student with no data? | Only what is knowable fires — typically R6, since completion of 0% is a fact | A student who sat nothing is not "fine"; nor is their course score zero. |

| Pre/post by date or by sequence? | **Sequence.** A date resolves to one only when every assessment is dated and none falls on the intervention's own day | Dates are optional here and ordering never depends on them; same-day order is unknowable, and guessing moves a result between windows. |
| One pre value per student, or per observation? | Per **student** — the mean of the baselines they sat | Otherwise a student who sat four papers counts four times against one who sat two. |
| A new threshold for the outcome label? | No — `cohort_shift_pp` | A net change is a movement of one group against another, which is what that key already governs. |
| What if an intervention was cancelled? | Insufficient, naming the status | A change measured after an action that did not happen is not an outcome of it — and it is not "no change" either. |
| Two interventions, same students, same window? | Both reported, both carrying `OVERLAP_CAVEAT` | The change sits after both. Assigning it to one would be an attribution this layer cannot make. |
| Is the summary a success rate? | No. `improved` counts groups whose average rose | The targeted students were chosen because they were behind; a rate would read as effectiveness, which nothing here can support. |

| Why not a PDF library? | DECISION-4 is open; WeasyPrint is RISK-6 on Windows and ReportLab would settle a product question unilaterally. A ~250-line writer covers a text report with no dependency | The exporter interface is unchanged if DECISION-4 later picks an engine, so nothing is locked in. |
| One CSV per report, or per table? | One per report, with `# Table` banners; `table_to_csv()` exports a single grid for callers that want one | A faculty member who downloads "the attention report" should get one file, not five. |
| Percentages in XLSX: `62.40` or `0.624`? | `62.40`, with the unit in the header | So a reader comparing the sheet against the PDF sees the same digits. Excel's percent encoding would show 62.40% but store 0.624, which reads as a different number. |
| Formulas in the workbook? | None | A formula is a second source of truth; it can disagree with the analytics that produced the figure beside it. |
| Does report order depend on input order? | Yes, deliberately — cohort order *is* the snapshot's order | The platform returns students by register number, so the report follows it; nothing re-sorts downstream, which is what makes two renderings identical. |

| Do insights get a severity? | No — left unset | The contract allows one, but attaching it would invite ranking findings by it, and that ordering is a judgement for the person who knows the students. |
| Are cluster counts recomputed? | No — they are `rule_counts` from the attention engine | A second loop over students applying R3–R7 would be a second implementation of the same rules, free to drift from the first. |
| Segment *transitions* ("3 moved from Declining to Stable")? | **Not implemented** | Segmentation computes from the current series; a historical segment is derivable but not exposed by any contract, and §19 says not to invent transitions the data does not carry. |
| Why did the causal screen need fixing? | It matched substrings, so "proved" fired inside "improved" | The system says "improved" constantly and legitimately. Whole-word matching keeps every real claim rejected without banning honest wording. |

| Out-of-scope offering: 403 or 404? | **404**, from the platform's own read | A 403 confirms the offering exists. The platform already made this choice (contract C6); the API inherits it rather than deciding again. |
| A student not in the offering? | 404 | The question has no answer for them here, and an empty profile would read like a real one. |
| Does the router check permissions? | No — the service's read does | Two checks are two things to keep in step; a test asserts the router adds none. |
| Where do the API response models live? | `service.py`, composing the analytics contracts | They hold contracts rather than re-describing them, so there is still one definition of every number and the OpenAPI document comes from the engine. |

A guard worth naming: any function taking both a snapshot and a `ThresholdSet` rejects a set resolved against a different pass mark. Quoting one pass mark in an explanation while applying another in the arithmetic is the most misleading thing this layer could do, so it fails loudly instead.

### Deterministic insights (Phase 8, F21)

The analytics, said in sentences. One code, one template, one set of numbers — **no language model, no scoring, no ranking**. Each rule is an `if` over a fact the engine already produced, so running it twice on the same snapshot gives the same words in the same order.

```
existing analytics  ->  insight rules  ->  GeneratedInsight (contract 11)
```

#### Nothing is recalculated

| Insight | The fact behind it |
|---|---|
| class mean / pass rate moved | `ChangeAnalysis` and its `AssessmentComparison` |
| completion moved | `AssessmentComparison.completion_change` |
| decline, declining-trend, repeated-low, low-completion and borderline clusters | `rule_counts` from the attention engine — R3–R7 already evaluated, with their thresholds |
| improvement cluster | `ChangeAnalysis.groups` |
| attention summary | `cohort_attention` counts |
| distribution peak | `ClassHealth.course_score_distribution` |
| student insights | `StudentPerformanceProfile` and its findings |
| intervention | `InterventionOutcome` |

The clusters are the clearest case: "2 students had a decline of at least 15 percentage points" **is** R4's count, with R4's threshold, evaluated once. A fresh loop over students here would be a second implementation of the same rule, free to disagree with the first.

#### Codes

The eleven `InsightCode` members frozen in Phase 1 are reused unchanged. Eight were added for facts none of them named:

| Added | Why |
|---|---|
| `CLASS_COMPLETION_MOVED` | participation between two assessments |
| `DECLINING_TREND_CLUSTER`, `REPEATED_LOW_CLUSTER`, `IMPROVEMENT_CLUSTER` | cohort groups the brief asks for; the existing `STUDENT_*` codes are student-scoped |
| `DISTRIBUTION_PEAK` | the largest band |
| `STUDENT_LATEST_CHANGE`, `STUDENT_COMPLETION_LOW`, `STUDENT_BORDERLINE` | student-level "what changed" facts |

Every code has a category (`INSIGHT_CATEGORY`) and a place in `INSIGHT_ORDER`; a test asserts both mappings are total, so a new code cannot be added without deciding where it belongs.

#### Ordering, and why it is not a ranking

Insights are emitted in `INSIGHT_ORDER` — cohort performance, then participation, then movement, then attention, then the shape of the cohort, then one student, then actions taken. **This is presentation order, not priority.** It says nothing about which finding matters most; that is a judgement for the person reading, who knows the students. Nothing is sorted by severity, and `severity` is deliberately left unset on generated insights so nothing downstream is tempted to rank by it.

#### Duplicate suppression

One insight per `(code, subject_id)`. A fact reached by two paths is one fact; two *different* facts are two insights, so a falling class mean and a falling pass rate both survive. Two students with the same code both survive, because their subjects differ.

#### Insufficient data, and the zero that is not

The distinction this layer is most at risk of blurring:

| Situation | Result |
|---|---|
| one assessment, so no comparison | **no insight** — never "the class average was stable" |
| no students assessed in both | no insight |
| a rule nobody fired | no insight — never "0 students declined" |
| no attention flags at all | no insight — §15 forbids a manufactured warning, and an all-clear is a stronger claim than this layer should make |
| a tie for the largest distribution band | no insight — naming one of two would be a choice the data does not make |
| a genuine zero change | **"remained unchanged at 70.00%"** — that is a fact, and it is reported |

#### Evidence and provenance

Every insight carries structured evidence, not just prose: endpoint values, the change, the student count, the students affected by name, and — where a threshold decided the outcome — its value **and source** (`system_default`, `department_setting`, `offering_override`). The contract already refuses an insight with no evidence.

#### Wording

Neutral and observational: *increased, decreased, remained unchanged, below threshold, within threshold*. No loaded language, and no explanation of **why** — this system has no data about effort, attendance, health or circumstance, and a sentence that guessed would be fiction with a number attached. Tests sweep every generated sentence for speculative words as well as causal ones.

Every sentence passes through `FORBIDDEN_PHRASES` at construction, so a template reaching for "caused", "effectiveness" or "at risk of failing" fails in the test suite rather than in front of a teacher.

> **Defect fixed here:** that screen matched *substrings*, so "proved" fired inside "improved" — banning the entirely legitimate sentence "4 students improved by at least 5 percentage points". It now matches whole words. (An earlier repair attempt left a literal backspace byte in the source, which silently disabled the screen altogether; the current form uses space-padded containment and needs no escaping at all.)

#### Report integration

The class summary, student and intervention reports each gained an **Insights** section listing the sentence, its code and its evidence — so the insights reach CSV, XLSX and PDF through the Phase 7 pipeline with no new export path. The report builders still calculate nothing.

### The API (Phase 9)

The analytics reach an HTTP client without a second implementation of anything.

```
OfferingResultsService (platform, scoped)   ->  AnalyticsRepository  ->  OfferingContext
                                                                             |
                                            analytics/core  <-----------------
                                                   |
                                            AnalyticsService  ->  router  ->  JSON / file
```

| Endpoint | Returns |
|---|---|
| `GET /api/v1/offerings/{id}/analytics` | `ClassHealth`, `ChangeAnalysis`, attention counts, insights |
| `GET /api/v1/offerings/{id}/students/{student_id}/analytics` | profile, segment, flags, insights |
| `GET /api/v1/offerings/{id}/attention` | every flag, R1→R7, overlaps preserved |
| `GET /api/v1/offerings/{id}/insights` | the deterministic sentences |
| `GET /api/v1/offerings/{id}/reports/{kind}?format=csv\|xlsx\|pdf` | the report as a download |

#### Authorisation

There is **no second RBAC system**. Every read goes through `OfferingResultsService.for_user`, so an offering outside the caller's scope raises the platform's own `NotFoundError` — out-of-scope and non-existent are the same **404**, and existence is never disclosed. A student who is not enrolled in the offering is also a 404: "how is this student doing in this offering" has no answer for them, which is different from an empty profile.

#### One read, one computation

`class_health` builds the cohort's profiles and segments; `class_insights` needs the same health block, attention and comparison. The service computes each fact **once** and threads it down (`class_insights` gained optional `health`/`attentions`/`analysis` parameters for exactly this), so a dashboard request builds the cohort once rather than three times. A test asserts the platform is read exactly once per request.

#### Insufficient data is a 200

A trend that could not be classified, a comparison with no earlier assessment, an attention block that was not evaluated — each is a **value in the response carrying its own reason**, not an error and not a silent zero. The only 4xx responses concern the request itself: unauthenticated (401), out of scope or unknown student (404), unknown report kind (422, rejected by the enum) or unknown export format (404).

#### Serialisation

Response models **are** the analytics contracts, so the OpenAPI document at `/docs` is generated from the same definitions the engine produces — there is no parallel set of API schemas to drift. Decimals serialise as JSON numbers, enums as their values, and evidence, thresholds, threshold sources and data coverage all survive the trip.

> **Defect fixed here:** `SeriesPoint` used a plain `Decimal`, so a student's score serialised as the *string* `"45.00"` while every mean beside it was the number `45.0`. It now uses `JsonDecimal` like every other published number. Python-side values are unchanged — the type only affects JSON rendering.

#### Persistence (delivered in Phase 10)

Attention flags and interventions are now stored (D5/D6) and the C4 hook is the real implementation. `intervention_outcomes(...)` still takes caller-supplied records — that is what lets the outcome analytics be proved against fixtures with no database — and `GET /offerings/{id}/interventions/outcomes` passes the stored ones in.

### Reporting and export (Phase 7)

The last step of the loop: DATA → INSIGHT → ACTION → MEASUREMENT → **REPORT**. Reports format what the engine already computed; they calculate nothing.

```
analytics contracts  ->  reports/model.Report  ->  csv | xlsx | pdf
                            (one object)          (three serialisers)
```

Analytics is computed **once** per report and the three formats serialise the same object, which is why they agree — and why "they agree" is a test rather than a promise.

#### Report types

| Report | Answers | Built from |
|---|---|---|
| Class summary | how is this offering doing? | `class_health`, `assessment_analytics` per assessment, segment and attention counts |
| Student performance | how is this student doing? | `student_profile`, `student_segment`, `cohort_attention`, their interventions |
| Attention | who needs a teacher's time, and why? | `cohort_attention` — every flag with its evidence |
| Assessment comparison | what moved between two assessments? | `change_analysis` / `compare_assessments` |
| Intervention outcome | what was observed after each action? | `intervention_outcomes`, `outcome_summary` |

#### The cell, which is the whole design

A report is sections of tables of cells, and each cell carries three things:

| Part | Purpose |
|---|---|
| `text` | the canonical display string — what CSV writes and PDF prints |
| `number` | the same value as a `Decimal` when there is one, so XLSX stores a real number a spreadsheet can sum. `None` is **not** zero |
| `note` | *why* there is no number, when there is not — the shortfall analytics already worded |

That shape is what makes an absent result export as `absent` rather than `0`, and an unclassifiable trend export as `insufficient data (only 1 completed assessment (minimum 2))` rather than an empty cell.

#### Missing data, and the three different absences

| State | Exports as |
|---|---|
| not evaluated | `not evaluated` — this build did not look |
| insufficient data | `insufficient data` plus the reason |
| absent / exempt / missing result | the word (`absent`, `exempt`, `missing`), with "not a score of 0" as the note |

None of these is ever rendered as `0`, blank, `N/A`, "no change" or "passed".

#### Deterministic ordering

Decided in `builders.py` and re-sorted nowhere downstream, so two renderings are byte-identical:

| Thing | Order |
|---|---|
| students | the snapshot's cohort order (the platform returns students by register number) |
| assessments | `sequence_no` |
| attention flags | student order, then rule code R1 → R7 |
| interventions | the order the caller supplied |
| outcomes | intervention order |
| columns | header order; rows: as built |

Rule order is **determinism, not priority** — flags are never re-sorted by severity, so R1 and R3 (both High) keep their registry order.

#### Export conventions

The project had none, so these are chosen and recorded here:

| Aspect | Choice |
|---|---|
| CSV encoding | UTF-8 **with BOM**, so Excel opens non-ASCII names correctly |
| CSV line endings | `\r\n` (RFC 4180) |
| CSV structure | one file per report; each table preceded by a `# Table,<name>` banner, metadata and notes as `# ` rows |
| XLSX | a cover sheet, then one sheet per table; numbers stored as numbers; **no formulas**, since a formula is a second source of truth that can disagree with analytics |
| Percentages | `62.40%` in text; the bare number `62.40` in a spreadsheet cell (not Excel's `0.624`), so the digits match across formats |
| Percentage points | signed, `+0.00;-0.00;0.00` — a movement's direction is the point |
| Dates | ISO-8601 |
| NaN / Infinity | impossible: rejected by analytics at construction and by `Cell.number` as a pydantic field |

#### PDF, and DECISION-4

DECISION-4 (which PDF engine) is **still open**, and §14 of `PROJECT_CONTEXT.md` gates reports on it. WeasyPrint needs native GTK/Pango and is recorded as RISK-6 for blocking PDF generation outright on a Windows host; ReportLab would mean adding a dependency to a shared `pyproject.toml` and settling an open product question unilaterally.

So `reports/pdf.py` writes the PDF itself — about 250 lines, no dependency. A text-only report needs no library: PDF is a text container and the base-14 fonts (Helvetica) are present in every reader, so nothing is embedded. Output is valid PDF 1.4 with a correct xref table; text is selectable and searchable; long reports paginate.

**This does not pre-empt DECISION-4.** If the project later wants charts or styled layout, `pdf.render()` is replaced and the exporter interface above it does not change — it only ever receives a `Report`.

#### Attention and intervention export safety

Attention exports preserve every flag (a student with three fires appears three times, never collapsed to one "reason"), each with its actual value, threshold, **threshold source**, reference assessments and explanation.

Intervention exports use *observed change*, *target-group change*, *comparison-group change* and *observed difference in change*. The column header is "Observed difference in change"; there is no "effectiveness" column and no success rate. `OBSERVATIONAL_CAVEAT` is printed on the report. A word-boundary test sweeps every export for *treatment effect, causal, effectiveness, ineffective, proves, proved, resulted from, will fail, at risk of failing* — and asserts that the only occurrence of "caused" anywhere is inside the caveat's own denial of causation.

### Interventions and observed outcomes (Phase 6)

The ACTION → MEASUREMENT half of the loop. `core/interventions.py` measures what happened after a recorded intervention and **never attributes it**: the targeted students were chosen *because* they were struggling, the groups were not randomised, and nobody was withheld support to make the arithmetic cleaner. Every output carries `OBSERVATIONAL_CAVEAT`, and the contract screens its narrative for causal wording.

#### The record — `Intervention` (an input, in `core/contracts.py`)

| Field | Answers | Note |
|---|---|---|
| `student_ids` | **who** | one or more targets, no duplicates |
| `kind` | **what** | `InterventionKind`: academic support, remedial session, faculty meeting, peer support, additional practice, counselling referral, other |
| `after_sequence_no` | **when** | the assessment sequence the intervention follows; `0` means before any assessment |
| `recorded_on` | when, for display | never used to order assessments |
| `reasons` | **why** | `InterventionReason`: rule code, the value observed *at the time*, the threshold it was compared against, the assessments involved |
| `status` | planned / active / completed / cancelled | only `active` and `completed` can have an outcome |
| `note` | free text | allowed, but never the only record of the reason |

`reason_from_flag()` builds a reason from an `AttentionFlag`, freezing what the teacher saw — recomputing the flag later may give a different number, which is exactly why the original is kept.

#### Pre and post — a sequence, not a date

**Pre** is every published assessment at or below `after_sequence_no`. **Post** is the first published assessment after it.

The boundary is a *sequence* because assessment dates are optional in this system and ordering never depends on them (§3). `boundary_from_date()` converts a date to a sequence where the data allows, and **refuses** — returning `None` — when any published assessment has no date, or when an assessment falls on the intervention's own date. Same-day ordering is unknowable, and guessing would silently move a result from one window to the other.

#### The measurement

- A student contributes **one** pre value (the mean of the baselines they were *assessed* in) and **one** post value (their follow-up percentage). A student who sat four baselines does not outweigh one who sat two.
- Only students assessed in **both** windows are counted; absent, exempt and missing drop out and are reported in `coverage`, never as zeroes. A genuine 0 is a real score and stays in.
- **Target** = the intervention's students. **Peers** = the rest of the active cohort. Both are gated at `min_outcome_group_n` (3).
- `change = post_mean − pre_mean` per group; `net_change = target.change − peers.change`, in percentage **points**.
- The label reads the net change against `cohort_shift_pp` — the same magnitude every other cohort movement is judged by, rather than a new threshold: `target_improved_more`, `target_improved_less`, `no_measurable_difference`.

The peer group is the point. Without it, "the targeted students went up 8 pp" says nothing — the whole class may have gone up 8 pp.

#### Insufficient, and the several ways to be so

| Situation | Reported as |
|---|---|
| no assessment since the intervention | insufficient, "nothing yet to measure… not a finding that nothing changed" |
| nothing before the intervention | insufficient, no baseline to compare against |
| either group below `min_outcome_group_n` | that group's change insufficient; net and label insufficient |
| intervention cancelled or still planned | insufficient, naming the status — a change after an action that did not happen is not an outcome of it |

None of these is ever a change of zero.

#### Several interventions

Each is measured in **its own** window; they are never merged. Where two share students *and* a follow-up window, both outcomes carry `OVERLAP_CAVEAT`: the same change sits after both actions, and saying which one it belongs to would be an attribution this layer cannot make.

`outcome_summary()` (contract 15) gives descriptive statistics across several outcomes — how many were measurable, mean and median observed change, and counts up/down/unchanged. Deliberately **not** a success rate and not effectiveness: `improved` counts interventions whose targeted group's average rose, and nothing more.

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

### Class intelligence and "what changed?" (Phase 4)

Three modules, no new arithmetic: every number is a Phase 2 function applied to a cohort-level list, and every verdict is a threshold comparison. **There are no significance tests and no p-values.** Assessments are not equated for difficulty, so a movement is a fact about the marks and never, on its own, a claim about the students.

#### F15 — `AssessmentComparison` (contract 13), in `comparison.py`

A change is measured over the **cohort intersection**: the students assessed in *both* assessments. Subtracting two published means measures the change in who sat the paper as much as the change in how they did.

> Canonical CT1 → CT2: CT1's own mean is 63.67 (n=6) and CT2's is 62.40 (n=5). The naive difference is **−1.27 pp**, a fact about nobody — S7 sat CT1 and not CT2. Over the five students who sat both, the class moved **−4.00 pp**.

| Delta | Over | Source |
|---|---|---|
| `mean_change`, `median_change` | intersection | `statistics.mean_percent`, `median_percent` |
| `pass_percent_change` | intersection | `statistics.pass_percent` |
| `spread_change` | intersection (needs n ≥ 2) | `statistics.std_dev_percentage_points` |
| `completion_change` | **the whole active cohort** | `statistics.completion_percent` |

Participation is the deliberate exception: "did fewer students turn up?" is a question about everyone, not about the ones who turned up. Its two denominators are quoted in the explanation because they differ whenever someone is exempt from one assessment and not the other. Both assessments' own statistics travel in `from_analytics`/`to_analytics`, so both numbers are available and neither can be mistaken for the other.

#### F16 — `ChangeAnalysis` (contract 9)

Composes F15 and adds who moved. `class_mean_change` and `pass_percent_change` are the *same objects* as the comparison's, enforced by a validator — not a second calculation.

**Movement groups**, five, always present, each carrying its members (a count with no names is not actionable):

| Group | Condition |
|---|---|
| Crossed up to the pass mark | `P_before < pass ≤ P_after` |
| Crossed below the pass mark | `P_after < pass ≤ P_before` |
| Improved by at least the margin | `Δ ≥ improvement_delta_pp` |
| Declined by at least the margin | `Δ ≤ −improvement_delta_pp` |
| Newly showing a sharp decline | F10 true on the series truncated at the later assessment, and **not** true truncated at the earlier one |

"Newly" is a claim about two states, so the rule is evaluated twice against `policy.series_up_to`. A student whose earlier series was too short to judge counts as new when the condition holds now — the condition has appeared, which is what the word means.

**Class findings**, four, judged against `cohort_shift_pp`: `class_mean_moved`, `pass_rate_moved`, `participation_moved`, `spread_moved`. `detected = |Δ| ≥ cohort_shift_pp`, with `direction` carried separately so magnitudes are never read as gains. All four are always returned: "the pass rate did not move" is an answer a teacher wants.

#### F17 — `StudentSegment` (contract 7), in `segmentation.py`

Pure composition of the Phase 2/3 facts already on the student's profile.

| Segment | Satisfied when |
|---|---|
| Persistently Low | `W ≤ low_performance_percent`, or a trailing run below the pass mark (F11) |
| Declining | trend is Declining (F9), or a sharp decline (F10) |
| Borderline | `|W − pass_mark| ≤ borderline_band_pp` |
| Improving | trend is Improving (F9) |
| High Performer | `W ≥ high_performance_percent` |
| Stable | none of the above, **and the trend was classifiable** |

`primary` is the first satisfied in `SEGMENT_PRIORITY`; every satisfied segment travels as a `factor` with its own evidence. `segment_counts` counts primaries only, so a borderline-and-improving student is counted once.

#### F19 — `ClassHealth` (contract 5), in `class_health.py`

| KPI | Definition |
|---|---|
| `class_mean`, `median` | over the students' **weighted course scores** |
| `pass_percent` | share of *course scores* at or above the pass mark |
| `completion_percent` | over every `(student, published assessment)` cell the cohort was required to sit — cells, not students |
| `course_score_distribution` | the ten-bin histogram of course scores |
| `segment_counts` | primary segments (F17) |
| `latest_assessment` | that paper's own `AssessmentAnalytics` |
| `latest_comparison`, `findings` | the most recent adjacent comparison and its movements |
| `students_requiring_attention`, `flag_counts` | **not evaluated** — `None` and empty |

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

### How each rule is evaluated (Phase 5)

`core/attention.py` evaluates the registry; it computes nothing of its own. Each rule reads the Phase 2/3 fact that owns the number, and a test asserts the flag's `actual` **is** that measure.

| Rule | Fires when | Fact it reads |
|---|---|---|
| R1 | `W < low_performance_percent` | `student.weighted_course_score` |
| R2 | latest completed `P < pass_mark` | `series.latest_assessed` |
| R3 | trailing run `>= repeated_low_count` | `student.repeated_low_run` |
| R4 | `drop <= -decline_drop_pp` | `student.decline_against_earlier_mean` |
| R5 | trend classified Declining | `trends.student_trend` |
| R6 | `completion < low_completion_percent` | `student.completion_percent` |
| R7 | `|W - pass_mark| <= borderline_band_pp` | `student.pass_mark_distance` |

**A rule whose fact is insufficient data does not fire.** It returns nothing — not a flag, and not a "passed" verdict. The contract refuses a flag whose `actual` could not be computed.

**Boundary note, deliberate:** R1 is **strict** (`<`) because C9 says "below", while the Persistently Low *segment* (F17) is **inclusive** (`<=`) on the same threshold. A weighted course score of exactly `low_performance_percent` is therefore segmented low and unflagged. Both are as specified; a test pins the disagreement so it is not "tidied up".

**R3 never fires alone.** A trailing run below the pass mark means the latest completed assessment is below it, so R2 always accompanies R3. That follows from the definitions, not from the implementation.

### Overlapping flags, and what gets counted

Every fired rule is kept — a student who is low, failed the latest paper and has been below the mark three times running holds three flags, and each names a different fact. `StudentAttention` (contract 14) is the canonical home for one student's flags plus the verdict, and the contract **derives** `requires_attention` from the severities rather than accepting it, so no caller can reach a different answer.

Flags are ordered R1 → R7. That is **determinism, not priority**: nothing in C9 ranks one rule above another.

| Count | Over | Field |
|---|---|---|
| `flag_counts` | **flags**, by severity | `ClassHealth.flag_counts` |
| `rule_counts` | **students**, by rule (a rule holds at most one flag per student) | `ClassHealth.rule_counts` |
| students requiring attention | **students** meeting the escalation rule | `ClassHealth.students_requiring_attention` |

The canonical cohort makes the distinction concrete: **11 flags across 6 students, of whom 2 require attention**, with 3 High *flags* held by 2 *students*.

### Evaluated, versus not evaluated

`class_health()` and `change_analysis()` take `evaluate_attention` (default `True`).

| State | Looks like | Means |
|---|---|---|
| not evaluated | `students_requiring_attention` is `None`, counts empty | this build did not run the rules |
| evaluated, nobody | `students_requiring_attention.value == 0` with its `n`, counts empty | every student was put to the rules and none escalated |

These must never collapse into one. The second is a finding about the cohort; the first is a statement about the build.

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

### An attention flag (R1), and the student who holds it

One flag, from `attention.cohort_attention()` for canonical student RA004 (course score 41.00%).

```json
{
  "rule_code": "R1_LOW_PERFORMANCE",
  "severity": "high",
  "status": "open",
  "actual": { "status": "ok", "n": 3, "minimum_n": 1, "reason": null,
              "value": 41.0, "unit": "percent" },
  "threshold": { "key": "low_performance_percent", "value": 50.0, "source": "system_default" },
  "pass_mark_percent": null,
  "reference_assessments": ["CT1", "CT2", "FT1"],
  "message": "Weighted course score 41.00% across 3 completed assessments (CT1, CT2, FT1). Configured low-performance threshold 50%.",
  "explanation": {
    "formula": "W = sum(P_a * w_a) / sum(w_a) over completed assessments; W < threshold",
    "evidence": [
      { "name": "CT1", "value": "42.00", "unit": "percent" },
      { "name": "CT2", "value": "40.00", "unit": "percent" },
      { "name": "FT1", "value": "41.00", "unit": "percent" }
    ],
    "thresholds": [{ "key": "low_performance_percent", "value": 50.0, "source": "system_default" }],
    "assessments_used": ["CT1", "CT2", "FT1"]
  }
}
```

### A student holding several flags (RA005)

```json
{
  "flags": ["R1_LOW_PERFORMANCE", "R2_FAILED_LATEST", "R3_REPEATED_LOW"],
  "requires_attention": true,
  "highest_severity": "high",
  "explanation": {
    "narrative": "3 rules fired: R1_LOW_PERFORMANCE (high), R2_FAILED_LATEST (medium), R3_REPEATED_LOW (high). That meets the escalation rule - any High rule, or two Medium ones - so this student is listed as requiring academic attention."
  }
}
```

*(`flags` is shown by code here; each is a full `AttentionFlag` like the one above.)*

### A student with nothing to report (RA001)

```json
{
  "flags": [],
  "requires_attention": false,
  "highest_severity": null,
  "explanation": {
    "narrative": "No attention rule fired for this student. Every rule was put to the data available; where a rule needed more completed assessments than this student has, it was left unjudged rather than counted as passing."
  }
}
```

### Insufficient data for a rule

Canonical RA006 sat one assessment (absent, exempt, then 60%). R4 and R5 need two completed assessments, so neither is judged — and neither appears as a passed rule. Only R6 fires, on a completion of 50.00% that *is* knowable:

```json
{ "flags": ["R6_LOW_COMPLETION"], "requires_attention": false, "highest_severity": "medium" }
```

### Class-level counts, evaluated

```json
{
  "students_requiring_attention": { "status": "ok", "n": 7, "value": 2, "unit": "count" },
  "flag_counts": { "high": 3, "medium": 5, "low": 3 },
  "rule_counts": { "R1_LOW_PERFORMANCE": 2, "R2_FAILED_LATEST": 1, "R3_REPEATED_LOW": 1,
                   "R4_SHARP_DECLINE": 2, "R5_DECLINING_TREND": 2, "R6_LOW_COMPLETION": 2,
                   "R7_BORDERLINE": 1 }
}
```

### Class-level, attention not evaluated

```json
{ "students_requiring_attention": null, "flag_counts": {}, "rule_counts": {} }
```

Not the same as the block above with zeroes in it: this build did not run the rules.

### An intervention outcome

Four students given remedial sessions after CT2, against the four who were not.

```json
{
  "intervention_id": "…",
  "baseline_assessments": ["CT1", "CT2"],
  "follow_up_assessment": "CT3",
  "target": { "name": "target", "n": 4, "pre_mean": 50.0, "post_mean": 67.0, "change": 17.0 },
  "peers":  { "name": "peers",  "n": 4, "pre_mean": 70.0, "post_mean": 72.5, "change": 2.5 },
  "net_change": { "status": "ok", "n": 8, "value": 14.5, "unit": "percentage_points" },
  "label": { "status": "ok", "value": "target_improved_more", "vocabulary": "intervention_outcome" },
  "explanation": {
    "narrative": "Across the 4 targeted students assessed in both windows, the average moved from 50.00% before the intervention (CT1, CT2) to 67.00% in CT3: 17.00 percentage points. The 4 other students assessed in both windows moved from 70.00% to 72.50%: 2.50 percentage points. The observed difference in change is 14.50 percentage points.",
    "formula": "per student: pre = mean of assessed baselines, post = follow-up percentage; group change = mean(post) - mean(pre); net = target change - peers change",
    "caveats": ["Observed change only. Students were not randomly assigned and no control was held, so this comparison does not show that the intervention caused the change."]
  }
}
```

*(group means shown flattened; each is a full `Measure` with its `n`.)*

### An outcome that cannot be measured

```json
{
  "follow_up_assessment": null,
  "net_change": { "status": "insufficient_data", "value": null,
                  "reason": "no published assessment has been held since this intervention" },
  "label": { "status": "insufficient_data", "value": null },
  "explanation": { "narrative": "No published assessment has been held since this intervention, so there is nothing yet to measure. This is not a finding that nothing changed." }
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
| `interventions`, `intervention_students` — D5 | persisting interventions | migrated in `0007`, with `intervention_reasons` for the reason trail |
| `attention_flags` — D6 | flag persistence and history | migrated in `0007`; resolved, never deleted, so history survives recompute |
| cohort read method — D8 | `SnapshotSource` implementation | Phase 4 |
| seed dataset with the C11 patterns — D11 | end-to-end verification | not yet delivered |

The resolver already accepts both stored override layers, so when D3 and D4 land only the adapter changes — no rule does.

---

## 14. What Phase 1 delivered, and what is next

**Phase 1 delivered:** the module structure; the eleven contracts with their explainability payload and enforced invariants; the vocabularies; the configuration system (13 keys, four-layer resolution, provenance, validation); the missing-data policy as executable rules; the insufficient-data shape (C10); the frozen rule registry (C9); and the `SnapshotSource` / `RecomputeHook` ports (C4/U1 signature agreed).

**Phase 2 delivered:** F1–F13 — the statistical primitives, per-assessment group statistics (contract 1), the histogram (contract 6), student metrics and history (contracts 2 and 3), and trends (contract 4). 535 pure tests, every canonical expectation hand-computed and quoted in the test that asserts it.

**Phase 3 delivered:** contract 12 (`StudentPerformanceProfile`) composing the Phase 2 measures into one student's history, comparisons, trend and findings; `StudentFinding` with its three-valued verdict; and `repository.py`, the pure mapper plus thin repository that reads real stored data through contract C3.

**Phase 4 delivered:** F15 (`AssessmentComparison`, contract 13), F16 (`ChangeAnalysis`, contract 9), F17 (`StudentSegment`, contract 7) and F19 (`ClassHealth`, contract 5); `ClassFinding` for cohort movement; one new threshold, `cohort_shift_pp`; and a cached result index behind `OfferingSnapshot.result_for`. 783 pure tests.

**Phase 5 delivered:** F18 — the R1–R7 engine over the Phase 2/3 facts, `StudentAttention` (contract 14) with a derived verdict, cohort counts (flags by severity, students by rule, students requiring attention), `ClassHealth` and `ChangeAnalysis` integration behind `evaluate_attention`, and the evaluated-versus-not-evaluated distinction. 924 pure tests.

**Not in Phase 5, deliberately:** `attention_flags` storage (D6), migration `0007`, and the real C4 `recompute` implementation. They needed a database to test the write path and the migration chain, and none was reachable at the time — delivered in **Phase 10**.

**Phase 6 delivered:** F20 — the `Intervention` record (who, what, when, why), sequence-based pre/post windows, per-student pairing, target-against-peer observed change, `InterventionOutcomeSummary` (contract 15), and a causal-language screen extended to the vocabulary an intervention report must never reach for. 1,000 pure tests.

**Phase 7 delivered:** the report model (metadata, sections, typed cells), five report builders, and three exporters — CSV, XLSX and a dependency-free PDF writer. Analytics is computed once per report and serialised three ways, with cross-format agreement asserted by test. 98 report tests, 1,098 pure tests in total.

**Phase 8 delivered:** F21 — nineteen insight codes with a category and a fixed presentation order, rules that read only existing facts, duplicate suppression, threshold provenance in the evidence, and an Insights section in the class, student and intervention reports. 118 insight tests; 1,218 pure tests in total.

**Phase 9 delivered:** `AnalyticsService` and five `/api/v1` endpoints serving class analytics, student analytics, attention, insights and report downloads — reusing the platform's scope, computing analytics once per request, and generating the OpenAPI document from the analytics contracts themselves. 60 API tests, 1,278 pure tests in total.

**Phase 10 delivered:** the deferred persistence, against real PostgreSQL. `attention_flags` (D6) materialised from the engine by the C4 recompute hook; `interventions`, `intervention_students` and `intervention_reasons` (D5); migration `0007`; and four intervention endpoints. 47 database-backed tests, 1,646 in total.

**Where the truth lives.** The analytics engine stays the single source of truth for attention: `GET /offerings/{id}/attention` and every report still compute from the current snapshot, so no response changed in Phase 10. The table is a *materialised* copy maintained by recompute — it exists for history (D6), for the dashboard index `attention_flags(offering_id, status)` (D9), and so an intervention reason can point by foreign key at the flag that prompted it. It is deliberately **not** readable or writable over HTTP: two endpoints answering "what is firing?" would be two sources of truth, and a client-created flag would be indistinguishable from a rule that actually fired.

**Synchronisation.** A rule that fires with no live row inserts one (`open`); one that still fires has its value, threshold and message refreshed in place, keeping `created_at` and any `acknowledged` status; one that no longer fires becomes `resolved` with a `resolved_at`. Recomputing unchanged data therefore inserts nothing, and a partial unique index on `(offering_id, student_id, rule_code) WHERE status <> 'resolved'` makes that a database guarantee rather than an assumption about interleaving.

**No stored outcomes.** Outcome measurement stays in the Phase 6 engine. An outcome changes the moment a new assessment lands, so a stored copy would be a second answer that disagrees with the first.
