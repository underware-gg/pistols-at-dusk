# 0007 - Adopt the Three-Axis Tile-Compatibility Model and Build Machine-Verifiable Seam Profiles

- Status: accepted
- Supersedes: [0006](0006-defer-cross-kit-interchangeability-to-seam-profiles.md)

## Context

[ADR 0006](0006-defer-cross-kit-interchangeability-to-seam-profiles.md) deferred cross-kit interchangeability under YAGNI: no runtime consumer, only one ingested tileset (`minimal8`), and `connects_on` could not verify interchangeability anyway. Two forces invalidate that record's central premise.

1. **The single-tileset premise has lapsed.** Multiple real packs sit un-ingested in `resources/` (`demonic-dungeon`, `mini-medieval`, `Super Assets 3000`); only `minimal8` is ingested. Cross-source composition — using and blending tiles from more than one pack — is an explicit goal, which makes "no consumer" false. The absence of a consumer was partly circular: a composition primitive attracts no callers until it exists.

2. **"Compatible" was under-modelled.** Two tiles belonging together in a scene requires three independent properties on a *verifiability gradient*: **mechanical** (do edges physically compose — derivable and verifiable), **aesthetic** (do they read as one visual set — partly derived, partly curated), and **semantic** (do they plausibly co-occur — mostly authored). 0006 addressed only a slice of the mechanical axis, and bundled a standalone correctness improvement — seam verification of *existing* constructions — into the deferral.

The durable design lives in the project brain vault as the **Tile Composition Compatibility** hub (the three axes plus a composition engine that consumes them).

## Decision

Reverse 0006's deferral and adopt the **three-axis tile-compatibility model**. Of the three axes, only the **mechanical axis — machine-verifiable seam profiles — is accepted for build** by this record; the aesthetic and semantic axes and the composition engine are recorded as proposed, not adopted.

The mechanical axis is decided as follows:

- **Seam identity is derived, not declared.** A tile-side's seam profile is the **occupancy mask of its 1px contact line**, computed from the background-normalised art. A hash of the mask gives exact-match identity and a **source-blind** cross-source collision signal — the key carries no pack or kit identity, so equal keys across packs *are* the compatibility signal. Graded matchers compare the masks directly.
- **Mechanical identity is the silhouette.** Colour and shading are not part of mechanical fit; they are the aesthetic axis's concern. Sibling colourways therefore share seam identity. Per-pixel luminance structure and multi-pixel seam depth are outside the mechanical identity.
- **Fit is equality or complement.** Two sides fit when their masks are equal (butt-join) or complementary (interlocking), evaluated by independent scored matchers under a configurable combining policy.
- **Derived-first, author-overridable.** Derived keys are the source of truth; explicit, recorded overrides are the sanctioned exception. This inverts `connects_on`'s declaration-only model — derivation is the default, declaration the checked exception.
- **Bounded scope.** Seam matching is defined within a single grid size and applies to construction-internal adjacencies. Cross-resolution matching and texture-tiling continuity are outside this axis (the latter is a distinct, tolerance-based relation).

**The `connects_on` direction-flag model is superseded.** Seam-profile matching becomes the source of truth for construction adjacency; `connects_on` is no longer a trusted, hand-maintained field — at most a value derived from seam profiles.

## Consequences

- Construction-adjacency validation verifies facing seam profiles instead of `connects_on` set-membership. It now catches adjacencies that are both "open" yet do not physically line up — currently a silent rendering fault — and can verify cross-kit corner/edge mixes that `connects_on` could never check. The affected validators are `_validate_metatile_construction`, `_validate_parametric_run_construction`, and `_validate_parametric_frame_construction` in `scripts/tile_families.py`.
- `connects_on` is demoted from an authored source of truth to, at most, a value derived from seam profiles; the construction layer stops trusting a direction flag.
- Cross-kit interchangeability becomes a derived, verifiable property (matching seam keys) rather than a hand-declared one — the capability 0006 deferred.
- The mechanical axis has an explicit boundary with the other two: colour/shading continuity and co-occurrence are not mechanical concerns, which keeps "machine-verifiable" meaning only what is derived from the art.
- 0006 is superseded; its body is preserved as the record of why the deferral was sound under its original premise.
