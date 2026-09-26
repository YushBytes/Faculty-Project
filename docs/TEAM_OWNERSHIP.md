# ACADLYTICS — Team Ownership

**Last updated:** 2026-09-26
**Team:** two backend engineers (Claude Code agents). **No frontend engineer, no frontend scope.**
**Companion document:** `docs/PROJECT_CONTEXT.md` (scope, data limitations, contracts C1–C12, decisions, risks).

---

## 1. The boundary in one line

| Agent | Owns | Answers |
|-------|------|---------|
| **Agent 1** | Platform & Data Foundation | *"How do we store and safely access academic data?"* |
| **Agent 2** | Intelligence Layer | *"What can we reliably understand from that academic data?"* |

```
        +----------------------------------+
        | AGENT 1                          |
        | Platform & Data Foundation       |
        +----------------------------------+
        | Auth / RBAC / scope              |
        | Users                            |
        | Departments, Terms, Courses      |
        | Sections, Offerings              |
        | Students                         |
        | Assessments                      |
        | Assessment Results  (truth)      |
        | Excel/CSV Import + Validation    |
        | Audit, Import History            |
        | PostgreSQL, Alembic, Docker      |
        +----------------+-----------------+
                         |
                         |  clean data / service contracts  (C1-C12)
                         v
        +----------------------------------+
        | AGENT 2                          |
        | Intelligence Layer               |
        +----------------------------------+
        | Statistics                       |
        | Trends                           |
        | Class Health                     |
        | Attention (R1-R7)                |
        | Segmentation                     |
        | What Changed                     |
        | Interventions                    |
        | Observed Outcomes                |
        | Deterministic Insights           |
        | PDF / XLSX / CSV Reports         |
        | /analytics/* APIs                |
        +----------------------------------+
```

---

## 2. Ownership matrix

Legend — **OWNER**: writes and maintains the code. **CONSUMER**: uses it, may not modify it. **REQUEST CHANGES**: must go through §4. **SHARED CONTRACT**: schema by Agent 1, semantics and logic by Agent 2. **DATA SUPPORT**: provides the stored fields the other needs. **EXCLUDED**: not in this phase.

| Area | Agent 1 | Agent 2 |
|------|---------|---------|
| Project skeleton, `core/`, config | OWNER | CONSUMER |
| PostgreSQL | OWNER | CONSUMER |
| SQLAlchemy models — platform (users, academic, assessments, results, imports, audit) | OWNER | CONSUMER (read-only) |
| SQLAlchemy models — intelligence (attention flags, interventions) | CONSUMER | **OWNER**, registered in `app/db/models_intelligence.py` |
| Alembic migrations | OWNER of the chain + platform revisions (`0001, 0002, …`) | **Authors its own revisions** (`i0001, i0002, …`) in the same linear chain |
| Enums | OWNER of platform enums (`Role`, `AssessmentType`, `ResultStatus`) | OWNER of intelligence enums (rule codes, severities, segment and trend labels). No shared `core/enums.py` exists yet — see contract C1 |
| Auth / JWT / RBAC / offering scope | OWNER | CONSUMER (must apply on every route) |
| Users | OWNER | CONSUMER |
| Departments, Terms, Courses, Sections | OWNER | CONSUMER |
| Course Offerings (incl. `pass_percent`, `config`) | OWNER | CONSUMER |
| Faculty assignment | OWNER | CONSUMER |
| Students | OWNER | CONSUMER |
| Assessments (definitions, weightage, sequence) | OWNER | CONSUMER |
| Assessment Results / marks (source of truth) | OWNER | CONSUMER (read-only) |
| Excel/CSV import: parse, map, normalise | OWNER | — |
| Import validation rules | OWNER | — |
| Import preview / staging / fix / exclude | OWNER | — |
| Import confirm (atomic transaction) | OWNER | — |
| Import history / audit logs | OWNER | CONSUMER |
| `settings` table (threshold storage) | OWNER | Defines the keys; owns the resolver (C5) |
| `recompute(session, assessment_id)` hook | Calls it (C4) | OWNER (implements it) |
| Seed / demo data | OWNER | CONSUMER (depends on C11 patterns) |
| Docker / dev environment | OWNER | CONSUMER |
| Test infrastructure (fixtures, conftest, CI) | OWNER | CONSUMER + owns analytics tests |
| Statistics (mean, median, sd, pass %, completion %) | — | OWNER |
| Distributions / histograms | — | OWNER |
| Student performance + history | DATA SUPPORT | OWNER |
| Trends | — | OWNER |
| Class health | — | OWNER |
| Assessment comparison | — | OWNER |
| Attention rules R1–R7 | DATA SUPPORT (`attention_flags` table) | OWNER |
| Segmentation | — | OWNER |
| Borderline / most improved / consistency | — | OWNER |
| What Changed | — | OWNER |
| Deterministic insights | — | OWNER |
| Interventions | SHARED CONTRACT (tables + migration) | OWNER (all logic + API) |
| Outcome measurement | DATA SUPPORT | OWNER |
| PDF / XLSX / CSV reports | — | OWNER |
| `/analytics/*` APIs | — | OWNER |
| Analytics tests, performance tests | — | OWNER |
| `docs/DATA_MODEL.md`, `docs/IMPORT_FORMAT.md`, `docs/AGENT_2_ANALYTICS_CONTRACT.md` | OWNER | CONSUMER |
| `docs/ANALYTICS.md` | CONSUMER | OWNER |
| `docs/PROJECT_CONTEXT.md`, `docs/TEAM_OWNERSHIP.md`, `CLAUDE.md` | SHARED — either may update; changes to the ownership matrix or contracts need both to agree | SHARED |
| Frontend | EXCLUDED | EXCLUDED |
| Question analytics | EXCLUDED | EXCLUDED |
| Topic analytics | EXCLUDED | EXCLUDED |
| ML prediction / AI risk score | EXCLUDED | EXCLUDED |
| AI copilot | FUTURE | FUTURE |
| What-if simulation | FUTURE | FUTURE |
| Attendance, student login, department report | FUTURE | FUTURE |

