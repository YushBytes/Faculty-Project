# ACADLYTICS — security audit

Date: 2026-11-15/16. Branch `backend`. This is an application security review with live tests
against an isolated stack, not a penetration test by an independent party and not a
certification. What was not tested is listed in §7.

## 1. Threat model in one paragraph

The system holds student register numbers, names and marks. The people who must not see a given
mark are other faculty, other departments and anyone unauthenticated. The main risks are
therefore: an authorisation escape (IDOR) between faculty or departments; account takeover
(guessable, leaked or default passwords, token theft); a crafted upload that writes marks without
review or crashes the parser; and deployment mistakes (default secrets, plain HTTP, exposed
database).

## 2. Authentication and sessions

| Control | How it works | Evidence |
|---|---|---|
| Passwords | Argon2id (`argon2-cffi`), 8–128 characters, rehash on parameter change; a dummy hash is verified for unknown emails so timing does not reveal accounts | `core/security.py`; `test_auth_api.py::test_wrong_password_and_unknown_email_look_identical` |
| No default credentials | No built-in password in code, Compose, `.env.example` or docs. The first Administrator only from `ACADLYTICS_ADMIN_PASSWORD`; faculty created from reports get a random unknown password | `test_bootstrap.py`, `test_tlp_provision.py` |
| Access token | HS256 JWT, 15 minutes, in browser memory only; the role inside it is never trusted — the user is re-read from the database on every request, so deactivation and role changes apply at once | `auth/dependencies.py`; live: deactivated user's existing token → 401 at once (`verify_live.py`) |
| Refresh token | Opaque, 48 random bytes, only its SHA-256 stored, rotated on every use, 7 days. Lives in an httpOnly, SameSite=Strict cookie scoped to `/api/session`; page scripts cannot read it | live: `document.cookie` has no refresh token (`e2e/auth.spec.ts`) |
| Reuse detection | A rotated token presented again (after a 10 s race allowance) revokes the whole session family | `test_auth_api.py`; `e2e_live.py` |
| Logout | Revokes the session family; accepts the refresh token in the body even when the access token has expired (intended) | live 204, then refresh → 401 |
| Password change | Verifies the current password, revokes every session of the account, audited | `test_auth_api.py`; `e2e_live.py` |
| Administrator reset | `PATCH /users/{id}` with `password` revokes the user's sessions, audited | `users/service.py` |
| **Brute force (new)** | 10 wrong passwords for one email in 15 minutes → 429 with `Retry-After` until the window passes, correct password included; unknown emails throttled identically | `core/throttle.py`; `tests/test_login_throttle.py` (9 tests). Before: 50 wrong then the right one → 200 (live) |
| CSRF | The API authenticates with a Bearer header, which a cross-site form cannot set. The only cookie is SameSite=Strict and scoped to `/api/session` (login/refresh/logout) | design |
| CORS | No CORS middleware: the API is not meant to be called cross-origin; the browser reaches it only through the same-origin Next.js proxy | `main.py` |

**Throttle limits (accepted):** state is per API process (the image runs one uvicorn process; with
several, add a proxy rate limit — `DEPLOYMENT_READINESS.md`). Someone who knows an email can
keep that account locked for 15 minutes at a time by failing on purpose; the window does not
grow, and an administrator can reset the password.

## 3. Authorisation

Scope is resolved server-side in one module (`organization/scope.py`) and applied by every
offering-level service; an out-of-scope id answers **404** (existence not disclosed), visible but
not administrable answers 403.

Live test with two faculty members, one class each (`scripts/verify_live.py`, faculty B reading
class A): 15 GETs — class, analytics, attention, insights, roster, assessments, results matrix,
interventions, outcomes, student profile, assessment, assessment results, student, student
overview, import template — **all 404**. Writes — results upsert, assessment edit and delete,
assessment create, intervention, upload, report download, import batch read/preview/confirm —
**all 404**. B's class list, student list (6 of 6, none of A's) and attention list contain nothing of
A's. Faculty → `/users` 403; create user / department / recompute 403. HOD of the department sees
both classes. In the browser (`e2e/scope-and-reports.spec.ts`): faculty B opening A's class or
student sees *Not found or not in your scope*; their lists show only their own section.

Existing suite: `tests/security/test_authorization_idor.py` and `test_security.py` cover the five
roles across departments and courses.

