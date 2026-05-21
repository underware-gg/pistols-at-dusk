# Functional Documentation

## Compatibility Family Package Format

The active source-side ingest truth is the staged pack / tileset /
logical-tilesheet hierarchy. The current runtime compatibility bundle is still a
directory package
with manifests for variant metadata, source-sheet layout, semantics, and aliases:

- `family.json`
  - family ID
  - grid size
  - render defaults
  - variant list and per-variant sheet metadata
- `ingestion.json`
  - authoritative source-sheet regions, clusters, and collections
- `clusters.json`
  - semantic groupings and member sets
- `tiles.json`
  - per-tile semantic records keyed by stable tile IDs
  - direct sheet provenance via `sheet_col` / `sheet_row` for sheet-backed tiles
- `constructions.json`
  - legal multi-tile arrangements and parametric runs built from the tile catalogue
- `aliases.json`
  - canonical semantic aliases mapped to stable tile IDs

Current Minimal 8 source-side entrypoint:

- [prototypes/minimal8-harness/tile-packs/minimal8](../../prototypes/minimal8-harness/tile-packs/minimal8)

Current Minimal 8 compatibility bundle:

- [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8)

Minimal 8 now enters through the staged pack / tileset / logical-tilesheet
manifest hierarchy. The legacy family package remains the transitional
compatibility bundle that feeds the current runtime/library path.

[scripts/source_manifest_bridge.py](../../scripts/source_manifest_bridge.py) is the one-way transitional adapter that lets those staged source manifests feed the current family-backed compatibility/runtime path without making the source manifests themselves a runtime dependency.

## Addressing Formats

Three address forms are supported:

- Physical sheet address: `minimal8:20,17`
- Concrete variant identity: `minimal8@1bit_colored_bg:20,17`
- Raw tileset coordinate: `minimal8@1bit_colored_bg#20,24`
- Semantic alias: `indoors.table.long.left`
- Stable tile ID: `minimal8:terrain:1,15`

Rules:

- Physical and variant addresses are direct sheet-cell refs for sheet-backed family tiles.
- Raw tileset coordinates bypass the family catalogue and use `tileset_id#col,row`.
- Unprefixed `col,row` still means a raw coordinate on the default tileset.
- Stable tile IDs stay fixed across migrations and resolve as opaque identifiers.
- Semantic aliases resolve to tile IDs and are a convenience layer, not the primary identity.

## Project Consumption Model

Projects do not own sheet semantics anymore. They consume a family-backed runtime unit and pick a default variant. Minimal 8 now does that through the staged source-pack entrypoint:

```json
{
  "tile_family": {
    "source_pack": "./tile-packs/minimal8/pack.json",
    "tileset_id": "minimal8",
    "tilesheet_id": "main",
    "family_id": "minimal8",
    "variant_id": "1bit_colored_bg"
  }
}
```

Legacy direct-family loading still exists as a transitional fallback, and
projects may also mix multiple family-backed runtime units:

```json
{
  "tile_families": [
    {
      "source_pack": "./tile-packs/minimal8/pack.json",
      "tileset_id": "minimal8",
      "tilesheet_id": "main",
      "variant_id": "1bit_colored_bg"
    },
    {"path": "./tile-families/mini-medieval", "variant_id": "default"}
  ],
  "default_tileset": "minimal8@1bit_colored_bg"
}
```

When multiple family-backed units are loaded:

- the project still needs an explicit `default_tileset` for bare coordinate refs and other fallback cases
- explicit family refs like `family.id:3,4` or `family.id@variant:3,4` resolve against the owning loaded unit
- unique family aliases and unique tile ids may also resolve against a non-default loaded unit

At runtime, the harness now derives a compatibility view before doing ordinary scene work:

- staged source packs bridge into the current family-backed compatibility path
- legacy family packages may still be loaded directly as transitional compatibility inputs for migration and test coverage
- the runtime consumes a `TileLibraryUnit` compatibility surface carrying only the runtime data and lookups needed for normal scene work
- that compatibility surface now also carries the runtime-relevant metadata explicitly promoted from staged source manifests: source-pack identity, selected source tileset / tilesheet identity, named module-context axes when declared, effective render traits, and any documented hints that were explicitly promoted for runtime/tooling use
- loaded units are wrapped in `TileLibraryRegistry`, which owns cross-unit construction and alias lookup
- hot-path runtime tasks such as variant-backed tileset registration, ref resolution, construction lookup, and bounds-aware validation now go through that compatibility surface instead of reaching straight through the raw family object
- behavioural tests now also prove that once those compatibility units are built, ordinary runtime scene work still succeeds even if the staged source manifests and ingest/layout manifests are removed from disk

Projects still own:

