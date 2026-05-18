# 0004 - Runtime Registry Loads Multiple Compatibility Units

- Status: accepted

## Context

The runtime library boundary extraction already separated normal scene work from raw `TileFamily` access by introducing `TileLibraryUnit` as the runtime-facing compatibility view over one loaded family package.

That still left the harness with a one-unit assumption:

- one project could only load one family-backed runtime unit at a time
- construction and entity lookup assumed one loaded unit
- family-backed ref resolution assumed one loaded unit
- adding a second family package would have forced runtime code either back through ingestion-shaped structures or into ad hoc per-call selection logic

The broader tile-pack design is also explicit that this phase is not the final canonical asset-library model. At this stage the runtime still works over source-shaped compatibility units, but it must do so without depending on ingestion artefacts once those units have been built.

## Decision

Introduce `TileLibraryRegistry` as the runtime registry over one or more loaded `TileLibraryUnit` compatibility units.

The runtime uses this registry to:

- resolve constructions and derived entity templates across loaded units
- route explicit family-backed refs to the owning loaded unit
- route unique bare family aliases and unique bare family-owned tile ids to the owning loaded unit

Project loading may now bind multiple family-backed units at once through `tile_families`, but when more than one is loaded the project must declare an explicit `default_tileset` for bare coordinate refs and other fallback cases.

To keep runtime resolution honest and deterministic, the registry rejects load-time ambiguity:

- duplicate loaded-unit ids
- duplicate construction ids
- duplicate aliases
- duplicate tile ids
- cross-unit collisions where one loaded unit exports an alias that matches another loaded unit's bare tile id

This registry is a runtime compatibility layer only. It does not make tile packs, tilesets, or ingestion manifests first-class runtime routing keys, and it is not the final canonical engine-side asset registry.

## Consequences

- One project can now compose multiple loaded logical family-backed units in one consistent-geometry runtime domain.
- Runtime scene work remains functional without reading ingestion-only artefacts after library build.
- Ambiguous bare refs fail at load time instead of being resolved by hidden precedence.
- The runtime surface is still compatibility-shaped, so a later phase can replace or sit above it with a canonical library-asset registry without undoing this separation.
- Explicit unit-qualified alias syntax remains deferred; the current registry only supports explicit family tile refs plus unique bare alias/tile-id routing.
