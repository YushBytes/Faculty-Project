# ACADLYTICS — Project Context

**Status:** Agent 1's platform Phases 1–7 are complete on `backend` (auth/RBAC, organisation + scope, students, assessments + results, import pipeline, audit, seed data). The Agent 1 → Agent 2 handoff is `docs/AGENT_2_ANALYTICS_CONTRACT.md`; D1–D4 and D7–D11 are delivered, D5/D6 are Agent 2's own tables. Phase status moves fast — `README.md` on `backend` is the live source; the table in §14 records what this audit verified.
**Last updated:** 2026-09-26
**Repository:** `YushBytes/Faculty-Project`. **Development happens on the `backend` branch**; `main` holds only a placeholder README and receives reviewed merges. Public — see RISK-16.
**Source documents:** `docs/reference/ACADLYTICS_Project_Blueprint.pdf` (50 pp., dated 2026-09-22) and the Master Project Context prompt (reduced-scope directive, 2026-09-26). `README.md` is authoritative for layout, ownership and API conventions.
**Authority:** Where the blueprint and the reduced-scope directive disagree, **the reduced-scope directive wins.** Every such conflict is recorded in §11 and §12.

---

## 1. Project Overview

ACADLYTICS is an **Academic Performance Intelligence Platform** for faculty and HOD/Admin users. Its product loop is:

```
DATA  ->  INSIGHT  ->  ACTION  ->  MEASUREMENT
```

- **DATA** — faculty upload existing Excel/CSV assessment marks; the system validates, previews and stores them without altering academic values.
- **INSIGHT** — deterministic, explainable analytics over stored results (class health, trends, distributions, segmentation, attention flags).
- **ACTION** — faculty record interventions against a named set of students.
- **MEASUREMENT** — the system reports *observed change* after a follow-up assessment, against a peer baseline, without claiming causality.

The differentiator is not prediction accuracy. It is that **every number the system shows can be traced back to stored assessment data, a configured threshold, and a named rule.**

### Scale assumptions (from blueprint, to be confirmed)

1 department · ~4 batches · ~12 sections · ~800 students · ~40 faculty · ~60–70 students per section · ~200 rows per import.

This scale is handled synchronously by FastAPI + PostgreSQL. **No job queue, no Redis, no Celery, no microservices, no Kubernetes.**

---

## 2. Current Scope

**Backend only.** No frontend work (no React/Vite/Next.js) is in scope at this stage.

### In scope

| # | Capability | Layer |
|---|-----------|-------|
| 1 | Faculty/Admin login, JWT, refresh, RBAC | Platform |
| 2 | Faculty sees only their own course offerings (scope enforcement) | Platform |
| 3 | Departments, terms, courses, sections, offerings, faculty assignment | Platform |
| 4 | Student master data | Platform |
| 5 | Assessment definitions (CT1, CT2, FT1, Quiz, Assignment, Internal) | Platform |
| 6 | Assessment-level results (score, max, status) | Platform |
| 7 | Excel/CSV upload → parse → validate → preview → correct → confirm (atomic) | Platform |
| 8 | Import history and audit trail | Platform |
| 9 | Student performance, history, class performance | Intelligence |
| 10 | Assessment comparison, score distributions | Intelligence |
| 11 | Trends (improving / stable / declining / insufficient data) | Intelligence |
| 12 | Attention centre: R1–R7 explainable rules | Intelligence |
| 13 | Segmentation, borderline detection, most-improved | Intelligence |
| 14 | Consistency / volatility analysis | Intelligence |
| 15 | "What Changed?" analysis | Intelligence |
| 16 | Deterministic teacher insights (no LLM) | Intelligence |
| 17 | Interventions + observed-outcome measurement | Intelligence |
| 18 | PDF / XLSX / CSV reports | Intelligence |

### Out of scope now

Frontend · question-level data · topic-level data · question difficulty/discrimination · ML risk prediction · AI copilot · what-if simulation · attendance · student login · department-wide reports. Full list with reasons in §11.

---

## 3. Data Limitations — the single most important constraint

**We do not reliably have question-level or topic-level academic data.**

What real faculty sheets actually give us is *assessment-level*:

```
Register No | Student Name | Assessment | Score | Max Score | Percentage | Date | [Status] | [Course/Section/Offering]
```

### Consequences

1. **No analytics may depend on question or topic data.** Topic mastery, topic weakness, question difficulty, discrimination index, question-to-topic weighted mapping and topic-based interventions are all unavailable, because their input data does not exist.
2. **The system must never fabricate the missing layer.** Creating one synthetic "question" per assessment purely to satisfy the blueprint's schema is rejected — see DECISION-1 in §12.
3. **Analytics must be complete and correct on assessment-level data alone.** They must not degrade into "insufficient data" everywhere merely because a question layer is absent.
4. If question/topic structures are ever added for a future release, they must be **isolated**: no current analytic may read them, and no current analytic may break when they are empty.

### Missing-data policy (binding on both agents)

```
ABSENT != 0     MISSING != 0     NOT ASSESSED != 0     EXEMPT != 0
```

| State | How represented | In mean? | Counts as completed? |
|-------|-----------------|----------|----------------------|
| `present` | stored row, `score` not null | **Yes** | Yes (assessed) |
| `absent` | stored row, `score` null | No | No — counted as *not completed* |
| `exempt` | stored row, `score` null | No | Excluded from the denominator entirely |
| *missing* | **no row exists** (derived, not stored) | No | No — counted as not completed |
| *incomplete* | derived: results exist for some but not all published assessments in the offering | n/a | Reduces completion % |

Rules:

- Three **stored** statuses (`present`, `absent`, `exempt`); two **derived** states (`missing`, `incomplete`). Do not add `missing`/`incomplete` to the database enum — they are the *absence* of data, not a value.
- A blank cell in an upload becomes `absent`, **never** `0`. Faculty may explicitly override it to `0`, and that override is recorded in the audit log.
- Every statistic must carry its **n** (students included).
- Where **n is too small** for a label to be meaningful (blueprint default: n < 5 for group statistics; at least 2 completed assessments for a trend), return an explicit **insufficient-data** result — never a manufactured conclusion, never a silent zero.
- **Never** return `NaN`, `Infinity` or `-Infinity` through an API. See contract **C10** in §7.

