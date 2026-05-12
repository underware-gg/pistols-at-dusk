# 202605 Minimal 8 Scene Experiments

This folder contains the ad hoc scene-composition experiment track for Minimal 8.

It is separate from the main layout-engine prototype:

- Engine prototype: `scripts/minimal8_harness.py`
- Experiment workflow: `experiments/202605-minimal8-scene-experiments/scripts/minimal8_workflow.py`
- Canonical family metadata: `prototypes/minimal8-harness/tile-families/minimal8/`

Contents:

- `scripts/`: experimental renderer only; semantic tile meaning now lives in the shared tile-family package
- `generated/mockups/`: committed experimental mockup outputs kept with this experiment
- `scratch.local/`: ignored scratch boards, reference studies, and inspection images

This track is useful for discovery and visual iteration, but it is not the canonical engine architecture.
It should consume shared metadata rather than define its own tile semantics.
