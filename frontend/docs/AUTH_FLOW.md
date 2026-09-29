# Demo authentication and workspace flow

## Demo access

The `/login` screen asks the user to choose Faculty or Head of Department (HOD), then checks the email/password against local demo identities. The credentials are fictional demo-only values and are visible on the login screen:

| Role | Email | Password |
|---|---|---|
| Faculty | `faculty@srmist.edu` | `SRMdemo2026!` |
| HOD | `hod@srmist.edu` | `SRMdemo2026!` |

The password check is local to `components/login-form.tsx`. It issues no JWT, makes no API call, and does not represent production security.

## Faculty flow

Faculty land on the teaching dashboard, scoped to assigned courses, sections, students, assessment records, analytics, attention, interventions, and reports. Navigation keeps the existing routes. The Faculty badge and teaching context remain visible in the shell. Department-wide rollups and HOD overview are not shown to Faculty.

## HOD flow

HOD land on a separate department dashboard with illustrative faculty, section, student, assessment, performance, comparison, and attention summaries. HOD navigation adds a department overview entry and labels department scope. HOD can still use all existing faculty screens. All HOD dashboard figures are mock/demo values, not claims about live SRM records.

## Greeting and dashboard boot

After successful demo sign-in, the session is established and the user sees a short welcome card with name, department, institutional identity, and selected semester. The card fades into a staged boot sequence: connect, load records, process assessments, build insights, prepare attention, and render the dashboard. The complete transition is roughly 2–3 seconds and includes a skip control. Reduced-motion preferences route directly to the dashboard.

## Semester and session persistence

The accessible segmented selector supports only Odd Semester and Even Semester. The chosen semester changes dashboard context and selects a distinct demo summary set. Course/department scope and semester persist alongside the demo role. Remember me stores the demo session in local storage; with it disabled, the session is held in session storage. Sign-out removes both copies. This is presentation state and must not be treated as an authorization boundary.

## Skeleton loading

`components/skeletons/index.tsx` exports text, card, chart, table, metric, avatar, sidebar, and dashboard skeletons. Protected screens use layout-shaped shimmer placeholders while session restoration occurs, and route-level loading files share the same workspace skeleton. Shimmer and boot animations are disabled for reduced-motion users.

## Future JWT integration

Replace local credential matching with the agreed backend login adapter and map the authenticated principal into the stable `DemoUser`-like UI identity (renamed as needed). Preserve the `login`, `logout`, and current-context seam in `lib/auth/session.tsx`, but move production session authority to a reviewed server-side cookie/BFF or other backend-approved token transport. Do not persist refresh tokens in browser storage. Enforce faculty, department, and route scope on the server; role-adaptive navigation is not authorization. Align token refresh, logout, `/auth/me`, error mapping, and CSRF behavior with the backend owner before rollout.
