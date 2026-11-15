# ACADLYTICS — known limitations

What the system does not do, or does only partly, as of 2026-11-16. Each line says whether it is
a scope decision (by design), a gap that could be closed, or something unmeasured.

## Data and analytics (by design)

| Limitation | Why |
|---|---|
| Assessment-level marks only; no question- or topic-level analytics, difficulty or discrimination indices | Real faculty sheets carry one mark per assessment. Inventing a question layer would fabricate data (`PROJECT_CONTEXT.md` §3, DECISION-1). |
| No prediction, risk score, ML or LLM output | Every number must trace to stored marks, a configured threshold and a named rule. |
| Intervention outcomes are observations, never causes | Students are chosen because they struggle; there is no randomisation or control group. Responses and reports say so. |
| Trends need ≥ 2 completed assessments, consistency ≥ 3, group labels n ≥ 5 | Below that the API answers "insufficient data" rather than a guess. |
| Raw percentages are compared across assessments of different difficulty | A hard test makes a class look like it declined. The caveat is in comparison outputs; standardised scores were deferred. |
| No attendance, no student login, no grade bands | Out of the delivered scope (`PROJECT_CONTEXT.md` §11). |

## Product gaps (could be closed)

| Gap | Today | Severity |
|---|---|---|
| Password reset by email / invitation link | An Administrator or HOD sets the password in *People*; no forced change at first sign-in | MEDIUM |
| Per-assessment generic upload in the web app | The API has `POST /assessments/{id}/import`; the web import page uses the TLP/offering pipeline (which accepts plain sheets and the offering template, and now supports column mapping) | LOW |
| Editing a single mark in the web app | Marks change by re-importing (audited) or `PUT /assessments/{id}/results` via the API; there is no inline cell editor | LOW |
| Student create/edit screens | Students are created from TLP reports or `POST /students[/bulk|/import]`; the web app lists and profiles them but has no edit form | LOW |
| Department threshold settings | Stored and used by analytics (`/departments/{id}/settings`), but no screen to edit them; any signed-in user can read them (deliberate) | LOW |
| Throttle state is per process | Fine with the single uvicorn process the image runs; use a proxy limit if scaled out | LOW |
| Fictional-data generators live in the application package | `app/seed.py`, `app/demo/` — explicit CLI only, refused in production and on non-empty databases; tests depend on them | LOW |
| Former built-in passwords remain in Git history | No account accepts them; rewrite needs your decision (`SECURITY_AUDIT.md` §5) | HIGH until decided |

## Unmeasured

| Item | State |
|---|---|
| Performance at institutional scale | Single-request timings on tens of students only. No load test. |
| Browser coverage | Playwright ran on Chromium (desktop 1440×900 and Pixel 7 emulation). Firefox, Safari and real phones were not tested. |
| Accessibility | Roles, labels and keyboard focus were used by the browser tests (they select by role and label), but no screen-reader or WCAG audit was run. |
| Cloud deployment | Not performed. `docker-compose.prod.yml` is reviewed configuration, not a proven deployment. |
| Dependency vulnerabilities | No CVE scan triaged (`npm audit` reports advisories in the dev toolchain). |

## Environment notes (this machine)

- The repository sits inside OneDrive; virtualenvs and `node_modules` there are synced and can be
  locked by OneDrive. Docker volumes are not affected.
- `backend/.venv/Scripts/alembic.exe` exits silently on this machine; `python -m alembic` works.
- A leftover database `acadlytics_tlp_check` from earlier work is in the local PostgreSQL; it was
  not created or touched in this audit.
- The PyPI connection from Docker builds was intermittent during this audit (read timeouts);
  `constraints.txt` and the cached dependency layer reduce how often that matters.