---

## 3. Explicit "do not touch" lists

### Agent 1 must not

- Write analytics formulas, trend classification, attention rules, segmentation, insight text, or outcome maths.
- Add endpoints under `/analytics/`.
- Decide threshold semantics (it stores threshold values; Agent 2 interprets them).
- Implement report layout or export formatting.

### Agent 2 must not

- Create or edit **platform** models (`app/modules/**`, `models_platform.py`) or a platform Alembic revision. Agent 2's own models go under `app/intelligence/` and are registered in `models_intelligence.py`, with `i`-prefixed revisions in the same linear chain.
- Touch auth, RBAC, users, or the academic structure CRUD.
- Write import parsing or validation logic.
- Query platform tables ad hoc. Academic data is read through platform services/repositories so faculty scope and PII rules stay in one place (README rule 4); missing data is requested as a platform service method.
- Duplicate the source of truth — no shadow tables, no re-derived "authoritative" scores.
- Put analytics maths inside a FastAPI route function.

### Neither agent may

- Build frontend.
- Create `questions`, `topics`, `question_topics`, question-keyed `marks`, or `student_topic_summary`.
- Implement any ML prediction or "risk score".
- Convert `absent` / `missing` / `exempt` to `0`.
- Return `NaN` or `Infinity` from an API.
- Claim an intervention *caused* a change.
- Invent a cause for a student's performance.
- Silently modify an uploaded academic value.

---

## 4. Cross-boundary change protocol

Agent 2 needs something in Agent 1's layer (a column, an index, a repository method, a hook call site). **Do not edit Agent 1's code.** Instead:

1. **Document the requirement** — append a row to the dependency table in `docs/PROJECT_CONTEXT.md` §12 with a new `D<n>` id.
2. **Explain why** — which analytic is blocked, and what is impossible without it.
3. **Propose the smallest change** — one nullable column beats a new table; an index beats a denormalisation.
4. **Mark it as an integration dependency** and state which phase it blocks.
5. **Agent 1 implements it** (model + migration + repository method) and records it in `docs/DATA_MODEL.md`.
6. **An integration test verifies compatibility** before the dependency is considered closed.

The same protocol applies in reverse (`U<n>` ids) when Agent 1 needs something from Agent 2 — in practice the `recompute` signature, the rule registry, and the insufficient-data shape.

### Conflict rules

