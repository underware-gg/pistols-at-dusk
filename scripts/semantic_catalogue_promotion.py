"""Promotion from resolved ingest semantic catalogue into runtime tile units."""

from __future__ import annotations

from dataclasses import MISSING, fields, replace
from functools import cache
from typing import Mapping

from semantic_catalogue_ingest import INGEST_SEMANTIC_FIELDS, ResolvedSemanticTile, SemanticFactValue, index_by_content_hash
from tile_library import RUNTIME_AUTHORED_TILE_FIELDS, TileLibraryUnit, TileRecord


if INGEST_SEMANTIC_FIELDS & RUNTIME_AUTHORED_TILE_FIELDS:
    raise ValueError("INGEST_SEMANTIC_FIELDS and RUNTIME_AUTHORED_TILE_FIELDS must be disjoint")

_TILE_RECORD_FIELD_NAMES = frozenset(field.name for field in fields(TileRecord))
if missing_fields := sorted(INGEST_SEMANTIC_FIELDS - _TILE_RECORD_FIELD_NAMES):
    raise ValueError(f"INGEST_SEMANTIC_FIELDS are not TileRecord fields: {', '.join(missing_fields)}")


def promote_semantic_catalogue(
    unit: TileLibraryUnit,
    *,
    resolved: tuple[ResolvedSemanticTile, ...],
    content_hash_by_tile_id: Mapping[str, str],
) -> TileLibraryUnit:
    """Refresh ingest-originated tile facts from a resolved content-keyed catalogue.

    `content_hash_by_tile_id` must be computed over the same selected variant set
    as the resolved catalogue. A different variant set will fail loudly as missing
    resolved records rather than silently preserving stale semantics.
    """

    resolved_by_hash = index_by_content_hash(resolved, kind="resolved semantic record")
    unused_hashes = set(resolved_by_hash)
    runtime_tiles: dict[str, TileRecord] = {}
    for tile_id, tile in unit.tiles.items():
        content_hash = content_hash_by_tile_id.get(tile_id)
        if content_hash is None:
            raise ValueError(f"Missing content hash for tile {tile_id!r}")
        semantic_record = resolved_by_hash.get(content_hash)
        if semantic_record is None:
            raise ValueError(f"Tile {tile_id!r} content hash {content_hash!r} has no resolved semantic record")
        unused_hashes.discard(content_hash)
        runtime_tiles[tile_id] = _promote_tile_semantics(tile, semantic_record)
    if unused_hashes:
        raise ValueError(f"Resolved semantic catalogue contains unused content hashes: {', '.join(sorted(unused_hashes))}")
    return unit.with_tiles(runtime_tiles)


def _promote_tile_semantics(tile: TileRecord, semantic_record: ResolvedSemanticTile) -> TileRecord:
    updates = {
        field: _resolved_field_value(
            field,
            semantic_record.facts.get(field),
            tile_id=tile.id,
            content_hash=semantic_record.content_hash,
        )
        for field in sorted(INGEST_SEMANTIC_FIELDS)
    }
    return replace(tile, **updates)


def _resolved_field_value(
    field: str,
    value: SemanticFactValue | None,
    *,
    tile_id: str,
    content_hash: str,
) -> object:
    if value is not None:
        return value
    default = _tile_record_field_defaults()[field]
    if default is MISSING:
        raise ValueError(
            f"Resolved semantic record {content_hash!r} for tile {tile_id!r} omits required ingest field {field!r}"
        )
    return default


@cache
def _tile_record_field_defaults() -> dict[str, object]:
    defaults: dict[str, object] = {}
    for field in fields(TileRecord):
        if field.default is not MISSING:
            defaults[field.name] = field.default
        elif field.default_factory is not MISSING:
            defaults[field.name] = field.default_factory()
        else:
            defaults[field.name] = MISSING
    return defaults