---

## 4. Architecture

A **clean modular monolith**: one FastAPI service split into domain modules, one PostgreSQL database. No frontend at this stage.

```
   +-----------------------------------------+
   | FastAPI routers  /api/v1  (thin)        |
   +--------------------+--------------------+
                        |
   +--------------------v--------------------+
   | Auth dependency: JWT + RBAC + scope     |
   +--------------------+--------------------+
                        |
   +--------------------v--------------------+
   | Service layer (business rules)          |
   +------+--------------------------+-------+
          |                          |
   +------v-----------+     +--------v---------+
   | Analytics engine |     | Repository layer |
   | pure functions,  |---->| SQLAlchemy 2.0   |
   | no DB, no I/O    |     +--------+---------+
   +------------------+              |
                          +----------v---------+
                          | PostgreSQL 16      |
                          +--------------------+
```

**Hard architectural rules**

1. Routers never touch the database directly and never contain analytics maths.
2. Analytics core functions take plain data in and return plain data out — **unit-testable with no database**.
3. Services orchestrate; repositories own all SQL/ORM access.
4. `assessment_results` is the **only source of truth**. Any summary/cache table must be fully rebuildable from it (`POST /admin/recompute`).
5. Reports **format**; analytics **calculate**. No formula may be duplicated inside a report template.

### Actual layout (single codebase, established by Agent 1 — follow it)

The authoritative version is `README.md` on the `backend` branch ("One codebase, one branch"). Reproduced here because it defines where Agent 2 writes.

**Both agents build the same application in the same tree** — one FastAPI app, one PostgreSQL database, one Alembic chain, one test suite — and both push to the **`backend`** branch. `main` only receives reviewed merges from `backend`.

```
backend/
  app/
    core/            config, security, errors, pagination
    db/
      base.py, session.py, mixins.py
      models.py      every ORM model imported here (one list, both agents add to it)
    api/v1.py        every router registered here (one list, both agents add to it)
    modules/         one package per feature module, from both agents, side by side:
      auth/ users/                                            done (Agent 1)
      organization/ students/ assessments/ imports/ audit/    Agent 1
      analytics/ attention/ interventions/ reports/           >>> AGENT 2
  alembic/versions/  one linear migration chain
  tests/             one suite: test_<module>*.py, shared fixtures in conftest.py
  pyproject.toml     one dependency list
docker-compose.yml, .env.example, README.md
```

Agent 2's modules are `analytics/`, `attention/`, `interventions/`, `reports/` under `app/modules/`, each with `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, plus a pure-function core (proposal: `app/modules/analytics/core/`) that imports no session, no `Base` and no model.

> **History note.** Phase 2 briefly introduced a per-agent file split (`app/intelligence/`, `routes_platform.py`/`routes_intelligence.py`, `models_platform.py`/`models_intelligence.py`, `tests/platform|intelligence/`). Commit `e2963ea` removed it in favour of the single tree above, and `main` was reset to a placeholder with development moved to `backend`. Ownership is therefore **logical, not file-level**: it is defined by which module and which formulas an agent owns, not by which files only one agent may open. Two consequences: the shared registries (`app/db/models.py`, `app/api/v1.py`) and `tests/`, `conftest.py`, `pyproject.toml` now take concurrent additive edits from both agents, so pull immediately before touching them; and migration revision IDs are a single sequential series (`0003`, `0004`, …), not per-agent prefixes.

### Working rules (from README, binding)

1. **Same structure for every module:** `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`. Routers never touch the session; services own the transaction (one `commit()` per operation); repositories never commit.
2. **New module = new folder** under `app/modules/`, plus one line in `app/api/v1.py` (router) and one in `app/db/models.py` (models).
3. **Reuse, don't duplicate.** Analytics reads students, offerings, assessments and results through the existing services/repositories, so faculty scope and PII rules are enforced in one place. Protect endpoints with `CurrentUser` / `require_roles(...)` from `app.modules.auth.dependencies`. **If a query you need is missing, add it to the owning module's repository** rather than querying its tables from elsewhere.
4. **Migrations:** `git pull`, `alembic upgrade head`, then `alembic revision --autogenerate -m "..."`, renaming the revision ID to the next number in the single chain. `tests/test_migrations.py` fails on two heads or on model/schema drift; if two heads appear after a pull, point the newer migration's `down_revision` at the other one.
5. **Before every push:** `git pull --rebase origin backend`, then `pytest` and `ruff check . && ruff format --check .` must pass.
### Conventions inherited from Agent 1 (binding on Agent 2)

Originally recorded in `docs/DECISIONS.md` as D-001…D-008; that file was folded into `README.md` ("Design decisions") in Phase 2. Summarised here because they constrain how analytics code must be written. The D-numbers are kept for traceability.

| Ref | Convention | What it means for Agent 2 |
|-----|-----------|---------------------------|
| D-001 | `router.py -> service.py -> repository.py` per module; routers never touch the session | Analytics routers stay thin and resolve a service through a dependency — this matches §21 of the directive exactly |
| D-002 | **Synchronous** SQLAlchemy 2.x with psycopg 3 (no `AsyncSession`) | Analytics services and repositories are sync; no `async def` endpoints that touch the DB |
| D-003 | **Services own transactions; repositories never commit** | Analytics is read-mostly, so commit only in intervention services; `recompute` must not commit on its own — it runs inside the caller's transaction (see C4 note below) |
| D-004 | PostgreSQL only, **including tests**; test DB built by running Alembic migrations, never `create_all` | Analytics tests that need the DB use the `db_session` fixture; pure-function tests need no DB at all |
| D-005 | Fixed constraint naming convention on `Base.metadata` | Error handling may rely on predictable constraint names |
| D-006 | **Migration drift is a test failure** (`tests/test_migrations.py` asserts a single head, a full down/up round trip, and zero model/schema diff) | Agent 2 authors its own migrations as the next sequential ID in the single chain, and must never add a model without one — the suite fails loudly on drift or on a second head |
| D-007 | `/health` is unversioned and reports readiness | Analytics endpoints all live under `/api/v1` |
| D-008 | The API container runs `alembic upgrade head` before uvicorn | No manual migration step in local dev |

