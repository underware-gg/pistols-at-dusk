# Commit Messages

How to write good commit messages in this repo. Applies to every contributor, human and agent.

A good commit message does three things: makes the subject scannable in `git log`, explains the *why* in prose so a reader does not have to reconstruct it from the diff, and names specific identifiers when they add meaning.

## Process

Before drafting, read:

1. `git diff` and `git diff --stat`
2. `git log --oneline -15`
3. If the change ships a latest version, the matching `docs/CHANGELOG.md` row and `docs/changelog/vX.Y.Z.md` Summary
4. If the change is a stable release promotion, the matching release row in `docs/CHANGELOG.md` and `docs/changelog/releases/vX.Y.Z-<slug>.md`

This repo's older history predates the imported standard. Match the current style going forward; do not try to "correct" older commits retroactively.

## Subject Line

Versioned template: `<Summary> (vX.Y.Z)`

Stable release template: `release: promote vX.Y.Z to stable`

Non-versioned support template: `<prefix> <specific subject>`, where `<prefix>` is `docs:`, `test:`, or `chore:`

Non-versioned branch-work template: `WIP: <specific subject>`

- short — under about 70 characters
- specific — name the real thing by identifier when possible
- no period at the end
- imperative mood

### Versioned Commits

A versioned commit uses `<Summary> (vX.Y.Z)` as its subject, reusing the canonical Summary from `docs/changelog/vX.Y.Z.md` verbatim with the `(vX.Y.Z)` suffix appended. Versioned commits stay prefix-free.

Versioned commits are allowed on any branch. On `main` they become part of the shipped latest line and are frozen once landed. On other branches they may form a clean sequence intended for later integration onto `main`, and may be rebundled until they ship (see [Rebundling Versioned Commits](#rebundling-versioned-commits) below).

Every versioned commit must satisfy the full version bundle: `VERSION`, `docs/changelog/vX.Y.Z.md`, the matching `docs/CHANGELOG.md` row, and the README badge must all be coherent at that commit, and the subject must reuse the canonical Summary verbatim. The `commit-msg` hook enforces this regardless of branch. See [Versioning — One Version Per Commit](versioning.md#one-version-per-commit) for the full invariant.

Stable `release:` promotion commits remain `main`-only — see [Stable Release Commits](#stable-release-commits) below.

### Stable Release Commits

When promoting an existing latest version on `main` to stable, use:

- `release: promote vX.Y.Z to stable`

The matching release artefacts must already exist:

- `docs/changelog/releases/vX.Y.Z-<slug>.md`
- the `Release: <title>` row in `docs/CHANGELOG.md`

Stable release commits may omit a body when the release file itself carries the stable-release narrative.

### Non-Versioned Support Commits

Use prefixes only for support-only work that does not ship a version:

- `docs:` — documentation-only work
- `test:` — test-only work
- `chore:` — repo-only maintenance that does not ship a new version

Keep the prefix set narrow. Add new prefixes only if a real recurring support category appears.

### Non-Versioned Branch Work

For non-support work on branches other than `main`, you may explicitly skip versioning by using:

- `WIP: <specific subject>`

Use this for branch-local work that is not yet ready to become the latest shipped line. `WIP:` is the escape hatch from versioning, not a requirement — a branch may also carry versioned commits (see below).

`WIP:` commits must not land on `main`.

### Rebundling Versioned Commits

When a branch's versioned sequence is reshaped — squashed, rebased, reordered, partially dropped, or integrated onto `main` — the affected versions may need to be rebundled. See [Versioning — Rebundling Versioned Commits](versioning.md#rebundling-versioned-commits).

The commit-message implication is that subjects are **rewritten**, not concatenated:

- a squashed commit gets a single newly authored `<Summary> (vX.Y.Z)` subject describing the combined body of work, sourced from the rewritten `docs/changelog/vX.Y.Z.md` Summary — not the two old subjects joined together
- a renumbered version commit gets the new version's canonical Summary as its subject
- a dropped intermediate version no longer has a commit, so no subject survives

The subject and the canonical Summary are always kept in lockstep with the commit's actual content.

### Branch Policy

- on `main`, non-support commits must be either latest-version commits or stable `release:` promotion commits
- off `main`, non-support commits may use either a versioned `<Summary> (vX.Y.Z)` subject or `WIP:` — both are valid; pick `WIP:` when the work is not yet a latest-line candidate
- stable `release:` promotion commits are `main`-only
- support-only commits may use `docs:`, `test:`, or `chore:` on any branch

The distributed [`tools/git-hooks/commit-msg`](../../tools/git-hooks/commit-msg) hook is the strict local enforcement mechanism for this branch policy when hooks are enabled.

## Body

The body explains *why* the change exists — the motivation, mechanism, trade-off, or downstream effect. It is optional for trivial commits.

When used:

- prefer short concept-level bullets
- keep bullets concise and specific
- explain facts a reviewer cannot get from the subject or diff alone
- avoid repeating file lists the diff already shows

Use prose only when the change has one causal chain that is clearer as 2–4 connected sentences.

## Worked Examples

Good:

```text
docs: refresh contributor index and standards routing
chore: bump pyright pinned version
Ship the Minimal 8 harness as the repo's first public baseline (v0.1.0)
release: promote v0.1.0 to stable
WIP: port grid extraction onto current main
```

Avoid:

```text
update files
misc cleanup
docs update
```

## Rules

**Why, not what.** The diff already shows what changed.

**Specific beats generic.** Name the command, config key, module, or contract when it matters.

**One logical change per commit.** Split unrelated changes even if staging them together would be convenient.

**Versioned commits use the canonical Summary.** Do not paraphrase the `docs/changelog/vX.Y.Z.md` Summary into a different subject line.

**Support-only commits use the narrow prefix set.** Do not use `docs:`, `test:`, or `chore:` for shipped version bumps.

**Stable release commits are mechanical promotions.** They promote an existing version to stable and should not bump the version again.

**`WIP:` is for branch work only.** It is the explicit escape hatch for non-versioned, non-support commits before they are ready for `main`. Versioned commits remain allowed on branches — `WIP:` is an option, not a requirement, for off-`main` work.

## Related

- [Versioning](versioning.md) — when a change should bump the version
- [Changelog](changelog.md) — where the canonical latest-version Summary comes from
