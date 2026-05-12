# Panel variants and filler tiles

![Panel variants and filler tiles](../images/ui_panel_variants_and_fillers.png)

## Bounds
- Source-sheet cells: `55,17 -> 62,18`
- Tile span: `8 x 2`

## Current Read
- Compact frame fragments and fill/pattern tiles that may support smaller boxes, panel backgrounds, or ornamental insets.

## Seen In References
- `reference-dungeon-hud-character-sheet.png`

## Feedback
- Interpretation: This strip is not made of larger assemblies. It contains 16 individual tile-sized elements.
- Missing related tiles:
- Composition / usage notes: Most of the tiles are single-cell border fragments on one or more sides. The last two tiles are special cases: one is an `X` tile and the final tile is a filled/checker-style tile. Although these are individual `1x1` elements, they also act as a flexible collection: they can be composed together to create many different square UI shapes.
- Rename suggestions:
- Action later (do not change yet): Re-author this review unit as 16 separate `1x1` elements if finer-grained semantic authoring is needed, rather than treating the strip as grouped larger constructs.
