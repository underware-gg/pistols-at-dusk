#!/usr/bin/env python3
"""Ingest-side runtime asset producer.

Reads today's source/compat family, materialises runtime-owned atomic tile
pixels, and writes the runtime-family JSON plus content-addressed PNG assets.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image

from tile_family_ingest import load_source_tile_family
from tile_family_runtime import resolve_canonical_tile_image
from tile_library import (
    TileFamilyVariant,
    TileLibraryUnit,
    TileRecord,
)
from tile_library_codec import tile_library_unit_to_json
from runtime_asset_paths import atomic_asset_address_from_digest, atomic_asset_relative_path, runtime_family_root


ATOMIC_ASSET_FORMAT_HEADER = b"rgba8\n"


def canonical_rgba_bytes(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    return ATOMIC_ASSET_FORMAT_HEADER + f"{rgba.width}x{rgba.height}\n".encode("ascii") + rgba.tobytes()


def atomic_asset_address(image: Image.Image) -> str:
    digest = hashlib.sha256(canonical_rgba_bytes(image)).hexdigest()
    return atomic_asset_address_from_digest(digest)


def deterministic_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _write_atomic_asset(image: Image.Image, *, runtime_family_dir: Path) -> str:
    address = atomic_asset_address(image)
    path = runtime_family_dir / atomic_asset_relative_path(address)
    if path.exists():
        # Address is over canonical RGBA, not PNG bytes. Existing assets at the
        # same digest are trusted; a future audit can decode and verify if needed.
        return address
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
            temp.write(deterministic_png_bytes(image))
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
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


def _runtime_tile(tile: TileRecord, *, variant_assets: Mapping[str, str]) -> TileRecord:
    return replace(
        tile,
        image_override=None,
        variant_assets=variant_assets,
    )


def materialize_runtime_unit(family_dir: Path, *, runtime_families_dir: Path) -> TileLibraryUnit:
    family = load_source_tile_family(family_dir)
    unit = family.runtime_unit
    runtime_family_dir = runtime_family_root(runtime_families_dir, unit.family_id)
    image_cache: dict[Path, Image.Image] = {}
    runtime_tiles: dict[str, TileRecord] = {}
    for tile in unit.tiles.values():
        variant_assets: dict[str, str] = {}
        for variant in unit.variants.values():
            image = _materialize_tile_image(tile, variant=variant, unit=unit, image_cache=image_cache)
            variant_assets[variant.id] = _write_atomic_asset(image, runtime_family_dir=runtime_family_dir)
        runtime_tiles[tile.id] = _runtime_tile(tile, variant_assets=variant_assets)

    return replace(
        unit,
        root=Path("."),
        variants={variant_id: replace(variant, sheet_path=None) for variant_id, variant in unit.variants.items()},
    ).with_tiles(runtime_tiles)


def produce_runtime_family_asset(family_dir: Path, runtime_families_dir: Path) -> Path:
    runtime_families_dir.mkdir(parents=True, exist_ok=True)
    unit = materialize_runtime_unit(family_dir, runtime_families_dir=runtime_families_dir)
    output_path = runtime_families_dir / f"{unit.family_id}.json"
    output_path.write_text(tile_library_unit_to_json(unit), encoding="utf-8")
    return output_path