**Consequence for contract C4:** because services own the transaction (D-003), `recompute(session, assessment_id)` receives the caller's session and must **not** commit. Agent 1's import-confirm service commits once, so the results write and the recomputed flags land atomically.

### Runtime decisions

- **Compute on write, not on read.** After an import confirm or a results edit, recompute derived rows for that assessment and re-evaluate attention flags for that offering. Dashboards then read small tables. At our scale this is sub-second — hence no queue. This makes the write path depend on the analytics layer: contract **C4** in §7.
- **Migrations:** Alembic, single owner (Agent 1).
- **Contracts:** the FastAPI-generated OpenAPI document at `/docs` is the published interface.

---

## 5. Agent 1 — Backend Platform & Data

**The question Agent 1 answers:** *"How do we store and safely access academic data?"*

Agent 1 owns the source-of-truth academic data layer and must expose clean models, repositories, services and API contracts for Agent 2 to consume.

| Group | Responsibilities |
|-------|------------------|
| Foundation | Project structure, configuration, dependency management, `core/` (DB session, security, error envelope, pagination, enums) |
| Database | PostgreSQL, SQLAlchemy 2.0 models, **sole ownership of Alembic migrations** |
| Identity | Authentication, password hashing, JWT access/refresh, token revocation, RBAC (`ADMIN`, `HOD`, `FACULTY`), department scope (HOD) and offering scope (FACULTY) |
| Academic structure | Departments, academic terms, courses, sections, course offerings, faculty assignment |
| People | Students (master data, register numbers, section membership) |
| Assessment data | Assessment definitions; **assessment-level results** (score, max, status) |
| Ingestion | File detection, parsing, column mapping, normalisation, validation, staging, preview, row fix/exclude, re-validation, **atomic confirm** |
| Integrity | Import history, audit logs, duplicate-import handling, transactional guarantees |
| Infrastructure | Docker/compose development environment, test infrastructure, seed/demo data |
| Documentation | `docs/DATA_MODEL.md`, `docs/IMPORT_FORMAT.md`, `docs/AGENT_2_ANALYTICS_CONTRACT.md` |

**Agent 1 must not** implement analytics formulas, attention rules, trend classification, segmentation, insight generation, intervention outcome maths, or report layout.

**Blueprint mapping:** Agent 1 ≈ blueprint members **M1 (Platform & Foundation) + M2 (Assessments & Data Ingestion)**, minus M2's question/topic work and minus all frontend.

---

## 6. Agent 2 — Analytics, Intelligence, Interventions & Reporting

**The question Agent 2 answers:** *"What can we reliably understand from that academic data?"*

Agent 2 is the **correctness owner** for every number and label the system shows.

| Group | Responsibilities |
|-------|------------------|
| Statistics | Mean, median, std dev, min/max with student reference, pass %, completion %, histogram bins, distributions |
| Student intelligence | Performance history, per-assessment percentage, weighted course score, consistency/volatility |
| Trends | Improving / Stable / Declining / Insufficient Data, with slope, threshold and n |
| Class health | Offering-level KPIs, assessment comparison (e.g. CT1 → CT2), "What Changed?" |
| Attention centre | R1–R7 rule engine, severity, per-flag explanation, flag lifecycle |
| Segmentation | High Performer, Improving, Stable, Borderline, Declining, Persistently Low, Insufficient Data; primary actionable status plus supporting factors |
| Detection | Low performance, failed latest, repeated low, sharp decline, declining trend, low completion, borderline, most improved |
| Action | Intervention management (create, target students, track), **observed** outcome measurement against a peer baseline |
| Narrative | Deterministic template-based teacher insights — **no LLM** |
| Export | PDF, XLSX, CSV reports built on the same analytics engine |
| APIs | All `/api/v1/analytics/*`, `/interventions/*`, `/reports/*` routers (thin) |
| Quality | Analytics unit tests against hand-computed fixtures, edge-case tests, performance tests, `docs/ANALYTICS.md` |

**Agent 2 must not** create or edit SQLAlchemy models, write Alembic migrations, modify auth/RBAC, own import parsing/validation, bypass repositories, or duplicate the source of truth. Changes needed in Agent 1's layer go through the protocol in `docs/TEAM_OWNERSHIP.md` §4.

**Blueprint mapping:** Agent 2 ≈ blueprint members **M3 (Analytics & Insights) + the backend half of M4 (interventions, reports)**, minus the copilot and all frontend.

---

## 7. Shared Contracts

These are the interfaces across the ownership boundary. **Agent 1 provides; Agent 2 consumes.** Neither may change one unilaterally.

