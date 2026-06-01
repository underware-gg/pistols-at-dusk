# Minimal 8 Layout Engine

This prototype is now built around the normal retro workflow:

- slice a sheet on an exact logical grid
- refer to cells by tile ID or `col,row`
- define larger reusable `patterns`
- build maps as layered tile layouts
- crop a viewport for export

For Minimal 8 specifically, the project now uses an exact `8x8` source grid and
renders on that same `8x8` grid. The artwork may underfill the cell because the
asset is drawn as `7x7` art within `8x8` ownership cells, but tile placement
and runtime composition still snap to the full `8x8` grid.

For this family, the normal art anchor is **bottom-left**: the intended
1-pixel gutter usually sits on the **top** and **right** edges of each tile.
Synthetic tiles should preserve that same top-right gutter unless they are
deliberately matching a canonical exception.

## Files

- [project.minimal8.json](project.minimal8.json)
- [project.minimal8.characters.json](project.minimal8.characters.json)
- [pattern-migration-inventory.md](pattern-migration-inventory.md)
- active source-pack entrypoint:
  - [tile-packs/minimal8/pack.json](tile-packs/minimal8/pack.json)
  - [tile-packs/minimal8/tilesets/minimal8.json](tile-packs/minimal8/tilesets/minimal8.json)
  - [tile-packs/minimal8/tilesets/characters.json](tile-packs/minimal8/tilesets/characters.json)
- [tile-packs/minimal8/tilesheets/main.json](tile-packs/minimal8/tilesheets/main.json)
- [tile-packs/minimal8/tilesheets/characters.json](tile-packs/minimal8/tilesheets/characters.json)
- transitional compatibility bundle:
  - [tile-families/minimal8](tile-families/minimal8)
  - [tile-families/minimal8/ingestion.json](tile-families/minimal8/ingestion.json)
  - [tile-families/minimal8-characters](tile-families/minimal8-characters)
- canonical reference transforms:
  - [reference-transforms/README.md](reference-transforms/README.md)
  - [reference-transforms/reference-overworld-island-title-screen.json](reference-transforms/reference-overworld-island-title-screen.json)
  - [reference-transforms/reference-overworld-island-title-screen.md](reference-transforms/reference-overworld-island-title-screen.md)
  - [reference-transforms/reference-polychrome-temple-courtyard.json](reference-transforms/reference-polychrome-temple-courtyard.json)
  - [reference-transforms/reference-polychrome-temple-courtyard.md](reference-transforms/reference-polychrome-temple-courtyard.md)
  - [reference-transforms/reference-party-menu-character-stats.json](reference-transforms/reference-party-menu-character-stats.json)
  - [reference-transforms/reference-party-menu-character-stats.md](reference-transforms/reference-party-menu-character-stats.md)
- [assets/utility_land_undercoat.png](assets/utility_land_undercoat.png)
- [tile_families.py](../../scripts/tile_families.py)
- [minimal8_engine_smoke.json](layouts/minimal8_engine_smoke.json)
- [temple_sanctum.json](layouts/temple_sanctum.json)
- [polychrome_temple_courtyard.json](layouts/polychrome_temple_courtyard.json)
- [twin_chambers.json](layouts/twin_chambers.json)
- [causeway_approach.json](layouts/causeway_approach.json)
- [fool_and_flintlock.json](layouts/fool_and_flintlock.json)
- [island_overlook.json](layouts/island_overlook.json)
- [scene_template_showcase.json](layouts/scene_template_showcase.json)
- [minimal8_harness.py](../../scripts/minimal8_harness.py)
- [scene_templates.py](../../scripts/scene_templates.py)

## Current Confidence

- `fool_and_flintlock` is the only current composed-scene output that should be
  treated as a trustworthy visual anchor.
- `reference-overworld-island-title-screen.*` and
  `reference-polychrome-temple-courtyard.*` are trusted **reference-ingest**
  artefacts, and `island_overlook` / `polychrome_temple_courtyard` are now
  direct tile reconstructions authored from those committed reference solves.
  Treat them as trusted reference-backed visual anchors, not as proof that the
  higher-level semantic scene-authoring layer is solved for those spaces yet.
- `project.minimal8.characters.json` and the `minimal8.characters` source pack /
  compatibility family are the active scaffold for the separate Characters
  sheet. That track is intentionally **not** treated as a settled source-layout
  ingest yet: the pack bridge is committed, but the sheet structure still needs
  a manual pass before we land source regions, ignores, collections, or runtime
  actor constructions.
