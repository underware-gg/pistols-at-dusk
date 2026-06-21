"""Ingest/operator project-family loader wiring.

The runtime `layout_core` module loads produced runtime assets by itself. Today's
source-pack and legacy family forms still need ingest-side files, so operator
entrypoints import this module to register that transitional loader explicitly.
"""

from __future__ import annotations

from pathlib import Path

from layout_core import (
    ProjectTileFamilyConfig,
    TileFamilySelection,
    register_source_tile_family_loader,
    resolve_path,
    selected_variant_id_for_family,
)
from source_manifest_bridge import load_bridged_tile_family
from tile_family_ingest import load_source_tile_family


def load_source_tile_family_selection(
    *,
    base_dir: Path,
    spec: ProjectTileFamilyConfig,
) -> TileFamilySelection:
    if "path" in spec:
        raw_path = spec.get("path")
        if raw_path is None:
            raise ValueError("tile_family legacy path config must define path")
        selection_path = resolve_path(base_dir, raw_path)
        family = load_source_tile_family(selection_path)
    else:
        if "tileset_id" not in spec or "tilesheet_id" not in spec:
            raise ValueError("tile_family source_pack config must define tileset_id and tilesheet_id")
        raw_pack_path = spec.get("source_pack")
        if raw_pack_path is None:
            raise ValueError("tile_family source_pack config must define source_pack")
        selection_path = resolve_path(base_dir, raw_pack_path)
        family = load_bridged_tile_family(
            selection_path,
            tileset_id=spec["tileset_id"],
            tilesheet_id=spec["tilesheet_id"],
        )

    selected_variant_id = selected_variant_id_for_family(
        spec=spec,
        family_id=family.family_id,
        default_variant_id=family.default_variant_id,
        variant_ids=family.variants,
    )
    return TileFamilySelection(
        path=selection_path,
        runtime_unit=family.runtime_unit,
        selected_variant_id=selected_variant_id,
        source_family=family,
    )


def install_source_tile_family_loader() -> None:
    register_source_tile_family_loader(load_source_tile_family_selection)
