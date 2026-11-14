# ACADLYTICS — final quality audit, local release candidate

Date: 2026-11-14. Branch: `release/local-rc` (from `main` at `07e5258`). Machine: Windows 11,
Docker Desktop 29.8, PostgreSQL 16 (container), Python 3.12, Node 24.

Every result below was observed on that date. Where something was not checked, it says so.

## 1. Initial state

| Area | Found |
|---|---|
| Git | `main`, clean, level with `origin/main` |
| Backend tests | 1932 passed, 1 skipped; `ruff check` and `ruff format --check` clean |
| Frontend | `eslint`, `tsc --noEmit` and `next build` clean. No `typecheck` or `test` script. |
| Frontend data | No mock layer. Every page already read the API. |
| Migrations | One head, `0008` |
| Local database | The 97-section fictional seed (2026-10-07) plus one real-looking upload (2026-10-13) |
| Other projects on the machine | PostgreSQL containers on 5432, 5433, 5434 (WhistleDrop, BhashaBench) |

## 2. Demo material discovered

| Where | What |
|---|---|
| `frontend/components/login.tsx` | A "Sign-in accounts" list with four `@acadlytics.dev` addresses and a *Use* button each |
| `backend/app/bootstrap.py` | On an empty database: a CSE department and Administrator, HOD and Academic Head accounts, all with the built-in password `Demo@2026pass` |
| `backend/app/core/config.py`, `imports/provision.py` | Every faculty account created from a TLP report got the built-in password `Faculty@2026` |
| `backend/app/cli.py` | `seed-demo` fell back to `Demo@2026pass` |
| `docker-compose.yml`, `.env.example`, `README.md` | The same two passwords as defaults and in a table of accounts |
| `frontend/app/(app)/sections/page.tsx` | A KPI "Sections below 55%" with a threshold that exists nowhere in the backend |
| `frontend/app/page.tsx` | A landing illustration captioned "−9.8 pp drop" and the text "all ninety-seven" |
| `backend/app/demo/srm.py`, `backend/app/seed.py` | Generators of fictional institutions (explicit CLI command only; never run at start) |
| `demo/tlp-uploads/` | Four fictional TLP reports |
| Local database | 109 `@acadlytics.dev` users, 4,087 students, 582 classes, 3,201 assessments, 96,516 results, 50 interventions, 12 imports from the seed |

## 3. Demo material removed, and what was kept

Removed or changed:

- The account list and *Use* buttons on the sign-in page. The page now has email, password and a
  line telling people whom to ask for an account.
- Both built-in passwords. There is no default password anywhere in the code, Compose file or
  `.env.example`.
- Start-up no longer creates a department, a HOD or an Academic Head. It creates one
  Administrator, only when none exists and only from `ACADLYTICS_ADMIN_EMAIL` /
  `ACADLYTICS_ADMIN_PASSWORD`.
- A faculty account created from a report gets a random password nobody knows; it cannot sign in
  until an Administrator or HOD sets one (or `FACULTY_DEFAULT_PASSWORD` is configured).
- `seed-demo` refuses to run without `ACADLYTICS_DEMO_PASSWORD`.
- The invented 55% KPI (now "Sections with flagged students", from the API's own
  `attention_students`) and the invented figure on the landing illustration.

Kept, deliberately:

- `backend/app/seed.py` and `backend/app/demo/srm.py`: development tools behind an explicit
  command, refused in production and on a database that has data, and used by the test suite
  (analytics contract C11).
- `demo/tlp-uploads/`: fictional files used by the end-to-end check. Nothing loads them.
- All test fixtures under `backend/tests/`.

## 4. Database clean-up performed

Environment: the Compose volume `facultyproject_pgdata`, database `acadlytics`, reachable only on
`localhost:55432`; `APP_ENV=development`. Local development database.

Procedure:

1. Inspection. Every seeded row carries the seed transaction's timestamp
   `2026-10-07 10:03:49.499231+00`. One upload on 2026-10-13, `S2_arulalan_FP1.pdf`, created
   faculty `103059@srmist.edu.in`, section S2, one class of course 21DCS201P, 58 students and 58
   results. Its students belong to no seeded class.
