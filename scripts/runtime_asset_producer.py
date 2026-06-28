#!/usr/bin/env python3
"""Ingest-side runtime asset producer.

Reads today's source/compat family, materialises runtime-owned atomic tile
pixels, and writes the runtime-family JSON plus content-addressed PNG assets.
"""
from __future__ import annotations

import hashlib
import math
import os
import tempfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image

from layout_core import grid_dimensions_for_image
from legacy_semantic_bootstrap import legacy_tile_semantics_from_json
from pixel_content import canonical_rgba_bytes
from semantic_catalogue_ingest import ResolvedSemanticCatalogue, semantic_catalogue_with_identity_from_json
from source_manifest_bridge import BridgedSemanticInputs, load_bridged_tile_library_unit
from tile_family_ingest import load_source_tile_family
from tile_family_runtime import resolve_canonical_tile_image
from tile_library import (
    LEGACY_LAYER_TAG_PREFIX,
    REQUIRED_NON_CONTENT_TILE_FIELDS,
    TRANSITIONAL_NEUTRAL_TILE_LAYER,
    LegacyTileSemanticRecord,
    SheetCell,
    TileFamilyVariant,
    TileLibraryUnit,
    TileRecord,
    require_variant_sheet_path,
)
from tile_library_codec import tile_library_unit_to_json
from runtime_asset_paths import (
    atlas_cell_box,
    atomic_asset_address_from_digest,
    atomic_asset_relative_path,
    runtime_atlas_relative_path,
    runtime_family_root,
)


def atomic_asset_address(image: Image.Image) -> str:
    digest = hashlib.sha256(canonical_rgba_bytes(image)).hexdigest()
    return atomic_asset_address_from_digest(digest)


def deterministic_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(data)
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _write_atomic_asset(image: Image.Image, *, runtime_family_dir: Path) -> str:
    address = atomic_asset_address(image)
    path = runtime_family_dir / atomic_asset_relative_path(address)
    if path.exists():
        # Address is over canonical RGBA, not PNG bytes. Existing assets at the
        # same digest are trusted; a future audit can decode and verify if needed.
        return address
    _write_bytes_atomic(path, deterministic_png_bytes(image))
    return address


def _materialize_tile_image(
    tile: TileRecord,
    *,
    variant: TileFamilyVariant,
    unit: TileLibraryUnit,
    image_cache: dict[Path, Image.Image],
) -> Image.Image:
    return resolve_canonical_tile_image(
        tile,
        variant=variant,
        root=unit.root,
        tile_width=unit.tile_width,
        tile_height=unit.tile_height,
        image_cache=image_cache,
    )


def _runtime_tile(
    tile: TileRecord,
    *,
    variant_assets: Mapping[str, str],
    variant_atlas_cells: Mapping[str, SheetCell],
) -> TileRecord:
    return replace(
        tile,
        image_override=None,
        variant_assets=variant_assets,
        variant_atlas_cells=variant_atlas_cells,
    )


_HANDLED_REQUIRED_NON_CONTENT_TILE_FIELDS = frozenset({"category", "layer"})
if _HANDLED_REQUIRED_NON_CONTENT_TILE_FIELDS != REQUIRED_NON_CONTENT_TILE_FIELDS:
    raise ValueError(
        "runtime asset producer required non-content field seeding is out of sync with "
        f"REQUIRED_NON_CONTENT_TILE_FIELDS: handled={sorted(_HANDLED_REQUIRED_NON_CONTENT_TILE_FIELDS)} "
        f"required={sorted(REQUIRED_NON_CONTENT_TILE_FIELDS)}. If a required non-content field was added, add "
        "_seed_required_non_content_fields_from_legacy logic for it; do not only update the handled set."
    )


def _load_resolved_catalogue(path: Path) -> ResolvedSemanticCatalogue:
    try:
        return semantic_catalogue_with_identity_from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not load resolved semantic catalogue {path}: {exc}") from exc


def _load_legacy_semantics(path: Path) -> tuple[LegacyTileSemanticRecord, ...]:
    try:
        return legacy_tile_semantics_from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not load legacy tile semantics {path}: {exc}") from exc


