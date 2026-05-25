# Reference Notes — Overworld Island Title Screen

Companion note for:

- [reference-overworld-island-title-screen.json](reference-overworld-island-title-screen.json)
- [reference-overworld-island-title-screen--guide.png](../../../resources/Super%20Assets%203000/references/reference-overworld-island-title-screen--guide.png)

## Intent

This is the **clean canonical reference-ingest example** for Minimal 8.

It exists to prove that the reference slicing / matching workflow works on a
well-behaved reference before we rely on the same tooling for messier inputs.

## Why We Trust It

- the tiled body snaps cleanly under the committed exact-span solve
- the reference uses the same bottom-left / top-right-gutter convention as the
  current Minimal 8 family
- the matcher behaves well without any special rescue path taking the top slot
- the recreated overworld scene was already a trusted authoring anchor before
  these ingest tools were generalized

## Current Solve

- body starts below the title heading and fills the rest of the image
- committed transform lives in the JSON config above
- committed padded `--guide` sibling image is the human review surface

## Known Quirks

- this reference still contains the decorative heading at the top, so the solve
  deliberately treats the tiled body as a relevant region below that heading
- the reference is trusted for ingest calibration, but the reconstructed scene
  is still a scene authoring artefact rather than a literal recovered tile dump

## Confidence

High.

This is the best current example of the ingest workflow operating on a
reference that behaves like clean native tile art.

## How To Iterate

- rerun the slicer or matcher from the committed JSON config
- if a reviewer needs to trace a matched cell back to raw source-sheet
  structure, use `python3 scripts/source_ingest.py inspect-source-cell`
  rather than guessing from guide strips
- treat any new rescue-path activation here as suspicious until proven useful;
  this reference is the main guard against overfitting degraded cases
