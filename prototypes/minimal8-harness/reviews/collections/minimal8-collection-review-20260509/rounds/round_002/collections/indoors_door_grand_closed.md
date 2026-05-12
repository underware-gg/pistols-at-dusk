# Collection Review: Grand closed indoor door

- collection_id: `indoors.door.grand.closed`
- kind: `assembly`
- source_region_id: `tileset.column_1`
- source_cluster_id: `tileset.column_1.cluster_01`
- preview: `images/indoors_door_grand_closed.png`

## Current Members

- `alias` `indoors.door.grand.closed.tl` -> sheet:4,12
- `alias` `indoors.door.grand.closed.tr` -> sheet:5,12
- `alias` `indoors.door.grand.closed.bl` -> sheet:4,13
- `alias` `indoors.door.grand.closed.br` -> sheet:5,13

## Current Interpretation

Authored 2x2 doorway assembly built from four reusable door tiles.

## Feedback

- Keep / rename / split / merge: Keep as a single entity; do not split.
- Membership corrections: None for this specific 2x2 entity.
- Better label: Grand closed door.
- Better kind: Entity rather than a rearrangeable collection or kit; this is one fixed 2x2 composed object.
- Semantic notes: This is a grand door made from four tiles that always compose together in the same arrangement. It should not be described as specifically indoor-only; the important semantics are that it is a grand closed door and one 2x2 entity.

## Decision

- Status: Accepted as a fixed 2x2 entity with the current members.
- Follow-up: Update the authored description/labeling to emphasize "grand door" and "fixed 2x2 entity" without overcommitting it to indoor-only usage. Do not change the underlying collection data in this round; capture only.