2. The owner was asked and chose: remove the seed, keep that upload.
3. Backup first: `~/acadlytics-backups/acadlytics-pre-cleanup-2026-11-14.dump` (`pg_dump -Fc`,
   all 24 tables listed by `pg_restore --list`). Restore instructions: `LOCAL_DEMO_GUIDE.md`.
4. One transaction, which aborts unless the set to keep is exactly 1 class, 58 students and 1
   faculty member, the kept students are in no other class and the kept class has no
   interventions. It deletes child rows before parents, so every `RESTRICT` foreign key holds
   throughout.
5. Verification. A fingerprint of the kept class taken before and after is identical: 57 present
   results summing to 422.50, 1 absent with no score, the same 58 register numbers and names
   (MD5 over the ordered list), 6 attention flags.

After: 1 department, 1 term, 1 course, 1 section, 1 class, 58 students, 58 enrolments, 1
assessment, 58 results, 6 flags, 1 import, 2 audit rows, 1 faculty user. Start-up then created the
Administrator. Through the running application the class reads: average 74.12% over 57 students,
pass 98.25%, 1 absent, 6 flags; CSV, Excel and PDF class reports download.

The seeded department (CSE), term and course 21DCS201P were kept because the real class depends
on them.

## 5. Academic hierarchy

No model, migration, foreign key or authorisation code was changed. `git diff main -- backend/alembic
backend/app/modules/organization backend/app/modules/students backend/app/modules/assessments
backend/app/modules/analytics backend/app/modules/attention backend/app/modules/interventions
backend/app/modules/reports backend/app/modules/overview` is empty.

Department → term / course / section → course offering → faculty, enrolments, assessments →
results, flags, interventions is as it was. The offering remains the access boundary
(`organization/scope.py`). Checked after the work: one migration head (`0008`); `0001 → 0008`
applies to an empty database both on the host and in the container; the schema-integrity tests
(51) pass; the clean Docker stack had no unvalidated foreign keys, no result without a student and
no non-present result carrying a score.

## 6. Backend defects found and fixed

| # | Defect | Fix | Test |
|---|---|---|---|
| B1 | Built-in passwords for the first accounts and for every faculty account | Removed (section 3) | `test_bootstrap.py`, `test_tlp_provision.py`, `test_config.py` |
| B2 | Start-up fabricated a department and two role accounts | Start-up creates the Administrator only | `test_bootstrap.py::test_creates_only_the_administrator` |
| B3 | Nobody could change their own password; the configuration comment said faculty would "change it" | `POST /api/v1/auth/password`: verifies the current password, revokes every refresh token of the account, writes an audit row. A wrong current password is 422, not 401, so a typo is not mistaken for an expired session. | 8 tests in `test_auth_api.py` |
| B4 | `create-admin` and start-up printed the submitted password in validation errors (`input_value='…'`) | Errors list field and reason only | `test_bootstrap.py` (2 tests) |
| B5 | An empty `FACULTY_DEFAULT_PASSWORD=` from Compose would fail settings validation | Empty means unset | `test_config.py` |
| B6 | One report test skipped the class with no published assessment | The case is asserted: it exports in all three formats without NaN | `test_reports.py` |
| B7 | The 5,000-row, 200-column and 5 MB import limits had no tests | Boundary tests at the limit and one over | `test_tabular.py` (4 tests) |

Transactions remain service-owned; repositories still never commit. No SQLAlchemy was added to
`analytics/core`.

## 7. Frontend defects found and fixed

| # | Defect | Fix |
|---|---|---|
| F1 | Demo account list on the sign-in page | Removed |
| F2 | KPI with a threshold invented in the browser | Replaced by a count taken from the API response |
| F3 | Invented figure in the landing illustration | Removed |
| F4 | No way to change a password | *Settings → Change password*; signs out and returns to the sign-in page with a confirmation |
| F5 | The import page promised a faculty login without saying it needs a password | Text now says where the password is set |
| F6 | No `typecheck` script | `npm run typecheck` |

The visual design and component structure are unchanged.

## 8. API integration

