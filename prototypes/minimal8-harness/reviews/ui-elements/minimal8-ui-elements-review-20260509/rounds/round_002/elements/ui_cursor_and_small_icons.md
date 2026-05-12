# Cursor and small icon set

![Cursor and small icon set](../images/ui_cursor_and_small_icons.png)

## Bounds
- Source-sheet cells: `55,10 -> 58,12`
- Tile span: `4 x 3`

## Current Read
- Includes the right-pointing menu cursor, a boxed variant, and nearby small symbols used in menus and stats screens.

## Seen In References
- `reference-party-menu-region-selection.png`
- `reference-party-menu-character-stats.png`

## Feedback
- Interpretation: The leftmost `1x3` stack in this review unit is likely a checkbox state set: empty checkbox, partially selected / partially ticked checkbox, and fully selected / fully ticked checkbox.
- Missing related tiles:
- Composition / usage notes: Treat the checkbox-state stack as its own grid-aligned sub-unit inside this broader crop rather than conflating it with the cursor or nearby symbols. The missed section immediately to the right of the checkbox area also appears to be mostly dynamic-UI construction pieces rather than standalone icons: bracket/frame fragments, small square/frame pieces, and other border-building cells used to assemble flexible interface layouts in the reference shots. Best treatment is to describe them richly by purpose and keep them grid-aligned, rather than overclaiming exact standalone names.
- Rename suggestions:
- Action later (do not change yet): Split this broader unit into smaller grid-aligned review units, including the checkbox-state stack as its own reviewed set. Also carve out the missed right-hand section as its own exact grid review unit so those dynamic-UI construction pieces can be described and authored separately.
