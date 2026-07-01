# Versioning

How version numbers work in this repo.

This repo uses [semver](https://semver.org/) for shipped, releasable states of the engine, tooling, and contributor-facing surfaces. Versions are written as full `X.Y.Z` numbers. The current version lives in `VERSION` at the repo root and is the single source of truth.

In this repo, a **Version** and a **Release** are different things:

- a **Version** is a `<Summary> (vX.Y.Z)` commit with a coherent version bundle; the latest such version on `main` is the current experimental shipped state
- a **Release** is a later stable promotion of an existing version on `main`

## Pre-1.0 Semver Policy

This repo currently follows a strict **pre-`1.0.0` semver policy**.

- bump **PATCH** for shipped, backward-compatible engine, tooling, or contributor-facing infrastructure changes
- bump **MINOR** for shipped, breaking engine/tooling/data-contract changes while the repo is still pre-`1.0.0`
- do **not** bump **MAJOR** before the first major production release; `MAJOR` is reserved for a fundamental model reset

Semver applies to shipped states of the engine, harness tooling, and related infrastructure that affect contributors or downstream consumers. It does not apply to support-only prefixed commits such as `docs:`, `test:`, or `chore:`.

## Scope

Versioning applies to changes that are intended to ship as part of the current experimental engine, harness, or contributor-facing infrastructure.

Non-versioned support work does not bump the version:

- documentation-only changes
- test-only changes
- repo-only maintenance such as tooling, formatting, or local workflow cleanup

## Source Of Truth

- `VERSION` — current shipped version

There is no second version file in this repo. If the version changes, `VERSION` changes.

When the distributed Git hooks are enabled, [`tools/git-hooks/pre-commit`](../../tools/git-hooks/pre-commit) checks that the `README.md` version badge matches `VERSION` and rejects the commit if it does not.

The distributed hooks validate version/changelog consistency around the current version. They do not decide or auto-increment the next version for you.

## One Version Per Commit

A versioned commit carries exactly one version. At that commit, the bundle must be coherent and self-contained:

- exactly one version in `VERSION`
- exactly one `docs/changelog/vX.Y.Z.md` matching that version, with the canonical Summary
- exactly one row in `docs/CHANGELOG.md` linking `[vX.Y.Z](changelog/vX.Y.Z.md)` and reusing that Summary verbatim
- a README Version badge consistent with that version
- a `<Summary> (vX.Y.Z)` commit subject reusing the same canonical Summary

Two distinct versions in one commit, stray older bundle artefacts dirty alongside the new bundle, and a CHANGELOG row whose Summary disagrees with the version file all violate the standard. The Summary describes the body of work, not just a label attached to a version number — if the body of work changes, the Summary must change.

The [`tools/git-hooks/commit-msg`](../../tools/git-hooks/commit-msg) hook enforces this coherence at each commit when hooks are enabled.

## Rebundling Versioned Commits

A sequence of versioned commits on a branch is not frozen. When the work is reordered, squashed, rebased, integrated onto `main`, or otherwise reshaped, the version sequence may need to be **rebundled**: renumbered, collapsed, dropped, or split so that the resulting sequence on `main` is coherent.

Rebundling is a rewrite, not a concatenation:

- if two versioned commits are squashed into one, the result is a single commit at a single version, with a freshly authored Summary, a single changelog file, and a single CHANGELOG row that together describe the new combined body of work — not the two old Summaries appended, and not the two old changelog files stacked
- if an intermediate version is dropped, its file and CHANGELOG row are removed from the bundle entirely
- if commits are reordered or renumbered, every affected commit's version, Summary, changelog file, CHANGELOG row, README badge, and commit subject are rewritten so each commit remains a coherent single-version bundle

The invariant is unchanged: every versioned commit on the final sequence is exactly one version with exactly one coherent bundle.

When a granular working branch is reset to match a rebundled integration branch, preserve the old tip first as a dated backup ref. Use the source branch path under a `backup/` namespace so the backup remains easy to find and prune, for example `backup/dev/rob/20260516`. This keeps rebundling reversible without preserving duplicate active histories indefinitely.

## Bump Rules

Use the pre-`1.0.0` categories deliberately:

- **PATCH** — shipped, backward-compatible engine, tooling, or contributor-facing infrastructure change
- **MINOR** — shipped, breaking engine, tooling, or data-contract change
- **MAJOR** — reserved until the first major production release

If a change is not intended to create a new latest experimental shipped state, it should normally stay non-versioned.

Branch work that is not yet ready to become the latest shipped line should stay non-versioned and be marked explicitly with a `WIP:` commit subject per [Commit Messages](commit-messages.md). Branch work that *is* intended as part of the next latest-line sequence may instead use versioned `<Summary> (vX.Y.Z)` commits directly on the branch — see [One Version Per Commit](#one-version-per-commit) and [Rebundling Versioned Commits](#rebundling-versioned-commits) above.

## Latest Version Flow

When shipping a new version on `main`:

1. Bump `VERSION`
2. Create `docs/changelog/vX.Y.Z.md`
3. Add the new row to `docs/CHANGELOG.md`
4. Update the README version badge
5. Run `python scripts/release_workflow.py version-check`
6. Use the matching canonical Summary as the version commit subject per [Commit Messages](commit-messages.md)

That commit becomes the new **latest** experimental shipped state. It is not tagged.

## Stable Release Flow

When promoting an existing version on `main` to stable:

1. Run `python scripts/release_workflow.py release-prepare --title "<Title>" --slug <slug>` to scaffold the release file under `docs/changelog/releases/` and insert the `Release: <title>` row in `docs/CHANGELOG.md`; edit both to add the authored narrative (replace all `TODO` placeholders)
2. Run `python scripts/release_workflow.py release`

`release-prepare` scaffolds the release file and CHANGELOG row; the release title and narrative remain authored content. Both steps are `main`-only and fail loudly when run from any other branch.

`release` runs a full bundle validity check (equivalent to `version-check`) before creating anything, then creates:

- the stable promotion commit
- the stable Git tag `vX.Y.Z`

It does not push anything. Publication remains an explicit human step.

## Main Branch Policy

`main` is the latest experimental release-tracked branch.

- non-support latest-line commits on `main` must follow the versioned latest flow
- stable `release:` promotion commits are `main`-only
- versioned `<Summary> (vX.Y.Z)` commits are allowed on any branch — branches may carry a clean sequence of latest-line commits prior to integrating onto `main`, subject to the [One Version Per Commit](#one-version-per-commit) invariant
- once a versioned or stable `release:` commit lands on `main` it is **shipped and frozen**; the rebundling flexibility under [Rebundling Versioned Commits](#rebundling-versioned-commits) applies to in-flight branch sequences only, not to commits already on `main`
- `WIP:` commits are allowed on non-`main` branches only, and are the escape hatch for branch work that is not yet a latest-line candidate
- support-only commits may still use `docs:`, `test:`, or `chore:` without bumping the version, including on `main`

The distributed [`tools/git-hooks/commit-msg`](../../tools/git-hooks/commit-msg) hook is the strict local enforcement mechanism for this branch policy when hooks are enabled.

## Tag Policy

Only stable releases get Git tags.

- latest experimental version commits do **not** get tags
- stable promotion commits get the plain semver tag `vX.Y.Z`

## Historical Note

This standard was adopted after substantial repo history already existed.

- older commits do not necessarily follow this versioning workflow
- older shipped states do not need to be exhaustively backfilled into the changelog
- the changelog may include a non-version historical baseline record such as `pre-0.1.0`
- avoid fake semver entries like `0.0.0` unless that was a real shipped version

## Related

- [Changelog](changelog.md) — how shipped versions are recorded
- [Commit Messages](commit-messages.md) — how versioned, release, and non-versioned commits are written
