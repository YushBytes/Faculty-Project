# ACADLYTICS — final engineering audit

Audit of 2026-11-15/16 on branch `backend`, starting at `2b18ff3` (the reported local release
candidate). Companion documents: [`BUG_REGISTER.md`](BUG_REGISTER.md) (every defect with
evidence), [`TESTING_AND_VERIFICATION.md`](TESTING_AND_VERIFICATION.md) (every suite and result),
[`SECURITY_AUDIT.md`](SECURITY_AUDIT.md), [`DEPLOYMENT_READINESS.md`](DEPLOYMENT_READINESS.md),
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 1. Initial state (re-established, not assumed)

| Area | Observed on 2026-11-15 |
|---|---|
| Git | `backend` at `2b18ff3`, clean, level with `origin/backend`; `main`, `release/local-rc`, `origin/frontend/nachiketa-ui` also present |
| Backend suite | **1952 passed**, 0 failed, 0 skipped (414 s); `ruff check` and `ruff format --check` clean |
| Frontend | `eslint`, `tsc --noEmit` clean; no test runner; production build passes |
| Migrations | one head, `0008`; live database at `0008` |
| Running stack | `facultyproject` db / api / web healthy on 55432 / 8000 / 3001 |
| Application data | 2 users (Administrator, one faculty), 1 department, 1 term, 1 course, 1 section, 1 class, 58 students, 1 assessment, 58 results, 1 import, 2 audit rows |
| Other projects | BhashaBench (db on 5434; frontend/backend exited) and WhistleDrop (5432, 5433) — **not touched** at any point |
| Live end-to-end | `scripts/e2e_live.py` on a fresh isolated stack: 130 / 130 |
| Security | the faculty account still accepted a leaked former password (SEC-01) |

## 2. Architecture

```
Browser ──► Next.js 16 web (3001)
              ├─ /api/session/{login,refresh,logout}  httpOnly refresh cookie, SameSite=Strict
              └─ /api/v1/*  same-origin proxy ──► FastAPI (8000) ──► PostgreSQL 16 (55432)
                                                     │
              routers (thin) → services (own the transaction) → repositories (SQL only)
                                    └─► analytics core: pure functions, no I/O
```

- **Backend** (`backend/app`): one FastAPI app, 13 modules (`auth, users, organization, students,
  assessments, imports, audit, analytics, attention, interventions, reports, overview, system`).
  Synchronous SQLAlchemy 2.1 + psycopg 3; services own the transaction, repositories never commit.
  Compute-on-write: an import confirm or result edit recomputes the class's analytics, attention
  flags and `offering_summaries` in the same transaction.
- **Analytics** (`analytics/core`, ~9,000 lines, no database imports — enforced by
  `tests/analytics/test_architecture.py`): F1–F21 statistics, trends, profiles, class health,
  comparison, segmentation, R1–R7 rules, deterministic insights, intervention outcomes.
- **Frontend** (`frontend/`): App Router, React 19, typed adapters in `lib/api/endpoints.ts`
  (the only place URLs appear), in-memory access token, one silent refresh, 30 s GET cache cleared
  on any write, every view with loading / empty / error / insufficient-data states.
- **Runtime**: Docker Compose (db, api, web); API container migrates and bootstraps on start.

## 3. Academic hierarchy (preserved, verified)

```
Department ─┬─ AcademicTerm
            ├─ Course ──────────┐
            └─ Section ─────────┼─► CourseOffering ─┬─ OfferingFaculty → User
                                │   (course,term,   ├─ Enrollment → Student
               Term ────────────┘    section unique)├─ Assessment ─► AssessmentResult (student, assessment) PK
                                                    ├─ AttentionFlag
                                                    ├─ Intervention ─► InterventionStudent ─► InterventionReason
                                                    ├─ ImportBatch, OfferingSummary, GeneratedReport
                                                    └─ AuditLog (offering_id)
```

No model, migration or relationship was changed. Verified on the live schema: 44 foreign keys, all
validated; **every academic-history table is `ON DELETE RESTRICT`** (results, assessments,
enrolments, attention flags, interventions, import batches, offerings); only link and derived tables
cascade (`offering_faculty`, `offering_summaries`, `course_coordinators`, `intervention_students →
reasons`, `student_section_history`, `settings`, `refresh_tokens`). 13 unique constraints, 39
checks, 73 indexes. Live (`verify_live.py`): deleting an assessment with results, an offering with
results, a section with students, a course with offerings, or a department with courses is
refused, and the results are intact afterwards. The offering remains the authorisation boundary.

## 4. Web routes (all verified in a real browser)

Public: `/`, `/login`, not-found. Behind the session: `/dashboard`, `/departments[/id]`,
`/courses[/id]`, `/sections[/id]`, `/faculty[/id]`, `/team`, `/classes[/id]` (tabs: overview,
marks, assessments, attention, interventions, reports), `/analytics`, `/assessments[/key]`,
`/students[/id]`, `/attention`, `/interventions[/id]`, `/import`, `/reports`, `/admin/users`,
`/admin/structure`, `/audit`, `/settings`. Session routes `/api/session/*`, proxy `/api/v1/*`.

The brief's list included "Organization", "Results", "Import history", "Insights", "Profile" and
"Password management" as pages. In this product they are parts of other pages (structure → admin,
results → class *Marks* tab, import history → *Import* page, insights → class and student pages,
profile and password → *Settings*); no separate pages were invented.

