# scripts/

Shared engine code for the Minimal 8 layout harness and tile-family ingestion. This directory is indexed from the functional layer at [docs/functional/README.md](../docs/functional/README.md).

## Modules

- [minimal8_harness.py](minimal8_harness.py) — harness CLI: layout rendering, family bootstrap, inspect/export, review-pack export, semantic queries. Project-specific runtime callbacks for the scene DSL and entity expansion.
- [tile_families.py](tile_families.py) — generic tile-family loader and query model: family / cluster / tile catalogs, alias resolution, address parsing, construction loading and validation.
- [scene_templates.py](scene_templates.py) — scene template DSL: file-backed loading, validation, expression evaluation, data-mode scene expansion, cycle detection across `place_scene`.
- [scene_rules.py](scene_rules.py) — environment-specific scene-rules loader and validator for weighted stamp/entity/scene candidate catalogues.
- [prototype_output.py](prototype_output.py) — render pipeline output helpers (staged writes, archive rotation on diff).

## Tooling

- [check_pyright.sh](check_pyright.sh) — type-check entrypoint. Required to pass before committing typed engine changes.
- [check_coverage.sh](check_coverage.sh) — coverage entrypoint for the shared Python scripts.

## Tests

Tests for these modules live in [tests/](../tests). See [docs/functional/README.md](../docs/functional/README.md) for the test index.
