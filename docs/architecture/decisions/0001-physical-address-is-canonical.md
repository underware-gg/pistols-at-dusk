# 0001 - Physical Address Is Canonical Identity

- Status: accepted

## Context

The old Minimal 8 prototype mixed semantic meaning, scene vocabulary, and raw sheet coordinates in one Python catalog. That made it too easy to treat scene-specific aliases as if they were the intrinsic identity of a tile.

The repo also needs to support sibling colorway sheets where the same grid coordinate means the same thing across variants.

## Decision

The canonical physical identity of a sheet-backed tile is:

- `family_id:sheet_col,sheet_row`

Concrete rendered variants are addressed as:

- `family_id@variant_id:sheet_col,sheet_row`

Stable tile IDs remain opaque compatibility identifiers, for example `minimal8:terrain:1,15`.

When project code needs to bypass the family catalogue and address a loaded runtime tileset cell directly, it uses:

- `tileset_id#sheet_col,sheet_row`

Human-facing semantic names remain aliases that resolve onto canonical physical IDs.

## Consequences

- Semantic meaning stays anchored to the source asset.
- Multiple sheet variants can share one semantic catalog safely.
- Scene composition can swap variants without changing semantic references.
- Internal code must stop depending on scene-specific names as primary identity.
