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
| UI kit | `components/ui.tsx`, `components/charts.tsx` | Cards, KPIs, sortable tables, drawers, states; line/area, bar, histogram, donut, ranking, heat map, sparkline charts. |
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
red→teal performance scale for heat maps. Body 15.5 px, tables 14.5 px, metadata ≥ 13 px. Tokens
are CSS custom properties in `app/globals.css`. Motion is subtle and disabled under
`prefers-reduced-motion`.

UI visibility is never authorisation: the server enforces scope on every request.
