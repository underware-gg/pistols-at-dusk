# Repo Structure

How the repo is laid out, and the ownership rules contributors must follow when adding files or generated outputs.

## Top-level shape

| Path | Purpose |
|---|---|
| `scripts/` | Shared engine code plus contributor tooling. Engine: `scripts/harness.py` (harness CLI), `scripts/tile_family_runtime.py` (runtime family loader/validator), `scripts/tile_family_ingest.py` (ingest/operator family helpers), `scripts/source_layout_model.py` (shared source-layout values), `scripts/tile_families.py` (transitional compatibility facade), `scripts/tile_library.py` (runtime library surface — construction/tile records and the `TileLibraryUnit`/`TileLibraryRegistry` containers), `scripts/tile_library_codec.py` (runtime-asset serializer/deserializer for `TileLibraryUnit`), `scripts/runtime_asset_producer.py` (ingest/operator-side producer: materialises atomic content-addressed tile pixels and writes the runtime-family asset), `scripts/runtime_asset_paths.py` (format owner for the runtime atomic-asset address `sha256:<digest>` and its on-disk asset path), `scripts/tile_family_project_ingest.py` (project-side source-pack/legacy family loaders, registered into the runtime through the loader seam so `layout_core` carries no ingest imports), `scripts/pixel_content.py` (shared canonical-RGBA byte primitive underpinning both the atomic-asset address and the ingest content-hash identity), `scripts/semantic_catalogue_ingest.py` (ingest-side semantic catalogue resolver: detected base ⊕ authored patch, content-hash-keyed), `scripts/legacy_semantic_bootstrap.py` (one-time ingest/operator migration: legacy `tiles.json` semantics → durable content-keyed authored patches, fail-loud on divergent collisions), `scripts/scene_templates.py` (scene DSL evaluator). Contributor tooling: `scripts/release_workflow.py` (version-bundle and stable-release validation; invoked by hooks and contributors), `scripts/check_pyright.sh`, `scripts/check_coverage.sh`. |
| `prototypes/minimal8-harness/` | The main prototype track. Owns its tile-family package, scene templates, and generated outputs. |
| `experiments/202605-minimal8-scene-experiments/` | Separate exploratory scene-composition experiment track. Not the canonical architecture. |
| `resources/references/` | Shared human-provided references and source inspiration. |
| `resources/Super Assets 3000/` | Vendor / source asset packs. Treat as upstream — keep clean. |
| `tests/` | Test suite for shared engine modules. |
| `tools/` | Repo tooling. `tools/git-hooks/` holds the opt-in distributed `pre-commit` and `commit-msg` hooks plus the committed Git LFS passthrough shims; activate with `git config core.hooksPath tools/git-hooks`. |
| `.canaries/` | Canary briefs that gate subjective contributor work. `.canaries/pre-commit.md` is the current pre-commit brief; the matching transient `.canary--pre-commit` receipt is gitignored. See [docs/standards/canary.md](../standards/canary.md). |
| `docs/` | The five documentation layers (user, functional, architecture, contributor, standards). Start at [docs/README.md](../README.md). |
| `docs/standards/` | Cross-cutting standards: versioning, changelog, commit messages, canary. See [docs/standards/README.md](../standards/README.md). |
| `docs/changelog/` | One file per shipped version (`vX.Y.Z.md`) and a `releases/` subfolder for stable promotions. The newest-first index is [docs/CHANGELOG.md](../CHANGELOG.md). |

## Minimal 8 split

The Minimal 8 work currently spans the harness prototype and a parallel experiment track. The split:

| Concern | Location |
|---|---|
| Canonical family metadata | `prototypes/minimal8-harness/tile-families/minimal8/` |
| Harness prototype outputs | `prototypes/minimal8-harness/generated/` |
| Harness scratch / inspect / Tiled kit | `prototypes/minimal8-harness/scratch.local/` |
| Scene experiment code | `experiments/202605-minimal8-scene-experiments/scripts/` |
| Scene experiment outputs | `experiments/202605-minimal8-scene-experiments/generated/` |
| Scene experiment scratch | `experiments/202605-minimal8-scene-experiments/scratch.local/` |

The family package under `prototypes/minimal8-harness/tile-families/minimal8/` is the **single source of truth** for sheet facts, clusters, tile semantics, and aliases. Do not re-author this content in code or in scene templates.

## Ownership rules

- **Generated outputs live with the thing that owns the work.** Prototype-owned outputs go in that prototype's `generated/` (e.g. `prototypes/minimal8-harness/generated/`); experiment-owned outputs go in that experiment's `generated/` (e.g. `experiments/<date>-<name>/generated/`).
- **Do not introduce a shared top-level generated bucket.** Specifically, do not put new outputs under a shared `resources/generated/`.
- **Do not re-home upstream asset packs.** `resources/Super Assets 3000/` mirrors the vendor pack; keep it clean.

## Scratch rules

- Scratch lives in a `scratch.local/` folder inside the thing that owns the work. Examples:
  - `prototypes/minimal8-harness/scratch.local/`
  - `experiments/202605-minimal8-scene-experiments/scratch.local/`
- All `scratch.local/` directories are gitignored by name. Treat anything in scratch as throwaway.

## Git LFS

Git LFS is intentionally enabled broadly for common binary asset types in this repo. Keep it that way unless it creates a real tooling or runtime problem; if that happens, narrow LFS scope deliberately rather than ad hoc.

## Cross-references

- Working rules and change discipline: [working-rules.md](working-rules.md)
- Documentation standard adoption: [documentation-standard.md](documentation-standard.md)