## 5. API (102 operations, `GET /openapi.json`)

| Group | Operations |
|---|---|
| auth, me | login, refresh, logout, me, password change; `/me/workspace` |
| users | list, create, get, update (incl. administrator password reset), activate, deactivate |
| organization | departments, terms, courses (+ coordinators), sections — CRUD; department settings |
| offerings | CRUD, faculty assign/unassign, enrolments (enrol, from section, drop), roster |
| students | list/search, create, bulk JSON, file import, get, update, activate/deactivate, section history |
| assessments | list/create per offering, SRM scheme, get/update/delete, results get/put, remove one result, offering results matrix |
| imports | offering and assessment upload, templates, history, batch get/preview/fix/exclude/mapping/confirm/discard; TLP multi-file upload, status, confirm |
| analytics | class analytics, attention, insights, student analytics, class reports (5 kinds × CSV/XLSX/PDF) |
| interventions | create/list per offering, outcomes, per student |
| insights (overview) | scope overview, offerings, attention, interventions, one assessment across classes, one student, scope report, report history |
| audit, admin, system | audit log (scoped), recompute, `/health` |

## 6. Findings

22 defects found (CRITICAL 1, HIGH 4, MEDIUM 8, LOW 9 — see `BUG_REGISTER.md` for the
authoritative list), 20 fixed and verified, 2 open, both prepared and waiting for your
approval: SEC-06 (`main`, the default branch, must receive the current code) and SEC-02 (the
history rewrite, verified locally; the force-push is yours to approve). Highlights:

- **A leaked password still opened the real faculty account** — rotated (SEC-01).
- **Import could dead-end**: an unrecognised column blocked confirm with nothing on screen to act
  on; and an excluded row could not be brought back. Both fixed, both covered in the browser.
- **No brute-force protection** on sign-in — added (429 after 10 failures / 15 min / account).
- **Builds were not reproducible** (unpinned dependencies, network needed on every code change) and
  the API was SIGKILLed on every stop — fixed.
- **No production configuration** — `docker-compose.prod.yml`.
- **No frontend tests** — 21 unit + 13 browser tests; plus an independent live verifier.

## 7. Scan for unfinished work

`TODO|FIXME|HACK|XXX|not implemented|placeholder` in `backend/app`: none. Broad `except
Exception`: two, both intentional and commented (`provision.py`: a foreign key in use means
"keep it"; `overview/workspace.py`: a dropped student has no analytic profile — shown as
"no analytics", not as zeros). Mock/demo data in the runtime: none (`demo/` and the seed modules
are explicit CLI tools refused in production and on non-empty databases). Hard-coded thresholds
in the frontend: none (the previous audit removed the last one).

## 8. Subsystem readiness

| Subsystem | Status | Evidence |
|---|---|---|
| Authentication & sessions | PASS | unit/API tests; live: login, wrong password, refresh rotation, reuse, logout with expired access token, deactivation, password change; browser: reload keeps session, cookie unreadable |
| Brute-force protection | PASS (per process) | `test_login_throttle.py`; live before/after |
| Authorisation / faculty isolation | PASS | 15 reads + 9 writes 404 live; browser |
| Department threshold scope (2nd round) | PASS | 21 API tests (11 fail on the old code); 2 browser tests incl. a direct 404; 4 live checks |
| Academic hierarchy & deletion guards | PASS | schema inspection; live |
| Students | PASS (API) / PARTIAL (UI) | bulk, duplicate, validation, search, pagination live; no create/edit screen (by design, `KNOWN_LIMITATIONS.md`) |
| Assessments & results | PASS | boundaries (negative, > max, 3 decimals, blank, absent+score) refused, atomic, idempotent live |
| CSV import | PASS | browser and live |
| XLSX import | PASS | live (template filled, decimal 39.75 exact) |
| Import preview / fix / map / exclude / confirm / rollback | PASS | browser + live; confirm with errors writes nothing |
| Analytics (mathematics) | PASS | 19 analytics + 22 profile + 23 attention checks recomputed independently live (`verify_live.py`); 1,120 engine unit tests |
| Attention R1–R7 | PASS | every rule incl. strict/inclusive boundaries live; idempotent recompute; threshold override |
| Insights | PASS (unit) | engine tests; live outputs contain no NaN; wording checked |
| Student profiles | PASS | weighted score, completion, states, trend live |
| Interventions & outcomes | PASS | live and browser; observational wording |
| Reports CSV / XLSX / PDF | PASS | 15 downloads live; 3 in the browser; values match API |
| Frontend routes | PASS | every sidebar page, desktop and phone, no console errors |
| Database & migrations | PASS | one head; empty-database upgrade via fresh stack; backup/restore (see testing doc) |
| Docker local | PASS | see testing doc |
| Production deployment | NOT VERIFIED | configuration reviewed and validated; nothing deployed |
| Performance at scale | NOT VERIFIED | single-request timings on small data only |
| Default branch `main` | OPEN — prepared | still ships built-in passwords; merge tested clean, push awaits approval (SEC-06) |
| Git history secrets | OPEN — prepared | current tree clean and guarded; rewrite verified locally; push awaits approval (`GIT_HISTORY_REWRITE.md`) |
| Staging preparation | READY TO RUN | `STAGING_CHECKLIST.md`, `scripts/load_test.py` (smoke-tested only) |
