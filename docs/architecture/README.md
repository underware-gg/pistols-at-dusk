# Architecture Documentation

## Overview

The current prototype now has a clearer boundary between source-shaped ingestion data and the runtime surface that scene composition consumes.

Source-shaped family packages still contain the detailed ingestion catalogue:

1. **Family manifest**
   - grid facts
   - source-sheet layout entrypoints
   - sibling variants
   - render defaults
2. **Cluster catalog**
   - meaningful grouped areas or member sets on a sheet
3. **Tile catalog**
   - stable physical tile identities plus semantic metadata
4. **Entity template layer**
   - legal multi-tile constructions
   - derived runtime entity templates and footprints
5. **Alias resolver**
   - human-facing semantic names mapped onto physical tile identities

The harness runtime now derives a compatibility surface over that package:

- `TileFamily` remains the source-shaped loader/query object
- `TileLibraryUnit` is the runtime-facing compatibility view over one logical family package, carrying only the runtime data and lookups the harness needs
- `TileLibraryRegistry` is the runtime-facing registry over one or more loaded `TileLibraryUnit`s
- hot-path runtime concerns consume that runtime library surface rather than reading the whole source catalogue directly

That split keeps the source of truth aligned with the asset itself while also giving the runtime a narrower seam:

- sheet facts and provenance live with the family package
- semantic meaning still lives with tiles, aliases, and constructions
- constructions define legal multi-tile arrangements without becoming scene instances
- scene composition consumes a runtime-facing library surface instead of inventing semantics on demand

## Current Runtime Shape

- Loader/query module: [scripts/tile_families.py](../../scripts/tile_families.py)
- Harness entrypoint: [scripts/minimal8_harness.py](../../scripts/minimal8_harness.py)
- Minimal 8 family package: [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8)

In the current phase:

- `tile_families.py` still owns loading, validation, provenance, and rich source-family queries
- the harness derives `TileLibraryUnit` from the selected family, wraps loaded units in `TileLibraryRegistry`, and uses that runtime surface for work such as:
  - grid defaults
  - family-backed tileset registration
  - family-backed ref resolution
  - construction and entity-template lookup
  - bounds-aware family ref validation
- when more than one family-backed unit is loaded, the project must nominate an explicit `default_tileset` for bare ref resolution
- the runtime registry owns cross-unit routing for explicit family refs and unique family-owned aliases/tile ids
- inspect/export/audit flows may still use `TileFamily` directly while this boundary extraction is in progress

Scene templates now expand in two phases:

1. generic scene-template expansion emits ordinary scene ops plus unresolved entity requests
2. the harness resolves those requests into first-class `EntityInstance`s with placement anchors, bounds, occupied cells, and affordance-bearing cells, and only then lowers them to stamp ops for rendering

## Decision Records

See [docs/architecture/decisions/README.md](decisions/README.md).

## Subsystem Overviews

- [Construction and Scene Architecture](construction-system.md) — three-layer composition model (tile / construction / scene), validator rules, scene DSL, two-phase expansion.

## Related Notes

- [Minimal 8 Source-Sheet Notes](minimal8-source-sheet-notes.md) — sheet-level facts captured during Minimal 8 ingestion.
- [Source-Sheet Ingestion Model](source-sheet-ingestion-model.md) — separation between source-sheet layout and tile semantics.

## Cross-cutting design tokens

- [design.md](../../design.md) — palette, typography, layout, and component tokens consumed by the codebase, art pipeline, and engine theming. Lives at the repo root for tooling consumption; indexed here so it is reachable from the architecture layer.
