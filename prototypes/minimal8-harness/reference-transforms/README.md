# Reference Transforms

Committed render-grid transforms for screenshot/reference images used by the
Minimal 8 harness.

These files are intended to be executable examples and durable ingest state for:

- [reference_grid.py](../../../scripts/reference_grid.py)
- [reference_tile_match.py](../../../scripts/reference_tile_match.py)

Each JSON file stores:

- the reference image path
- the compatibility family path and preferred variant when matching is useful
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
