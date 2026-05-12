# Scene Rulesets

Scene rulesets are the environment-specific proc-gen layer for the harness.

They do not redefine tile meaning or construction legality. Instead they answer:

- what kinds of thing are allowed in this environment
- how likely each candidate is
- whether a slot should place a single tile, a construction, or a reusable scene fragment

The clean split is:

- `tiles.json`: generic semantic truth about individual tiles
- `constructions.json`: legal reusable multi-tile entities
- `scene-templates/*.json`: authored room structure and slot locations
- `scene-rules/*.json`: weighted environment-specific candidate catalogues

## Schema

Each ruleset file is a flat JSON document:

```json
{
  "ruleset_id": "tavern",
  "description": "Weighted tavern-specific placement catalogues.",
  "catalogues": {
    "dining_square_2x2": [
      {"id": "occupied_a", "kind": "scene", "scene": "tavern.cluster.square_2x2.occupied_a", "weight": 2},
      {"id": "occupied_b", "kind": "scene", "scene": "tavern.cluster.square_2x2.occupied_b", "weight": 1}
    ]
  }
}
```

Candidate kinds:

- `stamp`: place a single tile ref
- `entity`: place a construction by id
- `scene`: place a reusable scene-template fragment

Selection is deterministic by seed. Rulesets are deliberately slot-based in this
first pass: templates decide **where**, rulesets decide **what**, and fragment
templates decide **how multiple things relate**.

## Current Conventions

- Keep the namespace flat in this pass.
- Prefer fragment template names like `tavern.cluster.rect_3x2.occupied_a`.
- Keep environment-specific behaviour here rather than pushing it down into the
  tile database.
- Keep current authoring on the canonical alias set where possible. For
  example, the backless single-seat tiles are canonicalised as `indoors.stool`;
  `indoors.bench.*` remains a compatibility alias, not a separate behavioural
  concept.
