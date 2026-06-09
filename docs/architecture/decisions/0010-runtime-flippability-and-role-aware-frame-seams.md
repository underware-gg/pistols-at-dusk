# 0010 - Runtime Flippability and Role-Aware Frame Seam Verification

- Status: accepted
- Extends: [0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md), [0008](0008-locate-seam-contact-line-at-content-box-edge.md)

## Context

[ADR 0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md) adopted derived seam profiles as the source of truth for construction adjacency. [ADR 0008](0008-locate-seam-contact-line-at-content-box-edge.md) refined where a seam contact line is read for inset/guttered art. Fixed constructions and parametric runs can use that model directly: their internal contacts are ordinary butt-joins between filled cells.

Attempting to extend the same exact silhouette gate to Minimal 8 parametric frames exposed two separate concerns.

First, Minimal 8's top/right 1px gutter does not survive runtime flipping. A runtime horizontal or vertical flip moves the gutter to the wrong side, so a flipped variant no longer honours the tileset's authored contact-line convention. The renderer can still support runtime flips generically for tilesets that permit them, but Minimal 8 cannot safely use that capability.

Second, discrete gutter-anchored frame kits do not reduce to one uniform "every contact is a mechanical butt-join" relation. Repeating connector contacts and fill repeats are candidates for ordinary seam-profile verification, but corner/cap junctions are role-defined transitions. They may elaborate, terminate, or visually separate border motifs across a gutter while still rendering as an intended frame. Treating every corner-to-edge join as the same silhouette match as a table edge is the wrong relation.

The detailed follow-up design now lives in the brain as **Dynamic Construction Grammar and Role-Aware Seam Verification** under the Tile Composition Compatibility design lineage.

## Decision

Add explicit runtime-flippability metadata at the family/tileset boundary.

- A family/compatibility tilesheet declares whether its tiles are safe to runtime-flip.
- The value is promoted into runtime metadata alongside other ingest-to-runtime properties such as `cell_content_inset` and alignment origin; runtime consumers use the promoted family/runtime record, not ingest files.
- Minimal 8 declares `runtime_flippable: false`.
- Construction loading rejects `flip_x` / `flip_y` on any parametric-frame corner, edge, or fill slot whose family is not runtime-flippable. This is an authoring error, not a renderer limitation.
- The renderer's generic flip mechanism remains intact for future tilesets whose gutter/contact-line conventions allow runtime flipping.

Defer parametric-frame seam verification to role-aware construction grammar work.

- This sequence keeps `parametric_frame` structurally validated only: roles resolve, required slots and dimensions are valid, and non-flippable families cannot author runtime flips.
- Frame seam verification must distinguish role relations. Repeating connector/fill contacts can be checked as mechanical joins; corner/cap transitions need a role-aware rule rather than a uniform silhouette gate.
- Fixed constructions and parametric runs remain under the ADR 0007/0008 seam-profile validators.

## Consequences

- Families that draw asymmetric gutters fail loudly if authors try to derive frame slots through runtime flips.
- Minimal 8's flip-derived frames are parked until synthetic, gutter-honouring flipped tiles are authored or the role-aware construction grammar design decides a different representation.
- The codebase avoids committing an incorrect parametric-frame seam validator just to close the composition-asset sequence.
- The mechanical seam-profile model remains valid for contacts that are actually mechanical joins; frame-specific role semantics are moved into a design that can represent them explicitly.