**Accepted LOW:** `GET /departments/{id}/settings` (analytics thresholds) is readable by any
signed-in user — a deliberate, tested decision. Writing is restricted to the department's managers.
If you prefer it scoped, it is a two-line change in `assessments/router.py`; the test
`test_settings_api.py::test_write_permissions` would change with it.

## 4. Input and uploads

| Check | Result |
|---|---|
| SQL injection | All queries are SQLAlchemy expressions with bound parameters; a search string with SQL is matched as text and returns nothing (`test_input_security.py`) |
| XSS | React escapes all text; no `dangerouslySetInnerHTML` in the app. An intervention note containing `<script>` is stored and shown as text (live) |
| Validation | Every request body is a Pydantic model with `extra="forbid"`; invalid UUID → 422; malformed JSON → 422 |
| Error leakage | Unhandled errors return a generic 500 envelope; validation errors list location and reason, never the submitted value (`test_input_security.py`, now also for report formats) |
| Upload type | Detected from the bytes, not the name: `.xlsx`, UTF-8 CSV, SRM TLP text PDF only. Malformed workbook, non-UTF-8 text, unsupported type, empty file → refused with a reason, nothing stored (live and `test_upload_security.py`) |
| Upload size | 5 MB, 5,000 rows, 200 columns, each tested at the limit and one over; 5 MB + 1 refused live |
| Zip bombs / formulas | Workbooks are read with openpyxl read-only, values as strings; formulas are not evaluated |
| File names | Now reduced to the last path segment without control characters (SEC-04) |
| Writes before review | Impossible: nothing reaches `assessment_results` until confirm, which re-validates and is one transaction (`test_import_atomicity.py`; live: confirm with errors → 422, 0 rows) |

## 5. Secrets

| Item | State |
|---|---|
| `.env` | Gitignored; never committed (`git log --all -- '*.env'` empty) |
| Tracked files | No API keys, tokens or real passwords. `JWT_SECRET_KEY` in `docker-compose.yml` has a development fallback, which the application **refuses** when `APP_ENV=production`; `docker-compose.prod.yml` requires a real one |
| Former built-in passwords | **Public in Git history** (7 and 5 commits). In current files only as refused values in tests. No account in the running database accepts them (SEC-01 rotated the last one) |
| Local backups | `~/acadlytics-backups/acadlytics-pre-cleanup-2026-11-14.dump` (outside the repo) contains student names and marks — keep it off shared storage, delete when no longer needed |

### Git-history remediation plan (needs your approval — not done)

Rewriting history replaces every commit hash after the first leak and requires a force-push of
`main` and `backend`. Everyone with a clone must re-clone or hard-reset; open pull requests break.

1. Agree a time with everyone who has cloned `YushBytes/Faculty-Project`; ask them to push or
   discard local work first.
2. Make a mirror backup: `git clone --mirror https://github.com/YushBytes/Faculty-Project.git backup.git`.
3. In a fresh mirror clone, write the two values (one per line, `literal:<value>==>REDACTED`) to a
   file kept outside the repository, and run
   `git filter-repo --replace-text <that file>` (git-filter-repo; or BFG `--replace-text`).
4. Check: `git log --all -S<value>` is empty for both; run the backend suite.
5. `git push --force --mirror`; ask GitHub Support to purge cached views of old commits if the
   values must disappear from the web UI as well.
6. Everyone re-clones. Rotate anything else that ever shared those values.

Because the values no longer open any account (verified), the rewrite reduces disclosure; it does
not close an active hole. Whether it is worth the disruption is your call.

## 6. Deployment-dependent controls

HTTPS, Secure cookies, secret storage, database exposure, proxy rate limits and backups depend on
how the system is deployed. `docker-compose.prod.yml` sets the safe defaults and refuses to start
without secrets; `DEPLOYMENT_READINESS.md` lists what the host must provide.

## 7. Not tested

- No independent penetration test, fuzzing campaign or dependency CVE scan was run
  (`npm audit` reported advisories in development dependencies during install; not triaged here).
- Denial of service beyond the upload limits (many concurrent large uploads, slow clients).
- TLS configuration, headers (HSTS, CSP) — they belong to the reverse proxy, which does not exist yet.
- Multi-process deployment of the throttle.
