# Functional Documentation

## Sprite-Family Package Format

Each family package is a directory with source-of-truth manifests for variant metadata, source-sheet layout, semantics, and aliases:

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

Current Minimal 8 package:

- [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8)

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

Projects do not own sheet semantics anymore. They consume a family package and pick a default variant:

```json
{
  "tile_family": {
    "path": "./tile-families/minimal8",
    "family_id": "minimal8",
    "variant_id": "1bit_colored_bg"
  }
}
```

Projects still own:

- metatiles
- box styles
- scene templates
- local extra tilesets such as utility undercoats

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
- [prototypes/minimal8-harness/README.md](../../prototypes/minimal8-harness/README.md) — main prototype track: layout / scene / metatile / box-style authoring conventions and harness commands.
- [experiments/202605-minimal8-scene-experiments/README.md](../../experiments/202605-minimal8-scene-experiments/README.md) — exploratory scene-composition experiment track (not canonical).

## Tests As Documentation

Behavioural tests are part of the functional layer — they document what the system does, executably. They live under [tests/](../../tests):

- [test_tile_families.py](../../tests/test_tile_families.py) — family-package loading, address parsing, alias resolution, construction loading and validator behaviour (adjacency / exposure rules, parametric-run validation).
- [test_scene_expansion.py](../../tests/test_scene_expansion.py) — scene-template DSL: expression evaluator, data-mode expansion, `entity` / `place_scene` / `scatter` ops, binding isolation, cycle detection.
- [test_minimal8_harness.py](../../tests/test_minimal8_harness.py) — harness-level expansion (entity stamps, parametric-run lowering) and end-to-end render contracts.
- [test_prototype_output.py](../../tests/test_prototype_output.py) — staged render output and archive-on-diff behaviour.

Test naming follows the `test_<unit>_<behaviour>` convention; each test reads as a behavioural claim. Run the engine tests with the repo-local virtual environment:

```bash
.venv/bin/python -m unittest tests.test_tile_families tests.test_minimal8_harness tests.test_scene_expansion tests.test_prototype_output
```

To inspect line and branch coverage across the shared Python scripts:

```bash
bash scripts/check_coverage.sh
```
