# 0012 - Runtime Owns Its Pixels: Atomic Content-Addressed Tile Assets and Synthetic Runtime Sheets

- Status: extended
- Extended by: [0013](0013-content-keyed-semantics-and-legacy-metadata-layer.md)
- Scope: Ingestion–Runtime Separation Phase 2 (runtime asset model)
- Related: [0001](0001-physical-address-is-canonical.md), [0005](0005-runtime-tile-genesis-and-provenance.md), [0008](0008-locate-seam-contact-line-at-content-box-edge.md), [0011](0011-runtime-ingest-family-module-split.md)

## Context

The Ingestion–Runtime Separation invariant requires that runtime never depends on ingest-side data: delete every ingest artefact and runtime still loads, validates, and renders.

As of this decision, the runtime violates that invariant at the pixel level. For a sheet-backed tile, the render path opens the vendor source sheet (`TileFamilyVariant.sheet_path`) and live-crops at the tile's `TileGenesis` sheet cell at render time (`tile_family_runtime.py` `_tile_image_bytes` / `_crop_tile_from_sheet`); only `image_override` (derived/synthetic) tiles already read a standalone image. So the genesis sheet cell is currently a *live pixel source*, and runtime depends on the vendor source sheet for pixels. This is a deeper coupling than the manifest-level coupling (`tiles.json`, `ingestion.json`) the delete-ingest acceptance test names as its first concrete target.

This decision completes a direction the codebase already accepted. ADR 0005 holds that the runtime should not reopen source-sheet PNGs to answer ordinary composition questions, and that `TileGenesis` is provenance. ADR 0008 has the runtime derive seam profiles from *its own art*, never reading ingest-side data. Both presume runtime owns its art; this decision makes that true for rendering pixels as well, and defines the runtime asset format that follows from it.

## Decision

Runtime owns its pixels.

- **Atomic tile assets.** Each runtime tile is an atomic pixel asset whose pixels are materialised once, by the ingest-side producer, into the runtime asset tree. An atomic asset is addressed by a hash of its **canonical pixel content** — a pixel-blob content address used for de-duplication and stable referencing. This pixel-blob address is *not* tile identity: tile identity remains the physical address (ADR 0001) and the stable tile id. A tile lifted from a source sheet and a fully synthetic or generated tile differ only in provenance — `TileGenesis` records the source sheet cell or the synthetic derivation (ADR 0005) — and are otherwise the same kind of thing: an atomic runtime asset with no live source-sheet dependency.
- **Synthetic runtime sheets.** The runtime constructs and renders from its own synthetic sheets — a runtime-side packing of only the tiles the project actually uses, built from the atomic assets, with runtime-owned coordinates. The render path pulls a tile from a runtime sheet or atomic asset entirely within the runtime side; it never opens a vendor source sheet.
- **Vendor sheets are ingest-side only.** Vendor source sheets (under `resources/`) are ingest input and provenance, never a runtime pixel source. They are not copied or re-homed into the runtime tree (honouring the repo rule to keep `resources/` clean); the runtime holds its own materialised pixels instead.
- **Publishing falls out of the model.** Because the project's curated tileset is a self-contained set of atomic assets packed into synthetic sheets, the engine can export clean tilesheet images plus rich tile metadata — a tile-publishing capability. Export as an end-user feature is *enabled* by this model but sequenced after the boundary closes.

**Determinism.** Pixel materialisation must be deterministic so the repeatability acceptance test holds at the pixel level, not only for JSON: hash canonical RGBA pixel bytes, and encode any on-disk image bytes with fixed, timestamp-free parameters. Same inputs in, byte-identical atomic assets out.

**The stopgap is rejected.** A transitional runtime format that references or copies vendor sheets as a runtime pixel source is explicitly not built. That is the "transitional adapter" half-measure the Ingestion–Runtime Separation design names as the recurring cause of the boundary being declared done prematurely; it would be built, wired, tested, then migrated off. The atomic-asset + synthetic-sheet model is the real runtime format and is built directly.

## Consequences

- The ingest-side producer gains responsibility for pixel materialisation: crop each sheet-backed tile from the source sheet once (or take the synthetic image), content-address it, and write atomic assets into the runtime tree.
- The runtime asset serialisation (the `tile_library_codec` format introduced under the Phase 2 runtime-asset work) references tiles by atomic-asset address rather than carrying a vendor `sheet_path` + sheet cell as a pixel source. The sheet cell survives only as `TileGenesis` provenance.
- The render path changes from a vendor-sheet crop to pulling from runtime sheets / atomic assets.
- The delete-ingest acceptance test extends from manifests-only (`tiles.json`, `ingestion.json`) to pixels: deleting the vendor source sheets as well leaves runtime rendering unaffected. This sharpens the bar that the Phase 1 expected-failure import-boundary test (ADR 0011) flips to a real pass.
- Sequencing: build atomic content-addressed assets first; reintroduce runtime synthetic-sheet construction and the render-path swap next; wire the loader and extend the delete-ingest test last.

Live status and the implementation sequence are maintained in the architecture overview ([docs/architecture/README.md](../README.md)) and the Ingestion–Runtime Separation design-of-record. This ADR records the decision and its rationale, not live project status.
