# Removing the former built-in passwords from Git history

Status 2026-11-16: **prepared and rehearsed; nothing force-pushed.** Step 4.1 (updating `main`) was
approved and done: `main` is `f8f91f3`, a normal merge with the same tree as `backend`. The
force-push (4.4) still needs your explicit approval.

The two passwords were built into early versions (bootstrap, CLI, Compose, `.env.example`,
README, tests). Since `ccae1de` no code uses them, since SEC-01 no account accepts them, and since
`5ac8937` no current file contains them. They remain readable in the history of a **public**
repository.

## 1. What was inspected

| Item | Finding |
|---|---|
| First commit containing either value | `01beeef` (2026-09-26) |
| Where in history | 14 files over the project's life (README, `.env.example`, `docker-compose.yml`, `backend/app/{bootstrap,cli,core/config}.py`, four test files, `scripts/e2e_live.py`, three docs). Commit **messages**: none |
| GitHub branches affected | `main`, `backend` |
| Not affected | `frontend/nachiketa-ui` (keeps its hash); there are no tags |
| Local-only branch affected | `release/local-rc` (in your working copy only; not on GitHub) |
| Commits that get new hashes | every descendant of `01beeef` on those branches (36 of the 47 on GitHub) |
| GitHub repository | public; **0 forks**; **no pull requests**, so no `refs/pull/*` that GitHub would keep pointing at old commits; no branch protection |
| People with write access | the owner and **3 collaborators** (see the repository's *Settings → Collaborators*) |

### A finding that must be fixed first: `main` still ships the old code (SEC-06)

`main` — GitHub's **default branch**, the one people clone — is 10 commits behind `backend`. Its
tip (`07e5258`, 2026-11-03) still has the built-in passwords in **runtime code**: the bootstrap
default for the first accounts, the CLI's demo-password fallback, the Compose default and
`.env.example`. Anyone who clones the default branch and starts it gets accounts with a publicly
known password.

If the history were rewritten as it stands, those lines would become `"***REMOVED***"` — a new,
equally well-known default. So **`main` must receive the current code before the rewrite.**

Tested locally (worktree, nothing pushed): merging `backend` into `main` has no conflicts and the
result is **byte-for-byte the same tree as `backend`** — `main`'s own two commits
(`e485b98` architecture audit, `07e5258` merge) add no content that `backend` lacks.

## 2. Backups (taken, verified)

In `~/acadlytics-git-history/` (outside the repository and outside OneDrive; private):

| Backup | What | Verified |
|---|---|---|
| `backup-mirror.git` | `git clone --mirror` of GitHub (all branches) | `fsck` clean |
| `backup-github-2026-11-16*.bundle` | single-file bundles of that mirror | `git bundle verify` ok; restoring one reproduces every reference hash exactly |
| `backup-local-repo-2026-11-16.bundle` | your working repository's branches, including the local-only `release/local-rc` | `git bundle verify` ok |
| `refs-before*.txt` | every reference and its commit hash before any change | — |

The bundles hold the full history, including the passwords — keep them private like the database
dumps.

## 3. The rewrite (rehearsed)

Tool: `git-filter-repo` 2.47 (installed into `~/acadlytics-git-history/tools`, not the project).
Method: `--replace-text` with a private list (`replacements.txt`, the two values →
`***REMOVED***`), run on a **fresh copy** of the backup — never in the working repository, and the
copy has no remote, so it cannot be pushed by accident. The whole run is scripted in
`~/acadlytics-git-history/rewrite.sh` (refresh backup → rewrite → verify → print the push command;
it never pushes).

Rehearsal results (with `main` merged locally to simulate step 4.1):

| Check | Result |
|---|---|
| Commits still containing either value, any branch | **0** (also 0 by `git log -S`) |
| Commit messages containing either value | 0 |
| `git fsck --full` | 0 problems |
| Commits | 47 → 47 (48 in the rehearsal, which adds the local merge) |
| Authors, e-mails, dates, messages | identical (checked without the rehearsal merge) |
| `backend` tip | **same tree as before** — only history changes |
| `main` tip after the merge | same tree as `backend`; no placeholder in any runtime file |
| `frontend/nachiketa-ui` | unchanged hash |

## 4. Steps that need your approval

### 4.1 Bring `main` up to date (normal push — no force) — approval 1

```bash
git switch main && git pull --ff-only origin main
git merge --no-ff origin/backend -m "Merge backend: current platform (no built-in passwords)"
git push origin main
git switch backend
```

This is worth doing even if you decide against the rewrite: it stops the default branch from
shipping known passwords.

### 4.2 Tell the collaborators, then freeze — before approval 2

Message to the three collaborators (and anyone else with a clone):

> On <date/time> the history of `main` and `backend` will be rewritten to remove two old
> passwords. Push or save your work before <time>. Afterwards, do not push from your old clone:
> re-clone the repository, or on each branch run `git fetch origin && git reset --hard
> origin/<branch>` after saving local changes. Local branches based on old commits need
> `git rebase --onto origin/<branch> <old-base>`.

No one pushes between the start of 4.3 and the end of 4.4.

### 4.3 Final run (no push)

```bash
cd ~/acadlytics-git-history && bash rewrite.sh      # takes a fresh backup, rewrites, verifies
```

It must end with `VERIFIED. Nothing has been pushed.` and print the push command.

### 4.4 Force-push — approval 2 (the irreversible step)

```bash
cd ~/acadlytics-git-history/rewrite.git
git push --force --mirror https://github.com/YushBytes/Faculty-Project.git
```

`--mirror` pushes exactly the rewritten branches (`main`, `backend`, `frontend/nachiketa-ui`, the
last unchanged). Then check `git ls-remote` against `refs-after-*.txt`, and confirm on GitHub that
the old commit URLs of the affected files no longer show the values in the branch views.

### 4.5 Afterwards

- Your working copy: save nothing local first (it is clean), then
  `git fetch origin && git switch backend && git reset --hard origin/backend`, the same for `main`;
  delete `release/local-rc` or rewrite it (it is only local; its commits are in the backup bundle).
- Collaborators re-clone (4.2).
- Optional: ask GitHub Support to remove cached views of the old commits
  (*Support → "Remove cached views"* with the list of old hashes from `refs-before-*.txt`).
- CI runs on the push; the suite is unchanged (the `backend` tree is identical).

## 5. Impact and limits

- **Collaborators:** every existing clone keeps the old history and diverges from GitHub; pushing
  from an old clone would reintroduce the old commits. Hence the freeze and re-clone.
- **Links:** links to old commit hashes (in chats, issues, docs) stop resolving to the branch
  history. `CHANGELOG.md` and the audit documents name a few old hashes (`2b18ff3`, `ccae1de`,
  `b6edfd5`…); they will refer to commits that exist only in the backups.
- **What a rewrite cannot do:** anyone who already cloned or downloaded the repository still has
  the values, and they are already public. The rewrite reduces further disclosure; it does not
  make the values secret again. That is acceptable only because they no longer open any account.

## 6. Rollback

If something goes wrong after the force-push, restore GitHub exactly as it was:

```bash
git clone --mirror ~/acadlytics-git-history/backup-github-2026-11-16.bundle restore.git
cd restore.git && git push --force --mirror https://github.com/YushBytes/Faculty-Project.git
```

(After 4.1, use the bundle taken by the final run in 4.3, which includes the updated `main`.)