| ID | Contract | Provider | Notes |
|----|----------|----------|-------|
| **C1** | Shared enums | Agent 1 for platform enums; Agent 2 for intelligence enums | **No `app/core/enums.py` exists** — `Role` (`ADMIN`, `HOD`, `FACULTY`) lives with the users model. Platform enums (`AssessmentType`, `ResultStatus`) are Agent 1's and Agent 2 imports them, never redefines them. Intelligence enums (`AttentionRuleCode`, `FlagSeverity`, `FlagStatus`, `SegmentLabel`, `TrendLabel`) are Agent 2's, defined in the module that owns them under `app/modules/`. **Open question for Agent 1:** whether to introduce a shared `core/enums.py` or keep enums beside their models. |
| **C2** | `ResultStatus` enum + the missing-data policy of §3 | Agent 1 stores | Agent 2 applies it identically in every formula. |
| **C3** | Analytics read interface (platform service/repository methods Agent 2 may call) | Agent 1 | **Due in Agent 1's Phase 7** ("audit, seed data, analytics data contract"). README rule 4 already binds Agent 2: read academic data through platform services/repositories, never by ad-hoc queries on platform tables; data that is missing is requested as a platform service method. |
| **C4** | `recompute(session, assessment_id)` hook | signature agreed jointly; **implemented by Agent 2**, **called by Agent 1** | The hard handoff. Agent 1 calls it inside the import-confirm transaction and after a results edit. Agent 1 ships a no-op stub on day one so the write path is never blocked on analytics. |
| **C5** | Threshold resolution order | Agent 1 stores, Agent 2 resolves | `course_offerings.config` (JSONB) → `settings` row for the department → hard-coded default. Agent 2 owns the key names and the resolver; Agent 1 owns the storage. |
| **C6** | Auth dependencies — **DELIVERED (Phase 2):** `require_roles(...)` and `CurrentUser` in `app.modules.auth.dependencies`. Roles are `ADMIN`, `HOD`, `FACULTY`. The role in the JWT is never trusted; every request re-reads the user, so deactivation and role changes apply immediately. | Agent 1 | Agent 2 applies them to every analytics/intervention/report route — no analytics endpoint may be unscoped. **Offering scope was delivered in Phase 3** (`app/modules/organization/scope.py`): `OfferingAccess` (VIEW / ADMINISTER), `visible_offerings` / `visible_offering_ids`; an out-of-scope offering returns **404**, a visible-but-not-administrable one returns **403**. Agent 2 must route every offering-scoped analytic through these helpers rather than re-deriving visibility. |
| **C7** | Error envelope — **DELIVERED (Phase 2):** `{"error": {"code", "message", "details"}}`, `details` carrying field/row/cell items. Codes are **lower_snake_case**: `not_authenticated` 401, `permission_denied` 403, `not_found` 404, `conflict` 409, `validation_error` / `business_rule_violation` 422. | Agent 1 (`app/core/errors.py`) | Agent 2 raises the same shape. *Corrects an earlier assumption in this document that codes were SCREAMING_SNAKE.* An insufficient-data condition is **not** an error — it is a 200 response shaped per C10. |
| **C8** | List envelope — **DELIVERED (Phase 2):** `{items, total, limit, offset}`, `limit` 1–200 default 50. IDs are UUIDs. | Agent 1 (`app/core/pagination.py`) | Used by every paginated analytics list. *Corrects an earlier assumption in this document of `{items, total, page, size}` with `?page=&size=`.* |
| **C9** | Attention rule registry: canonical `rule_code`, severity, threshold key, and the settings keys behind them | Agent 2 defines, Agent 1 stores | Must be fixed **before** either agent writes rule code — see CONFLICT-2 in §11. |
| **C10** | Insufficient-data / null-value response shape | Agent 2 defines | Proposed: `{"value": null, "status": "insufficient_data", "reason": "only 1 completed assessment (minimum 2)", "n": 1}`. Numeric fields are `null` + a status, never `NaN`, never a fabricated `0`. |
| **C11** | Seed/demo dataset with known embedded patterns | Agent 1 | Must contain: declining students, at least one sharp drop, a borderline cluster around the pass mark, absent and exempt rows, a student with a single assessment, and a very small cohort. Agent 2's tests and demo depend on these patterns being stable. |
| **C12** | Audit log write on any overwrite of existing results | Agent 1 | Old values preserved; Agent 2's outcome measurement must never silently read over-written history. |

---

## 8. Data Flow

```
Excel / CSV
  -> Upload (multipart, <= 5 MB, .xlsx/.csv, MIME + extension check)
  -> File detection
  -> Parse (all cells as strings; no numeric coercion at read time)
  -> Column mapping (normalise headers; unmapped columns surfaced, not guessed)
  -> Normalisation (trim, register-no casing, "AB"/"A"/"-" -> absent)
  -> Validation (file-blocking / row-blocking / cell-blocking / warning / info)
  -> Staging in import_batches.rows (JSONB, per-cell status)   [nothing written to results]
  -> Preview (summary counters + per-cell error/warning detail)
  -> Faculty correction or row exclusion
  -> Server-side re-validation
  -> Confirm (allowed only when blocking errors = 0)
  -> ATOMIC TRANSACTION: upsert assessment_results + audit rows + mark batch committed
  -> recompute(assessment_id)   [contract C4]
  -> Analytics engine
  -> Insights
  -> Attention flags
  -> Intervention (faculty action, named target students)
  -> Follow-up assessment
  -> Observed outcome measurement (target vs peer baseline)
  -> Reports (PDF / XLSX / CSV)
```

**No stage may silently corrupt academic data.** Specifically: parsing does not coerce, normalisation does not invent, validation does not repair, and confirm is all-or-nothing (killing the database mid-import must leave no partial results).

### Validation levels

| Level | Meaning | Blocks confirm? |
|-------|---------|-----------------|
| File-blocking | Required headers absent, unreadable sheet | Yes — reject before staging |
| Row-blocking | Register number not in this offering's section; duplicate register number in file | Yes, for that row |
| Cell-blocking | Non-numeric score; score < 0 or > max | Yes, for that cell |
| Warning | Blank cell (imported as `absent`); name mismatch; enrolled student missing from file; results already exist (confirm will overwrite, old values audited) | No — surfaced, faculty decides |
| Info | `AB` / `A` / `-` recognised as `absent` | No |

---

## 9. API Boundaries

Base path `/api/v1`. Every endpoint except `login`, `refresh` and `health` requires a Bearer token. Faculty may touch **only** offerings they teach; admin may touch all (per RBAC).

### Agent 1 owns

```
POST   /auth/login | /auth/refresh | /auth/logout      GET /auth/me
GET    /users            POST /users       PATCH/DELETE /users/{id}
GET    /departments | /terms | /courses | /sections     (+ POST, admin)
GET    /offerings        POST /offerings   PATCH /offerings/{id}   (config: owning faculty)
GET    /students         POST /students    PATCH /students/{id}    POST /students/{id}/deactivate
GET    /offerings/{id}/assessments         POST same
GET    /assessments/{id}                   PATCH/DELETE /assessments/{id}
GET    /assessments/{id}/results            PUT /assessments/{id}/results     (bulk upsert)
GET    /assessments/{id}/import/template
POST   /assessments/{id}/import             (parse + validate, writes nothing to results)
PATCH  /imports/{batch_id}/rows             POST /imports/{batch_id}/confirm
GET    /imports                             (history)
POST   /students/import  (+ /confirm)
POST   /admin/recompute?offering_id=        (route: Agent 1; body of work: Agent 2 via C4)
GET    /health
```

### Agent 2 owns