- `reference-party-menu-character-stats.*` is now the canonical reviewed
  handoff for that screen, and `party_menu_character_stats` is the tracked
  data recreation of that reviewed tile-and-colour truth. The only intentional
  difference is `C31R17`, where the recreation keeps a brown tree trunk
  instead of the green reference colour.
- The remaining generated scene outputs are historical prototype attempts. They
  may still be useful as engine smoke fixtures or idea sketches, but they are
  not trustworthy scene references and should not be used to judge layout
  quality.

## Reference Syntax

Single tile:

- `minimal8@1bit_colored_bg:149`
- `minimal8@1bit_colored_bg:19,9`
- `minimal8:terrain:0,7`
- `19,9` if the layout sets `default_tileset`

Pattern:

- `@meander_band`
- `@door_arch`

Transformed ref:

- `{"ref": "@gold_ui_corner", "flip_x": true}`
- `{"ref": "55,5", "flip_y": true}`
- `{"ref": "prop.torch", "underpaint": "tavern.wall.a"}`
- `{"ref": "prop.tankard", "underpaint": "indoors.table.round", "offset_left": 1, "offset_bottom": 1}`

Composite single-tile refs can optionally use `underpaint` to precompose a
backing tile underneath the main tile before normal layer rendering. This is
useful for wall props and overlays where transparent gaps should reveal a chosen
supporting surface rather than whatever lower scene layer happens to be
present. Layered refs can also use `offset_left` and `offset_bottom` to shift
the foreground sprite relative to its anchor cell without clipping it back into
the 8x8 grid box, which is useful for perspective placement like drinks
resting on tables or counters.

This visual overflow is a rendering feature for single-tile props and fixtures
only. Logical placement, blocking, and scene occupancy still belong to the
anchor cell. True multi-cell entities such as doors, counters, shelves, and
other entity-like arrangements should continue to use constructions, while
project-level reusable non-entity snippets live under `patterns`. The committed
routing inventory for the historical registry now lives in
[pattern-migration-inventory.md](pattern-migration-inventory.md). Actor
occupancy and seated-pose composition remain a separate future layer.

## Supported Layer Ops

- `stamp`: place one tile or one pattern at `x,y`
- `fill`: tile a rectangle using a tile or pattern
- `mask_fill`: tile only the non-blank cells of a hand-authored mask shape
- `scatter`: sparsely stamp one or more refs across a hand-authored mask using a seed
- `repeat`: place the same tile or pattern `count` times using `dx,dy`
- `entity`: place a construction at `(x, y)` — e.g. a `parametric_frame` border kit for a room/corridor frame — optionally with `params` (width/height) and a `variant_id`
- `ascii`: compact grid authoring for tile placement

`mask_fill` is the important new primitive for overworld / shoreline work. It
lets a layout author paint an irregular land silhouette with an opaque
undercoat first, then layer decorative sparse terrain on top without letting
water lines bleed through the landmass.

## Scene Templates

Layouts can also declare a top-level `scenes` array. Those scene specs expand
into the lower-level layer ops at render time, so you can describe room grammar
instead of hand-placing every wall section.

Current built-ins:

- `sanctum`: outer shell, inner chamber, centered door
- `twin_chambers`: left/right rooms with a connector bridge
- `causeway`: water field, island room, lower stem, centered door
- `tavern`: Fool & Flintlock-style room with semantic floor, bar-back, counter, tables, patrons, and front door

The engine merges generated scene layers with any explicit `layers` in the
layout JSON, which keeps it easy to mix high-level composition with manual
ornament passes.

File-backed template loading, validation, expression evaluation, and data-mode
scene expansion now live in
[scene_templates.py](../../scripts/scene_templates.py),
while [minimal8_harness.py](../../scripts/minimal8_harness.py)
provides the project-specific runtime callbacks and render pipeline.

Scene templates now come in two modes:

- `mode: "code"` keeps behavior in a Python expander while the template file owns identity and parameter metadata.
- `mode: "data"` keeps both the template identity and the emitted scene ops in JSON.

The current worked example is [scene-templates/causeway.json](scene-templates/causeway.json). It uses:

