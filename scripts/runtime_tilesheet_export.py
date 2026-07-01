#!/usr/bin/env python3
"""Runtime-side clean tilesheet export.

Exports from committed runtime assets only: runtime-family JSON plus the
runtime-owned packed atlas sheets. This module intentionally does not import
source/ingest loaders.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image

from layout_core import LayoutProject, resize_nearest
from pixel_content import deterministic_png_bytes
from tile_library import SheetCell, TileFamilyVariant, TileGenesis, TileLibraryUnit, TileRecord


CANONICAL_REFERENCE_EXPORT_TYPE = "canonical-reference"
DEFAULT_CLEAN_TILESHEET_DIRNAME = "clean-tilesheets"


@dataclass(frozen=True)
class RuntimeTilesheetExportContext:
    tile_library: TileLibraryUnit
    asset_root: Path
    tileset_id: str
    variant_id: str


@dataclass(frozen=True)
class RuntimeTilesheetExportResult:
    export_type: str
    output_dir: Path
    tilesheet_path: Path
    metadata_path: Path
    manifest_path: Path
    scaled_tilesheet_path: Path | None = None


RuntimeTilesheetExporter = Callable[
    [RuntimeTilesheetExportContext, Path, Mapping[str, object]],
    RuntimeTilesheetExportResult,
]


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _tile_genesis_payload(genesis: TileGenesis) -> dict[str, object]:
    return {
        "kind": genesis.kind,
        "sheet_col": genesis.sheet_col,
        "sheet_row": genesis.sheet_row,
        "source_group": genesis.source_group,
        "cluster_ids": list(genesis.cluster_ids),
        "derivation": genesis.derivation,
        "parent_construction_ids": list(genesis.parent_construction_ids),
        "parent_tile_ids": list(genesis.parent_tile_ids),
        "authored_notes": genesis.authored_notes,
    }


def _sheet_cell_payload(cell: SheetCell) -> dict[str, int]:
    return {"col": cell.col, "row": cell.row}


def _tile_metadata_payload(tile: TileRecord, *, variant_id: str) -> dict[str, object]:
    try:
        atlas_cell = tile.variant_atlas_cells[variant_id]
    except KeyError as exc:
        raise ValueError(f"Tile {tile.id!r} has no atlas cell for variant {variant_id!r}") from exc
    return {
        "id": tile.id,
        "category": tile.category,
        "tags": list(tile.tags),
        "semantics": list(tile.semantics),
        "motifs": list(tile.motifs),
        "affordances": list(tile.affordances),
        "alt_uses": list(tile.alt_uses),
        "atlas_cell": _sheet_cell_payload(atlas_cell),
        "walkable": tile.walkable,
        "blocking": tile.blocking,
        "transparent": tile.transparent,
        "genesis": _tile_genesis_payload(tile.genesis),
    }


def _require_runtime_variant(context: RuntimeTilesheetExportContext) -> TileFamilyVariant:
    try:
        variant = context.tile_library.variant(context.variant_id)
    except KeyError as exc:
        raise ValueError(
            f"Runtime export tileset {context.tileset_id!r} references unknown variant {context.variant_id!r}"
        ) from exc
    if variant.atlas_path is None or variant.atlas_columns is None or variant.atlas_rows is None:
        raise ValueError(
            f"Runtime export tileset {context.tileset_id!r} variant {context.variant_id!r} "
            "is missing packed atlas metadata"
        )
    return variant


def _export_canonical_reference(
    context: RuntimeTilesheetExportContext,
    output_dir: Path,
    options: Mapping[str, object],
) -> RuntimeTilesheetExportResult:
    scale = options.get("scale", 1)
    if isinstance(scale, bool) or not isinstance(scale, int):
        raise ValueError(f"canonical-reference scale must be a positive integer, got {scale!r}")
    if scale < 1:
        raise ValueError(f"canonical-reference scale must be positive, got {scale}")

    variant = _require_runtime_variant(context)
    atlas_relative_path = variant.atlas_path
    atlas_columns = variant.atlas_columns
    atlas_rows = variant.atlas_rows
    assert atlas_relative_path is not None
    assert atlas_columns is not None
    assert atlas_rows is not None
    atlas_path = context.asset_root / atlas_relative_path
    if not atlas_path.is_file():
        raise ValueError(
            f"Runtime export tileset {context.tileset_id!r} variant {context.variant_id!r} "
            f"atlas missing at {atlas_path}"
        )
    expected_size = (
        atlas_columns * context.tile_library.tile_width,
        atlas_rows * context.tile_library.tile_height,
    )
    with Image.open(atlas_path) as atlas_header:
        atlas_size = atlas_header.size
    if atlas_size != expected_size:
        raise ValueError(
            f"Runtime export tileset {context.tileset_id!r} variant {context.variant_id!r} atlas {atlas_path} "
            f"has size {atlas_size}, expected {expected_size}"
        )

    family_dir = output_dir / context.tile_library.family_id / context.variant_id
    family_dir.mkdir(parents=True, exist_ok=True)
    tilesheet_path = family_dir / "tilesheet.png"
    metadata_path = family_dir / "metadata.json"
    manifest_path = family_dir / "manifest.json"
    scaled_tilesheet_path = None

    # The committed atlas is already the clean runtime-owned sheet; the 1x
    # export keeps the exact PNG bytes rather than re-encoding.
    shutil.copyfile(atlas_path, tilesheet_path)
    if scale != 1:
        scaled_tilesheet_path = family_dir / f"tilesheet@{scale}x.png"
        atlas_image = Image.open(atlas_path).convert("RGBA")
        scaled = resize_nearest(
            atlas_image,
            (atlas_image.width * scale, atlas_image.height * scale),
        )
        scaled_tilesheet_path.write_bytes(deterministic_png_bytes(scaled))

    tiles = [
        _tile_metadata_payload(tile, variant_id=context.variant_id)
        for tile in sorted(context.tile_library.tiles.values(), key=lambda record: record.id)
    ]
    metadata_path.write_bytes(
        _json_bytes(
            {
                "schema_version": 1,
                "export_type": CANONICAL_REFERENCE_EXPORT_TYPE,
                "family_id": context.tile_library.family_id,
                "variant_id": context.variant_id,
                "tiles": tiles,
            }
        )
    )
    manifest_payload: dict[str, object] = {
        "schema_version": 1,
        "export_type": CANONICAL_REFERENCE_EXPORT_TYPE,
        "family_id": context.tile_library.family_id,
        "tileset_id": context.tileset_id,
        "variant_id": context.variant_id,
        "tile_count": len(tiles),
        "tilesheet": {
            "path": tilesheet_path.name,
            "columns": atlas_columns,
            "rows": atlas_rows,
            "width": atlas_size[0],
            "height": atlas_size[1],
            "tile_width": context.tile_library.tile_width,
            "tile_height": context.tile_library.tile_height,
        },
        "metadata_path": metadata_path.name,
    }
    if scaled_tilesheet_path is not None:
        manifest_payload["scaled_tilesheet"] = {
            "path": scaled_tilesheet_path.name,
            "scale": scale,
        }
    manifest_path.write_bytes(_json_bytes(manifest_payload))
    return RuntimeTilesheetExportResult(
        export_type=CANONICAL_REFERENCE_EXPORT_TYPE,
        output_dir=family_dir,
        tilesheet_path=tilesheet_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        scaled_tilesheet_path=scaled_tilesheet_path,
    )


EXPORT_TYPES: Mapping[str, RuntimeTilesheetExporter] = {
    CANONICAL_REFERENCE_EXPORT_TYPE: _export_canonical_reference,
}


def export_runtime_tilesheet(
    context: RuntimeTilesheetExportContext,
    output_dir: Path,
    *,
    export_type: str = CANONICAL_REFERENCE_EXPORT_TYPE,
    scale: int = 1,
) -> RuntimeTilesheetExportResult:
    try:
        exporter = EXPORT_TYPES[export_type]
    except KeyError as exc:
        available = ", ".join(sorted(EXPORT_TYPES))
        raise ValueError(f"Unknown runtime tilesheet export type {export_type!r}; available: {available}") from exc
    return exporter(context, output_dir, {"scale": scale})


def runtime_tilesheet_context_from_project(
    project_path: Path,
    *,
    tileset_id: str,
    variant_id: str | None = None,
) -> RuntimeTilesheetExportContext:
    project = LayoutProject(project_path)
    tile_library = project.tile_library_unit_for_tileset(tileset_id)
    if tile_library is None:
        raise ValueError(f"Tileset {tileset_id!r} is not a runtime family tileset")
    asset_root = project.runtime_asset_root_for_tileset(tileset_id)
    if asset_root is None:
        raise ValueError(f"Tileset {tileset_id!r} is source-backed; clean tilesheet export requires runtime_asset")
    selected_variant_id = variant_id or project.variant_id_for_tileset(tileset_id)
    if selected_variant_id is None:
        raise ValueError(f"Tileset {tileset_id!r} does not have a selected runtime variant")
    if selected_variant_id not in tile_library.variants:
        raise ValueError(
            f"Variant {selected_variant_id!r} is not defined for runtime family {tile_library.family_id!r}"
        )
    return RuntimeTilesheetExportContext(
        tile_library=tile_library,
        asset_root=asset_root,
        tileset_id=tile_library.runtime_tileset_id(selected_variant_id),
        variant_id=selected_variant_id,
    )


def export_project_runtime_tilesheet(
    project_path: Path,
    *,
    tileset_id: str,
    variant_id: str | None = None,
    output_dir: Path,
    export_type: str = CANONICAL_REFERENCE_EXPORT_TYPE,
    scale: int = 1,
) -> RuntimeTilesheetExportResult:
    context = runtime_tilesheet_context_from_project(project_path, tileset_id=tileset_id, variant_id=variant_id)
    return export_runtime_tilesheet(context, output_dir, export_type=export_type, scale=scale)