See `INTEGRATION_AUDIT.md` for the page-to-endpoint table. Dashboard figures were compared in a
real browser against `GET /insights/overview` and against SQL on the same stack and matched (82
students; average 64.74; pass 75.64; 59 / 19 / 4; 20 needing attention; completion 65.32;
database: 81 present, 6 absent with NULL score, one real 0). A page reload keeps the session; a
page load makes each request once; no console messages.

## 9. Authentication and authorisation

Live, through the web server: wrong password 401; the old built-in passwords 401; refresh token
only in an httpOnly cookie on `/api/session` and absent from the response body; no token 401;
malformed token 401; silent refresh rotates; a rotated refresh token replayed after the 10-second
allowance is 401 and kills the newer token of that session too; logout 204 and no session
afterwards; sign in again works; password change works and invalidates the old password.

Existing suite (unchanged, passing): expired and malformed access tokens, expired refresh
tokens, idempotent logout, deactivated users, the five-role scope, last-administrator guards.
Logout takes only the refresh token in its body, so it still works when the access token has
expired. That is intended and was not changed.

## 10. Import

Live: Excel and PDF TLP reports for two sections staged, validated and confirmed, setting up
term, course, sections, classes, students and faculty; 0 results existed while staged; re-upload
reported as a duplicate. A CSV for one assessment with a valid mark, a real 0, `AB`, a blank, a
negative, a mark above the maximum, an unknown register number, a duplicated student and text in
the mark column: the preview named each problem (`score_below_zero`, `score_above_max`,
`unknown_student`, `duplicate_student_row`, `invalid_number`), confirm was refused with 422 and
nothing was written; after one fix and excluding the rest, confirm wrote exactly 5 rows.

| Input | Stored |
|---|---|
| `18` | 18, present |
| `0` | 0, present |
| `AB` | no score, absent |
| blank | no score, absent, with warning `blank_cell_absent` (the documented rule, `IMPORT_FORMAT.md`) |
| student not in the file | missing |
| above maximum, excluded | not written |

Also live: oversized file, unsupported type and empty file refused with 422. Existing suite: 90
import tests including atomicity, column mapping, malformed files, mixed rows, audit and history.

## 11. Analytics

1,120 unit tests of the deterministic engine pass (F1–F21, profiles, class health,
distributions, comparison, trends, segmentation, insights, ordering). Live: class analytics,
student profile, insights and the overview answer 200 and contain no NaN or Infinity (the client
rejects them while parsing). No ML, LLM or score model was added.

## 12. Attention

Live, on the clean stack: 72 flags; the summary total equals the flags listed; every flag carries
a message, the assessments used and either its threshold or the class pass mark; every R1 flag has
a value strictly below its threshold and every R2 flag strictly below the pass mark. Rules seen
live: R1, R2, R4, R5, R6, R7. R3 did not occur in that data; it is covered by
`tests/e2e/test_invariants.py`, whose cohort makes all seven rules fire.
Strictness at the threshold: `test_r1_is_strict_at_the_threshold` (exactly 50% does not fire),
and the same for R2 and R6.

## 13. Interventions and outcomes

Live: an intervention recorded from a persisted flag; duplicate student targets refused; a student
of another class refused; an unknown flag id refused; outcomes answer 200 and contain no causal
wording; a note containing `<script>` is stored as text (React escapes it on display). Existing
suite: 30 API tests plus the engine tests for baselines, follow-ups, missing follow-up,
insufficient data, date ambiguity and comparison-group size.

## 14. Reports

Live: class summary, student performance, attention, assessment comparison and intervention
outcome, each as CSV, Excel and PDF: 15 downloads, each 200, correct content type, a file name
with the right extension, non-empty; CSV free of NaN / Infinity; Excel opens with openpyxl; PDF
starts `%PDF`. Existing suite: 99 report tests including missing-data wording and the
observational caveat.

## 15. Security

Live, two faculty members with one class each: faculty B received 404 for A's class, analytics,
attention, insights, interventions, students, assessments, results, report, student profile and
import batch (12 reads), and 404 for recording an intervention in and uploading into A's class.
Invalid UUID 422; unknown UUID 404; malformed JSON 422; a SQL-injection-style search string is
treated as text and returns no rows. Existing suite: 80 security tests (IDOR across roles, input,
uploads).