def _legacy_fact_as_string(record: LegacyTileSemanticRecord, field: str, *, tile_id: str) -> str:
    value = record.facts.get(field)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"Legacy semantic record for tile {tile_id!r} must declare non-empty string {field!r}")
    return value


def _seed_required_non_content_fields_from_legacy(unit: TileLibraryUnit) -> TileLibraryUnit:
    runtime_tiles: dict[str, TileRecord] = {}
    for tile_id, tile in unit.tiles.items():
        legacy = unit.legacy_semantics.get(tile_id)
        if legacy is None:
            raise ValueError(f"Cannot seed required runtime fields for tile {tile_id!r}: missing legacy semantic record")
        category = _legacy_fact_as_string(legacy, "category", tile_id=tile_id)
        legacy_layer = _legacy_fact_as_string(legacy, "layer", tile_id=tile_id)
        layer_tag = f"{LEGACY_LAYER_TAG_PREFIX}{legacy_layer}"
        runtime_tiles[tile_id] = replace(
            tile,
            category=category,
            layer=TRANSITIONAL_NEUTRAL_TILE_LAYER,
            tags=tuple(sorted(set(tile.tags) | {layer_tag})),
        )
    return unit.with_tiles(runtime_tiles)


def _pack_order_key(tile: TileRecord) -> tuple[int, int, int, str]:
    if tile.genesis.sheet_col is not None and tile.genesis.sheet_row is not None:
        return (0, tile.genesis.sheet_row, tile.genesis.sheet_col, tile.id)
    return (1, 0, 0, tile.id)


def _runtime_variant(
    unit: TileLibraryUnit,
    variant: TileFamilyVariant,
    *,
    image_cache: dict[Path, Image.Image],
) -> TileFamilyVariant:
    sheet_path = require_variant_sheet_path(variant, context="runtime asset grid dimensions")
    sheet = image_cache.get(sheet_path)
    if sheet is None:
        sheet = Image.open(sheet_path).convert("RGBA")
        image_cache[sheet_path] = sheet
    grid_columns, grid_rows = grid_dimensions_for_image(
        image_width=sheet.width,
        image_height=sheet.height,
        tile_width=unit.tile_width,
        tile_height=unit.tile_height,
    )
    return replace(
        variant,
        sheet_path=None,
        grid_columns=grid_columns,
        grid_rows=grid_rows,
    )


def _pack_variant_atlas(
    variant: TileFamilyVariant,
    *,
    unit: TileLibraryUnit,
    runtime_tiles: Mapping[str, TileRecord],
    variant_images: Mapping[str, Image.Image],
    runtime_family_dir: Path,
    image_cache: dict[Path, Image.Image],
) -> tuple[TileFamilyVariant, dict[str, SheetCell]]:
    runtime_variant = _runtime_variant(unit, variant, image_cache=image_cache)
    ordered_tiles = sorted(runtime_tiles.values(), key=_pack_order_key)
    assert runtime_variant.grid_columns is not None
    atlas_columns = max(1, min(runtime_variant.grid_columns, len(ordered_tiles)))
    atlas_rows = max(1, math.ceil(len(ordered_tiles) / atlas_columns))
    atlas = Image.new(
        "RGBA",
        (atlas_columns * unit.tile_width, atlas_rows * unit.tile_height),
        (0, 0, 0, 0),
    )
    atlas_cells: dict[str, SheetCell] = {}
    for index, tile in enumerate(ordered_tiles):
        col = index % atlas_columns
        row = index // atlas_columns
        left, top, _right, _bottom = atlas_cell_box(
            col,
            row,
            tile_width=unit.tile_width,
            tile_height=unit.tile_height,
        )
        atlas.paste(variant_images[tile.id], (left, top))
        atlas_cells[tile.id] = SheetCell(col=col, row=row)
    atlas_path = runtime_atlas_relative_path(variant.id)
    _write_bytes_atomic(runtime_family_dir / atlas_path, deterministic_png_bytes(atlas))
    return (
        replace(
            runtime_variant,
            atlas_path=atlas_path,
            atlas_columns=atlas_columns,
            atlas_rows=atlas_rows,
        ),
        atlas_cells,
    )


