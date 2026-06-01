# Reference: Party Menu Character Stats

Primary files:

- [reference-party-menu-character-stats.json](reference-party-menu-character-stats.json)
- [reference-party-menu-character-stats--guide.png](../../../resources/Super%20Assets%203000/references/reference-party-menu-character-stats--guide.png)

## What this reference is for

This is the committed canonical reference handoff for the party-menu screen.

The solve is now trusted for the full non-text reconstruction surface:

- the committed JSON is trusted for the **layout grid**
- the reviewed `reviews` map is trusted for the **canonical tile + colour**
  truth of the reference cells we reproduce as data
- the tracked scene recreation now mirrors that reviewed truth exactly, except
  for one explicit artistic deviation noted below

One important correction: this reference is not usefully sliced on the raw
`32px` render raster. The earlier `85 x 60` solve was too fine and obscured the
real authored layout. The current committed solve uses the coarser menu/layout
grid instead.

## Confirmed facts

These points have been manually reviewed and should be treated as current
ground truth:

- the committed `34 x 24` coarse grid looks correct and lines up with known
  authored elements in the reference
- the reference contains three large party characters sourced from
  [minimal8-characters](../tile-families/minimal8-characters)
- each party character occupies a `2 x 3` block of standard tile cells
- the reference also contains free-form text that is not expected to match
  runtime tiles directly
- those text cells should be treated as excluded reference cells rather than as
  tile-matching targets
- this includes the central `Party` heading and its underline
- the Characters sheet is still under manual source-layout review and should
  not yet be treated as a committed runtime-construction library
- the tracked data recreation now has tile-and-colour parity with the
  reference for the solved scene cells
- the only intentional difference between the reference and the tracked data
  recreation is `C31R17`: the reference uses the green trunk, while the
  recreation intentionally keeps the brown sibling for readability

This still means the whole image should not be treated as a naive
"one source tile per grid cell" matching surface. The coarse grid is the right
starting point, but some cells are semantic excludes and some cells are
compound character art rather than single-tile matches.

## Practical reading

- trust the grid solve
- trust the reviewed `reviews` map as the canonical non-text tile/colour truth
- treat the tracked scene recreation as the canonical data copy of that truth,
  with the single explicit `C31R17` brown-trunk deviation
- do not assume the current Characters family already has stable source-layout
  metadata, stable runtime tile semantics, or approved multi-cell actor
  constructions
- the next active follow-up is matcher tuning against this now-canonical
  reference/recreation pair
- any future runtime-facing actor meaning should be promoted from reviewed
  source evidence into constructions or another explicit composition surface,
  not inferred directly from the raw sheet

At the moment this means:

- [reference_grid.py](../../../scripts/reference_grid.py) is the right tool for
  the whole-screen party-menu guide
- the current whole-screen [reference_tile_match.py](../../../scripts/reference_tile_match.py)
  output is still only a candidate generator, not the authority
- the authority for this screen is now the reviewed reference handoff plus the
  tracked data recreation
- matcher work from here should be measured against the canonical reviewed
  cells, not against older scratch output or stale best-guess passes
