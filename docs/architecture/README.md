# Architecture Documentation

## Overview

The current prototype now has a clearer boundary between source-shaped ingestion data and the runtime surface that scene composition consumes.

The current ingest/runtime boundary is:

- staged pack / tileset / logical-tilesheet manifests now exist on the source side
- a one-way bridge adapts those staged source manifests into the current family-backed compatibility path
- the Minimal 8 project now enters through that staged source-pack path
- the runtime still consumes `TileLibraryUnit` / `TileLibraryRegistry` rather than source manifests directly
- `TileLibraryUnit` now carries the runtime-relevant metadata explicitly promoted from the staged source manifests: source-pack identity, source tileset / tilesheet identity, named module-context axes when declared, effective render traits, and documented hints that were intentionally promoted for runtime/tooling use

Detailed ingest/runtime metadata is split across the staged source-manifest
hierarchy and the transitional family compatibility bundle:

1. **Pack / tileset / logical tilesheet manifests**
   - grid facts
   - logical sheet bounds and source-layout entrypoints
   - sibling variants and source-side render traits
   - pack / tileset grouping and module-context facts
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

- sheet facts and source-side provenance live with the staged pack / tileset / logical-tilesheet manifests
- the compatibility family bundle remains an adapter payload for the current runtime/library path
- semantic meaning still lives with tiles, aliases, and constructions
- constructions define legal multi-tile arrangements without becoming scene instances
- scene composition consumes a runtime-facing library surface instead of inventing semantics on demand

## Current Runtime Shape

- Ingest/loader/query module: [scripts/tile_families.py](../../scripts/tile_families.py)
- Runtime library surface module: [scripts/tile_library.py](../../scripts/tile_library.py)
- Shared layout base (LayoutProject + render/draw primitives): [scripts/layout_core.py](../../scripts/layout_core.py)
- Source-ingest operators (inspect/export/audit/validate/detect): [scripts/source_ingest_ops.py](../../scripts/source_ingest_ops.py)
- Harness entrypoint (scene-runtime + render + CLI): [scripts/harness.py](../../scripts/harness.py)
- Minimal 8 source pack: [prototypes/minimal8-harness/tile-packs/minimal8](../../prototypes/minimal8-harness/tile-packs/minimal8)
- Minimal 8 compatibility bundle: [prototypes/minimal8-harness/tile-families/minimal8](../../prototypes/minimal8-harness/tile-families/minimal8)

In the current implementation:

- `tile_families.py` owns ingest: loading, validation, provenance, `TileFamily`, source-layout, detection/bootstrap, and rich source-family queries
- `tile_library.py` owns the runtime library surface: the construction records (`MetatileConstruction` / `ParametricRunConstruction` / `ParametricFrameConstruction`), tile/cluster records, and the catalog containers (`TileLibraryUnit` / `LoadedTileLibraryUnit` / `TileLibraryRegistry`); the dependency runs one-directional, ingest → library
- `layout_core.py` owns the shared base: `LayoutProject`, the project/layout config + tile data types, and the render/draw/geometry primitives; it imports only upstream modules and is consumed by both the harness and the operators
- `source_ingest_ops.py` owns the operator bodies (inspect/export/audit/validate/detect + helpers); it depends on `layout_core` and is invoked by the `source_ingest.py` CLI
- `harness.py` is now just the scene-runtime + entity-resolution layer, the layout render pipeline, and the CLI dispatch
- `source_manifests.py` owns the staged pack / tileset / logical-tilesheet source hierarchy
- `source_manifest_bridge.py` is the transitional one-way adapter from staged source manifests into the current `TileFamily` / `TileLibraryUnit` compatibility path
- `project.minimal8.json` and `project.minimal8.2bit.json` now select Minimal 8 through `tile_family.source_pack` rather than a direct family path
- the harness derives `TileLibraryUnit` from the selected family, wraps loaded units in `TileLibraryRegistry`, and uses that runtime surface for work such as:
  - grid defaults
  - family-backed tileset registration
  - family-backed ref resolution
  - construction and entity-template lookup
  - bounds-aware family ref validation
- once the compatibility units are built, ordinary runtime scene work no longer requires the staged source manifests or ingest/layout manifests to remain on disk
- when more than one family-backed unit is loaded, the project must nominate an explicit `default_tileset` for bare ref resolution
- the runtime registry owns cross-unit routing for explicit family refs and unique family-owned aliases/tile ids
- inspect/export/audit flows may still use `TileFamily` directly as a richer source-facing tool surface outside the runtime boundary

Scene templates now expand in two phases:

1. generic scene-template expansion emits ordinary scene ops plus unresolved entity requests
2. the harness resolves those requests into first-class `EntityInstance`s with placement anchors, bounds, occupied cells, and affordance-bearing cells, and only then lowers them to stamp ops for rendering

## Decision Records

See [docs/architecture/decisions/README.md](decisions/README.md).

## Subsystem Overviews

- [Construction and Scene Architecture](construction-system.md) — three-layer composition model (tile / construction / scene), validator rules, scene DSL, two-phase expansion.

## Related Notes

- [Minimal 8 Source-Sheet Notes](minimal8-source-sheet-notes.md) — sheet-level facts captured during Minimal 8 ingestion.
- [Runtime Tile Genesis and Provenance](decisions/0005-runtime-tile-genesis-and-provenance.md) (ADR 0005) — runtime-owned provenance model for tracing resolved tiles and scene stamps back to their promoted source genesis without reopening ingest-time files.
- [Source-Sheet Ingestion Model](source-sheet-ingestion-model.md) — separation between source-sheet layout and tile semantics.

## Operator Surfaces

The operator surface is fully split: `source_ingest.py` is the CLI entrypoint and the operator function bodies live in `source_ingest_ops.py` (which depends on `layout_core`). The operator-facing split should be read as follows:

- source-side ingest and review work starts from [scripts/source_ingest.py](../../scripts/source_ingest.py), [scripts/reference_grid.py](../../scripts/reference_grid.py), and [scripts/reference_tile_match.py](../../scripts/reference_tile_match.py)
- runtime/composition work starts from [scripts/harness.py](../../scripts/harness.py) and the scene/layout artefacts it renders

That keeps raw-sheet interpretation, reference solving, and ingest review away from the runtime harness surface that renders and composes scenes.

## Cross-cutting design tokens

- [design.md](../../design.md) — palette, typography, layout, and component tokens consumed by the codebase, art pipeline, and engine theming. Lives at the repo root for tooling consumption; indexed here so it is reachable from the architecture layer.
