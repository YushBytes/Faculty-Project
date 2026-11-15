# ACADLYTICS — testing and verification

Every result here was observed on 2026-11-15/16 on Windows 11, Docker Desktop 29.8 (Compose
5.5.1), PostgreSQL 16 (container), Python 3.12.5, Node 24.18. Nothing is carried over from earlier
reports without being re-run.

## 1. Results at a glance

| Suite | Command | Result |
|---|---|---|
| Backend tests (real PostgreSQL) | `cd backend && pytest` | **1974 passed, 0 failed, 0 skipped** (322 s). Baseline before this audit: 1952 |
| Backend lint / format | `ruff check .` / `ruff format --check .` | clean / 214 files formatted |
| Frontend lint | `npm run lint` | clean |
| Frontend type check | `npm run typecheck` | clean |
| Frontend unit tests (new) | `npm test` | **21 passed** (2 files) |
| Frontend production build | `npm run build` | compiled successfully |
| Browser end-to-end (new) | `npm run test:e2e` | **13 passed** (desktop Chromium 1440×900 + Pixel 7) |
| Live HTTP end-to-end | `scripts/e2e_live.py` | **130 / 130** on an empty stack — see §5 for the final clean stack |
| Live independent verification (new) | `scripts/verify_live.py` | **228 passed, 0 failed** |
| Docker clean start | §5 | see §5 |
| Backup and restore | §6 | 24 / 24 tables identical |

## 2. Where tests ran

Destructive or data-creating checks never ran against the application database. They ran on:

- **audit stack** — `docker compose -p acadlytics-audit` (own volume; ports 55440 / 8010 / 3010),
  rebuilt from the working tree as fixes landed;
- **local web build** on port 3011 (`next start`, production mode) pointed at the audit API, for the
  browser runs while the web image was not rebuilt;
- **final clean stack** — `docker compose -p acadlytics-final`, built from the finished tree with an
  empty volume (§5).

The backend suite uses its own `acadlytics_test` database, which it drops and recreates. **Run
one pytest session at a time** — two concurrent sessions break each other (this happened once
during the audit and the run was discarded and repeated alone).

## 3. What each suite covers

### Backend (pytest, 1974)

Unchanged areas from the previous release (auth, five-role scope and IDOR, organisation,
students, assessments and results, import validation/atomicity/mapping/TLP, 1,120 analytics engine
tests, attention, interventions, reports in three formats, query budgets, migrations — single head,
round trip, zero drift — schema integrity), plus 22 new tests:

| New tests | For |
|---|---|
| `test_login_throttle.py` (9) | SEC-03 sign-in throttle |
| `test_tabular.py::test_safe_file_name…` (11 cases) | SEC-04 file names |
| `test_upload_security.py::…path_in_the_file_name…` | SEC-04 end to end |
| `test_imports_api.py::…excluded_row_stays_in_the_issues_view…` | IMP-02 |
| two strengthened assertions | API-01 (422 + location + value not echoed) |

### Frontend unit (Vitest, 21) — `frontend/tests/`

HTTP client: query building; the backend error envelope becomes `ApiError` with code, message,
details; non-JSON failures become a readable error; 204; the bearer token and same-origin proxy;
on 401 exactly one refresh and one retry; concurrent 401s share **one** refresh (a rotated cookie is
never replayed); a failed refresh calls the session-lost handler; no retry loop; sign-out forgets the
token; GET cache hit, invalidation on writes, no cached failures, **no cross-user cache after a new
sign-in**; wrong password stores no token. Display helpers: missing values render "—", a real 0
renders 0, insufficient-data measures render "—", all seven rule labels exist.

### Browser (Playwright, 13) — `frontend/e2e/`

The global setup creates its own department `E2E<run>`, two faculty members, two classes, 12
students and marks (one genuine 0, one absent, one missing) through the API, so every run is
independent and repeatable.

