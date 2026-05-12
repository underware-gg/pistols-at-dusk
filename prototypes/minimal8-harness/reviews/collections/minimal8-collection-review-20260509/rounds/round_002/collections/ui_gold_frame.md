# Collection Review: Gold frame border kit

- collection_id: `ui.gold_frame`
- kind: `kit`
- source_region_id: `ui.column_4`
- source_cluster_id: `ui.column_4.cluster_01`
- preview: `images/ui_gold_frame.png`

## Current Members

- `tile_id` `minimal8:ui:1,4` -> sheet:55,5
- `tile_id` `minimal8:ui:2,3` -> sheet:56,4
- `tile_id` `minimal8:ui:2,6` -> sheet:56,7
- `tile_id` `minimal8:ui:6,3` -> sheet:60,4
- `tile_id` `minimal8:ui:6,4` -> sheet:60,5
- `tile_id` `minimal8:ui:7,3` -> sheet:61,4
- `tile_id` `minimal8:ui:7,4` -> sheet:61,5

## Current Interpretation

Reusable gold UI boundary kit: corners and edge pieces that compose into extensible framed panels.

## Feedback

- Keep / rename / split / merge: Keep as a border/frame kit, but the current crop is not clean and should not be treated as the final authored membership.
- Membership corrections: The current crop is partial and mixes multiple related border structures. It includes a 6x3 segment containing two variations of the same border, plus partial neighboring frame pieces that should not stay half-cropped in the long-term authored version.
- Better label: Gold frame border kit.
- Better kind: Border/frame kit.
- Semantic notes: The main intended structure is two adjacent 3x3 border squares. Each 3x3 square has top-left corner, top edge, top-right corner; left edge and right edge; bottom-left corner, bottom edge, and bottom-right corner. The first 3x3 has open gaps. The second 3x3 is the same underlying border idea but connects smoothly. These are two style variations of the same kind of frame. The current crop also includes the edge of a 2x2 square to the right, the top of two different 3x3 squares below, and the top-left corner of another 3x3 square below. Those partial neighboring pieces should not remain partially cropped into the authored kit.

## Decision

- Status: Accepted as a border/frame kit concept, but the current authored crop is known to be incomplete and impure.
- Follow-up: Revisit this collection in a later authoring pass and recrop it cleanly into full frame kits and style variants instead of partial mixed excerpts. Document the open-gap and smooth-join variants explicitly when the collection membership is revised. Do not change the authored members in this review round; capture only.