- `bindings` for named derived values
- small expression objects such as `{"param": "width"}`, `{"add": [...]}`, and `{"centered_x": {...}}`
- `when_present` for optional branches

`when_present` currently preserves the old scene-template semantics after
defaults are applied: `null`, `false`, and `""` disable an optional branch.
That is why `stem_style: ""` and `door_ref: null` suppress those causeway ops
without needing a larger conditional DSL.

## Scene Rulesets

The harness now has a separate environment-specific proc-gen layer under
`scene-rules/`.

Use this layer when the question is not "what is this tile?" but "what kinds of
thing should appear in a tavern / temple / shop, and how often?".

The intended split is:

- `tiles.json`: generic semantic truth about individual tiles
- `constructions.json`: legal reusable multi-tile entities
- `scene-templates/*.json`: authored room structure and slot locations
- `scene-rules/*.json`: weighted environment-specific candidate catalogues

Scene templates can now declare `slot_groups` and use a `populate_slots` op.
That keeps the first proc-gen foundation very small and explicit:

- the template defines **where** something may go
- the ruleset catalogue defines **what** kinds of thing may appear there
- reusable fragment templates define **how multiple things relate**

Candidate kinds are:

- `stamp`: place one tile ref
- `entity`: place one construction
- `scene`: place one reusable scene-template fragment

Selection is deterministic by seed. This first pass is intentionally slot-based,
not a general room-packing solver.

The current worked example is the tavern:

- [scene-rules/tavern.json](scene-rules/tavern.json)
- [scene-templates/tavern.json](scene-templates/tavern.json)
- [scene-rules/README.md](scene-rules/README.md)

## Seat Naming

The backless single-seat tiles in the reviewed furnishing row are now
canonicalised as `indoors.stool`.

`indoors.bench.*` still exists, but only as a compatibility alias and alternate
human reading for the same underlying art. It is not a separate behavioural
system. In this harness there is just one gameplay concept there: a single-seat
backless furnishing tile that a character can occupy.

## Frame Kits

Room shells, corridors, platforms, and shrine chambers are framed with
**`parametric_frame`** border kits — family-owned constructions that live in the
tileset's `constructions.json` beside `metatile` and `parametric_run` (see
[docs/architecture/construction-system.md](../../docs/architecture/construction-system.md)).
A frame kit binds tiles to the nine border roles (corners, edges, optional
fill), supports per-slot flip-derivation and fat (NxM) corners, and renders at
any size. The Minimal 8 kits include `ui.frame.gold_room` (fat 2x2 gold
corners), `ui.frame.glyph_stone` (single-tile glyph corners), and the party
menu's `ui.frame.outer_screen` / `ui.frame.inner_window`.

A layout or scene places a frame through the `entity` op, supplying the size via
`params`; the floor is a separate `fill` op inset by the corner extent:

```json
{ "kind": "entity", "construction": "ui.frame.gold_room", "x": 13, "y": 9,
  "params": { "width": 27, "height": 16 } },
{ "kind": "fill", "ref": "@temple_floor_sparse", "x": 15, "y": 11, "width": 23, "height": 12 }
```

This is the same construction/entity pipeline used for furniture and actors —
there is no separate border subsystem.

## Useful Commands

Bootstrap a brand new compatibility family bundle from any grid-aligned sheet:

```bash
python3 scripts/minimal8_harness.py bootstrap-family \
  "resources/Super Assets 3000/Minimal 8/1bit png/minimal_8 v2.1_1bit-1_bit_-_colored.png" \
  prototypes/minimal8-harness/scratch.local/example-family \
  --tile-width 8 \
  --tile-height 8
```

That command still scaffolds the family-shaped compatibility bundle. The staged
source-pack manifests remain the primary committed entrypoint and currently need
to be added around that bundle explicitly.

Scaffold a pattern snippet from a selected grid rectangle:

```bash
python3 scripts/minimal8_harness.py scaffold-pattern \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset minimal8_bg_1bit_colored \
  --name door_arch \
  --x 2 \
  --y 11 \
  --width 4 \
  --height 3
```

Inspect the selected family variant and get the real tile catalog:

```bash
python3 scripts/source_ingest.py inspect-family prototypes/minimal8-harness/project.minimal8.json --tileset 'minimal8@1bit_colored_bg'
```

Validate the full ingest contract for the canonical review sheet:

```bash
python3 scripts/source_ingest.py validate-family-ingest prototypes/minimal8-harness/project.minimal8.json --tileset 'minimal8@1bit_colored_bg'
```

