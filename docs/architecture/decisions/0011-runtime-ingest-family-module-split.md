# 0011 - Runtime/Ingest Family Module Split

- Status: accepted
- Scope: Ingestion–Runtime Separation Phase 1
- Related: [0005](0005-runtime-tile-genesis-and-provenance.md)

## Context

The Ingestion–Runtime Separation design sets the load-bearing invariant for the next ingestion pipeline work: runtime must not depend on ingest-side data. Deleting ingest artefacts from disk must eventually leave runtime load, validation, and rendering unaffected.

Before this decision, `scripts/tile_families.py` was a roughly 3500-line grab-bag. It mixed runtime family loading and validation with source-layout manifest loading, source-layout coverage reporting, detector/bootstrap helpers, and a broad compatibility query surface. That made it hard to tell whether a runtime caller was importing only runtime records or also pulling in ingest file IO. It also made the first Phase 2 acceptance test, delete-ingest, impossible to reason about module by module.

At the same time, as of this decision, the project still has transitional paths that legitimately need source-layout ingest data. Operator tools such as reference matching and source-ingest reporting consume source-layout regions. `layout_core` also still reaches ingest data while loading projects: source-pack families go through `source_manifest_bridge`, and legacy-path families use the ingest-aware family loader so source-layout validation and operator behaviour remain intact.

## Decision

Split the family module into three narrower modules behind a transitional facade.

- `scripts/tile_family_runtime.py` owns runtime family loading, validation, and the family-backed compatibility view. Runtime base modules import this module rather than the old facade. Its direct dependencies are runtime/shared modules, not ingest file IO.
- `scripts/tile_family_ingest.py` owns ingest/operator-side family helpers: source-layout manifest loading, legacy source-layout loading, coverage, detection, bootstrap, and the ingest-aware `load_source_tile_family(...)` helper used by transitional operator paths.
- `scripts/source_layout_model.py` owns shared source-layout value records and pure helpers. It is allowed on both sides of the boundary because it contains no ingest file IO or detector logic.
- `scripts/tile_families.py` remains as a transitional compatibility facade, re-exporting the old surface while callers migrate to the narrower modules.

Make the boundary observable in tests.

- `RuntimeImportBoundaryTests` asserts that runtime base modules do not directly import `tile_family_ingest`, the transitional `tile_families` facade, or operator tools such as `reference_tile_match`.
- Add a separate expected-failure test to record the known transitional gap: importing `layout_core` still transitively imports `tile_family_ingest` through the source-pack bridge and legacy-path loader. The test is intentionally marked as expected failure until the Phase 2/3 runtime-asset work removes those load-path dependencies.

Do not solve the full delete-ingest problem in this decision. Retiring `tiles.json` as a runtime source, removing `ingestion_spec` from project load, and dismantling the bridge equality gate remain in the Ingestion–Runtime Separation implementation sequence.

Current boundary status is maintained in the living architecture overview ([docs/architecture/README.md](../README.md)) and the Ingestion–Runtime Separation design-of-record. This ADR records the Phase 1 decision and rationale, not live project status.

## Consequences

- Runtime-family implementation code is smaller and has a clear ingest-clean module boundary.
- Source-layout value types can remain available to validation and operator code without smuggling source-layout file loading into runtime.
- Existing tests and operator callers can continue to import `tile_families.py` while the facade is retired incrementally.
- As of this decision, two things are simultaneously true: the runtime base modules are directly ingest-clean, and the larger runtime load path is not yet delete-ingest clean because `layout_core` still reaches ingest through transitional project-loading paths.
- Phase 2 has a sharper first target: move project load onto produced runtime assets so `layout_core` no longer imports or transitively loads ingest data.
