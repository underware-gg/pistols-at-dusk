# Reference Notes — Polychrome Temple Courtyard

Companion note for:

- [reference-polychrome-temple-courtyard.json](reference-polychrome-temple-courtyard.json)
- [reference-polychrome-temple-courtyard--guide.png](../../../resources/Super%20Assets%203000/references/reference-polychrome-temple-courtyard--guide.png)

## Intent

This is the **messy but important ingest case**.

It exists to pressure-test the reference tools against a real reference that is
visually close to Minimal 8 but not clean enough to behave like a direct native
tile render.

## Why It Matters

- it exposed the need for exact-span solving instead of free-running
  `origin + cell_size` rounding
- it exposed the need for a normalized ingest surface built from the exact
  tiled-body span
- it exposed the need for shape-first matching instead of heavy dependence on
  exact colour or exact anchored mask overlap
- it exposed the need for checked-in manual review state, not scratch-only notes

## Current Read Of The Reference

- the heading at the top is non-tiled ornament and is intentionally excluded
- the tiled body solves well enough to act as a trusted ingest target
- the source appears visually closer to the older 1-bit sheet, but the best
  available committed source matches currently come from the `2bit_colored_bg`
  variant
- at least some cells appear to reflect an older or phase-shifted tile
  revision rather than a slicing bug in the current tooling

## Manual Review State

The JSON config carries committed `reviews` for the currently inspected cells.

That includes:

- confirmed tile selections where the matcher needed human confirmation
- confirmed blank cells where a semantic blank is the right ingest outcome
- notes explaining why a reviewed choice was accepted

## Important Matcher Insight

This reference is the reason the matcher now carries a conservative
trimmed-logical-mask rescue.

That rescue exists for cases where:

- the broad shape is clearly the right motif
- projection and chamfer metrics are already strong
- but whitespace placement inside the cell has drifted enough to collapse raw
  anchored `mask_iou`

The rescue is intentionally narrow. It should help this class of degraded
reference without changing clean references such as the overworld anchor.

## Confidence

Medium-high.

This is now in good shape as an ingest/reference workflow, but it should still
be read as a degraded-reference case rather than as proof that every historical
reference is as clean as the overworld anchor.

## How To Iterate

- rerun the slicer or matcher from the committed JSON config
- inspect the committed guide image, not scratch-only overlays
- use `python3 scripts/source_ingest.py inspect-source-cell` when a human description refers to raw sheet
  structure like “top section of the second column”
- prefer explaining a disagreement in terms of reference drift or reviewed
  confidence before assuming the grid solve is wrong again