def materialize_runtime_unit_from_unit(unit: TileLibraryUnit, *, runtime_families_dir: Path) -> TileLibraryUnit:
    runtime_family_dir = runtime_family_root(runtime_families_dir, unit.family_id)
    image_cache: dict[Path, Image.Image] = {}
    variant_images_by_id: dict[str, dict[str, Image.Image]] = {variant_id: {} for variant_id in unit.variants}
    variant_assets_by_tile_id: dict[str, dict[str, str]] = {}
    for tile in unit.tiles.values():
        variant_assets: dict[str, str] = {}
        for variant in unit.variants.values():
            image = _materialize_tile_image(tile, variant=variant, unit=unit, image_cache=image_cache)
            variant_images_by_id[variant.id][tile.id] = image
            variant_assets[variant.id] = _write_atomic_asset(image, runtime_family_dir=runtime_family_dir)
        variant_assets_by_tile_id[tile.id] = variant_assets

    runtime_variants: dict[str, TileFamilyVariant] = {}
    atlas_cells_by_variant_id: dict[str, dict[str, SheetCell]] = {}
    for variant_id, variant in unit.variants.items():
        runtime_variant, atlas_cells = _pack_variant_atlas(
            variant,
            unit=unit,
            runtime_tiles=unit.tiles,
            variant_images=variant_images_by_id[variant_id],
            runtime_family_dir=runtime_family_dir,
            image_cache=image_cache,
        )
        runtime_variants[variant_id] = runtime_variant
        atlas_cells_by_variant_id[variant_id] = atlas_cells

    runtime_tiles = {
        tile.id: _runtime_tile(
            tile,
            variant_assets=variant_assets_by_tile_id[tile.id],
            variant_atlas_cells={
                variant_id: atlas_cells_by_variant_id[variant_id][tile.id]
                for variant_id in unit.variants
            },
        )
        for tile in unit.tiles.values()
    }

    return replace(
        unit,
        root=Path("."),
        variants=runtime_variants,
    ).with_tiles(runtime_tiles)


def materialize_runtime_unit(family_dir: Path, *, runtime_families_dir: Path) -> TileLibraryUnit:
    family = load_source_tile_family(family_dir)
    return materialize_runtime_unit_from_unit(family.runtime_unit, runtime_families_dir=runtime_families_dir)


def produce_runtime_family_asset_from_unit(unit: TileLibraryUnit, runtime_families_dir: Path) -> Path:
    runtime_families_dir.mkdir(parents=True, exist_ok=True)
    runtime_unit = materialize_runtime_unit_from_unit(unit, runtime_families_dir=runtime_families_dir)
    output_path = runtime_families_dir / f"{runtime_unit.family_id}.json"
    output_path.write_text(tile_library_unit_to_json(runtime_unit), encoding="utf-8")
    return output_path


def produce_runtime_family_asset(family_dir: Path, runtime_families_dir: Path) -> Path:
    family = load_source_tile_family(family_dir)
    return produce_runtime_family_asset_from_unit(family.runtime_unit, runtime_families_dir)


def produce_source_pack_runtime_family_asset(
    pack_path: Path,
    *,
    tileset_id: str,
    tilesheet_id: str,
    resolved_catalogue_path: Path,
    legacy_semantics_path: Path,
    runtime_families_dir: Path,
) -> Path:
    catalogue = _load_resolved_catalogue(resolved_catalogue_path)
    legacy_semantics = _load_legacy_semantics(legacy_semantics_path)
    promoted = load_bridged_tile_library_unit(
        pack_path,
        tileset_id=tileset_id,
        tilesheet_id=tilesheet_id,
        semantic_inputs=BridgedSemanticInputs(
            resolved=catalogue.records,
            legacy_semantics=legacy_semantics,
            # Reproducibility invariant: use the variant set persisted with the
            # catalogue, not family.variants or a recomputed default.
            variant_ids=catalogue.content_identity.variant_ids,
        ),
    )
    seeded = _seed_required_non_content_fields_from_legacy(promoted)
    return produce_runtime_family_asset_from_unit(seeded, runtime_families_dir)
