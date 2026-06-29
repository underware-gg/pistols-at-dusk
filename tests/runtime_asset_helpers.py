from __future__ import annotations

from pathlib import Path

from runtime_asset_producer import materialize_runtime_unit_from_unit, produce_runtime_family_asset_from_unit
from tile_families import TileFamily
from tile_library import TileLibraryUnit


def load_family_runtime_unit(family_dir: Path) -> TileLibraryUnit:
    return TileFamily.load(family_dir).runtime_unit


def materialize_family_runtime_unit(family_dir: Path, *, runtime_families_dir: Path) -> TileLibraryUnit:
    return materialize_runtime_unit_from_unit(
        load_family_runtime_unit(family_dir),
        runtime_families_dir=runtime_families_dir,
    )


def produce_family_runtime_asset(family_dir: Path, runtime_families_dir: Path) -> Path:
    return produce_runtime_family_asset_from_unit(load_family_runtime_unit(family_dir), runtime_families_dir)
