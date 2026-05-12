# Collection Review: Red actor 2x2 sprite

- collection_id: `actor.red`
- kind: `assembly`
- source_region_id: `characters_and_icons.column_3`
- source_cluster_id: `characters_and_icons.column_3.cluster_01`
- preview: `images/actor_red.png`

## Current Members

- `sheet_cell` `sheet:38,4` -> sheet:38,4
- `sheet_cell` `sheet:39,4` -> sheet:39,4
- `sheet_cell` `sheet:38,5` -> sheet:38,5
- `sheet_cell` `sheet:39,5` -> sheet:39,5

## Current Interpretation

Example 2x2 character assembly expressed in raw sheet cells so the source-layout layer stays honest even when runtime semantic aliases are later refined.

## Feedback

- Keep / rename / split / merge: Keep as one character grouping for now; do not split in this review round.
- Membership corrections: None to the current four source cells.
- Better label: Red character pose set.
- Better kind: Character pose/state grouping rather than a fixed 2x2 composed object.
- Semantic notes: These four sprites are different aspects of the same character, not four tiles that always compose into one larger sprite. Top left faces right. Bottom left faces left. Top right is a shorter sitting/ducking pose facing right. Bottom right is the matching shorter sitting/ducking pose facing left. The left/right facings presumably support movement direction. The purpose of the shorter pose is uncertain: it may represent sitting, ducking, or an alternate animation frame such as part of a walk cycle. Review feedback now says all 34 characters on the sheet follow this same four-sprite behavior pattern; see `../character_identification_walkthrough.md` for the current first-pass per-character identity guesses.

## Decision

- Status: Accepted as a same-character pose/state grouping with unresolved interpretation on the shorter frames.
- Follow-up: Keep the source-cell grouping as-is for now, but revisit whether this should become a broader character-state collection model rather than a generic assembly. If and when authored character collections are expanded, fan this shared four-state behavior out across the full 34-character set using the current walkthrough as review input. Do not change the authored collection structure in this round; capture only.
