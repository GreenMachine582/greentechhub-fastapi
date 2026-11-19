[← Back to README](README.md)

# Contributing

<!-- >>> repo-kit: branches -->
## 🔀 Branches

```
feat/x ──commits──► draft PR to dev ──► ready ──► checks pass ──► merge commit ──► dev
                                                                                    │
           tag vX.Y.Z ◄── release PR merged ◄── dev → main PR ◄─────────────────────┘
               │
               └──► main merged back into dev
```

- **`dev`** is the default branch and the base for feature PRs.
- **`main`** only holds released code, and only takes release PRs from `dev`. Consumers pin tags (`…@vX.Y.Z`),
  never branches.
- Neither takes a direct push: every change goes through a PR, merged with a **merge commit**.
- Branches are named `<type>/<short-description>` (`feat/folder-picker`, `docs/adoption`), using the commit types
  below. Each holds one topic and lives until its PR merges.
- One branch is one worktree: `rk wt start <branch>` creates both and sets the worktree up. When the PR has merged,
  `rk wt done <branch>` removes them.
<!-- <<< repo-kit: branches -->

<!-- >>> repo-kit: pull-requests -->
## 📬 Pull requests

- A PR is one topic, made of related commits. Code and the docs that describe it go in the same PR.
- Open it as a **draft**, and mark it ready when it's done. Only ready PRs are kept current by the PR bot, which
  merges the base in when it moves. Add the `wip` label to a ready PR under rework.
- Update an open PR by adding commits, or by merging its base in with `rk wt sync`. Never rebase or force-push:
  others may have the branch, or have chained a PR on it.

### Commits

PRs are merged with a merge commit, so every commit lands on `dev` as written and release-please reads each one.
**Every commit** must be a [Conventional Commit](https://www.conventionalcommits.org), with a first line of at most
100 characters and a body that explains why. Merge commits are skipped by the `commits` check. `rk install --hooks` runs the same check on each
commit, before it's made.

| Type | For | In the changelog |
|---|---|---|
| `feat` | New behaviour | Yes (minor bump) |
| `fix` | Something that was broken | Yes (patch) |
| `perf` | Faster or lighter, same behaviour | Yes (patch) |
| `build` | Tooling and dependencies | Yes (patch) |
| `docs` | Documentation only | No |
| `refactor` | Restructuring with the same behaviour | No |
| `test` | Tests only | No |
| `ci` | GitHub Actions workflows | No |
| `chore` | Housekeeping that changes no behaviour | No |
| `style` | Formatting only | No |
| `revert` | Undoing an earlier commit | Yes |

A breaking change is `feat!:` (or any type with `!`), plus a `BREAKING CHANGE:` footer in that commit's body
explaining what to change.

### PR titles

PR titles are **not** Conventional Commits: write a plain sentence, such as `Add the folder picker`. The merge commit carries the title, and release-please reads a conventional line there as one more change, so a `feat: …` title would list that change twice. GitHub suggests a one-commit PR's subject as its title, so rewrite it. Release PRs (`release: …`, `chore(main): release …`) are allowed.
<!-- <<< repo-kit: pull-requests -->

<!-- >>> repo-kit: chained-prs -->
## 🔗 Several PRs at once

Small PRs are reviewed faster and conflict less. When one piece of work builds on another, chain them instead of
opening one big PR:

1. `feat/a` → a PR into `dev`.
2. `rk wt start feat/b --from feat/a` → a PR with **base `feat/a`**. Its diff shows only B's commits, and the checks
   run on it as usual.
3. Merge A. GitHub deletes `feat/a` and retargets B's PR to `dev` by itself. B already holds A's commits
   (merge commits keep them), so nothing conflicts and nothing needs rebasing.
4. Merge B, and so on down the chain.

Merge the chain in order, starting from the PR nearest `dev`: merging B first would land A's commits with
it. To pick up a fix made in A after B was branched, merge `feat/a` into `feat/b`.
<!-- <<< repo-kit: chained-prs -->

<!-- >>> repo-kit: releasing -->
## 🚢 Releasing

Release whenever `dev` is worth shipping. There's no fixed cadence.

1. Open a PR from `dev` to `main`, titled `release: …`. Wait for the checks, and merge it with a merge commit.
2. release-please opens or updates **`chore(main): release X.Y.Z`** on `main`, with the version bump and the new
   `CHANGELOG.md` section worked out from the commits. It's opened by the `gth-release-bot` GitHub App, so the
   checks run on it.
3. Review the notes and merge it. That tags `vX.Y.Z`, publishes the GitHub Release with the same notes, and merges
   `main` back into `dev`.

Never bump a version or edit a released `CHANGELOG.md` section by hand, and never move a `v*` tag: consumers pin
exact tags.
<!-- <<< repo-kit: releasing -->

## Developing against local GTH repos

With greentechhub-core checked out next to this repo, `./scripts/use-local-gth.sh` runs this venv against that
checkout instead of the pinned release. `--status` shows which one is in use, and `--undo` goes back to the pin.
It changes only the venv, never `pyproject.toml`, so CI keeps testing the pin. Details, invariants and the release
order: [greentechhub-core's CONTRIBUTING.md](https://github.com/GreenMachine582/greentechhub-core/blob/dev/CONTRIBUTING.md#developing-against-local-gth-repos).

## Rules

GitHub settings live in the repo and are applied with `scripts/apply-rulesets.sh`, which needs an authenticated
`gh` with admin rights. Rerun it whenever one of these files changes:

| File | What it sets |
|---|---|
| [`.github/repo-settings.json`](.github/repo-settings.json) | Merge commits only (no squash or rebase), delete the branch on merge, the **Update branch** button, auto-merge |
| [`.github/rulesets/dev.json`](.github/rulesets/dev.json) | `dev`: PR with a merge commit, green required checks, no force-push or deletion |
| [`.github/rulesets/main.json`](.github/rulesets/main.json) | `main`: the same, with `test` required |
| [`.github/rulesets/tags.json`](.github/rulesets/tags.json) | `v*` tags can't be moved or deleted, and only release-please (the `gth-release-bot` app) creates them |

In an emergency the admin can merge a PR past failing checks (a logged bypass), but nobody, admin included, can push
straight to `main` or `dev`. Use the bypass to fix a broken pipeline, not to skip one.

`scripts/prune-branches.sh` cleans up branches after merges. It's a dry run by default, and `--apply` deletes. It
removes local branches whose PR merged, and origin branches whose PR merged or was closed. It never touches `dev`,
`main`, the checked-out branch, a branch with an open PR or no PR, or one with commits beyond what its PR merged
(reported as `newer`, so check it by hand).
