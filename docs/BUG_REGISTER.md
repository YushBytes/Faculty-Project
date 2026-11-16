# ACADLYTICS — defect register

Audit of 2026-11-15/16 on branch `backend`, starting from `2b18ff3`. Every defect below was
**reproduced** before it was changed and **verified** afterwards; the evidence column says how.
"Live" means against a running stack: the isolated audit stack (`docker compose -p
acadlytics-audit`, own volume, ports 55440 / 8010 / 3010) or the local web build on 3011 that
points at it. The application stack with real data (3001 / 8000 / 55432) was only touched where
stated (SEC-01).

Severity: BLOCKER (unusable) · CRITICAL (data or security exposure) · HIGH (a primary workflow
cannot be completed) · MEDIUM (works, wrongly or with a real risk) · LOW (polish, hardening).

## Summary

| Severity | Found | Fixed | Open |
|---|---|---|---|
| BLOCKER | 0 | 0 | 0 |
| CRITICAL | 1 | 1 | 0 |
| HIGH | 4 | 3 | 1 (SEC-02: history rewrite prepared; the force-push awaits your approval) |
| MEDIUM | 9 | 9 | 0 |
| LOW | 9 | 9 | 0 |
| **Total** | **23** | **22** | **1** |

Not defects (checked and left as designed) are listed at the end.

## Register

### SEC-01 · CRITICAL · Authentication — a leaked password still opened a real account

| | |
|---|---|
| Reproduction | For each account in the running application database, sign in with each of the two former built-in passwords (read from the tracked test file, never printed). |
| Expected | 401 for every account. |
| Actual | `103059@srmist.edu.in` (FACULTY, the one real class) → **200**. The previous audit had recorded this as open ("an automated reset was not permitted"). |
| Root cause | The account was created before the built-in passwords were removed, and was never reset. The password is public in Git history (SEC-02). |
| Fix | Password replaced with a random 32-byte value that was never displayed or stored anywhere; every refresh token of the account revoked; an audit row `password_reset` written. Done through the application's own hashing and repository code inside the API container. |
| Verification | Same check afterwards: both former passwords → 401 for both accounts. |
| Action for you | Set a new password for this faculty member in **People** before they next sign in. |

### SEC-02 · HIGH · Repository — former built-in passwords remain in public Git history (OPEN — prepared, awaiting approval)

**Update 2026-11-16 (second round):** the current tree no longer contains either value (tests and
`scripts/e2e_live.py` use neutral values; `tests/test_no_hardcoded_credentials.py` now guards
runtime code and configuration). A backup and a fully rewritten copy of the repository are
prepared and verified locally; nothing has been force-pushed. Procedure, affected references and
the impact on collaborators: `SECURITY_AUDIT.md` §5.


| | |
|---|---|
| Reproduction | `git log --all -S<password>`: 7 commits for one, 5 for the other. |
| Current tracked files | After this audit, only as **refused values** in `backend/tests/test_bootstrap.py`, `test_tlp_provision.py`, `test_seed.py`, `test_srm_demo_seed.py` and `scripts/e2e_live.py` (assertions that these strings no longer sign anyone in, plus a fixture password for the fictional seed). The previous audit document printed them; it is now redacted (DOC-03). No `.env` was ever committed (`git log --all -- '*.env'` is empty). |
| Why open | Removing them from history means rewriting the published `backend` and `main` branches (force-push), which breaks every existing clone. That needs your explicit decision and coordination with anyone who has cloned the repository. |
| Mitigation in place | No account anywhere in the running database accepts either value (SEC-01). Any other installation made from an older commit must reset its Administrator, HOD, Academic Head and faculty passwords. |
| Remediation plan | `docs/SECURITY_AUDIT.md` §5. |

### SEC-06 · HIGH · Repository — the default branch `main` still shipped built-in passwords (FIXED 2026-11-16)

