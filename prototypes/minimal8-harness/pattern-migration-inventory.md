# Minimal 8 Pattern Migration Inventory

This is the committed routing inventory promised by the metatile-convergence
plan.

The historical project-level `metatiles` registry contained 74 entries shared
by the current `project.minimal8.json` and `project.minimal8.2bit.json`
fixtures. That registry is now gone as an active project/runtime concept. Each
historical entry has been routed onto one honest composition surface:

- `construction` for entity-shaped composites
- `pattern` for project-local reusable non-entity tile-grid snippets
- `alias/direct ref` for pure naming convenience
- `scene/sub-scene` for higher-order authored arrangements

For this tranche, no historical registry entries needed promotion to
`scene/sub-scene`. The current scene system remains the home for any future
higher-order reusable arrangements if they appear.

## Routed to constructions

These entries already had honest construction equivalents in the Minimal 8
family package, so authored usage now goes through `entity` / `construction`
surfaces instead of pattern stamping:

| Historical entry | Runtime/library construction | Status |
| --- | --- | --- |
| `indoors_door_grand_open` | `indoors.door.grand.open` | migrated |
| `indoors_door_grand_closed` | `indoors.door.grand.closed` | migrated |

## Routed to aliases / direct refs

These were 1x1 convenience names rather than meaningful higher-order assets:

| Historical entry | Replacement | Status |
| --- | --- | --- |
| `overworld_land_undercoat` | project alias -> `utility_land:0,0` | migrated |
| `overworld_route_node` | project alias -> `20,12` | migrated |

## Retained as honest patterns

These entries remain project-scoped `patterns` because they are still honest
non-entity reusable snippets: room shells, banded borders, decorative walls,
shoreline modules, symbolic panels, actor composites, and other authored
tile-grid fragments that do not want a single entity footprint.

### Interior and authored architectural snippets

- `corridor_floor`
- `courtyard_floor`
- `door_arch`
- `entry_steps`
- `gold_ui_corner`
- `green_symbols`
- `indoors_band_run`
- `indoors_dining_cluster`
- `indoors_ladder_access`
- `maze_block`
- `meander_band`
- `plinth_left`
- `plinth_right`
- `rock_bank_left`
- `shrine_face_top`
- `small_door`
- `symbols_crown`
- `symbols_left`
- `symbols_mid`
- `symbols_right`
- `tavern_back_wall_a`
- `tavern_back_wall_b`
- `tavern_outer_wall_side`
- `tavern_outer_wall_top`
- `temple_floor_gold`
- `temple_floor_sparse`
- `temple_maze_corner`
- `temple_maze_side`
- `temple_maze_top`

### Actor composites

- `actor_gold_full`
- `actor_purple_full`
- `actor_red_full`
- `actor_teal_full`

### Overworld terrain, shoreline, and silhouette snippets

- `overworld_cloud_swirl`
- `overworld_continent_lower`
- `overworld_continent_mid`
- `overworld_continent_top`
- `overworld_cyan_fill`
- `overworld_grass_ridge`
- `overworld_green_fill`
- `overworld_ground_fill`
- `overworld_land_cap`
- `overworld_mountain_bank`
- `overworld_mountain_cluster_large`
- `overworld_mountain_patch`
- `overworld_mountain_ridge`
- `overworld_mountain_ridge_cluster`
- `overworld_mountain_ridge_top`
- `overworld_mountain_volcano_band`
- `overworld_mountain_volcano_cluster`
- `overworld_nature_boundary_inset_4x4`
- `overworld_nature_boundary_outer_4x4`
- `overworld_nature_boundary_strip_a`
- `overworld_nature_boundary_strip_b`
- `overworld_nature_cap_inset_4x2`
- `overworld_nature_cap_outer_4x2`
- `overworld_orange_fill`
- `overworld_purple_fill`
- `overworld_route_strip`
- `overworld_ruin_band`
- `overworld_ruin_cyan_tower`
- `overworld_ruin_yellow_keep`
- `overworld_spire`
- `overworld_water_boundary_east_5x5`
- `overworld_water_boundary_west_4x5`
- `overworld_water_fill_4x5`
- `overworld_wave_corner`
- `overworld_yellow_fill`
- `water_lines`
- `water_short`

## Routed to scenes / sub-scenes

None in this tranche.

The current historical registry never needed to become a second persisted scene
system. If future reusable authored arrangements want multi-placement or
cross-fragment behaviour, they should move onto the existing scene-template /
`place_scene` machinery rather than back into a generic registry.
