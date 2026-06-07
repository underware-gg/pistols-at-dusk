# 0009 - Composition Asset Model: Tiles (incl. Metatiles), Constructions, Scenes, and Variations

- Status: accepted
- Extends: [0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md)
- Related: [0003](0003-scene-entities-are-first-class-runtime-objects.md), [0008](0008-locate-seam-contact-line-at-content-box-edge.md)

## Context

[0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md) adopted machine-verifiable seam profiles and decided to retire the boolean `connects_on` flag, moving the construction validators onto seam matching. Doing that work exposed a deeper modelling problem the seam decision had assumed away.

The codebase models `metatile` as a **construction kind** — a fixed-shape multi-tile *entity* (`MetatileConstruction`, in the `Construction` union, `expose_as_entity`, an `EntityFootprintSpec`). It is not a tile: a construction cell resolves only to a single `TileRecord`, so a "metatile" cannot be used where a tile can, and it has no connection surface of its own. This conflation is the canonical meaning of *metatile* ("a tile made of tiles") applied to the wrong thing.

Flipping the metatile validator onto seam matching surfaced the cost. The grammar's `metatile` kind is a catch-all for two unlike things:

- **Bespoke composite assets** — a character, a large door: one artwork spanning cells. Their internal cell boundaries are slice lines, not connections. Seam-checking them is a false rejection (observed: 57 of 85 internal adjacencies in the `minimal8.characters` family "failed", scores as low as 0.25 — none of them were ever seams).
- **Kit-stitched fixed arrangements** — a table L-corner built from the table set's edge/corner/fill tiles. Here the pieces genuinely abut and the seams *should* be verified (these were wrongly exempted by being labelled metatiles; their leg-row near-misses are real).

A deeper observation: 0007's "derive openness from the pixels (non-null seam = open)" cannot by itself separate these — a sprite-fragment edge and a tiling edge are both painted. The distinguishing signal is the **composition relationship** (is this one asset, or pieces stitched by rules?), not the pixels.

The full treatment — including the variation and attachment systems and the entity/behaviour split — lives in the brain design **Composition Asset Model** (`Designs/tileset-tilesheet-fkd/Composition Asset Model.md`).

## Decision

Adopt a layered, symmetric **composition asset model**. The placeable layers are **tile**, **construction**, and **scene**; two composition systems — **variation** and **attachment** — apply uniformly over placeable units; a placed unit is an **entity** whose dynamics a separate **behaviour** layer drives.

- **Tile (including metatile).** A `tile` (one cell) and a `metatile` (N×M cells) are the **same kind** — a tile — differing only by footprint. A tile is no longer strictly atomic. A metatile is a **bespoke composite asset**, authored as one unit; it is **not** the product of a construction. Every tile exposes a **connection surface** (a single tile's four edges; a metatile's outer perimeter) so it can be a *piece* a construction stitches; a metatile's internal cell boundaries are **not** seams.
- **Construction.** The **assembly layer**: it stitches multiple tiles/metatiles by connection rules into a shape, fixed (a specific table L-corner) or parametric (`run`, `frame`), from a kit of reusable tiles. It is the **only** layer that verifies seams. Its placed result is a **construction instance** (an entity), not a tile. There is **no "metatile construction kind"**.
- **Scene.** A saved, reusable, recursive arrangement of tiles and constructions (the existing scene-template surface).
- **Variation.** A set of N **replace-self renderings** of a unit, exactly one active, selected by a pluggable **driver** — discrete **state** (door open/closed) or a **clock** (animation frames). State and animation are one system, not two. Variation applies **uniformly** to tile, construction (where the whole arrangement reconfigures — a drawbridge raised/lowered — irreducible to per-tile variation), and scene, and composes recursively.
- **Attachment.** Tiles **overlaid at anchored slots** on a base (decoration; swappable parts). Slot-fill selection (sword vs mace) lives here, not in variation. Defined at the tile/metatile level; extension to construction/scene follows by symmetry (to confirm at build).
- **Entity & behaviour.** A placed unit is an entity ([0003](0003-scene-entities-are-first-class-runtime-objects.md)) holding instance state (active variation, slot fills). The **behaviour** layer drives that state; the asset model declares only the dynamic *surface*, never the driver.
- **`connects_on` is retired as a validation input** — authored ingest metadata only; field removal is a later migration.

The chosen name for the variation operator is **`variation`** (over `aspect`/`variant`/`phase`/`alternation`).

## Consequences

- **Seam verification relocates from "construction kinds" to "the construction layer over tiles and metatiles."** Reclassifying current `kind: metatile` entries by the discriminator (bespoke single asset → metatile; kit-stitched shape → construction) makes the outcomes correct in both directions: characters/portraits become metatiles and are not internally seam-checked; table corners become constructions and *are* checked — so the table-leg-row near-misses are **real** construction seams, and the author-override / relaxed-threshold mechanism (0007's D3/D8) gains its first legitimate consumer.
- **This supersedes the brain Metatile Convergence design's call** that `metatile` is a construction kind and a tile is atomic — while *advancing* that design's goal (honest nouns owned at the right layer). The seam/composition pressure that makes "composite = tile" correct postdates that design.
- **It is a real refactor, planned/built separately.** Metatile becomes a first-class composite tile (with derived outer seam surface and footprint, composable into constructions); the fixed arrangements currently mislabelled `metatile` are reclassified; variation and attachment become first-class systems; entity/behaviour are separated. The build must be **additive** — every capability the current `metatile` kind carries (footprint, placement anchor, derived entity templates, provenance, attachment sets, `requires_exposed_on`) lands somewhere in the new layering; nothing is lost.
- **The `parametric_frame` corner↔edge seam check remains deferred** (flip-aware mask orientation + fat NxM corners — its own evidence-gated sub-work).
- Until the refactor lands, the committed validators still use `connects_on`; this record states the decided direction, not the current code.
