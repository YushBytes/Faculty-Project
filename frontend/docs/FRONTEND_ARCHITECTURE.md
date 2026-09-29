# Frontend architecture

## Runtime and layout

This frontend uses Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v4, Base UI, Lucide, Recharts, and Geist. Route entry points live under `app/`; workspace screens share `components/layout/app-shell.tsx` and `components/product-page.tsx`. The landing page and sign-in have dedicated compositions.

## Routes

- `/`: product landing page
- `/login`: demo sign-in entry
- `/dashboard`: faculty overview
- `/students` and `/students/[id]`: directory and student record
- `/assessments` and `/assessments/[id]`: assessment list and assessment view
- `/import`: staged import preview experience
- `/analytics`: assessment-level comparisons
- `/attention`: configured-threshold review queue
- `/interventions` and `/interventions/[id]`: action list and outcome timeline
- `/reports`: class summary builder and report history
- `/settings`: workspace preference foundations

Workspace routes use a client-side demo session, with separate Faculty and HOD views. Protected workspace screens redirect to `/login` when no demo session is restored. The sign-in is not a substitute for backend authorization.

## Design system

Design tokens and responsive primitives are in `app/globals.css`. The system uses a charcoal canvas, restrained teal accent, thin borders, compact mono metadata, and clear focus states. Shared buttons, panels, metrics, statuses, data tables, notices, and headings keep the application consistent. Breakpoints adapt the sidebar into a mobile drawer and make wide data tables horizontally scrollable.

## Components and motion

`components/layout/` contains the app shell, role-aware navigation, notices, and page headings. `components/product-page.tsx` composes the shared academic views and Faculty/HOD dashboard variants. `components/login-form.tsx` owns the role picker, demo login, and greeting/boot sequence. `components/semester-selector.tsx` provides the accessible semester switch. `components/skeletons/` provides shimmer layouts for workspace loading. `components/animations/motion-primitives.tsx` provides reusable reveal, mesh, cursor, magnetic, tilt, and counter primitives. The landing-page pinned workflow uses Framer Motion scroll progress without intercepting native scrolling. `components/sections/social-proof.tsx` contains clearly labeled placeholder logos and fictional demo testimonials. Reduced-motion preferences disable ambient animation and replace the pinned scene with a static sequence.

## Demo data and API boundary

Fictional records are defined in `lib/mock/data.ts` and typed in `types/academic.ts`. `lib/api/client.ts` defines the `AcademicDataSource` seam; keep UI DTOs stable and add a real source implementation there when API contracts are ready. Replace demo imports with source-backed data in page loaders or hooks. The import preview explicitly does not parse the selected file.

## Authentication

`lib/auth/session.tsx` isolates UI session state from the API adapter. The Faculty and HOD demo accounts are documented in `AUTH_FLOW.md`; demo auth never contacts the backend. Remembered demo sessions and semester/course context use browser storage. Replace this layer with a reviewed server-backed session/auth adapter when backend auth is ready. Do not store long-lived refresh tokens in browser storage. UI role visibility is not authorization; enforce role and department scope on the server.
