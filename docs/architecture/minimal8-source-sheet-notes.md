# Minimal 8 Source-Sheet Notes

## Raw User Observations

The following notes come directly from the user and should be treated as durable
source-sheet guidance for Minimal 8 ingest work.

- The sheet has four broad columns that carry semantic meaning.
- In this sheet, those columns are effectively the top-level ingest regions.
- Within each column, there are smaller gap-separated tile groups.
- Those smaller groups are the secondary clusters.
- A blank one-tile horizontal or vertical gap between groups is signal that the
  neighbouring groups are semantically different.
- Column counts for the canonical colored-background sheet are:
  - column 1: 5 clusters
  - column 2: 7 clusters
  - column 3: 8 clusters
  - column 4: 3 clusters
- Column 3 has a caveat: 6 of its 8 clusters are the character sets, and they
  are separated vertically rather than horizontally.
- The visible headings on the source sheet are cues, not tiles:
  - `tileset` spans the first two columns
  - `characters` labels the top section of the third column
  - `icons / items` labels the lower section of the third column
  - `UI` labels the fourth column
- The bottom-left `by algernon3000` signature is not tile content.
- The bottom-left color palette is not tile content and does not exist on the
  single-color sibling sheets.
- The canonical evidence sheet for first-pass ingest is:
  `minimal_8 v2.1_1bit_colored background-1_bit_-_colored.png`
- The eight sibling sheets share entity identity and grid placement even when
  the colors differ.
- The artist states that Minimal 8 is drawn as **7x7 artwork on an 8x8 tile
  grid**.
- That is a source fact, not a heuristic.
- The common anchoring pattern is **bottom-left**:
  - the artwork usually leaves its intentional 1-pixel gutter on the **top**
    and **right** edges of the 8x8 cell
  - some tiles deliberately touch one or both of those edges as exceptions, but
    the default synthetic-tile style should follow the bottom-left anchor
- Sparse or visually off-center pixels inside a correct 8x8 tile cell are
  expected and do not change which grid cell owns the art.
- Tiles can participate in larger logical collections:
  - 2x2 doors
  - natural or brick floor feature sets
  - extensible border kits with corners / middles / ends
  - furniture systems such as tables
- In this sheet, columns happen to act like regions. In a future sheet, the
  ingest regions may be arranged differently, but the concepts stay the same:
  regions, clusters, tiles, and collections.

## Refined Working Interpretation

- **Regions** are the top-level ingest areas on a sheet. On Minimal 8, the
  current regions are the four visible columns.
- **Clusters** are smaller bounded groups inside a region. On Minimal 8, these
  are usually row bands separated by one blank tile row, except in the
  characters section where several clusters are vertical strips.
- **Tiles** are the individual grid cells inside the ingested regions after
  explicit ignore regions are subtracted.
- Minimal 8 tile ownership is always determined by the **8x8 grid**, not by the
  visible pixel mass inside a tile.
- Because the artwork is intentionally drawn as 7x7 within those 8x8 cells,
  sparse-corner and slightly off-center drawings still belong fully to their
  grid-aligned tile rectangles.
- For synthetic tiles in this family, the default should be the same
  **bottom-left anchored 7x7-in-8x8** treatment:
  - preserve the 1-pixel gutter on the **top** and **right** edges
  - only break that rule when deliberately matching a canonical boundary-touching
    exception
- Runtime placement also uses that same **8x8** grid. The `7x7` fact describes
  how the art sits inside a tile cell, not a different placement stride.
- **Collections** are higher-level logical constructs built from multiple tiles,
  such as a 2x2 door or a corner / edge / middle border kit.
- **Ignore regions** are non-tile areas that still sit on the sheet grid, such
  as headings, the author credit, and the color palette.
- Final semantic meaning remains family-level and shared across sibling color
  variants. The canonical colored sheet is review evidence, not a separate
  semantic family.
- Synthetic tiles are allowed on the semantic side when the source sheet does
  not contain a useful authored cell for a needed role. These should not be
  forced back into source-layout regions or clusters just because they behave
  like normal tiles at runtime.
