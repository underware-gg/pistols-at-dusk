# 0008 - Locate the Seam Contact Line at the Content-Box Edge via a Declared Cell-Content Inset

- Status: accepted
- Extends: [0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md)

## Context

[0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md) defines a tile-side's seam profile as the occupancy mask of its **1px contact line** — the literal outermost pixel line of the cell. That holds only when art is painted flush to the cell boundary. Some tilesets deliberately inset their art: `minimal8` draws each tile as a 7×7 motif inside its 8×8 cell, leaving a consistent 1px transparent **gutter** on the top and right edges (a documented artist convention). Under the literal-edge rule, a guttered side's contact line is pure gutter — a null mask — so it can never match a neighbour's painted edge.

Evidence from deriving seam profiles for `minimal8` and matching every construction-internal adjacency: **84 of 85 adjacencies failed** exact matching, while the constructions render as coherent objects (tables, doors, bookcases). The failure was systematic — a tile's null gutter edge always faces a neighbour's painted edge — and rendering confirmed the constructions are correct, so the literal-edge contact line was asking the wrong question for inset art. The gutter is consistent per sheet but **not** universal across a family (full-bleed floor/UI tiles paint to the edge), so it cannot simply be inferred as "the transparent margin common to all tiles".

## Decision

A tile-side's seam contact line is read at the **content-box edge** — the cell edge inset by a **cell-content inset** ("gutter") — rather than the literal cell edge. Equivalently, tiles are compared as if composed overlapping their gutter, so painted content abuts painted content and the shared inset margin lands at the same index in both facing masks.

- **The inset is a declared property of the ingest configuration** for a sheet/tileset (per side: top/right/bottom/left), **detected or set manually**, defaulting to **0**. At inset 0 the contact line is the literal cell edge, so 0007's behaviour is unchanged for flush tilesets.
- **Individual tiles may override the sheet default** — a full-bleed tile that intentionally paints to the edge declares inset 0 while the sheet default is non-zero, and vice versa.
- **The inset flows through to runtime** as promoted tile/variant metadata; runtime derives seam profiles from its own art and its own promoted inset, never reading ingest-side data — consistent with the ingestion/runtime separation invariant (alongside existing promoted render traits such as alignment origin and transparent mode).

With the `minimal8` inset (top=1, right=1), 81 of 85 adjacencies match. The remaining 4 are genuine partial silhouette differences in table-leg rows — the tile bodies match exactly, only discrete leg pixels differ — scoring 0.75–0.88. That is the near-miss class that 0007's configurable matcher threshold (relaxed during tuning) and recorded author overrides exist to resolve; it is not a defect in the contact-line model.

## Consequences

- Seam derivation takes a per-side cell-content inset (sheet default plus per-tile override); flush tilesets declare inset 0 and behave exactly as under 0007.
- The cell-content inset is a new ingest-configuration property that must be promoted to runtime, joining the render-trait flow-through path; it is a concrete instance of the ingestion→runtime promotion model.
- Because the contact line is the content boundary, a consistent shared margin (gutter) is matched index-for-index instead of being read as a null edge, making the mechanical seam check meaningful for inset-art tilesets without overfitting to any one of them.
- 0007's threshold and author-override levers absorb genuine near-misses (e.g. discrete structural differences such as table legs) without weakening the exact default for flush seams.
- This record refines only 0007's contact-line definition. The rest of 0007 — derived-first identity, equality/complement matching, silhouette-only mechanical identity, bounded scope, and the `connects_on` supersession — stands unchanged.
