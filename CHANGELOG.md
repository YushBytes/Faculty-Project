# Changelog

What was built, in the order it was built. The project has no tagged releases yet, so this is a
development log rather than a list of versions; `git log` is the authority for detail.

Dates are the dates of the work.

## Unreleased

### Engineering audit and hardening — 2026-11-16

- Security: the last account that still accepted a leaked former password was rotated; sign-in is
  throttled per account (10 failures / 15 min → 429 with `Retry-After`); uploaded file names are
  reduced to their last path segment.
- Import: column mapping in the review drawer (an unmatched column no longer dead-ends the
  import); excluded rows stay in the review list so they can be included again; discard errors
  are shown.
- API: an unknown report format is a 422 validation error, consistent with `/insights/report`.
- Docker and deployment: pinned dependency versions (`backend/constraints.txt`), offline code-only
  rebuilds, graceful API shutdown (`exec uvicorn`), `docker-compose.prod.yml` (required secrets,
  no published database, 127.0.0.1 behind HTTPS, Secure cookies).
- Web: one-column cards on phones, a branded not-found page, corrected `roster` adapter type.
- Tests: Vitest (21) and Playwright (13) for the web app; `scripts/verify_live.py`, an independent
  live verifier (228 checks); 22 new backend tests (1,974 total). CI runs the frontend type check
  and unit tests and installs pinned versions.
- Docs: `FINAL_ENGINEERING_AUDIT`, `BUG_REGISTER`, `TESTING_AND_VERIFICATION`, `SECURITY_AUDIT`,
  `DEPLOYMENT_READINESS`, `KNOWN_LIMITATIONS`; README, `SECURITY.md`, local guide updated.

### Local release candidate — 2026-11-14

- No built-in passwords and no demo sign-in: the first Administrator comes from
  `ACADLYTICS_ADMIN_EMAIL` / `ACADLYTICS_ADMIN_PASSWORD`; start-up no longer creates a department,
  HOD or Academic Head; faculty accounts from TLP reports need a password set in *People*.
- Self-service password change (`POST /auth/password`, *Settings → Change password*).
- Default local ports 3001 (web), 8000 (API), 55432 (PostgreSQL); API health check in Compose.
- `scripts/e2e_live.py`, a live end-to-end check of a running stack (130 checks).
- `docs/LOCAL_DEMO_GUIDE.md`, `docs/INTEGRATION_AUDIT.md`,
  `docs/ACADLYTICS_FINAL_QUALITY_AUDIT.md`.

### Repository and documentation — 2026-11

- MIT licence, `CONTRIBUTING.md`, `SECURITY.md` and a documentation index at `docs/README.md`.
- GitHub issue templates, a pull request template, and a frontend CI workflow (lint + build)
  alongside the existing backend workflow.
- `.gitattributes` now declares binary formats explicitly, so a PDF or spreadsheet added later
  cannot be silently corrupted by line-ending normalisation.
- The development docs were rewritten in neutral engineering terms: `TEAM_OWNERSHIP.md` became
  [`LAYER_OWNERSHIP.md`](docs/LAYER_OWNERSHIP.md) and `AGENT_2_ANALYTICS_CONTRACT.md` became
  [`ANALYTICS_CONTRACT.md`](docs/ANALYTICS_CONTRACT.md). No technical content changed.

### Integration and polish — 2026-09-30 to 2026-10-08

- The whole platform starts **empty**. Semesters, courses, sections, students, faculty and marks
  are created from uploaded TLP reports; only the sign-in accounts are bootstrapped.
- Integrated web app: real authentication, five role-specific workspaces, the TLP import
  interface, analytics pages and report downloads.
- Section resolution from existing student placement, then the file name, then the user.
- Course coordinator demo logins exposed for the walkthrough.
- Session race fix, faster institution overview, period labels, resilient container builds, and a
  Docker layer that caches API dependencies separately.

### Analytics and intelligence — 2026-09-26 to 2026-09-29

- Core statistical analytics: average, median, standard deviation, pass/fail/completion,
  ten-band distribution and SRM six-band ranges.
- Student performance intelligence, class intelligence and what-changed comparisons.
- The attention engine: seven explained rules (R1–R7) with severities, thresholds resolved from
  department settings and per-class overrides, and flags persisted with their evidence.
- Interventions with observed outcomes, reported against a peer group and never claimed as cause.
- Reporting and export: five class reports and three scope reports in PDF, Excel and CSV.
- Deterministic insights, and aggregate views pooled from one materialised result per class so a
  department average is the class definition over more students.
- Attention flags and interventions persisted in their own tables; a flag that stops firing is
  resolved rather than deleted, so history survives a recompute.

### Platform and data foundation — 2026-09-26 to 2026-09-29

- Phase 1: FastAPI skeleton, configuration, SQLAlchemy session, Alembic baseline, `/health`,
  Docker Compose, and a pytest suite that runs against real PostgreSQL.
- Phase 2: users and authentication — Argon2 hashing, JWT access tokens, rotating refresh
  tokens, role-based access control.
- Phase 3: departments, terms, courses, sections and offerings, faculty assignment, and
  server-side offering scope.
- Phase 4: students, section history, enrolments, and student bulk import.
- Phase 5: assessments, assessment-level results, department settings, audit log, recompute hook.
- Phase 6: the marks import pipeline — stage, preview, fix/exclude/map, atomic confirm.
- Phase 7: audit-log API, seed and demo data, the analytics contract and platform docs.
- The five-role hierarchy, SRM TLP ingestion, aggregate analytics, and a 97-section demo
  institution.
- Backend and frontend merged into one repository with one module tree, one router list, one
  model registry and one test suite.
- Integration, security and schema hardening, and an end-to-end reconciliation against a real
  teacher dataset.
