# Changelog Standard

How shipped release history is documented in this repo.

## Package

The live release-history package is:

- `VERSION` — source of truth for the current repo version
- `docs/CHANGELOG.md` — newest-first index of shipped versions
- `docs/changelog/vX.Y.Z.md` — one file per shipped version

## Versioning

This repo uses pre-1.0 [semver](https://semver.org/):

- backward-compatible changes are patch
- breaking repo/tooling/data-contract changes are minor
- major is reserved for a fundamental model reset

## Update Flow

When shipping a new version:

1. Bump `VERSION`.
2. Create `docs/changelog/vX.Y.Z.md`.
3. Add the new row to `docs/CHANGELOG.md`.
4. Reuse the same Summary text in the per-version file, the index row, and the versioned commit subject.
5. Do not rewrite older per-version files to "fix history". Record corrections in the current version instead.

## Per-Version Files

Each `docs/changelog/vX.Y.Z.md` file documents one shipped version.

Required shape:

- `# vX.Y.Z — YYYY-MM-DD`
- one top-line bold `Summary`
- optional short prose context
- top-level detail bullets as needed to describe the shipped surface clearly; there is no fixed cap when more detail materially improves release clarity
- optional one-level nested bullets for important identifiers
- `Migration:` notes when install-manager action is required

Rules:

- Summary text is one short scannable sentence, imperative mood, no trailing period.
- Top-level detail bullets describe shipped behaviour, release surface, or contributor-facing effect — not raw file inventories.
- Changelog entries may be detailed; optimise for readable release notes rather than forcing an artificial bullet limit.
- Each top-level detail bullet must anchor itself in at least one important identifier such as a file path, function, type, folder, config key, or test file.
- When identifiers would make a top-level bullet unreadable, use one nested list level to carry the important identifiers underneath the outcome-first bullet.
- Nested bullets are for important identifiers only, not exhaustive changed-file lists.
- Vague bullets such as "refactor code", "tests added", or "docs updated" are not acceptable without named identifiers.
- Public changelog files may reference only public-safe identifiers and paths.

## Index

`docs/CHANGELOG.md` is the scannable entry point.

- one row per shipped version
- newest first
- `Version` links to `docs/changelog/vX.Y.Z.md`
- `Summary` reuses the same canonical Summary text as the per-version file

## Related

- [commit-messages.md](commit-messages.md) — commit-history standard