**Resolved:** approved and done — `main` received `backend` by a normal merge, `f8f91f3`, same tree, GitHub CI green on both workflows. No history was rewritten.


| | |
|---|---|
| Found | 2026-11-16, while preparing the history rewrite |
| Reproduction | `git grep` on `origin/main` (GitHub's default branch, 10 commits behind `backend`): the bootstrap default for the first accounts, the CLI's demo-password fallback, the Compose default and `.env.example` still use the former built-in passwords. |
| Impact | Anyone who clones the default branch and starts it gets accounts with a publicly known password. A history rewrite done first would turn those lines into a new well-known value (`***REMOVED***`). |
| Fix (prepared) | Merge `backend` into `main`. Tested in a separate worktree: no conflicts; the result is the same tree as `backend`. Not pushed: `main` receives reviewed merges, and pushing it needs your approval (`GIT_HISTORY_REWRITE.md` §4.1). |

### SEC-07 · MEDIUM · Users — two concurrent writes could create two active Administrators (FIXED 2026-11-16)

| | |
|---|---|
| Found | Product audit of 2026-11-16 |
| Reproduction | `tests/test_single_administrator.py` with the new index removed: two transactions that both pass the service's count check before either writes (the window when no Administrator exists: two API processes bootstrapping, or bootstrap racing `create-admin`) → **two active Administrators** committed. |
| Root cause | The rule was a count-then-write check in the service only; HOD and Academic Head had a database index, the Administrator did not. |
| Fix | Migration `0009`: partial unique index `uq_users_single_active_admin`. Conflict message made accurate ("there can be only one" — the old text promised a transfer that does not exist). Bootstrap treats losing that race as success. The UI no longer offers Administrator as a role for anyone else. |
| Regression tests | 12 tests in `test_single_administrator.py`, including three real-concurrency tests (creations, promotions, bootstraps). |
| Verification | Without the index: 4 failed (two winners). With it: 12 passed. Migration applied to the local database after a backup: one Administrator before and after, all row counts identical. |

### SEC-05 · MEDIUM · Authorisation — department thresholds were readable by every signed-in user

| | |
|---|---|
| Decision | Previously a deliberate, tested design ("anyone signed in may read"). Changed on your decision of 2026-11-16 to scope-based access. |
| Reproduction | Faculty of department A: `GET /departments/<B>/settings` → 200 with B's thresholds. |
| Expected | ADMIN: every department. HOD / Academic Head: their department. Course Coordinator: the departments of their courses. Faculty: their home department and the departments of the classes they teach. Anything else **404**, indistinguishable from a department that does not exist. |
| Fix | `organization/scope.py::threshold_department_ids` (one rule), enforced in `SettingsService` for reads and before the write check (a department the actor cannot see is 404 for writes too; visible but not manageable stays 403). The analytics engine's own threshold resolution is unchanged. `GET /me/workspace` lists `threshold_departments` (with `can_edit`) computed by the same rule; the web app's new read-only *Analytics thresholds* card on Settings is built from that list. |
| Regression tests | `tests/test_settings_api.py` rewritten: 21 tests across every role, removal from a class removing access, 404 identical to a missing department, writes, workspace = API rule. Against the old code 11 of them fail. `frontend/e2e/thresholds.spec.ts` (faculty see only their department, read-only, and a direct API request for another department is 404 in the browser; the administrator picks any department and sees its values); `frontend/tests/endpoints.test.ts` (adapter URL; 404 is an error, not an empty list). `scripts/verify_live.py` +5 live checks. |
| Verification | pytest PASS (2003); Playwright 15/15; verify_live 232/232 on a fresh stack. |

### IMP-01 · HIGH · Import — a column the system cannot match blocks the import with nothing to act on

| | |
|---|---|
| Reproduction | Import page for a class → upload a CSV whose mark column is headed `Cycle Test 2` (the class has `CT2`) → the file shows **Errors** → **Review**. |
| Expected | The problem is shown and can be resolved (map the column, or ignore it), as `IMPORT_FORMAT.md` and `POST /imports/{id}/mapping` provide. |
| Actual | The drawer lists only row issues. The column error (`missing_assessment_definition`) lives in `preview.columns[].issues`, which the drawer never rendered; there was no mapping control. Confirm stays disabled with no visible reason; the only way out was to edit the file and upload again. |
| Root cause | The review UI was built for row/cell problems only; the backend's mapping endpoint had no adapter or control. |
| Fix | `frontend/app/(app)/import/page.tsx`: a *Columns* section listing every column with an issue or a manual mapping, an assessment picker (*Map column*), *Ignore this column* and *Undo*. `importsApi.mapColumns` in `lib/api/endpoints.ts`. |
| Regression test | `frontend/e2e/import.spec.ts` (maps the column in the browser, then confirms). |
| Verification | Playwright, live: PASS. |

### IMP-02 · MEDIUM · Import — an excluded row disappears from review and cannot be included again

| | |
|---|---|
| Reproduction | Review a staged file → *Exclude row* on an error row. |
| Expected | The row stays listed with *Include*, so a mistaken exclusion can be undone (the drawer has that button). |
| Actual | The row vanished; it could only be restored by discarding and re-uploading. |
| Root cause | `preview_read(only="issues")` keeps rows that have issues; an excluded row is not validated, so it has none. |
| Fix | `backend/app/modules/imports/service.py`: the *issues* view also keeps excluded rows (the *errors* view is unchanged). API parameter description updated. |
| Regression test | `tests/test_imports_api.py::…test_an_excluded_row_stays_in_the_issues_view_so_it_can_be_included_again`; `e2e/import.spec.ts` checks *Include* appears. |
| Verification | pytest PASS; Playwright live PASS (it failed before the fix — that run is how it was found). |

### IMP-03 · LOW · Import — *Discard file* in the review drawer had no error handling

| | |
|---|---|
| Reproduction | Code inspection: `await importsApi.discard(...)` with no `catch`; a failed discard (expired batch, session lost) became an unhandled rejection and the drawer closed as if it had worked. |
| Fix | Errors are caught and shown in the drawer; the button is disabled while working. |
| Verification | Typecheck/lint; covered by the drawer flow in `e2e/import.spec.ts`. |

### SEC-03 · HIGH · Authentication — no protection against password guessing

| | |
|---|---|
| Reproduction | 50 wrong passwords in a row for one account: every one answered 401 at full speed; the 51st, correct, signed in. |
| Expected | Repeated failures for one account are slowed or stopped. |
| Root cause | Not implemented. |
| Fix | `backend/app/core/throttle.py`: after `LOGIN_MAX_FAILURES` (10) wrong passwords for one email within `LOGIN_WINDOW_SECONDS` (900), sign-in for that email answers **429 `too_many_attempts`** with `Retry-After` until the window passes — the correct password included. Keyed on the normalised email (all browser traffic reaches the API from the web server's address, so an address key would lock out everyone); unknown emails are counted the same way, so it does not reveal which accounts exist. Memory is bounded. The sign-in page shows the server's message. Limits: per process, and a known email can be locked for up to 15 minutes by someone failing on purpose — see `SECURITY_AUDIT.md`. |
| Regression test | `tests/test_login_throttle.py` (9 tests: limit, fixed window, reset on success, case/space evasion, unknown emails, other accounts unaffected, disable with 0, memory bound). |
| Verification | pytest PASS. |

### SEC-04 · LOW · Import — the uploaded file name was stored exactly as the client sent it

| | |
|---|---|
| Reproduction | Upload with the name `../../etc/passwd<script>.csv` → import history shows that name. |
| Impact | Upload bytes are never written to disk and React escapes the name, so no traversal or XSS; but a path chosen by the client was kept as a label and fed the file-name section hint. |
| Fix | `safe_file_name()` in `backend/app/core/tabular.py` (last path segment, no control characters, ≤ 255), used by both import entry points; the TLP `sections` map is keyed the same way. |
| Regression tests | `tests/test_tabular.py::test_safe_file_name_keeps_only_the_last_segment` (11 cases); `tests/security/test_upload_security.py::…test_a_path_in_the_file_name_is_not_recorded`. |
| Verification | pytest PASS; `scripts/verify_live.py` live PASS. |

### API-01 · LOW · Reports — an unknown export format was a 404

| | |
|---|---|
| Reproduction | `GET /offerings/{id}/reports/class_summary?format=docx` → 404 `not_found`. `GET /insights/report?format=docx` → 422. |
| Expected | 422 `validation_error` (contract C7: 404 is for missing or out-of-scope resources). |
| Fix | The `format` query parameter is a `Literal["csv","xlsx","pdf"]`, validated like every other parameter, before any report is built. |
| Tests | Two existing tests asserted the 404; both now assert the 422, the `validation_error` code, the `["query","format"]` location, and (security test) that the rejected value is not echoed back. |
| Verification | pytest PASS; live PASS. |

### OPS-01 · MEDIUM · Docker — every code-only rebuild of the API image needed PyPI

| | |
|---|---|
| Reproduction | Change one backend file, `docker compose build api`. The final `pip install --no-deps .` downloads `setuptools` into an isolated build environment each time; on this connection it failed with a read timeout. |
| Fix | `backend/Dockerfile`: `setuptools` is installed in the cached dependency layer and the application layer is built with `--no-build-isolation`, so a code-only rebuild is offline. |
| Verification | See `TESTING_AND_VERIFICATION.md` §Docker. |

### OPS-03 · MEDIUM · Docker / CI — dependency versions were not pinned

| | |
|---|---|
| Reproduction | A fresh `docker compose build api` resolved the newest releases (pydantic 2.14.3, not the 2.13.5 the suite ran against); when the index stalled on `pydantic-core`, pip backtracked through 40 pydantic releases and failed with `ResolutionImpossible` after 518 s. |
| Impact | The image and CI ran versions nobody had tested; builds were not reproducible. |
| Fix | `backend/constraints.txt` (exact versions of the tested environment), used as `pip install -c constraints.txt` in the Dockerfile and CI. `pyproject.toml` ranges unchanged. |
| Verification | The next build installed exactly the pinned set with no backtracking; image built; all live suites pass on it. |

### OPS-04 · MEDIUM · Docker — the API was killed, not stopped, on every `docker stop`

| | |
|---|---|
| Reproduction | `docker exec api cat /proc/1/cmdline` → `sh -c "alembic … && uvicorn …"`; `docker stop` → exit code **137**. |
| Root cause | `sh` was PID 1 and does not forward SIGTERM; uvicorn never saw it and was SIGKILLed after the timeout, cutting off in-flight requests. |
| Fix | `exec uvicorn …` in the container command, so uvicorn becomes PID 1. |
| Verification | PID 1 is uvicorn; `docker stop` takes 1 s, exit code 0, log ends "Application shutdown complete". |

### OPS-02 · MEDIUM · Deployment — no production configuration

| | |
|---|---|
| Finding | The only Compose file is the local one: it publishes PostgreSQL on the host, falls back to a development JWT secret and a default database password, and sets `ACADLYTICS_INSECURE_COOKIES=1`. |
| Fix | `docker-compose.prod.yml` override: `APP_ENV=production`, every secret required (`${VAR:?}`), PostgreSQL not published, API and web bound to 127.0.0.1 behind an HTTPS proxy, Secure cookies, restart policies. |
| Verification | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` with an empty env file → exit 1 naming the five missing secrets; with them → no database port, `host_ip: 127.0.0.1` for api and web, `APP_ENV: production`, `ACADLYTICS_INSECURE_COOKIES: "0"`. Not deployed anywhere. |

### UI-01 · MEDIUM · Layout — pages scrolled sideways on a phone

| | |
|---|---|
| Reproduction | Browser crawl at 390 × 844: `/settings` 149 px wider than the screen; content cards in `.g-2` stayed two-up on phones. |
| Fix | `app/globals.css`: below 560 px `.g-2` is one column (KPI tiles stay two-up), list items wrap, the period selector wraps. |
| Regression test | `e2e/mobile.spec.ts` (7 pages, horizontal overflow ≤ 1 px, menu opens). |
| Verification | Playwright (Pixel 7) live PASS. |

### UI-02 · LOW · Navigation — unknown addresses showed the framework's bare 404

| | |
|---|---|
| Fix | `frontend/app/not-found.tsx` in the product's style with *Go to your overview*. |
| Regression test | `e2e/navigation.spec.ts`. Verification: PASS. |

### FE-01 · LOW · API client — the `roster` adapter's type did not match the API

| | |
|---|---|
| Finding | `offeringsApi.roster` declared a paginated `Page<…>`; `GET /offerings/{id}/students` returns a plain list. Unused by any page today, so nothing broke — the first use would have. |
| Fix | Type corrected to the list shape. Verification: typecheck. |

### TEST-01 · MEDIUM · Testing — the web app had no automated tests

| | |
|---|---|
| Fix | Vitest (`npm test`, 21 tests: HTTP client — auth header, one shared silent refresh, retry once, session-lost, error envelope, cache invalidation and per-user isolation; display helpers — missing values never 0) and Playwright (`npm run test:e2e`, 13 browser tests: sign-in/out, wrong password, deep link, role navigation, every sidebar page, not-found, marks grid with zero/absent/missing, CSV import with mapping/exclusion/confirm, unreadable file, faculty isolation, report downloads in 3 formats, intervention, phone layout). CI runs the unit tests. |
| Verification | All pass (numbers in `TESTING_AND_VERIFICATION.md`). |

### TEST-02 · LOW · Testing — no independent check of the analytics numbers on a live stack

| | |
|---|---|
| Fix | `scripts/verify_live.py`: builds its own department, two faculty, two classes and a 10-student cohort designed to hit every boundary (exactly 50 %, slope exactly +5, a genuine 0, absent, exempt, missing), computes every expected value with the Python standard library only, and compares the API. Also hierarchy, deletion guards, imports, interventions, reports, isolation, sessions. |
| Verification | All checks pass live (see `TESTING_AND_VERIFICATION.md`). |

### DOC-01 · LOW · `SECURITY.md` described passwords that no longer exist

It said `FACULTY_DEFAULT_PASSWORD` has a "documented default" and that the README and
`.env.example` contain development passwords. Neither has been true since `ccae1de`. Rewritten.

### DOC-02 · LOW · Docs said the web app has no tests

`frontend/docs/FRONTEND_ARCHITECTURE.md`, `docs/LOCAL_DEMO_GUIDE.md`, the frontend CI comment.
Updated.

### DOC-03 · LOW · The previous audit document printed the leaked passwords

`docs/ACADLYTICS_FINAL_QUALITY_AUDIT.md` §2 quoted both values. Redacted to "former built-in
password 1/2".

## Checked and left as designed (not defects)

| Item | Why it stays |
|---|---|
| Faculty can read the audit log | It is filtered to the offerings they can view (`audit/router.py`); faculty B saw none of class A's rows in the live check. |
| Logout accepts an expired access token when the refresh token is in the body | Intended (preserved, verified live). |
| `ABSENT`, `MISSING`, `EXEMPT`, `0` | Distinct in storage, API, analytics, reports and on screen — verified live and in the browser. |
| R1 / R2 at exactly the threshold | Do not fire (strict `<`); R7 at the pass mark does fire (inclusive band); a slope of exactly +5 is *improving* (inclusive). Verified live. |
| The words "caused" in outcome responses | Appears only in the disclaimer "…does not show that the intervention caused the change". |
