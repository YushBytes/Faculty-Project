# Navigation, roles and sign-in

What each role sees, where every page lives in the sidebar, how the sign-in role choice works, and
the single-Administrator rule. Implemented 2026-11-16; the routes, pages, dashboards and the
analytics engine are unchanged — only the grouping, a few additions and wording changed.

UI visibility is never access control: every page reads the API, and the API enforces scope on
every request (`backend/app/modules/organization/scope.py`, `users/service.py`).

## 1. Sidebar groups and every route

Source: `frontend/lib/nav.ts`. Pinned by `frontend/tests/nav.test.ts`, which checks that each role
reaches exactly the destinations it reached before the regrouping.

| Group | Page (label) | Route | Shown to |
|---|---|---|---|
| Home | Overview — the existing role-specific dashboard | `/dashboard` | everyone |
| Academic Management | Departments | `/departments` (+ `/departments/[id]`) | Administrator |
| | Courses / My courses / Course portfolio | `/courses` (+ `/courses/[id]`) | everyone except Faculty |
| | Sections | `/sections` (+ `/sections/[id]`) | everyone except Faculty |
| | Classes / My classes | `/classes` (+ `/classes/[id]`) | everyone |
| | Faculty | `/faculty` (+ `/faculty/[id]`) | everyone except Faculty |
| | Team & roles / Coordinators | `/team` | Administrator, HOD, Academic Head |
| Performance Intelligence | Analytics | `/analytics` | everyone |
| | Assessments | `/assessments` (+ `/assessments/[key]`) | everyone |
| Student Support | Students | `/students` (+ `/students/[id]`) | everyone |
| | Attention | `/attention` | everyone |
| | Interventions | `/interventions` (+ `/interventions/[id]`) | everyone |
| Data & Imports | Import TLP marks (staging, review, confirm, **import history**) | `/import` | everyone (files route only into classes in scope) |
| Reports | Reports | `/reports` | everyone |
| Administration | People | `/admin/users` | capability `manage_users` (Administrator, HOD, Academic Head) |
| | Academic structure | `/admin/structure` | Administrator |
| | Audit log | `/audit` | capability `view_audit` (Administrator, HOD, Academic Head) |
| Sidebar footer | Settings | `/settings` | everyone |
| (public) | Landing, Sign in, not-found | `/`, `/login`, unknown URLs | — |

Detail pages (`[id]`, `[key]`) are reached from their list pages and from links inside the
dashboards, exactly as before. No page is orphaned. A group with nothing for the role is not shown
(Faculty and Course Coordinators see no Administration group).

Each sidebar link has a one-line tooltip (`title`) saying what the page is for.

## 2. Role workspaces

The dashboard (`/dashboard`) was already different per role and is unchanged. The new
**quick actions** row above it (`frontend/components/quick-actions.tsx`) links only to pages the
role already reaches from the sidebar:

| Role | Dashboard (unchanged) | Quick actions |
|---|---|---|
| Faculty | "What is happening in my classes and with my students?" | My classes · Upload TLP · Analytics · Review attention · Reports |
| Course Coordinator | the coordinated courses across every section | My courses · Sections · Faculty · Course analytics · Reports |
| Academic Head | the course portfolio | Course portfolio · Coordinators · Faculty · Analytics · Reports |
| HOD | the department | Department overview (`/departments/<own>`) · Department analytics · Review attention · Interventions · Faculty · Reports |
| Administrator | the whole institution (never filtered to a department) | Manage users · Departments · Institution analytics · Imports · Audit log |

Contextual help: Attention and Analytics have a collapsed **How it works** note
(`components/how-it-works.tsx`) that describes what the engine does without restating any number
it owns. List pages that used to fall back to "Nothing to show yet" now say what is missing and
what to do: Classes (role-aware: a faculty member is told classes appear when assigned), Courses,
Sections, Faculty, Departments, Team, Audit log and People.

## 3. Welcome tour

