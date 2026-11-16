# Web app ↔ API integration

State on 2026-11-14 (branch `backend`). The web app has no mock layer: there is no mock
client, no fixture file and no fallback data anywhere under `frontend/`. Every number on every
page is a field of a backend response.

## How the browser reaches the API

```
browser ──/api/session/login|refresh|logout──▶ Next.js route ──▶ FastAPI /api/v1/auth/*
        ──/api/v1/*  (Bearer access token) ──▶ Next.js proxy ──▶ FastAPI /api/v1/*
```

- The refresh token is never visible to page scripts: the session routes keep it in an httpOnly,
  SameSite=Strict cookie scoped to `/api/session`. The 15-minute access token is held in memory.
- A 401 triggers one silent refresh and one retry (`frontend/lib/api/http.ts`). Refresh tokens
  rotate; replaying a rotated one revokes the whole session (10-second allowance for two tabs
  refreshing at once).
- The proxy forwards method, query, body and the `authorization` header, and streams the response
  including downloads. Authorisation is entirely the backend's; an out-of-scope id is a 404.
- GET responses are cached in the page for 30 seconds; any write clears the cache.

## Page → API

| Page | Requests |
|---|---|
| `/login` | `POST /api/session/login` → `POST /auth/login`; then `GET /me/workspace` |
| every signed-in page | `POST /api/session/refresh` on load, `GET /me/workspace` |
| `/dashboard`, `/analytics`, `/departments[/id]`, `/courses[/id]`, `/sections[/id]`, `/faculty[/id]`, `/team`, `/assessments` | `GET /insights/overview` with the scope and period filters |
| `/classes` | `GET /insights/offerings` |
| `/classes/[id]` | `GET /offerings/{id}`, `/offerings/{id}/analytics`, `/assessments`, `/results`, `/interventions/outcomes`, `/reports/{kind}`, `/imports/template`; `PATCH /assessments/{id}`; `POST /offerings/{id}/assessments/apply-scheme` |
| `/assessments/[key]` | `GET /insights/assessments/{key}` |
| `/students` | `GET /students`, `GET /insights/overview` |
| `/students/[id]` | `GET /insights/students/{id}` |
| `/attention` | `GET /insights/attention`, `GET /insights/overview` |
| `/interventions`, `/interventions/[id]` | `GET /insights/interventions`, `GET /offerings/{id}/interventions/outcomes` |
| record-intervention drawer | `GET /insights/attention`, `GET /offerings/{id}/assessments`, `POST /offerings/{id}/interventions` |
| `/import` | `POST /tlp-uploads`, `GET /tlp-uploads/{group}`, `POST /tlp-uploads/{group}/confirm`, `GET /imports`, `GET /imports/{id}/preview`, `POST /imports/{id}/fix`, `/exclude`, `/discard` |
| `/reports` | `GET /insights/report`, `GET /insights/reports/history`, `GET /insights/offerings`, `GET /insights/overview` |
| `/admin/structure` | `GET`/`POST /departments`, `/terms`, `/courses`, `/sections`; `PATCH /terms/{id}` |
| `/admin/users` | `GET`/`POST /users`, `PATCH /users/{id}`, `POST /users/{id}/activate`, `/deactivate` |
| `/team` (assignment dialogs) | `POST`/`DELETE /courses/{id}/coordinators`, `POST`/`DELETE /offerings/{id}/faculty` |
| `/audit` | `GET /audit-logs` |
| `/settings` | `POST /auth/password`, `POST /api/session/logout` |

## What was verified, and how

| Check | Result |
|---|---|
| Every route above answers 200 through the proxy for a user in scope | `scripts/e2e_live.py`, 130/130 checks, on a host-run stack and on a clean Docker stack |
| Dashboard figures equal the API and the database | Browser vs `GET /insights/overview` vs SQL on the same stack: 82 students, average 64.74 → "64.7%", pass 75.64 → "75.6%", 59 passed / 19 below / 4 without a score, 20 needing attention, completion 65.32 → "65.3%". Database: 81 present, 6 absent with `score IS NULL`, one real 0. |
| A reload keeps the session | Browser: `POST /api/session/refresh` 200 → `GET /me/workspace` 200 |
| No duplicate requests on a page load | Browser network log on `/attention`: refresh, workspace, overview, attention; one each |
| Console | No messages on the pages opened in the browser |
| Responses never contain NaN or Infinity | The E2E client parses every JSON body with a parser that rejects them |

Pages read in a real browser: `/login`, `/dashboard`, `/settings`, `/sections`, `/reports`, and
`/attention` (network log). The remaining pages were checked for a 200 and for their
API calls over HTTP, not visually. See `ACADLYTICS_FINAL_QUALITY_AUDIT.md` for what that leaves
open.

## Wire-shape notes for anyone writing a client

- `GET /offerings/{id}/students` returns a plain list of enrolments (`{student, status, …}`), not
  a page.
- `GET /assessments/{id}/results` returns `{assessment, counts, rows}`; each row has `state`
  (`present` / `absent` / `exempt` / `missing`) and `result` (`null` when missing).
- Attention flag `R2_FAILED_LATEST` compares against the class pass mark (`pass_mark_percent`)
  and therefore has `threshold: null`; every other rule carries its `threshold`.
- Intervention reasons take persisted flag ids from `GET /insights/attention`
  (`items[].id`), not from the computed flags in `GET /offerings/{id}/attention`.
- The generic per-assessment upload (`POST /assessments/{id}/import`) is fully supported by the
  API; the web app's import page uses the TLP upload (`POST /tlp-uploads`) for all files.
