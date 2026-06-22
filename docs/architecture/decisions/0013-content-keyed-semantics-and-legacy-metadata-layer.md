# 0013 - Content-Keyed Semantics and a Preserved Legacy Metadata Layer

- Status: extended
- Extended by: [0014](0014-tile-membership-is-plural-category-is-a-primary-grouping.md)
- Scope: Ingestion–Runtime Separation Phase 3 (semantic catalogue flow-through)
- Extends: [0012](0012-runtime-owns-pixels-atomic-assets-synthetic-sheets.md)
- Related: [0001](0001-physical-address-is-canonical.md), [0005](0005-runtime-tile-genesis-and-provenance.md), [0011](0011-runtime-ingest-family-module-split.md)

## Context

The Ingestion–Runtime Separation work moved runtime pixels into produced runtime assets (ADR 0012). The remaining production boundary is semantic: the Minimal 8 runtime path still treats the hand-curated `tiles.json` file as a source of runtime tile semantics.

The Tileset Ingestion Architecture separates detected base facts from authored patches and keys the semantic catalogue by content hash. That key is deliberately resilient to source-sheet re-cropping, but it only works for facts that are actually properties of the pixels. The legacy `tiles.json` bundle mixes several kinds of information:

- visual facts such as contrast, motif, orientation, or texture temperature;
- placement and usage facts such as UI/map/sprite layer, category, usage, and footprint;
- provenance and review notes such as source-row prose, confidence, and source notes.

Bootstrap analysis over the real Minimal 8 family confirmed the distinction. The full legacy field set produced 18 divergent identical-pixel collision groups. Most were driven by source-region and usage fields, especially a 609-tile blank/transparent group where identical blank pixels carried different row, layer, category, and prose annotations. Keeping those fields content-keyed would either lose information or force false merges.

At the same time, the legacy values are still useful. They encode human review history, source placement, compatibility tags, and rough usage hints. They can feed later agent-driven procedural generation and higher-order composition work, but they are not clean content-keyed semantics.

## Decision

Content-keyed ingest semantics carry only clean visual facts.

The content-keyed semantic catalogue is narrowed to visual facts that can coherently belong to the pixel content:

- `contrast`
- `facing`
- `motifs`
- `noise`
- `orientation`
- `pose`
- `semantics`
- `style`
- `temperature`

`facing`, `pose`, and `semantics` are retained only as visual-content fields. Legacy values that merely reflect a source row, a placement context, or an uncertain review note are not valid content-keyed values for those fields; bootstrap reports them as collisions for authoring cleanup rather than silently accepting them.

The legacy semantic payload is preserved separately as a marked, per-physical-tile metadata layer.

- It is keyed by runtime tile id / physical tile identity, not content hash.
- It is linked to the tile it came from and marked as legacy source metadata.
- It preserves the original legacy semantic values, including fields removed from the content-keyed set.
- It is opt-in: consumers must explicitly ask for the legacy layer, and it never silently overrides content-keyed facts or runtime-authored fields.

The following legacy/context/provenance fields are therefore not content-keyed:

- `category`
- `footprint`
- `layer`
- `meaning`
- `meaning_confidence`
- `overlay`
- `source_notes`
- `tags`
- `usage`

Rich multi-use semantics and procedural affordance modelling are not designed here. They remain part of the existing runtime-authored semantic surface and the Metatile Convergence / Higher-Order Composition direction. The preserved legacy layer can feed that later work, but this decision does not add a new procgen semantics mechanism.

## Consequences

- The semantic resolver and bootstrap operate on a smaller, cleaner content-keyed field set.
- The one-time legacy bootstrap can fail loudly on the small residual set of dirty visual collisions instead of treating broad legacy context fields as content facts.
- Runtime assets gain a future marked legacy metadata layer so that the original `tiles.json` semantic payload is not discarded when `tiles.json` stops being a runtime source.
- The bridge-replacement slice must consume two semantic products: clean content-keyed facts and physical-tile legacy metadata.
- Runtime code that wants content facts reads the promoted clean semantic fields. Tools that need historical source prose or rough legacy usage hints must explicitly opt into the legacy layer.

Live status and the implementation sequence are maintained in the architecture overview and the Ingestion–Runtime Separation design-of-record. This ADR records the semantic taxonomy decision and its rationale, not live project status.
