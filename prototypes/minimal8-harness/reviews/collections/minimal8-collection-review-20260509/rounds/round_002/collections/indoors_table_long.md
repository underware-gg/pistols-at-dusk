# Collection Review: Long indoor table

- collection_id: `indoors.table.long`
- kind: `assembly`
- source_region_id: `tileset.column_2`
- source_cluster_id: `tileset.column_2.cluster_02`
- preview: `images/indoors_table_long.png`

## Current Members

- `alias` `indoors.table.long.left` -> sheet:20,17
- `alias` `indoors.table.long.middle` -> sheet:21,17
- `alias` `indoors.table.long.right` -> sheet:22,17

## Current Interpretation

Three-part table kit with left / middle / right reuse semantics.

## Feedback

- Keep / rename / split / merge: Keep this authored example, but treat it as one arrangement within a broader table collection rather than the whole table story.
- Membership corrections: The current left / middle / right composition is correct for this specific arrangement.
- Better label: Keep a clear long-table label for this arrangement, but note that the wider table family is larger than this one three-part example.
- Better kind: Collection / kit rather than a fixed single entity.
- Semantic notes: Tables compose in multiple ways. This example correctly captures a left / middle / right table run, but there are additional table tiles elsewhere that belong to the same broader table collection. We want to identify all table-related members and record how they compose. We may also want specific prebuilt table configurations in addition to the reusable underlying kit.

## Decision

- Status: Accepted as a correct current arrangement, but incomplete as the full table collection model.
- Follow-up: During collection expansion, identify the missing table-related tiles, fold them into the broader table collection, and document both composition rules and possible prebuilt table configurations. Do not change the authored collection membership in this round; capture only.