That report now machine-checks that every Minimal 8 tile record has a
`source_group`, at least one `cluster_id`, a non-empty `meaning`, and an
explicit `meaning_confidence`. The report also shows the confidence
distribution so a first-pass catalog full of tentative guesses does not
masquerade as fully-confirmed ingest. The `1bit_colored_bg` sheet is the
canonical first-pass review evidence source for that ingest, but the resulting
semantics still live at family level and are shared across the sibling color
variants.

Minimal 8 currently uses a dual-axis cluster model:

- `minimal8:cluster:source.*` clusters describe where a tile sits in the
  source-sheet column / gap-separated cluster structure.
- curated thematic clusters such as `indoors.*` and `icons_and_items` describe
  higher-level reuse semantics that can cut across those source bands.

That means `cluster_count` is an ontology count, not a clean source-sheet
partition count, and individual tiles can intentionally carry more than one
`cluster_id`.

Minimal 8 now enters through staged source manifests in
[tile-packs/minimal8/pack.json](tile-packs/minimal8/pack.json),
[tile-packs/minimal8/tilesets/minimal8.json](tile-packs/minimal8/tilesets/minimal8.json),
and [tile-packs/minimal8/tilesheets/main.json](tile-packs/minimal8/tilesheets/main.json).
The current tilesheet manifest still points at
[tile-families/minimal8/ingestion.json](tile-families/minimal8/ingestion.json)
for the source-layout payload through the current transitional
compatibility/source-layout adapter:

- `regions` describe the top-level ingest areas on the raw sheet
- `clusters` describe bounded subgroups inside those regions
- optional `ignore_regions` can subtract non-tile content when a sheet cannot be described cleanly by region bounds alone
- `collections` describe larger logical constructs built from multiple cells
  using typed member refs (`tile_id`, `alias`, or `sheet_cell`)

Synthetic tiles are now a first-class semantic concept as well:

- they can be derived from canonical source-sheet art or created entirely new
- they do not need to pretend they came from an ingest region or source-sheet
  cluster
- they still participate fully in the tile database with normal semantic
  metadata, aliases, composition roles, and scene-facing usage notes
- when generated, they should carry clear provenance and reproducible metadata
  instead of behaving like undocumented one-off assets

That source-layout layer is intentionally separate from the semantic
`source.*` / `indoors.*` cluster ontology. The source layout answers "where is
the art on the sheet?" while the semantic clusters answer "what does this art
mean and how is it reused?"

When a human description starts from the raw sheet layout — for example "top
section of the second source-sheet column, third tile from the left" — do not
guess from review strips or from family tile IDs alone. Start with the
authoritative source-layout map instead:

```bash
python3 scripts/source_ingest.py inspect-source-cell \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@2bit_colored_bg' \
  --sheet-col 21 \
  --sheet-row 4
```

That reports the zero-based source-sheet cell, its source-layout region and
cluster, and any mapped family tile in one JSON payload. It also makes the
important context boundary explicit: source-layout cluster IDs are about
physical sheet structure, while semantic `cluster_ids` on the tile record are
about reuse meaning and can legitimately describe a different grouping.

Audit the current alias / project reference surface against those confidence
values:

```bash
python3 scripts/source_ingest.py audit-family-semantic-usage prototypes/minimal8-harness/project.minimal8.json --tileset 'minimal8@1bit_colored_bg'
```

That report surfaces family aliases, project aliases, pattern cells,
and explicit layout refs that still land on non-confirmed family
meanings, so ingest can expose semantic contradictions instead of silently
papering them over.

Detect a first-pass source-layout suggestion directly from the bitmap:

```bash
python3 scripts/source_ingest.py detect-source-layout prototypes/minimal8-harness/project.minimal8.json --tileset 'minimal8@1bit_colored_bg'
```

That writes `source_layout.detected.json` with suggested regions, clusters, and
connected multi-tile component candidates derived from non-empty grid cells on
the canonical review sheet.

That inspection now also exports a pattern preview/contact sheet based on the
project spec, plus `tile_edges.json` and `seam_candidate_tiles.png` for
wall-family and edge-contact inspection.

By default those inspection files live under `prototypes/minimal8-harness/scratch.local/inspect/`.

The inspect folder keeps those canonical outputs at top level. One-off contact
studies and tile boards belong under `studies/`.

