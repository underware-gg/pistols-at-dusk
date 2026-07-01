# Working Rules

Practical guidance for contributors and agents working in this repo. Repo layout and ownership rules live in [repo-structure.md](repo-structure.md); documentation standard adoption lives in [documentation-standard.md](documentation-standard.md); verification, hooks, and release workflow live in [process.md](process.md) and [release-workflow.md](release-workflow.md); commit/version/changelog rules live in [docs/standards/](../standards/README.md).

## Code design

- Use the `software-design-principles` skill / reference while designing, writing, and refactoring code in this repo.
- Prefer clean refactors over backwards-compatibility shims for internal prototype code. The repo currently has no external consumers that justify carrying bad old assumptions forward.
- Refactor touched code toward clearer domain language and simpler structure as you go, but avoid speculative architecture we do not need yet.

## Canonical sources of truth

- Minimal 8 authored semantic content (tiles, aliases, clusters, constructions): [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8) — transitional compatibility / producer input; the active source-ingest entrypoint is [tile-packs/minimal8](../../prototypes/minimal8-harness/tile-packs/minimal8) and the production runtime entrypoint is [runtime-families/](../../prototypes/minimal8-harness/runtime-families).
- Harness runtime: [scripts/harness.py](../../scripts/harness.py).
- Shared project/render base: [scripts/layout_core.py](../../scripts/layout_core.py).
- Source-ingest CLI: [scripts/source_ingest.py](../../scripts/source_ingest.py).
- Transitional family compatibility facade: [scripts/tile_families.py](../../scripts/tile_families.py).
- Runtime library surface: [scripts/tile_library.py](../../scripts/tile_library.py).
- Scene DSL evaluator: [scripts/scene_templates.py](../../scripts/scene_templates.py).

Use stable family / region / grid tile IDs and semantic aliases. Do not invent scene-specific IDs. Treat the scene experiment track as exploratory and not the canonical architecture; prefer extending the harness for reusable engine / layout work.

## Asset meaning vs source context

- Keep `meaning` asset-focused — what the tile *is*.
- Keep `source_notes` (and similar) focused on provenance, adjacency, or reviewer guidance — context about the *sheet*.

Source-sheet / process commentary is not asset meaning. Mixing them dilutes the catalog.

## Review workflow

Two review lanes are supported:

1. **Human lane**
   - Export a review pack.
   - Write plain-language notes in `review_notes.md`.
2. **Structured lane**
   - Translate reviewed meaning into family manifests.
   - Update `tiles.json`, `aliases.json`, and `clusters.json`.

The engine does not parse freeform human notes automatically — humans translate the human lane into the structured lane.

## Change discipline

- **Update docs alongside code.** Per the agent-ready documentation standard, behavioural changes carry doc changes in the same change. See [documentation-standard.md](documentation-standard.md).
- **Identity / routing changes need a decision record.** When you change identity or routing rules, update the relevant ADR or add a new one under [docs/architecture/decisions/](../architecture/decisions). Do not rewrite a landed decision record — supersede it.
- **Generated output stays in the owning prototype or experiment** — see [repo-structure.md](repo-structure.md).
- **Versioned changes ship the full bundle in one commit.** When a change ships a new latest version, bump `VERSION`, create `docs/changelog/vX.Y.Z.md`, add the row to `docs/CHANGELOG.md`, update the README badge, and commit with the canonical `<Summary> (vX.Y.Z)` subject. See [docs/standards/versioning.md](../standards/versioning.md), [docs/standards/changelog.md](../standards/changelog.md), and [release-workflow.md](release-workflow.md).

## Verification, hooks, and commits

Verification expectations, hook activation, the canary brief, and commit/version/changelog rules are the canonical responsibility of the contributor process and standards layer. Start there:

- [process.md](process.md) — verification commands, hook activation, canary workflow
- [release-workflow.md](release-workflow.md) — latest-version and stable-release flows
- [docs/standards/commit-messages.md](../standards/commit-messages.md) — versioned, release, support, and `WIP:` subject rules
- [docs/standards/versioning.md](../standards/versioning.md) — pre-1.0 semver policy, one-version-per-commit, branch policy
- [docs/standards/changelog.md](../standards/changelog.md) — changelog package shape
- [docs/standards/canary.md](../standards/canary.md) — canary brief pattern
