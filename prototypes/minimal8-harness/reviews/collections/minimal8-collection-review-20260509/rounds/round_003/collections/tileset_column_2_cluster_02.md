# Tileset column 2 cluster 02

![Tileset column 2 cluster 02](../images/tileset_column_2_cluster_02.png)

## Bounds
- Source-sheet cells: `19,17 -> 34,20`
- Cluster id: `tileset.column_2.cluster_02`

## Current Read
- High-value indoor furniture / storage / stair cluster used heavily by tavern-like scenes.

## Feedback
- Interpretation: This cluster contains tables, low counters or shelves, tall shelving/bookcase runs, cabinet/storage pieces, seats, and stair variants.
- Row 1, left to right:
  1. Round table.
  2. Table segment, left end.
  3. Table segment, repeatable middle; can connect on left, right, and top, but not bottom.
  4. Table segment, right end.
  5. Small low counter or shelf, standalone.
  6. Small low counter or shelf, left end.
  7. Small low counter or shelf, middle segment, repeatable.
  8. Small low counter or shelf, right end.
  9. Tall shelves, standalone.
  10. Tall shelves, left end, with no authored repeatable middle yet.
  11. Tall shelves, right end, with no authored repeatable middle yet.
  12. Single cabinet or cupboard.
  13. Large bin or open-top container.
  14. Cabinet / shelves / storage variant.
  15. Cabinet / shelves / storage variant, with items.
  16. Cabinet / shelves / storage variant, with items.
- Missing related tiles: The tall-shelf left/right pair wants a synthetic repeatable middle piece.
- Composition / usage notes: The low counter/shelf run is a standard left / repeatable middle / right composition. The tall-shelf pair should also be made repeatable by generating a middle tile in the same spirit as the low run.
- Row 2, left to right:
  1. Table segment, top end.
  2. Table segment, middle; connects on all four sides.
  3. Table segment, bottom end.
  4. Square standalone table.
  5. Chair, facing right.
  6. Bench, facing right.
  7. Bench, facing left.
  8. Chair, facing left.
  9. Bed, vertical.
  10. Bed, horizontal.
  11. Unresolved.
  12. Unresolved.
  13. Ladder.
  14. Ladder, leading down.
  15. Ladder, leading up.
  16. Blank spacer.
- Row 3, left to right:
  1. Treasure chest, closed.
  2. Treasure chest, open.
  3. Chain, vertical.
  4. Chain, horizontal.
  5. Blank spacer.
  6. Blank spacer.
  7. Blank spacer.
  8. Blank spacer.
  9. Blank spacer.
  10. Blank spacer.
  11. Blank spacer.
  12. Blank spacer.
  13. Blank spacer.
  14. Blank spacer.
  15. Blank spacer.
  16. Blank spacer.
- Row 4, left to right:
  1. Empty minecart.
  2. Empty minecart, crouching or moving animation variation.
  3. Full minecart.
  4. Full minecart, crouching or moving animation variation.
  5. Blank spacer.
  6. Candle or torch, variation 1, or animation frame 1.
  7. Candle or torch, variation 2, or animation frame 2.
  8. Candle or torch, variation 3, or animation frame 3.
  9. Candle or torch, variation 4, or animation frame 4.
  10. Blank spacer.
  11. Switch, facing left / off.
  12. Switch, facing right / on.
  13. Blank spacer.
  14. Brazier / hearth / ember tray.
  15. Brazier / hearth / ember tray variant / animation frame 2.
  16. Blank spacer.
- Rename suggestions:
- Action later (do not change yet): Generate a repeatable middle for the tall shelves by cropping the left-edge pixels and duplicating the second-from-left edge pixels in place, analogous to the existing repeatable middle behavior of item 7.
