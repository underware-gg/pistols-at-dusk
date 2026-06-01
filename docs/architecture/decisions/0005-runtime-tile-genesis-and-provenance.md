# 0005 - Runtime Tile Genesis and Provenance

- Status: accepted

## Context

The current runtime is mostly on the right side of the ingest/runtime split:

- scene composition consumes runtime tiles, aliases, constructions, and entity templates
- runtime work does not usually need to reopen source sheets to render a scene
- many sheet-backed tiles already carry useful source facts such as `sheet_col`, `sheet_row`, `source_group`, and `cluster_ids`

But the system still fails an important operator contract:

- from a resolved runtime tile or expanded scene stamp, it is not yet trivial to answer where that tile came from
- the answer exists in pieces, but not as one clean runtime-facing lookup

That makes reference-backed reconstruction, runtime debugging, and metadata audits much harder than they need to be.

The goals driving this design are:

1. Keep runtime composition self-sufficient.
2. Make tile genesis explicit and complete on the runtime side.
3. Allow every resolved runtime stamp to be traced back to its genesis in one hop.
4. Preserve the one-way ingest -> runtime promotion boundary.
5. Make synthetic and sheet-backed tiles equally first-class, but clearly distinguished.

Non-goals:

- The runtime engine should not reopen source-sheet PNGs to answer ordinary composition questions.
- Scene composition should not depend on `ingestion.json` remaining available on disk after the compatibility/runtime units are built.
- This design does not make source-layout structures the new runtime composition vocabulary. Runtime still composes from runtime metadata.

## Decision

The following structural choices constitute this design:

1. Every runtime tile must carry an explicit genesis record. For sheet-backed tiles this record captures source pack id, source tileset id, source tilesheet id, family id, source sheet cell, and source-layout region / cluster / collection ids where relevant. For synthetic or derived tiles the record captures genesis kind, derivation type, parent tile ids / construction ids / collections where relevant, and authored provenance notes when the tile is hand-built rather than mechanically derived.

2. The ingest side is allowed to *promote* genesis data into the runtime layer. The runtime side is not allowed to *reach back* into ingest-time files to infer missing facts on demand. Source manifests and source-layout manifests remain the source of truth; `TileFamily` / `TileLibraryUnit` / `TileLibraryRegistry` carry the promoted runtime-facing genesis facts needed after load; ordinary runtime work must succeed even if the source-sheet files are not consulted again.

3. `TileFamily`, `TileLibraryUnit`, and `TileLibraryRegistry` are the runtime surfaces that carry promoted genesis. The runtime library surface must be able to answer `tile id -> genesis` and `alias -> tile id -> genesis` directly. Construction and entity inspection must expose the resolved tile genesis for each placed cell. Scene inspection exports must emit per-stamp provenance — family, tileset / tilesheet, source sheet cell (if sheet-backed), synthetic derivation (if synthetic), and optional source-layout region / cluster / collection ids — as a first-class field, not a manual reconstruction exercise.

4. A canonical runtime genesis structure replaces the loose combination of existing fields (`sheet_col`, `sheet_row`, `source_group`, `cluster_ids`). This structure is explicit and runtime-owned rather than implied by whatever happened to be promoted piecemeal.

5. Synthetic tiles carry explicit provenance. They must not pretend to have a source-sheet cell when they do not. Their provenance must be explicit enough to debug and audit them.

6. Runtime inspection exports emit per-stamp genesis as a first-class field. The `inspect-layout-scene` surface and equivalent runtime-debug exports must include this field directly.

Genesis metadata is distinct from composition metadata. Runtime composition still relies on aliases, composition roles, connectivity, kit membership, constructions, entity templates, and scene-facing categories and usage notes. This design makes provenance complete and inspectable while keeping composition on the runtime layer.

A second-order implication: the party-menu reconstruction exposed that the UI sheet content was not promoted with a strong enough runtime-facing vocabulary. The fix is not to compose directly from source-sheet cells forever but to use source-backed provenance to identify the exact art, promote the correct UI families and widgets into runtime, compose scenes from those runtime aliases/kits/entities, and retain the ability to trace those runtime choices back to the source. This applies to frame families, border primitives, separators, row-lead widgets, cursor / marker families, and future decorator/attachment families.

## Consequences

**Intended delivery steps:**

1. Define the runtime genesis data shape.
2. Promote genesis into `TileLibraryUnit` as canonical runtime-owned metadata.
3. Add runtime lookup helpers for tile id / alias -> genesis.
4. Extend construction / entity / scene inspection exports to include genesis.
5. Tighten synthetic provenance so every synthetic tile can answer its own origin story as clearly as a sheet-backed tile.
6. Audit UI kits, scenery exact promotions, and attachment/decorator systems against the new contract.

**Acceptance criteria.** This design is complete when all of the following are true:

- a scene can be composed entirely from runtime metadata
- a resolved runtime stamp can be traced back to its genesis in one hop
- synthetic tiles clearly identify themselves as synthetic and explain their derivation
- source-sheet files are not required at runtime to answer composition questions
- source-side tools and runtime-side tools no longer have to be mixed together just to answer "where did this tile come from?"

**Frame/border UI second-order effect.** Implementing this design unblocks correct promotion of UI frame and border families. Alias/kit/entity-driven composition of those families becomes reliable only once provenance is complete enough to trace which source art was promoted.

**Current enforcement status.** The boundary rule declared in the Decision is only partially enforced today. The ingest/runtime CLI split is incomplete at the implementation level — 7 ingest function bodies remain in `minimal8_harness.py` rather than in an ingest-only module. No canonical genesis structure has yet been promoted onto `TileLibraryUnit`; the loose field combination (`sheet_col`, `sheet_row`, `source_group`, `cluster_ids`) remains the de-facto runtime provenance surface. The steps above represent work still to be done, not a completed migration.