- patterns
- box styles
- scene templates
- local extra tilesets such as utility undercoats

Inspect/export/audit tooling may still use the richer source-shaped family object directly, but normal runtime composition should treat the compatibility view as the primary boundary.

## Scene Entity Runtime

Scene templates now preserve entity identity instead of lowering `entity` ops directly to stamp ops.

- `scene_templates.py` expands a scene into ordinary scene ops plus unresolved entity requests
- `minimal8_harness.py` resolves those requests against the selected family into first-class entity instances
- each entity instance now carries an explicit placement anchor plus occupied-cell and affordance-cell sets
- rendering still lowers entity instances to stamp ops as the final step

This keeps the runtime honest about the distinction between:

- source-layout collections
- constructions
- derived entity templates
- placed scene entities
- render-time stamp ops

## Public Pack Exports

Family-backed public tile-pack export now includes:

- `entity_templates.json`
  - derived runtime entity templates backed by authored constructions
- `constructions.json`
  - public construction payloads for legal multi-tile arrangements

## Review-Pack Workflow

1. Export a review pack from the family-backed catalog.
2. Annotate `review_notes.md` in plain English.
3. Translate those notes into:
   - `tiles.json`
   - `aliases.json`
   - `clusters.json` when sheet-group meaning becomes clearer

The engine does not parse freeform human notes automatically in this pass.

## Module-Level Documentation

The functional content of the codebase is also documented co-located with the modules and tracks themselves:

- [scripts/README.md](../../scripts/README.md) — shared engine modules: harness CLI, tile-family loader, scene-template DSL, scene-rules loader, and render output helpers.
- [scripts/source_manifests.py](../../scripts/source_manifests.py) — staged source-side pack / tileset / logical-tilesheet manifest loader and validator for the current ingest model.
- [scripts/source_manifest_bridge.py](../../scripts/source_manifest_bridge.py) — transitional one-way adapter from staged source manifests into `TileFamily` / `TileLibraryUnit` compatibility inputs.
- [prototypes/minimal8-harness/README.md](../../prototypes/minimal8-harness/README.md) — main prototype track: layout / scene / pattern / box-style authoring conventions and harness commands.
- [experiments/202605-minimal8-scene-experiments/README.md](../../experiments/202605-minimal8-scene-experiments/README.md) — exploratory scene-composition experiment track (not canonical).
- [scripts/reference_grid.py](../../scripts/reference_grid.py) — reference-sheet review helper: turn a resolved render-grid transform into a repeatable crop/contact-sheet/guide-overlay workflow for screenshots and title screens.
- [scripts/reference_tile_match.py](../../scripts/reference_tile_match.py) — reference matching helper: compare the recovered `8x8` reference cells to a chosen family variant source sheet and report exact matches, candidate matches, and unresolved cells.

## Tests As Documentation

Behavioural tests are part of the functional layer — they document what the system does, executably. They live under [tests/](../../tests):

- [test_tile_families.py](../../tests/test_tile_families.py) — family-package loading, address parsing, alias resolution, construction loading and validator behaviour (adjacency / exposure rules, parametric-run validation).
- [test_source_manifests.py](../../tests/test_source_manifests.py) — staged source-side pack / tileset / logical-tilesheet manifest loading and validation, including explicit sparse-coverage checks for render variants.
- [test_source_manifest_bridge.py](../../tests/test_source_manifest_bridge.py) — one-way source-manifest bridge coverage: synthetic adapter fixtures plus equivalence checks against the current Minimal 8 family-backed runtime shape.
- [test_scene_expansion.py](../../tests/test_scene_expansion.py) — scene-template DSL: expression evaluator, data-mode expansion, `entity` / `place_scene` / `scatter` ops, binding isolation, cycle detection.
- [test_minimal8_harness.py](../../tests/test_minimal8_harness.py) — harness-level expansion (entity stamps, parametric-run lowering) and end-to-end render contracts.
- [test_prototype_output.py](../../tests/test_prototype_output.py) — staged render output and archive-on-diff behaviour.
- [test_reference_grid.py](../../tests/test_reference_grid.py) — render-grid crop math, exact base-tile recovery from scaled screenshots, and non-destructive guide overlay placement.
- [test_reference_tile_match.py](../../tests/test_reference_tile_match.py) — exact duplicate detection, structural candidate scoring, and no-match classification for recovered reference cells.

Test naming follows the `test_<unit>_<behaviour>` convention; each test reads as a behavioural claim. Run the engine tests with the repo-local virtual environment:

```bash
.venv/bin/python -m unittest tests.test_tile_families tests.test_minimal8_harness tests.test_scene_expansion tests.test_prototype_output
```

To inspect line and branch coverage across the shared Python scripts:

```bash
bash scripts/check_coverage.sh
```