Query the semantic catalog directly:

```bash
python3 scripts/minimal8_harness.py query-semantic prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg' \
  --scene tavern \
  --category floor \
  --contrast low
```

Render the sample layout:

```bash
python3 scripts/minimal8_harness.py render-layout prototypes/minimal8-harness/layouts/minimal8_engine_smoke.json
```

Render all current samples:

```bash
python3 scripts/minimal8_harness.py render-all prototypes/minimal8-harness/layouts
```

Render the current tavern scene:

```bash
python3 scripts/minimal8_harness.py render-layout prototypes/minimal8-harness/layouts/fool_and_flintlock.json
```

If the target output already exists, the harness writes the new render to a temporary file first. When that staged file is byte-for-byte identical to the current canonical output, the staged file is discarded and no archive entry is created. When it differs, the previous render is archived to `generated/archive/` using a four-digit sequence such as `fool_and_flintlock-0001.png`, `fool_and_flintlock-0002.png`, and then the staged render replaces the canonical filename.

Export a Tiled-ready `8x8` kit:

```bash
python3 scripts/minimal8_harness.py export-tiled-kit prototypes/minimal8-harness/project.minimal8.json --tileset 'minimal8@1bit_colored_bg'
```

The Tiled kit now contains:

- `cells.tsx` for raw `8x8` cells from the full spritesheet import
- `patterns.tsx` for larger reusable structures and snippets derived from the project spec
- `starter_c64_room.tmj` with tile layers plus object layers for prefab use

By default that kit is written under `prototypes/minimal8-harness/scratch.local/tiled-kit/`.

The current Minimal 8 project is configured with `catalog_scope: "all"`, so
inspection and Tiled export include every non-empty sprite on the source sheet,
not just the hand-marked regions.

Export a filtered semantic review pack for manual naming / composition passes:

```bash
python3 scripts/source_ingest.py export-review-pack \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg' \
  --scene tavern \
  --category furniture \
  --category fixture \
  --category door \
  --output-dir prototypes/minimal8-harness/scratch.local/review-packs/tavern-furniture
```

That produces:

- `tiles/` with scaled tile copies named from the current semantic guess
- `index.md` and `index.json` with category / composition metadata
- `review_notes.md` as a human-editable annotation doc
- `contact_sheet.png` for fast visual scanning

Export a committed collection review pack for source-layout refinement:

```bash
python3 scripts/source_ingest.py export-collection-review-pack \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@1bit_colored_bg'
```

That writes under
`prototypes/minimal8-harness/reviews/collections/<slug>/` by default. Each
export creates a new committed round under `rounds/round_001/`,
`rounds/round_002/`, and so on. Each round includes:

- `manifest.json` with the authored collection metadata and resolved member cells
- `README.md` linking to the collection notes
- `images/*.png` cropped previews from the canonical review sheet
- `collections/*.md` feedback files intended to be edited and committed

This is the durable path for collection cleanup. Unlike `scratch.local`, these
review packs are meant to be versioned in git so collection feedback does not
get lost when a new export is generated later. New rounds are additive rather
than overwrite-in-place.

The project now points at a staged source-pack entrypoint that bridges into a
shared compatibility family bundle plus the generic tile-family loader. That
combined metadata layer gives the harness and any scene-layout experiments one
shared understanding of things like quiet floors, tavern fixtures, underworld
walls, door variants, usage, contrast, clusters, and semantic aliases.

Command surface rule of thumb:

- use `python3 scripts/source_ingest.py ...` for source-sheet ingest, review, and reference-tracing work
- use `python3 scripts/minimal8_harness.py ...` for runtime/composition work such as rendering layouts, exporting scene runtimes, or scaffolding project patterns

That means the inspect/export path is no longer just geometry:

- `catalog.json` now carries semantic fields where available
- `semantic_catalog.json` exports the canonical tile metadata directly
- `semantic_catalog.png` gives a quick contact-sheet view of the tagged tiles
- `query-semantic` lets an agent ask for tiles by meaning instead of raw coordinates

## Why This Is Better

The engine no longer depends on hand-cut scene-specific crops.

Instead it works from:

1. sheet metadata
2. grid coordinates
3. reusable patterns
4. logical map layers
5. editor-facing exports for both cells and patterns

That makes it reusable for this sheet and for other grid-based sheets later.
