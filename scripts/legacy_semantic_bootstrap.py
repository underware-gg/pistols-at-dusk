"""One-time legacy `tiles.json` to content-keyed semantic patch bootstrap."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from PIL import Image

from semantic_catalogue_ingest import (
    INGEST_SEMANTIC_FIELDS,
    AuthoredSemanticPatch,
    DetectedSemanticTile,
    SemanticFactValue,
    authored_patch_to_json,
    content_hash_for_variant_images,
    detected_base_to_json,
    semantic_payload_to_json,
)
from tile_family_runtime import TileFamily, resolve_canonical_tile_image
from tile_library import LegacyTileSemanticRecord, TileRecord


LEGACY_TILE_SEMANTICS_SCHEMA_VERSION = 1
LEGACY_TILE_SEMANTICS_ORIGIN = "legacy_tiles_json"

# Frozen snapshot of the legacy tiles.json semantic schema. Do not derive this
# from the live content-keyed taxonomy; this artifact preserves historical input.
LEGACY_TILE_SEMANTIC_FIELDS = frozenset(
    {
        "category",
        "contrast",
        "facing",
        "footprint",
        "layer",
        "meaning",
        "meaning_confidence",
        "motifs",
        "noise",
        "orientation",
        "overlay",
        "pose",
        "semantics",
        "source_notes",
        "style",
        "tags",
        "temperature",
        "usage",
    }
)

_TILE_RECORD_FIELD_NAMES = frozenset(field.name for field in fields(TileRecord))
if missing_legacy_fields := sorted(LEGACY_TILE_SEMANTIC_FIELDS - _TILE_RECORD_FIELD_NAMES):
    raise ValueError(f"LEGACY_TILE_SEMANTIC_FIELDS are not TileRecord fields: {', '.join(missing_legacy_fields)}")


@dataclass(frozen=True)
class BootstrappedPhysicalTile:
    tile_id: str
    content_hash: str
    facts: Mapping[str, SemanticFactValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@dataclass(frozen=True)
class SemanticCollision:
    content_hash: str
    tile_ids: tuple[str, ...]
    differing_fields: Mapping[str, Mapping[str, tuple[str, ...]]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tile_ids", tuple(sorted(self.tile_ids)))
        normalised = {
            field: MappingProxyType({value: tuple(sorted(tile_ids)) for value, tile_ids in values.items()})
            for field, values in self.differing_fields.items()
        }
        object.__setattr__(self, "differing_fields", MappingProxyType(normalised))

    def to_payload(self) -> dict[str, object]:
        return {
            "content_hash": self.content_hash,
            "tile_ids": list(self.tile_ids),
            "differing_fields": {
                field: {value: list(tile_ids) for value, tile_ids in values.items()}
                for field, values in sorted(self.differing_fields.items())
            },
        }


@dataclass(frozen=True)
class LegacySemanticBootstrapResult:
    detected_base: tuple[DetectedSemanticTile, ...]
    authored_patches: tuple[AuthoredSemanticPatch, ...]
    legacy_semantics: tuple[LegacyTileSemanticRecord, ...]
    physical_tiles: tuple[BootstrappedPhysicalTile, ...]
    collisions: tuple[SemanticCollision, ...]


class LegacySemanticBootstrapCollisionError(ValueError):
    def __init__(self, collisions: tuple[SemanticCollision, ...]) -> None:
        self.collisions = collisions
        super().__init__(f"Legacy semantic bootstrap found {len(collisions)} divergent content-hash collision group(s)")


def collision_report_to_json(collisions: tuple[SemanticCollision, ...]) -> str:
    return semantic_payload_to_json(collision_report_payload(collisions))


def collision_report_payload(collisions: tuple[SemanticCollision, ...]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "collisions": [collision.to_payload() for collision in sorted(collisions, key=lambda item: item.content_hash)],
    }


def legacy_tile_semantics_to_json(records: tuple[LegacyTileSemanticRecord, ...]) -> str:
    return semantic_payload_to_json(legacy_tile_semantics_payload(records))


def legacy_tile_semantics_payload(records: tuple[LegacyTileSemanticRecord, ...]) -> dict[str, object]:
    return {
        "schema_version": LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
        "legacy_tile_semantics": [
            record.to_payload()
            for record in sorted(records, key=lambda item: item.tile_id)
        ],
    }


def write_bootstrap_outputs(result: LegacySemanticBootstrapResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "detected-base.json").write_text(detected_base_to_json(result.detected_base), encoding="utf-8")
    (output_dir / "authored-patch.json").write_text(authored_patch_to_json(result.authored_patches), encoding="utf-8")
    (output_dir / "bootstrap-collisions.json").write_text(collision_report_to_json(result.collisions), encoding="utf-8")
    (output_dir / "legacy-tile-semantics.json").write_text(
        legacy_tile_semantics_to_json(result.legacy_semantics),
        encoding="utf-8",
    )


def bootstrap_legacy_semantic_patch(
    family: TileFamily,
    *,
    variant_ids: tuple[str, ...] | None = None,
    raise_on_collisions: bool = True,
) -> LegacySemanticBootstrapResult:
    selected_variant_ids = variant_ids or tuple(sorted(family.variants))
    _require_known_variants(family, selected_variant_ids, context="bootstrap")

    image_cache: dict[Path, Image.Image] = {}
    physical_tiles: list[BootstrappedPhysicalTile] = []
    legacy_semantics: list[LegacyTileSemanticRecord] = []
    by_content_hash: dict[str, list[BootstrappedPhysicalTile]] = {}
    for tile in family.tiles.values():
        content_hash = _content_hash_for_tile(
            tile,
            family=family,
            variant_ids=selected_variant_ids,
            image_cache=image_cache,
        )
        physical = BootstrappedPhysicalTile(
            tile_id=tile.id,
            content_hash=content_hash,
            facts=_semantic_facts_for_tile(tile),
        )
        physical_tiles.append(physical)
        legacy_semantics.append(_legacy_semantic_record_for_tile(tile))
        by_content_hash.setdefault(content_hash, []).append(physical)

    detected_base: list[DetectedSemanticTile] = []
    authored_patches: list[AuthoredSemanticPatch] = []
    collisions: list[SemanticCollision] = []
    for content_hash in sorted(by_content_hash):
        group = by_content_hash[content_hash]
        detected_base.append(DetectedSemanticTile(content_hash=content_hash, facts={}))
        collision = _collision_for_group(content_hash, group)
        if collision is not None:
            collisions.append(collision)
            continue
        # The legacy catalogue is treated as authored migration input. The
        # detector phase can later demote detector-agreed fields from patch to
        # base without losing human-reviewed corrections.
        authored_patches.append(AuthoredSemanticPatch(content_hash=content_hash, facts=group[0].facts))

    result = LegacySemanticBootstrapResult(
        detected_base=tuple(detected_base),
        authored_patches=tuple(authored_patches),
        legacy_semantics=tuple(sorted(legacy_semantics, key=lambda item: item.tile_id)),
        physical_tiles=tuple(sorted(physical_tiles, key=lambda item: item.tile_id)),
        collisions=tuple(collisions),
    )
    if result.collisions and raise_on_collisions:
        raise LegacySemanticBootstrapCollisionError(result.collisions)
    return result


def _content_hash_for_tile(
    tile: TileRecord,
    *,
    family: TileFamily,
    variant_ids: tuple[str, ...],
    image_cache: dict[Path, Image.Image],
) -> str:
    images_by_variant_id = {
        variant_id: resolve_canonical_tile_image(
            tile,
            variant=family.variants[variant_id],
            root=family.root,
            tile_width=family.tile_width,
            tile_height=family.tile_height,
            image_cache=image_cache,
        )
        for variant_id in variant_ids
    }
    # Durable bootstrap identity is the signature over the full selected
    # variant set. Re-running bootstrap must use the same variant set to
    # preserve authored-patch keys.
    return content_hash_for_variant_images(images_by_variant_id)


def content_hashes_by_tile_id(
    family: TileFamily,
    *,
    variant_ids: tuple[str, ...],
) -> dict[str, str]:
    """Compute content-hash identities for every physical tile in a family.

    The caller must pass the same variant set that keyed the resolved semantic
    catalogue. A different set produces different content identities by design.
    """

    _require_known_variants(family, variant_ids, context="content-hash")
    image_cache: dict[Path, Image.Image] = {}
    return {
        tile.id: _content_hash_for_tile(
            tile,
            family=family,
            variant_ids=variant_ids,
            image_cache=image_cache,
        )
        for tile in family.tiles.values()
    }


def _require_known_variants(family: TileFamily, variant_ids: tuple[str, ...], *, context: str) -> None:
    unknown_variants = sorted(set(variant_ids) - set(family.variants))
    if unknown_variants:
        raise ValueError(f"Unknown {context} variant ids: {', '.join(unknown_variants)}")


def _semantic_facts_for_tile(tile: TileRecord) -> Mapping[str, SemanticFactValue]:
    return MappingProxyType({field: getattr(tile, field) for field in INGEST_SEMANTIC_FIELDS})


def _legacy_semantic_record_for_tile(tile: TileRecord) -> LegacyTileSemanticRecord:
    return LegacyTileSemanticRecord(
        tile_id=tile.id,
        origin=LEGACY_TILE_SEMANTICS_ORIGIN,
        schema_version=LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
        facts={field: getattr(tile, field) for field in LEGACY_TILE_SEMANTIC_FIELDS},
    )


def _collision_for_group(content_hash: str, group: list[BootstrappedPhysicalTile]) -> SemanticCollision | None:
    differing_fields: dict[str, dict[SemanticFactValue, tuple[str, ...]]] = {}
    for field in sorted(INGEST_SEMANTIC_FIELDS):
        values: dict[SemanticFactValue, list[str]] = {}
        for physical in group:
            values.setdefault(physical.facts[field], []).append(physical.tile_id)
        if len(values) > 1:
            differing_fields[field] = {value: tuple(tile_ids) for value, tile_ids in values.items()}
    if not differing_fields:
        return None
    return SemanticCollision(
        content_hash=content_hash,
        tile_ids=tuple(physical.tile_id for physical in group),
        differing_fields={
            field: {_fact_value_key(value): tile_ids for value, tile_ids in values.items()}
            for field, values in differing_fields.items()
        },
    )


def _fact_value_key(value: SemanticFactValue) -> str:
    if isinstance(value, tuple):
        return "tuple:" + json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return "null"
    return f"string:{value}"
