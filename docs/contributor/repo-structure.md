# Repo Structure

How the repo is laid out, and the ownership rules contributors must follow when adding files or generated outputs.

## Top-level shape

| Path | Purpose |
|---|---|
| `scripts/` | Shared engine code. `scripts/minimal8_harness.py` is the harness CLI; `scripts/tile_families.py` is the family loader/query module; `scripts/scene_templates.py` is the scene DSL evaluator. |
| `prototypes/minimal8-harness/` | The main prototype track. Owns its tile-family package, scene templates, and generated outputs. |
| `experiments/202605-minimal8-scene-experiments/` | Separate exploratory scene-composition experiment track. Not the canonical architecture. |
| `resources/references/` | Shared human-provided references and source inspiration. |
| `resources/Super Assets 3000/` | Vendor / source asset packs. Treat as upstream — keep clean. |
| `tests/` | Test suite for shared engine modules. |
| `tools/` | Repo tooling (e.g. `git-hooks/`). |
| `docs/` | The four documentation layers. Start at [docs/README.md](../README.md). |

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