```
GET    /analytics/dashboard?offering_id=
GET    /analytics/offerings/{id}/class-health
GET    /analytics/assessments/{id}                      (stats, distribution, histogram)
GET    /analytics/assessments/compare?offering_id=&a=&b=
GET    /analytics/offerings/{id}/attention
GET    /analytics/offerings/{id}/segments
GET    /analytics/offerings/{id}/most-improved
GET    /analytics/offerings/{id}/what-changed
GET    /analytics/students/{id}?offering_id=            (history, trend + rule, flags, insight)
GET    /analytics/students/{id}/consistency?offering_id=
GET/POST   /offerings/{id}/interventions
GET/PATCH  /interventions/{id}                          (detail + observed outcome)
GET    /reports/{type}/{id}?format=pdf|xlsx|csv         (type in: section, assessment, student, attention, intervention)
```

**Boundary rules**

- Analytics routers are thin: `router -> service -> analytics engine -> repository -> DB`.
- Agent 2 does not add write endpoints outside `interventions/`.
- Agent 1 does not add endpoints under `/analytics/`.
- Both use C7 (errors), C8 (pagination) and C6 (auth dependencies).

---

## 10. Analytics Boundaries

### Available on assessment-level data (in scope)

| Area | Definition | Explainability payload |
|------|-----------|------------------------|
| Assessment percentage | `P = 100 * score / max_marks` | score, max, status |
| Weighted course score | `W = sum(P_a * w_a) / sum(w_a)` over **completed** assessments only, so missing future assessments do not drag it down | per-assessment P and w, n |
| Group statistics | mean, median, population std dev, min/max with student reference, over **assessed** students | n, list of excluded statuses |
| Pass % | `100 * (students with P >= pass_percent) / assessed` | threshold source (offering config) |
| Completion % | `100 * assessed / active enrolled`, `exempt` excluded from the denominator | n, denominator basis |
| Histogram | 10-point bins: 0–9, 10–19, … 90–100 | bin counts, n |
| Trend | `< 2` completed -> Insufficient Data; `== 2` -> `P[-1] - P[-2]`; `>= 3` -> least-squares slope in pp per assessment. `slope >= +TREND_DELTA` -> Improving; `<= -TREND_DELTA` -> Declining; else Stable. Default `TREND_DELTA = 5`. | slope, threshold, assessments used, n |
| Sharp decline | `drop = P_latest - mean(P over earlier assessments)`; fires when `drop <= -DECLINE_DROP`. Default 15 pp. | previous mean, latest, drop, threshold |
| Repeated low | `k` consecutive assessments with `P < pass_percent`. Default `k = 3`. | the k assessments, each P, threshold |
| Borderline | `abs(P - pass_percent) <= BORDERLINE_BAND`. Default band 5 pp. **Do not hard-code 50%** — the pass mark comes from the offering. | P, pass_percent, band |
| Consistency / volatility | std dev of a student's P series (plus range); requires `>= 3` completed | series, std dev, n |
| Most improved | measurable pp improvement between two comparable assessment points; both must have `present` results for the student | from-assessment, to-assessment, delta pp |
| Assessment comparison | mean/median/pass %/completion delta between two assessments in the offering, with the cohort intersection stated | both n, intersection n |
| What changed | deltas introduced by the latest assessment: class mean change, count of new sharp declines, count crossing the pass mark in each direction, new flags | every count with its member list |
| Segmentation | rule-derived labels: High Performer, Improving, Stable, Borderline, Declining, Persistently Low, Insufficient Data. A student may satisfy several; the API returns one **primary actionable status** plus supporting factors. | every satisfied rule with its evidence |
| Observed intervention outcome | target pre/post mean, peer pre/post mean, `net = target_change - peer_change`; only students with data in **both** baseline and follow-up are counted | both n values, both means, the wording "observed", never "caused" |
| Insight sentences | deterministic templates over the outputs above | every number traceable to an analytics result |

### Attention rules (canonical numbering — reduced scope)

| Code | Rule | Default threshold | Severity |
|------|------|-------------------|----------|
| `R1_LOW_PERFORMANCE` | weighted course score below threshold | 50% | High |
| `R2_FAILED_LATEST` | latest assessment `P < pass_percent` | offering pass % | Medium |
| `R3_REPEATED_LOW` | `k` consecutive assessments below pass | k = 3 | High |
| `R4_SHARP_DECLINE` | drop vs previous mean | −15 pp | Medium |
| `R5_DECLINING_TREND` | trend classified Declining | 5 pp/assessment | Low |
| `R6_LOW_COMPLETION` | completion % below threshold | 75% | Medium |
| `R7_BORDERLINE` | within band of the pass mark | ±5 pp | Low |

A student is listed as **requiring academic attention** when any High rule fires or at least two Medium rules fire. Each flag carries: `rule_code`, `severity`, `threshold`, `actual_value`, reference assessment(s), `student_id`, `offering_id`, human-readable `message`, `n`, `generated_at`.

Display text must read like: *"Latest assessment 42%. Configured low-performance threshold 50%. Below 50% in 3 consecutive assessments (CT1 46%, CT2 48%, FT1 42%)."* Never *"will fail"*, never *"high risk of failing"*, never an invented cause.

### Forbidden analytics

- Anything requiring question or topic data (§11).
- Any ML or statistical **prediction** of future failure; any "AI risk score"; any black-box label.
- Any causal claim about an intervention.
- Any invented explanation of *why* a student is performing poorly.
- Any label based on `n` below the configured minimum.
- `NaN` / `Infinity` in a response.

---

## 11. Explicitly Excluded Features

| Excluded | Reason | Future? |
|----------|--------|---------|
| Frontend (React/Vite/Next.js) | Backend-only phase | Later phase |
| Question creation / question CRUD | No question-level data | Only with real data support |
| Question-to-topic mapping (`question_topics`, weights) | No data | Only with real data support |
| Question difficulty index, discrimination index (upper–lower 27%) | Requires per-question scores | Only with real data support |
| Topic / subtopic tree, topic mastery, topic weakness, `student_topic_summary` | No data | Only with real data support |
| Question-level or topic-level marks table | No data | Only with real data support |
| Question-level causal analysis | No data, and causality is not claimed regardless | No |
| ML failure prediction, "AI risk score" | Explicitly forbidden: ethical and demo liability; violates explainability | No |
| AI copilot / LLM narration | Not needed for MVP; insights are deterministic | V3 |
| What-if simulation | Blueprint V2, and its current form is topic-based | V2, redesign needed |
| Attendance module | Cut from MVP in blueprint | V2 |
| Student login / student role | Cut from MVP in blueprint | V2 |
| Department-wide report | Cut from MVP in blueprint | V2 |
| Redis / Celery / Kubernetes / microservices | Unjustified at this scale | No |

