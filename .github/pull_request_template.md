# What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem it solves. Link the issue if there is one: Closes #123 -->

## How it was verified

<!-- Replace the unchecked boxes with what you actually ran. -->

- [ ] `cd backend && pytest`
- [ ] `cd backend && ruff check . && ruff format --check .`
- [ ] `cd frontend && npm run lint && npm run build`
- [ ] Checked by hand in the running app — say which role and which page

## Checks that apply to this change

<!-- Tick what is relevant; delete what is not. -->

- [ ] **Migration.** Schema changes are a new Alembic revision, and no merged migration was edited.
- [ ] **Scope.** New or changed endpoints enforce role scope in the API, and an out-of-scope id
      returns 404 rather than a partial answer.
- [ ] **Analytics semantics.** Absent, exempt and missing stay apart from a real zero. Pass
      percentage counts students who have a result. Insufficient data is reported, not guessed.
- [ ] **One engine.** Any aggregate view calls the class engine's own functions rather than
      recomputing with a second formula.
- [ ] **Imports.** Staging, preview, fix/exclude and atomic confirm are preserved, discard still
      unwinds whatever the file set up, and the action is audited.
- [ ] **Docs.** `README.md` and the pages under `docs/` reflect what this changes.

## Anything a reviewer should look at closely

<!-- Judgement calls, trade-offs, things you are unsure about. -->