- **Migrations:** one linear chain, two authors. Agent 1 uses `0001, 0002, …`; Agent 2 uses `i0001, i0002, …`; filename `YYYYMMDD_<rev>_<slug>.py`. Before creating one: `git pull`, `alembic upgrade head`, then autogenerate. If two heads appear, the later migration repoints its `down_revision` at the other head. `tests/platform/test_migrations.py` fails on two heads or on model/schema drift.
- **Shared files** (`app/core/`, `app/db/base.py`/`session.py`/`mixins.py`/`models.py`, `app/api/v1.py`, `tests/conftest.py`, `pyproject.toml`, `docker-compose.yml`, `.env.example`, `README.md`, and this document): small additive edits only, and pull immediately before editing. Never reorder or rename existing members.
- **`git pull --rebase` before every push** (README rule 6). Line endings are LF via `.gitattributes`.
- **Frozen before coding:** contracts **C1**, **C4**, **C7**, **C8**, **C9**, **C10**. Changing one of these after implementation has started requires both agents to update together.

---

## 5. Definition of done, per agent

**Agent 1 is done when:** a fresh clone plus one command brings up a seeded application; admin and faculty log in; every endpoint rejects unauthorised roles in tests; a faculty member can upload a real assessment sheet and see a preview with correct per-cell errors; confirm is atomic (killing the database mid-import leaves no partial results); a blank cell lands as `absent` with a null score; overwriting existing results writes audit rows; `docs/DATA_MODEL.md`, `docs/IMPORT_FORMAT.md` and `docs/AGENT_2_ANALYTICS_CONTRACT.md` are accurate.

**Agent 2 is done when:** every metric and rule in `docs/PROJECT_CONTEXT.md` §10 has a unit test against a hand-computed fixture; every label carries its rule, threshold, actual value and n; the edge-case matrix passes (no data, one assessment, all pass, all fail, identical scores, absent/exempt students, tiny cohorts, duplicate imports); no response can contain `NaN` or `Infinity`; every analytics route enforces offering scope; interventions report observed change with the peer baseline and the observational caveat; all three report formats export from the same analytics engine.

---

## 6. Current status — 2026-09-26

**This Claude Code session is Agent 2 (Analytics & Intelligence).** It must not create models, migrations, auth, or import logic; those belong to Agent 1 and go through §4.

**Shared repository:** `YushBytes/Faculty-Project`, default branch `main`, **public** (see RISK-16).

**Agent 1 progress:**

| Commit | Phase | Contents |
|--------|-------|----------|
| `433c7d9` | 1 | Backend skeleton: FastAPI, config, SQLAlchemy session, Alembic baseline `0001`, `/health`, Docker Compose, pytest on PostgreSQL |
| `a34308f` | 2 | `users` + `refresh_tokens` (migration `0002`), Argon2id, JWT + rotating refresh tokens, RBAC (`ADMIN`/`HOD`/`FACULTY`), `/auth` + `/users`, unified error envelope, pagination, `create-admin` CLI, and the file-level ownership layout |

Agent 1's next phases, in their order: 3 organisation + faculty scope, 4 students, 5 assessments and assessment-level results, 6 import pipeline, 7 audit + seed data + **analytics data contract**.

**Agent 2 progress:** Phase 0 only (this audit). No implementation.

**Agent 2's home**, created for it by Agent 1 in Phase 2:

```
backend/app/intelligence/            code (one sub-package per module)
backend/app/api/routes_intelligence.py   router registration
backend/app/db/models_intelligence.py    model registration
backend/tests/intelligence/          tests
```

**Agent 2's blockers.** No academic tables exist yet — no offerings, students, assessments or `assessment_results`. Until Agent 1's Phases 3–5 land, Agent 2 cannot write a DB-backed analytic; and until Phase 3 lands, faculty offering scope cannot be enforced. Unblocked now: the pure, database-free analytics core plus hand-computed fixtures, the C9 rule registry, and the C10 insufficient-data shape.

Settled: **DECISION-1** — results keyed `(student_id, assessment_id)` in `assessment_results`; no `questions` or `marks` table. **RISK-2** — a git repository now exists inside the project folder with a `.gitignore`.

Still open before implementation: **RISK-3** (OneDrive syncing `.venv` / Docker volumes), **DECISION-2** (Python version pin — local interpreter is 3.14.6), **DECISION-3** (grades in or out), **DECISION-4** (PDF engine).

**Agent 2's critical blocker:** Phase 3 of `docs/PROJECT_CONTEXT.md` §14 does not exist yet — there are no models, no seed data, and no `recompute` stub. Until Agent 1 delivers them, Agent 2's only unblocked work is the pure, database-free analytics core (`app/analytics/`) plus hand-computed fixtures, the C9 rule registry and the C10 insufficient-data shape.