### Conflicts between the blueprint and the reduced scope

| ID | Conflict | Resolution |
|----|----------|------------|
| **CONFLICT-1** | Blueprint decision #3 states *"every assessment has at least one question; a totals-only assessment is one question with no topic"*, and its `marks` table is keyed by `question_id`, not `assessment_id`. The reduced scope forbids question-level structures. | The question layer is dropped; results are keyed by `(student_id, assessment_id)`. See **DECISION-1** in §12. |
| **CONFLICT-2** | Attention rule codes collide. Blueprint: `R1_LOW_OVERALL`, `R2_LOW_TOPIC`, `R3_SHARP_DECLINE`, `R4_DECLINING_TREND`, `R5_LOW_COMPLETION`, `R6_FAILED_LATEST`. Reduced scope: R1 low performance, R2 failed latest, R3 repeated low, R4 sharp decline, R5 declining trend, R6 low completion, R7 borderline. The **same number means different rules** in the two documents. | Reduced-scope numbering is canonical (§10). `R2_LOW_TOPIC` is deleted (no topic data). `R3_REPEATED_LOW` and `R7_BORDERLINE` are new. Codes are frozen as contract **C9** before any rule code is written. |
| **CONFLICT-3** | Blueprint's intervention model hangs interventions off a `topic_id`, and its outcome maths compares topic scores, requiring the follow-up assessment to contain a question mapped to that topic. | `topic_id` is removed. Outcome compares **assessment percentages** between a baseline assessment (set) and a follow-up assessment, for students with data in both. |
| **CONFLICT-4** | Blueprint's generated insight sentence is topic-based (*"strong in X, needs practice in Y"*, strong = topic score ≥ 75, weak < 50). | Redesigned onto assessment-level facts: class-mean movement, decline counts, borderline counts, completion. Templates must be rewritten, not ported. |
| **CONFLICT-5** | Blueprint has 22 tables including `topics`, `questions`, `question_topics`, `marks`, `student_topic_summary`. | Those five are **not created**. Reduced set: 16 tables (+1 optional `grading_schemes`). See §12. |
| **CONFLICT-6** | Blueprint assumes 4 members each owning backend + frontend of a vertical slice. | Two backend agents, no frontend. Mapping in §5 and §6. |
| **CONFLICT-7** | Blueprint's grade bands / `grading_schemes` and grade distribution depend on a configured scheme not mentioned in the reduced scope. | Deferred as optional. If grades are wanted, storage is Agent 1 (`grading_schemes` or `offering.config`) and the distribution is Agent 2. Flagged as **DECISION-3**. |

**No question/topic functionality is currently being treated as required.** The only place the blueprint made it structurally mandatory was the `marks`-via-`question_id` key, which DECISION-1 removes.

---

## 12. Integration Dependencies and Open Decisions

### Decisions needed before implementation

**DECISION-1 — RESOLVED 2026-09-26: Option A.** Results are keyed `(student_id, assessment_id)` in a single `assessment_results` table. **No `questions` table, no `marks` table.** The agreed shape:

```
assessment_results
  student_id           FK -> students
  assessment_id        FK -> assessments
  score                NUMERIC(5,2) NULL      -- NULL for absent/exempt; never defaulted to 0
  status               present | absent | exempt
  max_marks_snapshot   -- max in force when the result was recorded
  PK(student_id, assessment_id)
```

`score` is nullable with **no default**, so `absent` and `exempt` cannot silently become `0`. If question-level data is ever supported, add `questions` + `question_marks` and an explicit `assessment_results.source` column (`direct_entry` | `rolled_up_from_questions`) — the rollup stays auditable and no current analytic changes.

Original options, retained for the record:

- *Option A (recommended):* a single `assessment_results` table keyed `(student_id, assessment_id)` holding `score` (nullable), `status`, `max_marks_snapshot`. `questions`/`marks` are never created. Forward path if question data ever arrives: add `questions` + `question_marks`, and add `assessment_results.source` (`direct_entry` | `rolled_up_from_questions`) so the rollup is explicit and auditable.
  *Pro:* simplest correct model for the data we have; no synthetic rows; analytics read one table; honest.
  *Con:* a future question layer needs a documented rollup and a migration.
- *Option B:* keep the blueprint's `marks(question_id)` with exactly one synthetic question per assessment.
  *Pro:* blueprint-compatible; no future migration.
  *Con:* every read joins through a fake entity; invites exactly the question-level analytics the scope forbids; edges toward "pretending data exists".

**Option B was rejected.**

**DECISION-2 — RESOLVED by Agent 1's Phase 1: Python 3.12.** `backend/Dockerfile` uses `python:3.12-slim`; `pyproject.toml` declares `requires-python = ">=3.11"` and ruff targets `py311`. The local host interpreter is **3.14.6**, which is *not* what the project runs on — **run tests and the app in the container**, or install 3.12 locally, rather than using the host interpreter. Verified: the Phase 1 suite passes 9/9 on `python:3.12-slim`.

**DECISION-3 (open) — grades.** In or out for this phase? (CONFLICT-7.)

**DECISION-4 (open) — PDF engine.** The blueprint chose WeasyPrint, which needs native GTK/Pango libraries and is painful on Windows hosts. Options: generate PDFs inside the Linux container only, or choose a pure-Python engine (ReportLab). See RISK-6.

### What Agent 2 needs from Agent 1 (requests, never silent edits)