`frontend/components/tour.tsx`. Four or five steps per role, in a small card in the corner — no
overlay and no focus trap, so the page stays usable behind it. *Skip tour*, *Back*, *Next*, *Done*
and Escape all work. Completion is remembered per user on that device in `localStorage`
(`acadlytics.tour.v1.<user id>`), the same pattern as the remembered academic period; there is no
backend state. *Settings → Replay tour* shows it again. Steps only mention destinations the role
has (e.g. the HOD's *People* step only when `manage_users` is true).

## 4. Sign-in role confirmation

The sign-in page shows five checkbox-style options — Faculty, Course Coordinator, Academic Head,
HOD, Administrator. They are a radio group underneath (one choice, arrow keys move it), styled as
checkboxes. *Sign in* stays disabled until one is chosen.

| Layer | Behaviour |
|---|---|
| Website (`app/api/session/login/route.ts`) | `role` **required** and must be one of the five values (else 422 before the API is called). Only email, password and role are forwarded. |
| API (`POST /api/v1/auth/login`) | `role` **optional** — existing scripts, tools and clients that omit it keep working. Unknown or malformed values are 422; other unknown fields are still 422 (`extra="forbid"`). |
| Check (`auth/service.py`) | Password and active account are verified first. Only then, if a role was sent, it must equal the stored role. A mismatch is **401 `role_mismatch`**, **no tokens are issued**, and it counts as a failed attempt for the sign-in throttle. |
| Messages | Wrong password, unknown email, inactive account: the existing generic message, whatever role was chosen. Correct password, wrong role: "The selected role does not match your account. Please choose your assigned role." — so only someone who already has the password learns anything. |
| Permissions | Never taken from the choice. Tokens are built from the stored user; every request re-reads the user from the database (`auth/dependencies.py`), so a role in a request body or token claim grants nothing. |

Tests: `backend/tests/test_login_role.py` (all five roles × every wrong role, no tokens on
mismatch, faculty claiming ADMIN, smuggled fields, unknown and malformed values, inactive account,
throttle, no-role compatibility, refresh/logout), `test_auth_api.py::test_a_role_field_cannot_elevate`,
`frontend/tests/http.test.ts`, `frontend/e2e/login-role.spec.ts`, and checks in
`scripts/e2e_live.py` and `scripts/verify_live.py`.

## 5. Exactly one active Administrator

| Safeguard | Where |
|---|---|
| Creating, promoting or reactivating a second active Administrator is refused (409) | `users/service.py::_check_single_admin` |
| The Administrator cannot deactivate or demote themselves; the last active Administrator cannot be deactivated or demoted | `users/service.py::_guard_last_admin` |
| **Database:** at most one active `ADMIN` row — two concurrent writes cannot both succeed | partial unique index `uq_users_single_active_admin` (`role` WHERE `role = 'ADMIN' AND is_active`), migration `0009` |
| A concurrent second creation surfaces as the same 409 | `write_guard` maps the unique violation; message "There is already an active Administrator; there can be only one." |
| Two API processes bootstrapping an empty database | the loser's copy is refused by the index and treated as "already done", not a start-up failure (`app/bootstrap.py`) |
| The UI never offers Administrator as a role for anyone else; the Administrator's own role is shown fixed | `admin/users/page.tsx::roleOptions` |
| Institution-wide access | `scope.py::visible_offerings` (ADMIN → everything), thresholds `None` = all departments, audit log unfiltered |

Tests: `backend/tests/test_single_administrator.py` — API rules, the index directly, inactive
Administrators not counting, and three **real-concurrency** tests (two simultaneous creations, two
simultaneous promotions, two simultaneous bootstraps) on separate committed transactions in the
isolated test database. With the index removed, the two concurrency tests produce two active
Administrators; with it, exactly one.

**No handover.** There is no operation that transfers the Administrator role to someone else: the
Administrator cannot demote themselves, a second active Administrator cannot exist, and the last
one cannot be deactivated. Replacing the Administrator today requires direct database access by
an operator. A secure transfer workflow is a separate, not-yet-designed feature
(`KNOWN_LIMITATIONS.md`).