## 16. Database

PostgreSQL 16 only. One head. Empty-database upgrade verified twice (host, container). Recompute
idempotence and query budgets: existing tests (17 and 10) pass. The test suite uses its own
database and never the application's.

## 17. End-to-end

`scripts/e2e_live.py`: 130 of 130 checks on a host-run stack against an empty database, and 130
of 130 on a clean Docker stack built from this branch (`docker compose -p acadlytics-clean`, own
volume, ports 55433 / 8002 / 3003), which was then removed with its volume.

Full backend suite after all changes: **1952 passed, 0 skipped, 0 failed** (328 s).
`ruff check`, `ruff format --check`, `eslint`, `tsc --noEmit`, `next build`: clean.

Timings from the Docker run, one request each unless noted, 82 students, through the web proxy:
overview 95 ms, class analytics 186 ms, attention 69 ms, insights 129 ms, student profile 72 ms,
outcomes 73 ms, reports median 62–86 ms (max 230 ms), uploads median 75 ms (max 758 ms). These
are single measurements on a small data set, not a load test.

## 18. Docker

`docker compose up -d --build` starts db, api and web. Added: an API health check, and the web
container now waits for a healthy API. Migrations and the Administrator step run on every start
and are idempotent. Default host ports changed to 55432 / 8000 / 3001. No secret is committed:
`.env` is ignored and was not staged. Containers of other projects (WhistleDrop, BhashaBench)
were running before and after and were not touched.

## 19. Addresses (running at the time of writing)

| | |
|---|---|
| Web app | http://localhost:3001 |
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| PostgreSQL | localhost:55432 |

## 20. Remaining issues

| Severity | Issue |
|---|---|
| BLOCKER | None known. |
| HIGH | The faculty account `103059@srmist.edu.in` in the local database was created before this work and still has the former built-in password, which is public in the repository history. Set a new one in *People* before anyone else can reach this machine's port 3001. (An automated reset was not permitted in the working session.) |
| HIGH | The two former built-in passwords are in the public Git history. Any other installation made from an earlier commit must change its Administrator, HOD, Academic Head and faculty passwords. |
| MEDIUM | The web app has no automated tests of its own. It is covered by lint, type check, build, the HTTP end-to-end script and a partial manual pass in a browser (sign-in, dashboard, settings, sections, reports, attention). The other pages, dialogs, forms, the file-drop interaction and small-screen layout were not checked visually. |
| MEDIUM | A new faculty account needs an Administrator or HOD to set its password by hand. There is no invitation or reset-by-email flow and no forced change at first sign-in. |
| MEDIUM | The backup taken before the clean-up (`~/acadlytics-backups/…dump`) contains student names and marks. Keep it off shared storage; delete it when no longer needed. |
| LOW | If the Administrator uploads a report before any department exists, set-up creates a department named after the course-code prefix. Create the department first (documented). Not tested. |
| LOW | The generic per-assessment upload exists in the API but the web import page offers only the TLP upload. |
| LOW | On this machine the virtualenv launcher `backend/.venv/Scripts/alembic.exe` exits silently without migrating; `python -m alembic upgrade head` works (the README now uses it). The container is unaffected. |
| LOW | A database `acadlytics_tlp_check` from earlier work is still in the local PostgreSQL. It was not created in this work and was left alone. |
| LOW | The fictional-data generators live inside the application package (`app/seed.py`, `app/demo/`). They are explicit-only; moving them out would need the tests that use them to move too. |
| DEFERRED | Performance at institutional scale is unmeasured. No load test was run and no claim is made. |
| DEFERRED | Hosting: HTTPS, secure cookies (the local Compose file sets `ACADLYTICS_INSECURE_COOKIES=1`), secret management, backups, rate limiting on sign-in. This is a local release candidate, not a cloud deployment. |

## 21. Git

Branch `release/local-rc`, created from `main` (`07e5258`); `main` was not modified. Commits:
the application changes, then the documentation. Not pushed: `origin` has no `release/local-rc`
until the owner pushes it. `git status` is clean after the documentation commit; `git log` on the
branch has the exact hashes.
