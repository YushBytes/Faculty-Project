# Frontend architecture

Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind 4 (base only), Recharts,
Framer Motion, Lucide, self-hosted Inter and Plus Jakarta Sans. No mock data: every screen reads
the FastAPI backend.

## Layers

| Layer | Files | Rule |
|---|---|---|
| Backend-for-frontend | `app/api/session/{login,refresh,logout}`, `app/api/v1/[...path]` | The refresh token lives only in an httpOnly SameSite=Strict cookie scoped to `/api/session`; `/api/v1/*` is proxied same-origin to `ACADLYTICS_API_URL`. |
| HTTP client | `lib/api/http.ts` | In-memory access token, one silent refresh + retry on 401, backend error envelope → `ApiError`, downloads, upload progress. |
| Adapters | `lib/api/endpoints.ts`, `lib/api/types.ts` | The only place URLs and wire types appear. Pages import adapters, never `fetch`. |
| Session | `lib/auth/session.tsx` | Restores the session, loads `/me/workspace` (role, department, courses coordinated, classes taught, terms, capabilities), holds the academic period, `useScope()` merges period + URL filters. |
| Data | `lib/hooks/use-api.ts` | Keyed loading with stale-response dropping; every view has loading, empty, error and success states. |
| UI kit | `components/ui.tsx`, `components/charts.tsx` | Cards, KPIs, sortable tables, drawers, states; line/area, bar, grouped and stacked bar, histogram, donut, ranking, multi-series matrix, sparkline charts. |
| Views | `components/overview.tsx` | The one dashboard for every level; `variant` changes emphasis, never what is counted. |

## Routes (`app/(app)/…`, all behind the session)

`/dashboard` (role-specific), `/departments[/id]`, `/courses[/id]`, `/sections[/id]`,
`/faculty[/id]`, `/classes[/id]`, `/team`, `/analytics`, `/assessments[/key]`,
`/students[/id]`, `/attention`, `/interventions[/id]`, `/import`, `/reports`, `/admin/users`,
`/admin/structure`, `/audit`, `/settings`. Public: `/`, `/login`.

Filters and period live in the URL (`?year=2025-26&sem=EVEN&course_id=…`) so every view is a
shareable link; the period selector sets the default for the user on that device.

## Design

Light institutional theme: off-white canvas, white surfaces, ink-navy type, one teal accent, a
red→teal performance scale for section tiles, distribution and ranking bars. Body 15.5 px,
tables 14.5 px, metadata ≥ 13 px (dense chart labels 12.5 px). Tokens
are CSS custom properties in `app/globals.css`. Motion is subtle and disabled under
`prefers-reduced-motion`.

UI visibility is never authorisation: the server enforces scope on every request.

## Sign-in and accounts

The sign-in page has an email and a password field and nothing else: no account list, no role
picker, no prefilled credentials. Accounts come from the Administrator (*People*) and from
uploaded TLP reports; see the repository README, "First sign-in".

*Settings → Change password* calls `POST /api/v1/auth/password`. The server revokes every
refresh token of the account, so the page then signs out and returns to `/login?changed=1`.

## States every view has

| State | What is shown |
|---|---|
| Loading | `LoadingDashboard` / skeletons from `components/ui.tsx` |
| Empty | An empty-state card saying what is missing (for example no classes in the period). Never sample numbers or a placeholder chart. |
| Insufficient data | The backend's own `status` / `reason` for the measure (`pctOf`, `Delta` in `lib/format.ts` render "—" with the reason), never a computed fallback |
| Error | `ErrorState` with the server's message and a retry that bypasses the 30-second GET cache |

## Checks

```bash
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm test             # Vitest: tests/*.test.ts (HTTP client, display helpers)
npm run build        # next build
npm run test:e2e     # Playwright: e2e/*.spec.ts in a real browser, against a running stack
```

`npm test` needs nothing running. `npm run test:e2e` needs a throwaway stack and an
Administrator account (`E2E_WEB`, `E2E_API`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`); its global
setup creates its own department, two faculty members, two classes and marks, so it never depends
on or changes other data. See `docs/TESTING_AND_VERIFICATION.md`. The HTTP-level checks
`scripts/e2e_live.py` and `scripts/verify_live.py` complement it. Locally the app is
served on http://localhost:3001 (`WEB_PORT`).
