# Architecture Documentation

## Overview

The ingestion/render stack is split into five layers:

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

That split keeps the source of truth aligned with the asset itself:

- sheet facts live with the family
- semantic meaning lives with tiles and clusters
- constructions define legal multi-tile arrangements without becoming scene instances
- scene composition consumes those semantics instead of inventing them

## Current Runtime Shape

- Loader/query module: [scripts/tile_families.py](../../scripts/tile_families.py)
- Harness entrypoint: [scripts/minimal8_harness.py](../../scripts/minimal8_harness.py)
- Minimal 8 family package: [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8)

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
