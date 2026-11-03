# ACADLYTICS documentation

Start with the [repository README](../README.md) to run the system and sign in. These pages are
the detail behind it.

## Reference

| Page | What it answers |
|---|---|
| [`DATA_MODEL.md`](DATA_MODEL.md) | Every table, its columns and the constraints that hold the academic hierarchy together. Read this before writing a migration. |
| [`IMPORT_FORMAT.md`](IMPORT_FORMAT.md) | The SRM TLP5 report layout as the parsers read it — the title block, the summary block, and what each field becomes. |
| [`ANALYTICS_SPEC.md`](ANALYTICS_SPEC.md) | Every metric, its exact formula, the seven attention rules and their thresholds, and the semantics that never bend. |
| [`ANALYTICS_CONTRACT.md`](ANALYTICS_CONTRACT.md) | What the platform layer guarantees to the analytics layer: the stored fields, the queries available, and the contracts C1–C12. |

## Architecture and history

| Page | What it answers |
|---|---|
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Scope, the data limitations the design works around, contracts C1–C12, recorded decisions and risks. The reasoning behind the shape of the system. |
| [`LAYER_OWNERSHIP.md`](LAYER_OWNERSHIP.md) | The boundary between the platform layer and the analytics layer — which owns which module, formula and decision, and how a change crosses it. |
| [`../frontend/docs/FRONTEND_ARCHITECTURE.md`](../frontend/docs/FRONTEND_ARCHITECTURE.md) | How the web app is laid out: pages, typed API adapters, session handling. |

## Source material

[`reference/`](reference) holds the original ACADLYTICS project blueprint (50 pp.) the system was
specified from, as PDF and extracted text. Where the blueprint and the delivered scope disagree,
`PROJECT_CONTEXT.md` §11–§12 records which won and why.

## The rules that do not bend

These are specified in `ANALYTICS_SPEC.md` and enforced throughout the code. A change that bends
one of them needs the spec changed first:

- Absent, exempt and missing are never a zero — in storage, analytics, charts or exports.
- Pass percentage is over students who have a result; absence is reported as completion.
- A trend without enough assessments reports insufficient data rather than guessing.
- Attention is seven explained rules, never a score.
- Intervention outcomes are observations, never causes.
- An aggregate view calls the class engine's own functions over more students — never a second
  formula for a wider scope.
