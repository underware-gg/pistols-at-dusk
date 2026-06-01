# Construction and Scene Architecture

How the current stack, initially realised through Minimal 8, composes tile-based scenes from atomic tiles, named multi-tile constructions, and recursive scenes. This is a current-state living document; decisions that shaped it are recorded under [decisions/](decisions).

This document should be read as the current composition-side baseline after the metatile-convergence phase, not as a speculative future design:

- the staged source-pack ingest/runtime boundary is now established at the CLI surface — `source_ingest.py` provides the operator-facing ingest entrypoint, though the ingest function bodies currently remain in `minimal8_harness.py` pending a full implementation-level split
- constructions, entity templates, and recursive scene placement are healthy and remain the right centre of gravity here
- the project-level `metatiles` registry is gone as an active harness/project concept; project-local tile-grid snippets now live under explicit `patterns` consumed through `stamp`, `fill`, `repeat`, `box`, and similar pattern-oriented surfaces
- former mixed-use registry entries have now been routed onto honest composition nouns: entity-shaped cases onto constructions, pure naming conveniences onto aliases/direct refs, and non-entity reusable snippets onto patterns
- any future higher-order reusable authored arrangements should ride the existing scene/sub-scene system rather than reviving a generic peer registry

## Three layers

| Layer | Concept | Scope | Validates against |
|---|---|---|---|
| **Tile** | Atomic unit | Single cell | Nothing — it just exists |
| **Construction** | Named legal arrangement of tiles forming one entity | Single collection (one kit) | Tile-level rules (adjacency, exposure) |
| **Scene** | Arrangement of entities and primitives | Cross-collection, recursive | Future: scene-level rules (overlap, layer use) |

### Entity vs scene

**Entity** is the supertype of placeable values: a tile reference, a project pattern reference, or a construction reference with bound parameters. Anything that, given (x, y), occupies cells.

**Scene** is *not* an entity. A scene is a procedure that emits entities into a coordinate space. When a parent scene places a sub-scene at (x, y), the sub-scene's contents unroll into the parent — function inlining, not nested placement. A scene is "top-level" by *use* (the scene the renderer is pointed at), not by data; the same artefact serves both top-level and nested roles.

## Constructions

Constructions live in `tile-families/<family>/constructions.json`. Each record carries:

- `id` — namespaced as `<collection_id>.<short_name>` (e.g. `indoors.door.grand.closed`, `indoors.table.kit.horizontal_run`).
- `collection_id` — backref to the source-layout collection.
- `kind` — currently `metatile` (fixed-shape multi-tile composite), `parametric_run` (variable-length run with start / repeat / end roles), or `parametric_frame` (resizable border/frame kind — the 2-D analogue of `parametric_run` — placed through the entity/construction pipeline; `expose_as_entity` defaults `true`).

For `metatile`: an explicit 2D `cells` grid with role-bound entries; `.` for empty. For `parametric_run`: `axis: "x" | "y"`, `length_param`, `start_role`, `repeat_role`, `end_role`. For `parametric_frame`: corners (1×1 by role, fat N×M via a `cells` grid, flip-derived, or borrowed by tile-id), edges (with flip-derivation and role/tile overrides), and an optional fill slot; `fill_mode` enum (`repeat` / `round`) is a no-op for single-cell tiles; resizable `width`/`height` are supplied via the entity op's `params`.

`metatile` preserves the canonical graphics-programming meaning; `parametric_run` extends to variable-length runs without overloading the term.

### Role binding

Cells reference tiles by **role** (`compose_role`), not by alias or tile id. The loader resolves a role by querying the kit (`compose_group == collection_id` and `compose_role == cell.role`). One tile per role; multiple matches are an authoring error and load-time validation rejects them.

This keeps constructions neutral about alias-level mapping — the kit owns it.

### Validation

Validation is a pure function (no I/O, no shared state) and runs at family load over every construction. Two cell-level rules:

- **Adjacency.** Every internal edge between two filled cells must agree on `connects_on`. If cell A's east neighbour is cell B, then `"east"` must appear in A's `connects_on` and `"west"` must appear in B's.
- **Exposure.** Every cell whose tile lists `requires_exposed_on: [dir]` must have no internal cell on that side. Edge-of-construction or empty cells are acceptable; an internal neighbour is a violation.

Failures carry the construction id, cell coordinates, and a human-readable reason. Load-time enforcement is deliberate: a family containing an invalid construction fails to load, so tile-level rules become load-bearing rather than decorative metadata. Runtime resolution can then trust that every construction it sees is structurally valid.

## Scenes

Scenes are templates in `scene-templates/`. The DSL evaluator currently supports:

- **`box`**, **`fill`**, **`stamp`**, **`spread_stamps`** — primitive layout ops.
- **`entity`** — places one entity (construction instance) at (x, y), optionally with parameters for parametric kinds. Resolves construction → cells → stamps.
- **`place_scene`** — places another scene's contents at (x, y), passing arguments. Cycle detection at load. Sub-scene's (0, 0) becomes parent's (x, y). Each call is a fresh binding frame; sub-scenes do not see parent bindings except via passed arguments.
- **`scatter`** — sparse stamp placement against a hand-authored mask using a deterministic seed (data-mode wrapper over the runtime variant).
- **`populate_slots`** — slot-based entity population.

Expression operators include `param`, `add`, `sub`, `mul`, `centered_x` / `centered_y`, `min`, `fill_rows`, plus `when_present` for optional branches.

## Two-phase expansion

Scene-template expansion runs in two phases at render time:

1. **Generic scene-template expansion** — `scene_templates.py` evaluates the scene DSL into ordinary scene ops plus unresolved entity requests. This phase is family-agnostic.
2. **Entity resolution** — the harness (`minimal8_harness.py`) resolves entity requests against the selected family into first-class entity instances, then lowers those instances to stamp ops for rendering.

This preserves the distinction between source-layout collections, constructions, derived entity templates, placed scene entities, and render-time stamp ops, instead of collapsing them all into stamps eagerly.

## Open shape

The architecture is realised end-to-end: the tavern (`fool_and_flintlock`) renders via this pipeline (constructions + scene DSL, no code-mode expander).

Known open questions, deferred:

- **Variant slots within a construction** (alternates per role).
- **Affordance / walkability propagation** from tile rules up to construction-level composite affordances.
- **Cross-kit constructions.**
- **Scene-level validation** (overlap detection, layer correctness, reachability).

## Out of scope

- Animation, pose-set, and state-group axes — orthogonal to composition; live as tile metadata.
- Game-logic layers (movement, interaction, simulation) — the harness renders, it does not simulate.
- Procedural / generative scene templates — scenes stay declarative.

## References

- [scripts/tile_families.py](../../scripts/tile_families.py) — construction loading and validation.
- [scripts/scene_templates.py](../../scripts/scene_templates.py) — DSL evaluator.
- [scripts/minimal8_harness.py](../../scripts/minimal8_harness.py) — entity resolution and render pipeline.
- [prototypes/minimal8-harness/tile-families/minimal8/constructions.json](../../prototypes/minimal8-harness/tile-families/minimal8/constructions.json) — current Minimal 8 construction set.
- [prototypes/minimal8-harness/scene-templates/](../../prototypes/minimal8-harness/scene-templates) — current scene templates.
