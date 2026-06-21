"""Promotion from resolved ingest semantic catalogue into runtime tile units."""

from __future__ import annotations

from dataclasses import MISSING, fields, replace
from typing import Mapping

from semantic_catalogue_ingest import INGEST_SEMANTIC_FIELDS, ResolvedSemanticTile, SemanticFactValue, index_by_content_hash
from tile_library import LegacyTileSemanticRecord, RUNTIME_AUTHORED_TILE_FIELDS, TileLibraryUnit, TileRecord


if INGEST_SEMANTIC_FIELDS & RUNTIME_AUTHORED_TILE_FIELDS:
    raise ValueError("INGEST_SEMANTIC_FIELDS and RUNTIME_AUTHORED_TILE_FIELDS must be disjoint")

_TILE_RECORD_FIELD_NAMES = frozenset(field.name for field in fields(TileRecord))
if missing_fields := sorted(INGEST_SEMANTIC_FIELDS - _TILE_RECORD_FIELD_NAMES):
    raise ValueError(f"INGEST_SEMANTIC_FIELDS are not TileRecord fields: {', '.join(missing_fields)}")

_TILE_RECORD_FIELD_DEFAULTS: dict[str, object] = {}
for field in fields(TileRecord):
    if field.default is not MISSING:
        _TILE_RECORD_FIELD_DEFAULTS[field.name] = field.default
    elif field.default_factory is not MISSING:
        _TILE_RECORD_FIELD_DEFAULTS[field.name] = field.default_factory()
    else:
        _TILE_RECORD_FIELD_DEFAULTS[field.name] = MISSING
if fields_without_defaults := sorted(
    field for field in INGEST_SEMANTIC_FIELDS if _TILE_RECORD_FIELD_DEFAULTS[field] is MISSING
):
    raise ValueError(
        "INGEST_SEMANTIC_FIELDS must have TileRecord defaults for authoritative reset: "
        f"{', '.join(fields_without_defaults)}"
    )


def promote_semantic_catalogue(
    unit: TileLibraryUnit,
    *,
    resolved: tuple[ResolvedSemanticTile, ...],
    content_hash_by_tile_id: Mapping[str, str],
    legacy_semantics: tuple[LegacyTileSemanticRecord, ...] = (),
) -> TileLibraryUnit:
    """Refresh ingest-originated tile facts from a resolved content-keyed catalogue.

    `content_hash_by_tile_id` must be computed over the same selected variant set
    as the resolved catalogue. A different variant set will fail loudly as missing
    resolved records rather than silently preserving stale semantics.
    If `legacy_semantics` is omitted or empty, the unit's existing legacy layer is
    preserved; a non-empty value replaces that layer wholesale.
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
    promoted = unit.with_tiles(runtime_tiles)
    if not legacy_semantics:
        return promoted
    return replace(promoted, legacy_semantics=_legacy_semantics_by_tile_id(legacy_semantics))


def _promote_tile_semantics(tile: TileRecord, semantic_record: ResolvedSemanticTile) -> TileRecord:
    updates = {
        field: _resolved_field_value(field, semantic_record.facts.get(field))
        for field in sorted(INGEST_SEMANTIC_FIELDS)
    }
    return replace(tile, **updates)


def _resolved_field_value(field: str, value: SemanticFactValue | None) -> object:
    return value if value is not None else _TILE_RECORD_FIELD_DEFAULTS[field]


def _legacy_semantics_by_tile_id(
    legacy_semantics: tuple[LegacyTileSemanticRecord, ...],
) -> dict[str, LegacyTileSemanticRecord]:
    records: dict[str, LegacyTileSemanticRecord] = {}
    for record in legacy_semantics:
        if record.tile_id in records:
            raise ValueError(f"Duplicate legacy semantic record for tile {record.tile_id!r}")
        records[record.tile_id] = record
    return records
