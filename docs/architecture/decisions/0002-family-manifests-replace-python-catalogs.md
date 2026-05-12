# 0002 - Family Manifests Replace Python Semantic Catalogs

- Status: accepted

## Context

The previous Minimal 8 system stored source-sheet regions, semantic overrides, aliases, and review-driven meaning in `scripts/minimal8_semantic_catalog.py`.

That worked as a spike, but it made the source of truth:

- code-only
- family-specific
- hard to review as data
- awkward to reuse for other sprite families

## Decision

Move the semantic source of truth into a family package with:

- `family.json`
- `clusters.json`
- `tiles.json`
- `aliases.json`

Runtime code loads these manifests through a generic family loader/query module.

## Consequences

- Sprite-sheet ingestion becomes repeatable for new families.
- Human review can focus on data, not Python code.
- Variants, clusters, and tiles become explicit first-class concepts.
- Migration effort increases up front, but future families get cheaper to add.
