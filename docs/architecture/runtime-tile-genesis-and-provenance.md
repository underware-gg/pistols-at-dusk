# Runtime Tile Genesis and Provenance

This note captures the design needed to close a gap exposed while rebuilding
`reference-party-menu-character-stats` as a fully data-backed scene.

Operator context and the richer friction log live in the linked report:
[Pistols at Dusk — Runtime Tile Genesis and Provenance Gap](</Users/robmorris/Library/Mobile Documents/iCloud~md~obsidian/Documents/Brain/_Temporal/Reports/2026-05/20260527-report~Pistols at Dusk — Runtime Tile Genesis and Provenance Gap.md>)

## Problem

The current runtime is mostly on the right side of the ingest/runtime split:

- scene composition consumes runtime tiles, aliases, constructions, and entity
  templates
- runtime work does not usually need to reopen source sheets to render a scene
- many sheet-backed tiles already carry useful source facts such as
  `sheet_col`, `sheet_row`, `source_group`, and `cluster_ids`

But the system still fails an important operator contract:

- from a resolved runtime tile or expanded scene stamp, it is not yet trivial
  to answer where that tile came from
- the answer exists in pieces, but not as one clean runtime-facing lookup

That makes reference-backed reconstruction, runtime debugging, and metadata
audits much harder than they need to be.

## Goals

1. Keep runtime composition self-sufficient.
2. Make tile genesis explicit and complete on the runtime side.
3. Allow every resolved runtime stamp to be traced back to its genesis in one
   hop.
4. Preserve the one-way ingest -> runtime promotion boundary.
5. Make synthetic and sheet-backed tiles equally first-class, but clearly
   distinguished.

## Non-goals

- The runtime engine should not reopen source-sheet PNGs to answer ordinary
  composition questions.
- Scene composition should not depend on `ingestion.json` remaining available on
  disk after the compatibility/runtime units are built.
- This design does not make source-layout structures the new runtime
  composition vocabulary. Runtime still composes from runtime metadata.

## Core model

Every runtime tile must have an explicit genesis record.

### Sheet-backed genesis

For tiles promoted from a source sheet, the runtime should know:

- source pack id
- source tileset id
- source tilesheet id
- family id
- source sheet cell
- source-layout region id when relevant
- source-layout cluster id when relevant
- source-layout collection id when relevant

These are promotion facts. They should be copied forward into the runtime
library surface when the compatibility family / runtime unit is built.

### Synthetic genesis

For synthetic or derived tiles, the runtime should know:

- genesis kind
- derivation type
- parent tile ids / construction ids / collections where relevant
- authored provenance notes when the tile is hand-built rather than
  mechanically derived

Synthetic tiles should not pretend to have a source-sheet cell when they do
not. Their provenance must still be explicit enough to debug and audit them.

## Boundary rule

The ingest side is allowed to *promote* genesis data into the runtime layer.
The runtime side is not allowed to *reach back* into ingest-time files to infer
missing facts on demand.

That means:

- source manifests and source-layout manifests remain the source of truth
- `TileFamily` / `TileLibraryUnit` / `TileLibraryRegistry` carry the promoted
  runtime-facing genesis facts needed after load
- ordinary runtime work should succeed even if the source-sheet files are not
  consulted again

This keeps the dependency direction clean:

- ingest shapes source truth
- runtime consumes promoted truth

## Runtime surfaces that should expose genesis

### Tile-level lookup

The runtime library surface should be able to answer:

- `tile id -> genesis`
- `alias -> tile id -> genesis`

This belongs on the runtime-facing library, not only on source-side inspection
tools.

### Construction and entity inspection

A construction is composed of runtime tiles. An entity instance resolves to
runtime tile placements. For both of those layers, the operator should be able
to see:

- the resolved tile ids
- the resolved tile genesis for each placed cell

That is especially important once aliases, constructions, and entity templates
hide the underlying tile ids from the scene author.

### Scene inspection

`inspect-layout-scene` or an equivalent runtime-debug export should emit
per-stamp provenance in human terms:

- family
- tileset / tilesheet
- source sheet cell when sheet-backed
- synthetic derivation when synthetic
- optional source-layout region / cluster / collection ids

This should be a first-class field in the runtime debug surface, not a manual
reconstruction exercise using multiple tools.

## Composition metadata remains separate

Genesis metadata is not the same thing as composition metadata.

Runtime composition still relies on:

- aliases
- composition roles
- connectivity
- kit membership
- constructions
- entity templates
- scene-facing categories and usage notes

The point of this design is not to compose from source-sheet structure. It is
to make provenance complete and inspectable while letting composition stay on
the runtime layer.

## UI-specific implication

The party-menu reconstruction exposed a second-order issue: the UI sheet
content was not promoted with a strong enough runtime-facing vocabulary.

The fix is not to compose directly from source-sheet cells forever. The fix is:

1. use source-backed provenance to identify the exact art
2. promote the correct UI families and widgets into runtime
3. compose scenes from those runtime aliases/kits/entities
4. retain the ability to trace those runtime choices back to the source

That applies equally to:

- frame families
- border primitives
- separators
- row-lead widgets
- cursor / marker families
- future decorator/attachment families

## Proposed implementation shape

### 1. Introduce a canonical runtime genesis structure

Add a promoted runtime genesis shape owned by the runtime-facing library
surface. It should be explicit rather than implied by a loose combination of
existing fields.

### 2. Promote genesis one-way at load time

When building `TileFamily` / `TileLibraryUnit`, promote complete genesis data
from:

- source pack / tileset / tilesheet manifests
- compatibility family manifests
- source-layout manifests
- synthetic derivation metadata

After promotion, runtime consumers should not need to consult those source
documents again.

### 3. Expose genesis through runtime inspection

Extend scene/entity/construction inspection exports so they include per-stamp
genesis directly.

### 4. Keep exact source promotions honest

Where a reference reconstruction temporarily promotes exact source cells before
broader semantic modelling is complete, those runtime tiles should still be
valid first-class runtime entries with explicit genesis, not half-ingested
exceptions.

## Migration sequence

1. Define the runtime genesis data shape.
2. Promote genesis into `TileLibraryUnit` as canonical runtime-owned metadata.
3. Add runtime lookup helpers for tile id / alias -> genesis.
4. Extend construction/entity/scene inspection exports to include genesis.
5. Tighten synthetic provenance so every synthetic tile can answer its own
   origin story as clearly as a sheet-backed tile.
6. Audit UI kits, scenery exact promotions, and attachment/decorator systems
   against the new contract.

## Success criteria

This design is complete when all of the following are true:

- a scene can be composed entirely from runtime metadata
- a resolved runtime stamp can be traced back to its genesis in one hop
- synthetic tiles clearly identify themselves as synthetic and explain their
  derivation
- source-sheet files are not required at runtime to answer composition
  questions
- source-side tools and runtime-side tools no longer have to be mixed together
  just to answer “where did this tile come from?”