| Spec | Checks |
|---|---|
| `auth.spec.ts` | wrong password: message, no session, protected page redirects; sign in → reload keeps the session → refresh cookie unreadable from script → sign out → protected page redirects, no console errors or failed calls; deep link returns after sign-in; faculty menu hides admin items and `/admin/users` refuses on the server |
| `navigation.spec.ts` | every sidebar link as Administrator (20+ pages): heading visible, no error state, no `NaN`/`undefined`/`[object Object]`, no console errors, no failed API calls; branded not-found page; class marks grid shows 0, AB and — distinctly; assessment counts 6 present / 1 absent / 1 missing |
| `import.spec.ts` | CSV upload into a class → Errors → Review → map `Cycle Test 2` to CT2 → exclude the row above the maximum (it stays listed with *Include*) → 0 errors → Confirm → the API shows exactly 41, 0, absent, missing → the class grid shows 41; an unreadable workbook is Rejected with a reason |
| `scope-and-reports.spec.ts` | faculty B gets *Not found or not in your scope* for A's class and student and sees only their own section and students; class summary PDF / XLSX / CSV download with the right file name and file signature, no NaN; an intervention recorded from the attention tab appears with the observational notice |
| `mobile.spec.ts` | 7 pages on a Pixel 7 with ≤ 1 px horizontal overflow; the menu opens and navigates |

### Live independent verification (`scripts/verify_live.py`, 228)

Every expected number is computed in the script from the marks it enters, with the Python
standard library only — never with application code — then compared with the API.

| Section | Passed | Highlights |
|---|---|---|
| Academic hierarchy | 23 | duplicate department/section/offering 409; bad academic year and reversed dates 422; unknown department/section 404; faculty cannot create offerings; second HOD and second administrator 409 |
| Students | 11 | bulk dry run writes nothing; 16 created; re-run creates nothing; duplicate register number 409; malformed 422; search; pagination |
| Assessments and results | 27 | negative, above max, 3 decimals, blank, absent-with-score, present-without-score, other class's student, unknown register number all refused; one bad row rejects the whole request; re-entering a mark is "unchanged"; **0 present 0, absent no score, exempt no score, missing no row**; max marks locked once results exist |
| Analytics | 19 | latest assessment mean, median, population sd, pass %, completion %, lowest, highest, n, histogram bins; class mean/median/pass %/completion of weighted course scores; coverage; per-assessment mean with a genuine 0 and completion with exempt excluded |
| Attention | 23 | each of 10 students gets exactly the rules computed independently; **R1 and R2 do not fire at exactly 50 %; R7 does**; flag message carries 49.2 and 50; no predictive/causal words; recompute idempotent; persisted flags = computed; an offering threshold override changes R1 (strict at 60) and removing it restores the flags |
| Student profile | 22 | weighted course score, completion and per-assessment state for 5 students; slope exactly +5 is *improving*; another class's student 404 |
| Imports | 34 | CSV staged, nothing written; every problem code reported; confirm refused with errors; other faculty 404 on the batch; fix clears an error; exclusion; **confirm writes exactly the previewed cells**; 0 / AB / blank stored correctly; excluded rows not written; second confirm refused; re-upload flagged; history; audit; XLSX template filled and imported (5 present, 1 exempt, 39.75 exact); empty file, header only, no register column, duplicate columns, unsupported extension, fake/malformed workbook, non-UTF-8, 5 MB + 1 all handled; path-traversal name neutralised; unknown class 404 |
| Interventions | 9 | recorded and listed; note stored as text; cross-class target, duplicate targets, empty targets refused; other faculty 404; outcome wording observational; no follow-up → insufficient data, never a number |
| Reports | 22 | 5 kinds × 3 formats: 200, MIME type, file name extension, file signature, non-empty; class summary CSV has no NaN/None and carries the API's class mean; attention CSV lists every flagged student and no rule for unflagged ones; unknown kind 404/422; unknown format 422; other faculty 404 |
| Isolation | 25 | 15 reads and 3 writes by faculty B on A's class 404; B's lists contain only B's data; faculty audit log scoped; `/users` 403; creating users/departments and recompute 403; HOD sees both classes |
| Deletion guards | 5 | assessment, offering, section, course with dependents not deletable; results intact |
| Sessions | 7 | rotation; garbage/missing token 401; logout with only the refresh token 204; logged-out session cannot refresh; deactivation kills an existing access token at once and blocks sign-in; reactivation restores |

### Sign-in throttle, live

Before the fix (audit stack, original image): 50 wrong passwords → 50 × 401, then the correct
password → 200. After: 10 × 401, then 429 `too_many_attempts` with `Retry-After: 900`; another
account unaffected.

## 4. Browser crawl (exploratory)

