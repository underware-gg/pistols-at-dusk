# Reference Transforms

Committed render-grid transforms for screenshot/reference images used by the
Minimal 8 harness.

These files are intended to be executable examples and durable ingest state for:

- [reference_grid.py](../../../scripts/reference_grid.py)
- [reference_tile_match.py](../../../scripts/reference_tile_match.py) when a
  reference is genuinely ready for whole-cell matching

Each JSON file stores:

- the reference image path
- the candidate source family path(s) and preferred variant(s) when matching is
  useful
- either the solved grid origin/pitch or an exact tiled-body `span_box`, plus
  the logical `content_box`
- an optional `normalize_cell_size` for building a uniform ingest surface from
  awkward native reference spans
- any relevant tiled regions and exclusion zones needed to isolate the real tile
  body from headings or other non-tiled ornament
- whether partially visible edge cells should stay in the ingested sheet or be
  cropped away

## Current solves

- [reference-overworld-island-title-screen.json](reference-overworld-island-title-screen.json)
- [reference-overworld-island-title-screen.md](reference-overworld-island-title-screen.md)
- [reference-polychrome-temple-courtyard.json](reference-polychrome-temple-courtyard.json)
- [reference-polychrome-temple-courtyard.md](reference-polychrome-temple-courtyard.md)
  - active reviewed ingest config for the temple courtyard reference
  - uses normalized span ingest and committed manual review overrides
  - the current best source matches come from the `2bit_colored_bg` variant even
    though the reference visually appears to derive from the older 1-bit sheet
- [reference-party-menu-character-stats.json](reference-party-menu-character-stats.json)
- [reference-party-menu-character-stats.md](reference-party-menu-character-stats.md)
  - committed canonical handoff for the party-menu screen
  - captures the trusted `34 x 24` grid solve plus the reviewed tile-and-colour
    truth for the solved non-text cells
  - the tracked recreation now mirrors that reviewed truth, with one explicit
    intentional deviation at `C31R17` where the recreation keeps a brown trunk
    instead of the green reference colour

The JSON file is the executable ingest state. The sibling Markdown note is the
human-facing rationale: why we trust the reference, what is messy about it, and
how to interpret manual review decisions without replaying the whole debugging
history from chat.

## Usage

Render the solved crop/guide views:

```bash
python3 scripts/reference_grid.py \
  --config prototypes/minimal8-harness/reference-transforms/reference-overworld-island-title-screen.json \
  --output-dir /private/tmp/overworld-reference
```

Run the matcher against the same solved body:

```bash
python3 scripts/reference_tile_match.py \
  --config prototypes/minimal8-harness/reference-transforms/reference-overworld-island-title-screen.json \
  --output /private/tmp/overworld-reference/match.json
```

Matcher output now includes copy-pasteable refs for each exact/candidate tile:

- `physical_ref`: the stable family sheet cell, e.g. `minimal8:20,17`
- `variant_ref`: the same sheet cell on the matched sibling variant, e.g.
  `minimal8@2bit_colored_bg_green:20,17`
- `semantic_variant_ref`: the stable tile identity on that variant when the cell
  is catalogued, e.g. `minimal8@2bit_colored_bg_green:minimal8:terrain:1,15`

For colour-sensitive scene reconstruction, the matcher also emits a sibling
colourway recommendation on each exact/candidate match:

- `recommended_variant_id`
- `recommended_colorway`
- `recommended_variant_ref`
- `recommended_semantic_variant_ref`

That second pass runs only after tile identity has already been chosen. It keeps
shape/identity matching colour-light, then compares the reference cell's
foreground colours against the same sheet cell across sibling variants so a
reconstruction scene can use the best green/orange/red sibling without falling
back to ad hoc raw `#col,row` swaps.

For reference-review overrides, prefer recording a semantic tile plus explicit
`variant_id` when the tile identity is known and only the sibling colourway is
being corrected. Keep raw `source_cell` overrides for genuinely uncatalogued
cells or for exact source-sheet review work.

The slicer also writes a padded ingest guide beside the source image with a
`--guide` suffix. That checked-in sibling guide uses the same trimmed ingest
grid as the output-directory guide sheets, so excluded regions only appear when
they are inside the ingestable grid itself. The guide defaults to `separated`
line mode, which inserts thin grid lines between tiles instead of drawing over
source pixels; a compact `overlay` mode is also available when needed.

When a reviewed reference cell needs to be traced back to the raw source sheet,
use the source-side ingest CLI instead of guessing from the guide image or from
semantic tile IDs:

```bash
python3 scripts/source_ingest.py inspect-source-cell \
  prototypes/minimal8-harness/project.minimal8.json \
  --tileset 'minimal8@2bit_colored_bg' \
  --sheet-col 21 \
  --sheet-row 4
```

That reports the physical source-layout region/cluster and the mapped family
tile separately, which avoids confusing source-sheet structure with the tile
record's semantic `cluster_ids`.

When a sheet is dominated by multi-cell figures rather than one-cell semantic
tiles, start with the source-sheet inspection bundle instead of the semantic
review pack:

```bash
python3 scripts/source_ingest.py inspect-family \
  prototypes/minimal8-harness/project.minimal8.characters.json \
  --tileset 'minimal8.characters@2bit_colored'
```

When a committed source-layout map exists, that emits `source_layout.guide.png`,
a numbered zero-based source-sheet guide that makes it much easier to author or
review multi-cell collection blocks without guessing raw sheet coordinates from
the unlabelled art.

When `normalize_cell_size` is set, the slicer also writes a
`*_normalized_body.png` image and builds the guide/matcher surface from that
uniform normalized span instead of the raw uneven native crop.

Reference-ingest state must live in the repo once it becomes the active working
surface for a real reference. Scratch space is fine for throwaway experiments,
but another developer should be able to pick up a live ingest effort from the
checked-in config plus the checked-in `--guide` sibling image without needing
private `/tmp` history.

That means:

- canonical solved references belong here
- active in-progress reference ingests belong here once they become the working
  handoff surface
- only genuinely throwaway probes and abandoned experiments should stay local