| ID | Requirement | Why |
|----|-------------|-----|
| **D1** | `assessments`: `max_marks`, `weightage`, `sequence_no`, `date`, `type`, `is_published` | Ordering for trends; weighting for course score; published-only analytics |
| **D2** | `assessment_results`: nullable `score` + `status` enum | Missing-data policy (§3); absent must never arrive as 0 |
| **D3** | `course_offerings`: `pass_percent` + `config` JSONB | Pass mark and threshold overrides must not be hard-coded |
| **D4** | `settings` table, department-scoped, key + JSONB value | Department-level threshold defaults (C5) |
| **D5** | `interventions` + `intervention_students` tables | Shared contract: Agent 1 migrates, Agent 2 defines fields and all logic |
| **D6** | `attention_flags` table with `rule_code`, `severity`, `threshold`, `actual_value`, `message`, `status`, `computed_at` | Flags are persisted so history survives recompute |
| **D7** | `recompute(session, assessment_id)` called inside the import-confirm transaction and after `PUT /assessments/{id}/results` | Compute-on-write (C4) |
| **D8** | A cohort read method: active enrolled students for an offering, with each student's results across published assessments | Every group statistic needs a stable definition of "enrolled" |
| **D9** | Indexes: `assessment_results(assessment_id)`, `assessment_results(student_id)`, `assessments(offering_id, sequence_no)`, `attention_flags(offering_id, status)` | Dashboard latency target |
| **D10** | Audit rows whenever existing results are overwritten | Outcome measurement must not silently read rewritten history (C12) |
| **D11** | Seed dataset with the patterns listed in C11 | Agent 2 cannot build or test anything without data |

### What Agent 1 needs from Agent 2

| ID | Requirement | Why |
|----|-------------|-----|
| **U1** | The `recompute(session, assessment_id)` signature, agreed on day one and shipped as a no-op stub | The import write path must never block on analytics being finished |
| **U2** | The frozen attention rule registry (C9) and settings key names | Agent 1 stores the threshold values Agent 2 will read |
| **U3** | The insufficient-data response shape (C10) | Keeps error/empty semantics consistent across both agents' APIs |

---

