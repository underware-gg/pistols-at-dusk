# User Documentation

## Main Workflows

### Ingest a new sprite family

1. Prepare a grid-aligned source sheet.
2. Run `python3 scripts/minimal8_harness.py bootstrap-family <sheet> <output_dir> --tile-width <w> --tile-height <h>`.
3. Fill in the generated family package:
   - `family.json` for grid and variant metadata
   - `ingestion.json` for source-sheet regions, clusters, and collections
   - `clusters.json` for semantic groupings on the sheet
   - `tiles.json` for per-tile semantics
     and direct `sheet_col` / `sheet_row` provenance on sheet-backed tiles
   - `aliases.json` for canonical semantic names

### Inspect a family or selected variant

Run:

```bash
python3 scripts/minimal8_harness.py inspect-family \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg'
```

This exports:

- `catalog.json`
- `sheet_grid.png`
- `non_empty_tiles.png`
- `clusters.json`
- `clusters.png`
- `semantic_catalog.json`
- `semantic_catalog.png`

### Export a human review pack

Run:

```bash
python3 scripts/minimal8_harness.py export-review-pack \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg' \
  --scene tavern \
  --category furniture \
  --category fixture \
  --category door
```

Use the generated `review_notes.md` to write plain-language corrections per tile. Do not encode metadata by hand unless you want to.

### Inspect resolved scene entities

Run:

```bash
python3 scripts/minimal8_harness.py inspect-layout-scene \
  prototypes/minimal8-harness/layouts/fool_and_flintlock.json
```

This exports a JSON runtime snapshot that keeps scene entities intact before the renderer lowers them to stamp ops. Use it when you need to inspect:

- resolved construction choices
- entity placement anchors, bounds, and true occupied-cell footprints
- param values such as run length
- per-entity tile placements and affordance-bearing cells

### Choose a colorway when composing scenes

Projects select a default family variant in `tile_family.variant_id`.

Current Minimal 8 example:

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

Legacy projects may still point `tile_family.path` at a direct family package while
Phase 4 migration remains in progress.

You can still explicitly reference another loaded variant using direct sheet address syntax:

- `minimal8@1bit_red:44,12`
- `minimal8@2bit_colored_bg:68,9`

If you need a raw tileset cell that is not catalogued as a family tile, use `tileset_id#col,row`:

- `minimal8@1bit_colored_bg#20,24`
