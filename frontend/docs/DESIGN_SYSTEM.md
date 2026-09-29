# Design system

## Color tokens

| Token | Value | Use |
|---|---|---|
| Canvas | `#08090A` | Public page and application backdrop |
| Surface | `#111418` | Main panels |
| Raised surface | `#181B20` | Inputs and controls |
| Border | `rgba(255,255,255,.085)` | Quiet structure |
| Primary text | `#F4F5F5` | Headings and key values |
| Secondary text | `#9BA2A8` | Descriptions |
| Accent | `#56D7C8` | Main action and selected state |
| Warning | `#F59E0B` | Threshold/review cues |
| Danger | `#EF4444` | Errors only |

The CSS custom properties in `app/globals.css` are authoritative. Teal is a restrained product accent; it does not encode academic performance by itself.

## Type and spacing

Geist is used for interface text. Geist Mono is used for identifiers, dates, percentages, and compact metadata. Keep headings editorial on the landing page and compact/readable in the workspace. Use a 4px base rhythm, with common gaps of 8, 12, 16, 24, 32, 48, and 64px.

## Component principles

Use panels for grouped content, not every item. Prefer clear section headings, quiet dividers, restrained status color, and visible data context. Tables must retain horizontal access on small screens. Controls need labels, keyboard focus, and accessible names. Demo or incomplete backend data must be identified as such.

## Motion principles

Use motion for state feedback and spatial continuity. Avoid looping decoration and large blur/scroll effects. Global reduced-motion preferences remove transitions and smooth scrolling. Preserve information and functionality when motion is disabled.

## Institutional and workspace controls

Use the full SRM Institute of Science and Technology name at login and in workspace/public-page institutional context, with restrained scale. The sidebar semester segmented control supports only Odd Semester and Even Semester and keeps an obvious selected state. Faculty and HOD role badges share the accent outline; role access is UI presentation only. Loading uses layout-shaped shimmer skeletons with low-contrast teal glints, not flat gray placeholders.

## Responsive rules

The workspace sidebar becomes a dismissible drawer on tablet/mobile. Content columns collapse to one column at narrow widths; tables scroll horizontally; primary actions remain available without hover. Maintain readable font sizes and usable touch targets.
