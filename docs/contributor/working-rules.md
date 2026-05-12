# Working Rules

Practical guidance for contributors and agents working in this repo. Repo layout and ownership rules live in [repo-structure.md](repo-structure.md); documentation standard adoption lives in [documentation-standard.md](documentation-standard.md).

## Code design

- Use the `software-design-principles` skill / reference while designing, writing, and refactoring code in this repo.
- Prefer clean refactors over backwards-compatibility shims for internal prototype code. The repo currently has no external consumers that justify carrying bad old assumptions forward.
- Refactor touched code toward clearer domain language and simpler structure as you go, but avoid speculative architecture we do not need yet.

## Canonical sources of truth

- Minimal 8 sheet/family semantics: [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8).
- Harness runtime: [scripts/minimal8_harness.py](../../scripts/minimal8_harness.py).
- Family loader / query model: [scripts/tile_families.py](../../scripts/tile_families.py).
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
- **Versioned changes bump `VERSION` and update the changelog package.** When a change ships a new repo version, update `VERSION`, add a row to [docs/CHANGELOG.md](../CHANGELOG.md), and add `docs/changelog/vX.Y.Z.md`. See [changelog-standard.md](changelog-standard.md).

## Verification

- Tooling bootstrap for this repo:
  - install the pinned runtime via `asdf` (`.tool-versions` currently pins `python 3.12.13`)
  - create the repo-local virtual environment with `asdf exec python -m venv .venv`
  - install Python dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`
  - install the repo-local Node tooling with `pnpm install`
- For typed engine changes, run `bash scripts/check_pyright.sh` before committing.
- `pnpm typecheck` runs the same repo-local typecheck entrypoint.
- Run `bash scripts/check_coverage.sh` or `pnpm test:coverage` to inspect Python line and branch coverage across the repo scripts.
- Test commands for the harness modules:
  - `.venv/bin/python -m unittest tests.test_tile_families tests.test_minimal8_harness tests.test_scene_expansion tests.test_prototype_output`
- To enable the tracked local pre-commit hook, run `git config core.hooksPath tools/git-hooks`.

## Commits

- One commit per logically distinct change. Do not bundle unrelated changes.
- Behavioural change → tests and docs update in the same change.
- Versioned commit subjects reuse the canonical changelog Summary text as `<Summary> (vX.Y.Z)`; non-versioned support commits use `docs:`, `test:`, or `chore:` prefixes. See [commit-messages.md](commit-messages.md).
