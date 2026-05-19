# Source-Sheet Ingestion Model

This note defines the intended split between source-sheet structure and tile
semantics.

Current phase note:

- `scripts/source_manifests.py` now models staged pack / tileset / logical-tilesheet source manifests directly
- `scripts/source_manifest_bridge.py` is the temporary one-way adapter that feeds those staged source manifests into the current family-backed compatibility/runtime path
- Minimal 8 project loading now enters through the staged source-pack manifests rather than a direct family path
- the current Minimal 8 tilesheet manifest still points at `tile-families/minimal8/ingestion.json` for the source-layout payload during transition
- runtime scene work still must not depend on source-manifest files after compatibility units are built

## Problem

The earlier Minimal 8 ingest overloaded runtime semantic regions with
source-sheet geometry. That caused several failures:

- the first two source columns were truncated
- utility / bookkeeping groups were drawn like real source clusters
- headings and other non-tile art were not represented explicitly
- multi-tile entities had to be implied through per-tile metadata

## Model

The ingestion stack should separate two layers:

1. **Source-sheet layout layer**
   - sheet bounds
   - ingest regions
   - clusters within each region
   - optional ignore regions
   - logical collections
2. **Semantic metadata layer**
   - tile meanings
   - thematic clusters
   - aliases
   - scene-facing composition metadata

That gives us a stable way to describe any sprite sheet even when its visible
layout differs from Minimal 8.

## Concepts

### Ingest Regions

Top-level bounded areas of the sheet that are eligible for tile ingest.

- Minimal 8 currently uses four visible source columns as ingest regions.
- A future sheet might instead use blocks, panels, or islands of art.

### Clusters

Bounded subgroups inside an ingest region.

- Usually row bands separated by a blank tile row.
- Sometimes vertical strips separated by a blank tile column.
- They exist to preserve the artist's grouping, not to replace semantic
  clusters such as `indoors.*`.

### Ignore Regions

Bounded areas that should never be ingested as tiles even if they contain
visible pixels.

- headings
- signatures
- palettes
- decorative labels

For Minimal 8, the preferred steady state is simpler: regions define the ingest
surface, and everything outside those regions is simply not ingested. Ignore
regions remain available as an escape hatch for sheets that cannot be described
cleanly with positive region bounds alone.

### Tiles

Grid cells that fall inside an ingest region and outside every ignore region.

For Minimal 8 specifically, tile ownership must always be resolved against the
authoritative **8x8 grid**. The artist states that the artwork is intentionally
drawn as **7x7 inside those 8x8 cells**, so visible pixel mass is not a safe
proxy for tile bounds. Sparse corner pixels, asymmetric-looking art, and
underfilled tiles still belong to their full grid-aligned cell. Runtime
placement should also remain on that same **8x8** grid; the `7x7` fact is about
art inset, not tile stride. The default visual anchoring is **bottom-left**,
which means the intentional 1-pixel gutter normally sits on the **top** and
**right** edges of the tile cell.

### Collections

Logical multi-tile groupings that sit above individual cells.

Examples:

- 2x2 door assemblies
- extensible wall or border kits
- table systems
- repeated floor-feature families

Collections are part of the source-sheet layout layer because they describe how
authored cells belong together before any scene or alias logic consumes them.

Collections should use typed member references so the source of truth is
explicit:

- `tile_id` for a specific canonical tile record
- `alias` for a semantic alias that may later retarget
- `sheet_cell` for raw source-sheet coordinates when the source-layout layer
  must stay honest about unresolved semantic mapping

### Synthetic Tiles

Synthetic tiles live in the **semantic tile database layer**, not the
source-sheet ingestion layer.

They are useful when we want to:

- derive a repeatable middle slice from an authored endcap
- make a clean variation of an existing canonical tile
- introduce an entirely new tile that never existed as a source-sheet cell

Synthetic tiles should therefore follow these rules:

- they do **not** need source-sheet ingest semantics such as source regions,
  source clusters, or source-sheet collection membership
- they **do** need the same rich semantic metadata as canonical tiles:
  meaning, confidence, thematic clusters, aliases, composition roles,
  connectivity, and scene-facing usage notes
- they should carry explicit provenance describing how they were created
  and what canonical art they relate to
- generation must be reproducible from clear metadata rather than relying on
  an undocumented one-off asset edit
- for Minimal 8 specifically, they should normally preserve the same
  **bottom-left anchored 7x7-in-8x8** look:
  - keep the intentional 1-pixel gutter on the **top** and **right** edges
  - only fill or cross those edges when deliberately matching a known
    canonical exception

The current bookshelf middle slice is the first example of this class. It
should be treated as a proving case for a broader synthetic-tile pipeline, not
as a special exception.

## Detection Goals

The detection engine should *suggest* source-sheet structure, not silently
overwrite it.

Desired automatic suggestions:

- top-level ingest regions from contiguous occupied column bands
- cluster candidates from horizontal or vertical whitespace splits
- non-empty tile coverage inside those bounds
- multi-tile component candidates from connected occupied-cell groups

Minimal 8's current colored-background sheet should be the first proving case
for that model.

For Minimal 8, any detection or review workflow that attempts to infer tile
ownership from connected visible pixels instead of the 8x8 grid is wrong.

## Review Workflow

Collection review feedback should be exported into a committed repo path rather
than `scratch.local`.

- The pack itself is a generated scaffold.
- Each export creates a new committed round rather than overwriting the prior one.
- The reviewer edits the per-collection Markdown files in that round in place.
- Changes are committed so feedback, corrections, and decisions remain durable
  and versioned instead of being overwritten by the next export run.