## 13. Risks

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| **RISK-1** | **RESOLVED 2026-09-26.** The local working copy was empty, but Agent 1 had already pushed Phase 1 (backend skeleton) to `YushBytes/Faculty-Project`. The risk of both agents bootstrapping the foundation in parallel is gone. | ~~High~~ | Agent 1's structure and conventions are authoritative (§4). Agent 2 still has no models or seed data to consume, so its only unblocked work remains the pure, database-free analytics core plus fixtures. **Always `git fetch` and inspect `origin/main` before starting a phase** — the local folder is not evidence of what the shared repo contains. |
| **RISK-16** | The GitHub repository `YushBytes/Faculty-Project` is **public**. The system is designed to hold student register numbers, names and marks — personal data the blueprint itself commits to handling under the spirit of India's DPDP Act 2023. | Medium now, **High** once real data exists | Never commit real student data, real sheets, or a populated dump. Seed/demo data must be synthetic. Consider making the repository private before any real import fixture is added. |
| **RISK-2** | **RESOLVED 2026-09-26.** The git repository was rooted at `C:\Users\ayush\OneDrive\Desktop`, not at the project folder — 77 untracked entries (resumes, CVs, personal PDFs, other projects, game shortcuts), no `.gitignore`, zero commits. A single `git add -A && git commit` would have committed personal documents into project history. | ~~High~~ | A git repository was initialised inside `Faculty project/` (branch `main`) with a `.gitignore`, so git commands run from the project now target the project repo only. **Never run `git add`/`git commit` from the Desktop root.** The Desktop repo still exists with 77 untracked entries and no `.gitignore` — worth cleaning up separately. |
| **RISK-3** | Project lives inside **OneDrive**. Sync will fight a `.venv`, `__pycache__`, and any Postgres data directory — file locks, sync conflicts, corrupted virtualenvs. | High — **still open** | `.gitignore` now excludes `.venv/`, `__pycache__/`, `pgdata/` from *git*, but that does not stop OneDrive syncing them. Either exclude those paths from OneDrive sync, or move the repository outside OneDrive. Keep Postgres data in a Docker volume, never in a synced folder. |
| **RISK-4** | **Mitigated.** Python 3.14.6 is the only *host* interpreter, but the project targets 3.12 (DECISION-2). Running `pip install` / `pytest` on the host risks source builds and wheel gaps for psycopg, pandas and PDF tooling. | Low if the container is used | Run everything in `python:3.12-slim` or the compose `api` service. Do not create a host venv on 3.14. |
| **RISK-5** | **Mitigated.** No local PostgreSQL server or `psql` client, but `docker-compose.yml` provides `postgres:16-alpine`. | Low | `docker compose up -d db`. **Host port 5432 and 5433 are already taken on this machine by an unrelated project's containers (WhistleDrop), which auto-start with Docker Desktop.** Override the published port instead of stopping them: `POSTGRES_PORT=55432 docker compose up -d db`, and point `TEST_DATABASE_URL` at that port (or run the test container on the `facultyproject_default` network and use host `db:5432`). |
| **RISK-6** | WeasyPrint (blueprint's PDF choice) requires native GTK/Pango libraries; on a Windows host this typically blocks PDF generation entirely. | Medium | DECISION-4: render PDFs only inside the Linux container, or use ReportLab. |
| **RISK-7** | **Scope creep back into question/topic analytics.** The blueprint is detailed and persuasive on topic analytics and discrimination index; it is easy to implement them by habit. | Medium-High | §11 exclusion list is binding. Add a guard test asserting no `questions` / `topics` / `question_topics` / `marks` / `student_topic_summary` table exists in the migration head. |
| **RISK-8** | **Rule-code divergence** (CONFLICT-2): two documents number the same rules differently, so the two agents could persist mismatched `rule_code` values. | High | Freeze C9 before any rule code is written; the codes live in one module (`app/core/enums.py`) owned by Agent 1 but authored by Agent 2. |
| **RISK-9** | **Absent silently becoming 0** through pandas (`NaN` then `fillna(0)`), or through a default-0 column. | High | `score` is nullable with no default; parse every cell as a string; explicit test: blank cell imports as `absent` with `score IS NULL`. |
| **RISK-10** | Comparing raw percentages across assessments ignores differing difficulty: a hard CT2 makes the whole class look like it is declining. | Medium | State the caveat in every trend/comparison response and report. (Blueprint's z-score refinement is V2 and out of scope now.) |
| **RISK-11** | Duplicate imports silently overwriting results. | Medium | Warning-level validation ("62 existing results will be updated"), explicit confirm, and audit rows (C12). |
| **RISK-12** | Two agents creating Alembic revisions in parallel produces multiple heads. | Medium | Agent 1 is the sole migration author; Agent 2 requests changes via §12. |
| **RISK-13** | No `CLAUDE.md`, so conventions drift between the two agents. | Medium | Create `CLAUDE.md` immediately after the skeleton: layout, naming, error envelope, test commands, ownership boundary. |
| **RISK-14** | Misleading labels on very small cohorts (n < 5) or single-assessment students. | Medium | One central insufficient-data gate (C10) applied by every analytic; tested with 0-, 1-, 2-student and single-assessment fixtures. |
| **RISK-15** | **RESOLVED 2026-09-26.** The 50-page blueprint lived only on the Desktop, outside the repository. Agent 1 recorded in `docs/DECISIONS.md` that *"the Blueprint and the Agent 1 work package were not available when the backend was started"* and that the Blueprint wins wherever it conflicts with an entry there. | ~~Low-Medium~~ | The blueprint is now committed at `docs/reference/ACADLYTICS_Project_Blueprint.pdf`, with a machine-readable `.extracted.txt` beside it (the host has no `pdftoppm`/`pypdf`, so the text form is what agents can actually grep). **Action for Agent 1:** re-check D-001…D-008 against it and revise any entry it contradicts. |

---

## 14. Recommended Implementation Order

Sequenced so that Agent 2 is unblocked as early as possible while Agent 1 still owns the foundation.

**Phase 0 — Environment and hygiene (blocking, no application code) — PARTLY DONE 2026-09-26**
Done: git repository initialised in the project folder with a `.gitignore` (RISK-2); blueprint copied to `docs/reference/`; DECISION-1 settled (Option A).
Still open: RISK-3 (OneDrive sync of `.venv` / Docker volumes), DECISION-2 (Python version pin), DECISION-3 (grades), DECISION-4 (PDF engine).

**Phase 1 — Skeleton and foundation (Agent 1) — DONE**, commit `433c7d9`, 9/9 tests passing.
Delivered: `backend/` package, `pyproject.toml`, `Settings` with a psycopg-only `DATABASE_URL` validator, `db/base.py` + `db/session.py`, Alembic baseline `0001`, `/health` readiness endpoint, `docker-compose.yml` (Postgres 16 + api), pytest harness on real PostgreSQL, ruff config, `README.md`, `docs/DECISIONS.md`.
Not yet delivered (still blocks Agent 2): the error envelope (C7), pagination (C8) and `enums.py` (C1) are not present in Phase 1 and are expected with the domain modules.

**Phase 2 — Users, auth and RBAC (Agent 1) — DONE**, commit `a34308f`.
Delivered: `users` + `refresh_tokens` (migration `0002`), Argon2id passwords, JWT access (15 min) + rotating refresh tokens (7 days) with reuse/theft detection, `/auth` login/refresh/logout/me, `/users` admin CRUD with last-admin and self-lockout guards, roles `ADMIN`/`HOD`/`FACULTY` re-read from the database on every request, the unified error envelope (C7), pagination (C8), and a `create-admin` CLI. A per-agent file split shipped in this commit was removed again in `e2963ea` in favour of a single module tree (see §4).
Still outstanding from the original Phase 2 scope: the **academic** data model (offerings, students, assessments, `assessment_results`) is Agent 1's Phases 3–5, and **department/offering scope** lands in Phase 3.

**Phase 3 (Agent 1's numbering) — Organisation and offering scope — DONE**, commit `a1f8125`.
Delivered: departments, academic terms, courses, sections, course offerings with faculty assignment (migration `0003`); `users.department_id`; a single-current-term partial unique index; code/date/pass-mark check constraints; server-side offering scope; a `write_guard` mapping constraint violations to 409/422 while keeping the session usable. 143 tests. This satisfies dependency **D3** (offering `pass_percent`) and contract **C6**'s scope half.

**Phase 3 (this document's numbering) — Seed data + the recompute stub (Agent 1, unblocks Agent 2)**
Seed/demo generator with the C11 patterns; the no-op `recompute(session, assessment_id)` stub (U1); `docs/DATA_MODEL.md` and `docs/AGENT_2_ANALYTICS_CONTRACT.md`. **This phase is the gate for Agent 2 starting.**

**Phase 4 — Two tracks in parallel**

- *4a, Agent 1:* academic structure CRUD, students, assessments, `GET/PUT /assessments/{id}/results`, then the import engine (parse → validate → stage → preview → fix/exclude → atomic confirm → audit) with fixture-driven validation tests and `docs/IMPORT_FORMAT.md`.
- *4b, Agent 2:* pure analytics functions with **no database** — percentages, weighted score, group statistics, histogram, trend, decline, consistency — each proved against a hand-computed fixture; plus the C9 rule registry and the C10 insufficient-data shape.

**Phase 5 — Analytics services and APIs (Agent 2)**
Repository-backed services over real seeded data, the real `recompute` implementation behind C4, attention rule engine, segmentation, class health, assessment comparison, what-changed, deterministic insights, and all `/analytics/*` routes with C6 scope enforcement.

**Phase 6 — Interventions and outcomes (Agent 2, on D5)**
Intervention CRUD, target-group selection, observed pre/post measurement against the peer baseline, with `n` and the observational caveat in every response.

**Phase 7 — Reports (Agent 2, after DECISION-4)**
CSV → XLSX → PDF, in that order of difficulty, all reading the same analytics engine.

**Phase 8 — Integration and hardening (both)**
Cross-boundary integration tests (import → recompute → flags → intervention → outcome → report), edge-case matrix from §22 of the directive (no data, one assessment, all pass, all fail, identical scores, tiny cohorts, duplicate imports, invalid values), performance check on the dashboard, and final documentation.

**Ordering rules**

- Nothing in Phases 4b onward may start before Phase 3 exists.
- Agent 2 never waits for the import engine: seed data is the substitute.
- The `recompute` signature is agreed in Phase 1, stubbed in Phase 3, implemented in Phase 5.
