# 0003 - Scene Entities Are First-Class Runtime Objects

- Status: accepted

## Context

Minimal 8 already had three distinct concepts in the authored data:

- source-layout collections on the sheet
- constructions that define legal multi-tile arrangements
- scene-template `entity` ops that intend to place meaningful room objects

Before this decision, the runtime collapsed the third concept into plain stamp ops during generic scene-template expansion. That made scene rendering work, but it discarded entity identity too early:

- constructions doubled as both shape definitions and runtime object identity
- entity parameters, footprint intent, and compose-role groupings were not preserved as runtime objects
- export and inspection tooling had to infer entities back out of stamp clusters

## Decision

Treat scene entities as first-class runtime objects with a two-phase expansion model.

1. `scene_templates.py` expands generic scene templates into:
   - ordinary scene ops
   - unresolved entity requests
2. `minimal8_harness.py` resolves each entity request against the selected family into an `EntityInstance` that preserves:
   - stable entity ID
   - source template ID
   - derived entity template
   - layer
   - placement anchor, origin, and bounds
   - resolved tile placements
   - occupied cells with per-cell traversal metadata
   - affordance-bearing cells for interaction-facing queries
   - param values
3. Rendering remains stamp-based, but only as a final lowering step from `EntityInstance` to stamp ops.

Constructions stay the authority for legal tile arrangements. Derived entity templates become the runtime bridge between constructions and scene instances; they expose collection membership, footprint shape, affordances, compose roles, and state/animation groupings without pretending to be a placed object.

## Consequences

- Runtime inspection and export can preserve entity identity without reverse-engineering stamp clusters.
- Scene-template expansion stays generic and family-agnostic until the harness resolves entities.
- Rendering remains simple because the final render primitive is still a stamp op.
- Future occupancy, interaction, animation, and scene-export work now has an honest runtime object to attach to.
- Bounding rectangles are no longer the only footprint signal; L-shapes and sparse constructions preserve their true occupied-cell sets.
- Generic scene-template tests and harness/runtime tests must now verify both unresolved entity requests and resolved entity instances.