`frontend/e2e/crawl.mjs` opened every route as the Administrator at 1440×900 and at 390×844,
recording console errors, page errors, failed requests, duplicate API calls, horizontal overflow and
raw `NaN`/`undefined` text, with a full-page screenshot of each. Findings: `/settings` overflowed a
phone by 149 px (UI-01); unknown routes showed the framework's bare 404 (UI-02). No duplicate API
calls on any page (2–6 calls per page), no console errors, no raw values. Deliberate error routes
(`/classes/<unknown uuid>`, `/students/not-a-uuid`) showed *Not found or not in your scope* and
*Could not load this view* with a retry.

## 5. Docker: clean start from the finished tree

`docker compose -p acadlytics-final up -d --build` from the finished working tree, with a new
env file (random secrets), an empty volume and ports 55441 / 8011 / 3012:

| Step | Result |
|---|---|
| `docker compose config` | valid |
| Build (both images, from scratch) and start | exit 0 in 301 s |
| db / api health | healthy / healthy; web started after the API was healthy |
| Migrations on the empty database | `0001 → 0008` in order; `/health` reports `0008` |
| Administrator | created from `ACADLYTICS_ADMIN_*`; the log names the variable, not the password |
| `scripts/e2e_live.py` (through the web container) | **130 / 130** |
| `scripts/verify_live.py` | **228 passed, 0 failed** |
| `npm run test:e2e` against the web **container** | **13 passed** |

The stack was then removed with its volume and images (`down -v --rmi local`).

Timings from that run (single requests through the web proxy): overview 184 ms, class analytics
127 ms, attention 60 ms, insights 105 ms, student 87 ms, outcomes 42 ms, reports median 48–76 ms
(max 201 ms), uploads median 55 ms (max 726 ms), workspace 305 ms.

### The application stack (real data) after redeploying

`docker compose up -d --build` on `facultyproject` (63 s; the database container was not
restarted). A `pg_dump` was taken first (`~/acadlytics-backups/acadlytics-pre-upgrade-2026-11-16.dump`,
24 tables, outside the repository). Afterwards: `/health` ok at `0008`; `/login` and `/dashboard`
200, an unknown page 404; API PID 1 is uvicorn; the real class reads as before — 58 results,
mean 74.12 % over 57 present, 1 absent with no score, pass 98.25 %, 6 open flags — both in SQL and
through the web app; the faculty account refuses both former passwords. The only write was the
Administrator's `last_login_at` from the read-only check.

## 6. Backup and restore

On the audit stack: `pg_dump -Fc` → `createdb acadlytics_restore` → `pg_restore` → row counts of
all 24 tables identical to the source, `alembic_version` `0008`; scratch database dropped. The
procedure is the one in `LOCAL_DEMO_GUIDE.md`.

## 7. Docker behaviour fixed and verified

| Check | Before | After |
|---|---|---|
| Code-only rebuild of the API image | re-downloaded setuptools; failed twice on read timeouts | 7 s, 8 cached layers, nothing downloaded |
| Dependency versions in the image | newest on PyPI (pydantic 2.14.3 resolved; backtracking over 40 releases when the index stalled) | pinned to the tested set (`constraints.txt`) |
| PID 1 in the API container | `sh` | `uvicorn` |
| `docker stop api` | exit code 137 (SIGKILL) | 1 s, exit code 0, "Application shutdown complete" |
| Production config without secrets | n/a (none existed) | refuses: exit 1 naming the five missing variables |

## 8. Performance observations (not a load test)

Single requests through the web proxy on small data (tens of students), from the live runs:
overview 113 ms, class analytics 140 ms, attention 50 ms, insights 118 ms, student 50 ms,
outcomes 60 ms, reports median 53–80 ms (max 215 ms), uploads median 91 ms (max 1.27 s),
workspace 437 ms (first call after sign-in). The backend suite's query-budget tests (unchanged)
bound the number of SQL statements per request independently of class size. No load test was run;
no claim about institutional scale is made.

## 9. Not verified

- Production deployment on any host or cloud (not performed).
- Firefox, Safari, real phones; screen readers.
- Load and concurrency at the design scale.
- Playwright and the live scripts do not run in GitHub Actions (they need a running stack).

The edited GitHub Actions workflows did run on the push of `62b47a6`: **backend** (pinned
install, ruff, full pytest on PostgreSQL 16) passed in 4 min 36 s; **frontend** (lint, type
check, unit tests, build) passed in 1 min 44 s.
