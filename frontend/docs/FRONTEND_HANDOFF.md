# Frontend/backend handoff

## Current backend facts

The `origin/backend` branch documents `/api/v1`, bearer access tokens, refresh/logout, `/auth/me`, and admin user management. Academic organization, students, assessment records, imports, analytics, attention, interventions, and reports are planned workstreams, not completed contracts in the checked-out backend snapshot. The frontend uses fictional local data for those screens.

## Integration points

- API base URL: `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`); do not put credentials in this variable.
- API adapter seam: `lib/api/client.ts`.
- Mock records: `lib/mock/data.ts`.
- Shared DTO types: `types/academic.ts`.
- Demo sign-in replacement: `components/login-form.tsx` and `lib/auth/session.tsx`. Demo credentials are UI-only and must be removed when connecting production authentication.
- Import preview replacement: `components/import-workflow.tsx` should call the validated parse/stage/preview/confirm API flow once its request and response schemas are published.

## Suggested DTO alignment

The existing backend convention returns paginated lists as `{ items, total, limit, offset }`, UUID IDs, and errors as `{ error: { code, message, details } }`. Build response adapters from those wire DTOs into the stable UI types; preserve server-side paging, faculty scope, and error details. Agree the precise student, assessment, result, threshold, and intervention schemas with the backend owners before connecting these screens.

## Authentication

Backend docs describe login returning short-lived access and opaque refresh tokens in the JSON body, rotating refresh, logout, and `/auth/me`. The current frontend supports demo-only Faculty/HOD role selection, remember-me behavior, session restoration, and role-adaptive screens. Replace the demo login at the isolated auth/session boundary. Decide with the backend owner whether the production browser app uses a same-site secure cookie/BFF or another reviewed token transport before implementation. Enforce role/faculty/department scope on the server; UI route hiding is not authorization. See `AUTH_FLOW.md`.

## Safe integration edits

Backend integration should focus on `lib/api/`, the auth/session layer, environment configuration, typed adapters, and swapping the mock source. Keep transformations at the adapter boundary when server DTOs differ from the view models.

## UI-owner review

Ask the frontend owner before changing `components/ui/`, `components/animations/`, chart styling, `components/layout/`, shared design tokens, or major page compositions. Keep backend source, migrations, tests, and configuration outside this frontend handoff.
