# User Documentation

## Main Workflows

For the current architecture, read the command surfaces this way:

- use `python3 scripts/source_ingest.py ...` for source-sheet ingest, reference review, and semantic review work
- use `python3 scripts/harness.py ...` for runtime/composition work such as rendering layouts or inspecting resolved scenes

### Ingest a new sprite family

1. Prepare a grid-aligned source sheet.
2. Run `python3 scripts/harness.py bootstrap-family <sheet> <output_dir> --tile-width <w> --tile-height <h>`.
3. Treat the generated family bundle as the current compatibility/bootstrap layer, not the final source-side entrypoint.
4. Fill in the generated compatibility bundle:
   - `family.json` for grid and variant metadata
   - `ingestion.json` for source-sheet regions, clusters, and collections
   - `clusters.json` for semantic groupings on the sheet
   - `tiles.json` for per-tile semantics
     and direct `sheet_col` / `sheet_row` provenance on sheet-backed tiles
   - `aliases.json` for canonical semantic names
5. Hand-author the staged source-pack manifests after bootstrap so they point at that populated bundle:
   - `pack.json`
   - `tilesets/<name>.json`
   - `tilesheets/<name>.json`
6. Point projects at the staged source-pack entrypoint with `tile_family.source_pack`, `tileset_id`, and `tilesheet_id`.

### Inspect a family or selected variant

Run:

```bash
python3 scripts/source_ingest.py inspect-family \
  prototypes/minimal8-harness/project.minimal8.source.json \
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

For the committed Minimal 8 family, the current checked-in human reference
copies live beside the family metadata at:

- `prototypes/minimal8-harness/tile-families/minimal8/sheet_grid.png`
- `prototypes/minimal8-harness/tile-families/minimal8/source_layout.guide.png`

### Export a human review pack

Run:

```bash
python3 scripts/source_ingest.py export-review-pack \
  prototypes/minimal8-harness/project.minimal8.source.json \
  --tileset 'minimal8@1bit_colored_bg' \
  --scene tavern \
  --category furniture \
  --category fixture \
  --category door
```

Use the generated `review_notes.md` to write plain-language corrections per tile. Do not encode metadata by hand unless you want to.

### Export a clean runtime tilesheet

Run (runtime-side, no ingest inputs required):

```bash
python3 scripts/harness.py export-clean-tilesheet \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg' \
  --type canonical-reference
```

Two `--type` values are supported:

- `canonical-reference` — clean atlas PNG + rich `metadata.json` + manifest.
  Accepts an optional `--scale N` multiplier (e.g. `--scale 4` for a 4× preview).
- `tiled` — game-engine Tiled `.tsx` tileset alongside the atlas sheet.
  Scale is not accepted; Tiled exports are native 1× engine-import artefacts.

Both types write to `prototypes/minimal8-harness/scratch.local/clean-tilesheets/`
by default (override with `--output-dir`). The export reads committed
runtime-family assets only — ingest inputs (`tiles.json`, vendor source sheets,
`ingestion.json`) are not required and are never read.

### Inspect resolved scene entities

Run:

```bash
python3 scripts/harness.py inspect-layout-scene \
  prototypes/minimal8-harness/layouts/fool_and_flintlock.json
```

This exports a JSON runtime snapshot that keeps scene entities intact before the renderer lowers them to stamp ops. Use it when you need to inspect:

- resolved construction choices
- entity placement anchors, bounds, and true occupied-cell footprints
- param values such as run length
- per-entity tile placements and affordance-bearing cells

### Choose a colorway when composing scenes

Projects select a default family variant in `tile_family.variant_id`.

The production runtime project (`project.minimal8.json`) loads committed
runtime-family JSON directly via `runtime_asset`:

```json
{
  "tile_family": {
    "runtime_asset": "./runtime-families/minimal8.json",
    "family_id": "minimal8",
    "variant_id": "1bit_colored_bg"
  }
}
```

The source-ingest operator project (`project.minimal8.source.json`) uses
`source_pack` instead, which points at the staged pack / tileset / tilesheet
hierarchy and feeds source-side tooling (inspect, review-pack, ingest
validation):

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

Direct `tile_family.path` loading still exists as a transitional fallback for
legacy family packages.

You can still explicitly reference another loaded variant using direct sheet address syntax:

- `minimal8@1bit_red:44,12`
- `minimal8@2bit_colored_bg:68,9`

When the tile is already catalogued, prefer a variant-qualified semantic ref
instead of dropping to raw source coordinates:

- `minimal8@2bit_colored_bg_green:indoors.table.long.left`
- `minimal8@2bit_colored_bg_green:minimal8:terrain:4,32`

That keeps the tile identity stable while making the colourway choice explicit.
It is the preferred way to say “use the same tile, but from the green/orange/red
sibling sheet”.

If you need a raw tileset cell that is not catalogued as a family tile, use `tileset_id#col,row`:

- `minimal8@1bit_colored_bg#20,24`
