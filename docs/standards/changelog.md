# Changelog

How latest versions and stable releases are documented in this repo.

This repo currently uses a strict pre-`1.0.0` semver policy:

- `PATCH` = shipped, backward-compatible engine, tooling, or contributor-facing infrastructure change
- `MINOR` = shipped, breaking engine, tooling, or data-contract change
- `MAJOR` is reserved until the first major production release

See [Versioning](versioning.md) for the full policy.

## Package

The live changelog is a small package:

- `docs/CHANGELOG.md` — newest-first index of latest-version and stable-release events
- `docs/changelog/vX.Y.Z.md` — one file per shipped version
- `docs/changelog/releases/vX.Y.Z-<slug>.md` — one file per stable release promotion

The package may also include a clearly marked non-version historical baseline note, for example `docs/changelog/pre-0.1.0.md`, when structured changelog tracking starts after substantial earlier history.

## Update Flow

When creating a versioned commit (on `main` to ship a new latest version, or on a branch building toward one):

1. Bump `VERSION`
2. Create `docs/changelog/vX.Y.Z.md`
3. Add the new row to `docs/CHANGELOG.md`
4. Update the README version badge
5. Reuse the same canonical Summary text in the changelog and the versioned commit subject per [Commit Messages](commit-messages.md)

A versioned commit on `main` is shipped and frozen once landed. On a branch it is a draft that may be rebundled before integration — see [Rebundling Versioned Commits](#rebundling-versioned-commits).

When promoting an existing latest version on `main` to stable (a `main`-only step):

1. Create `docs/changelog/releases/vX.Y.Z-<slug>.md`
2. Add the matching `Release: <title>` row to `docs/CHANGELOG.md`
3. Use the stable promotion subject from [Commit Messages](commit-messages.md)

Contributors may use `python scripts/release_workflow.py release-prepare` as a structural scaffold for the release file and changelog release row, but the release title and narrative remain authored content. Both `release-prepare` and `release` are `main`-only steps and fail loudly when run from any other branch.

Do not silently rewrite older entries to make history look cleaner. If a correction is needed, add it explicitly in a newer entry or in a clearly marked historical note.

## Rebundling Versioned Commits

Branches may carry versioned commits prior to integration onto `main` (see [Versioning — Rebundling Versioned Commits](versioning.md#rebundling-versioned-commits)). When that sequence is reshaped — squashed, rebased, reordered, or partially dropped — the changelog artefacts are **rewritten**, not concatenated.

For each affected commit, the rewrite produces:

- one `docs/changelog/vX.Y.Z.md` file at the commit's version, with a single canonical Summary authored to describe the actual combined body of work at that commit
- one matching row in `docs/CHANGELOG.md` reusing that Summary verbatim
- removal of any version files and CHANGELOG rows for versions that no longer exist in the new sequence

Two old version files are never stacked into one. Two old Summaries are never appended into one. The Summary describes the body of work at the rewritten commit, sourced fresh from that commit's actual scope.

The "do not silently rewrite older entries" rule above applies to versions that have already shipped on `main`. Branch-local versions that have not yet integrated are still in flight and may be rebundled freely.

## Per-Version Files

Each `docs/changelog/vX.Y.Z.md` file documents one version. On `main` that version is the latest experimental shipped state; on a branch it is a draft that becomes shipped when the branch integrates to `main`.

Required shape:

- `# vX.Y.Z — YYYY-MM-DD` heading
- a top-line bold `**Summary**` line: one short sentence describing the contributor-visible or downstream-visible effect of the version
- optional short prose context
- top-level detail bullets as needed to describe the shipped surface clearly; there is no fixed cap when more detail materially improves release clarity
- optional one-level nested bullets for important identifiers

Rules:

- the `Summary` is the canonical release subject source, so it must satisfy the commit-subject rules from [Commit Messages](commit-messages.md): short, specific, imperative, no period, no version suffix
- the `Summary` is the canonical latest-version commit subject source
- keep references public-safe: repo paths, semver versions, public URLs, and named public standards are fine
- when a version contains multiple distinct shipped changes, keep one top-line Summary and group supporting bullets underneath it
- each top-level detail bullet should anchor itself in at least one important identifier such as a file path, function, type, folder, config key, or test file
- when identifiers would make a top-level bullet unreadable, use one nested list level to carry the important identifiers underneath the outcome-first bullet
- vague bullets such as "refactor code", "tests added", or "docs updated" are not acceptable without named identifiers
- if an entry is a baseline or adoption record rather than a literal historical ship note, say so explicitly in the file

## Stable Release Files

Each `docs/changelog/releases/vX.Y.Z-<slug>.md` file documents the later stable promotion of an existing version.

Required shape:

- top-line heading `# <Title> (vX.Y.Z)`
- `Shipped: YYYY-MM-DD`
- a link back to `docs/changelog/vX.Y.Z.md`
- `## Overview`
- `## Highlights`
- `## Stable Validation`
- `## Version`

Rules:

- there is exactly one stable release file per version
- release files are authored by contributors; scripts may scaffold them but must not invent the release title or narrative
- release files narrate why the version is stable, not why the version exists at all

## Index

`docs/CHANGELOG.md` is the scannable entry point.

- newest first by release-history event
- version rows use full `X.Y.Z` semver numbers and link to `docs/changelog/vX.Y.Z.md`
- stable release rows reuse that same version link and use `Release: <title>` in the `Summary` column, with the title linked to `docs/changelog/releases/vX.Y.Z-<slug>.md`
- insert each new event directly under the table header, above all older rows
- the version row `Summary` is one short canonical line reused by the per-version file and the version commit subject
- if a historical baseline note exists, list it clearly at the bottom of the same index rather than pretending it is a numbered release

For a single semver version, the changelog may therefore contain:

- one version row when the latest experimental state is created
- one later stable release row when that same version is promoted

## Historical Note

This repo adopted structured changelog tracking after earlier development had already happened.

- backfill only when it adds real value
- prefer an explicit historical baseline note over speculative reconstruction
- keep the live changelog honest about what was recorded contemporaneously and what was documented later

## Related

- [Versioning](versioning.md) — when versions change
- [Commit Messages](commit-messages.md) — latest-version and stable-release commit rules
