#!/usr/bin/env python3
"""Regenerate the committed Minimal 8 runtime-family assets."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime_asset_producer import produce_source_pack_runtime_family_asset


ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "prototypes/minimal8-harness"


@dataclass(frozen=True)
class Minimal8RuntimeAssetSpec:
    family_id: str
    tileset_id: str
    tilesheet_id: str
    catalogue_dir: str


MINIMAL8_RUNTIME_ASSETS: tuple[Minimal8RuntimeAssetSpec, ...] = (
    Minimal8RuntimeAssetSpec(
        family_id="minimal8",
        tileset_id="minimal8",
        tilesheet_id="main",
        catalogue_dir="minimal8-clean-fields",
    ),
    Minimal8RuntimeAssetSpec(
        family_id="minimal8.characters",
        tileset_id="characters",
        tilesheet_id="characters",
        catalogue_dir="minimal8-characters-clean-fields",
    ),
)


def minimal8_runtime_asset_spec(family_id: str) -> Minimal8RuntimeAssetSpec:
    for spec in MINIMAL8_RUNTIME_ASSETS:
        if spec.family_id == family_id:
            return spec
    raise ValueError(f"Unsupported Minimal 8 family id: {family_id!r}")


def minimal8_source_pack_spec(
    family_id: str,
    *,
    variant_id: str,
    source_pack: str,
) -> dict[str, object]:
    spec = minimal8_runtime_asset_spec(family_id)
    return {
        "source_pack": source_pack,
        "tileset_id": spec.tileset_id,
        "tilesheet_id": spec.tilesheet_id,
        "family_id": family_id,
        "variant_id": variant_id,
    }


def produce_minimal8_runtime_assets(
    *,
    harness_root: Path = HARNESS_ROOT,
    runtime_families_dir: Path | None = None,
) -> tuple[Path, ...]:
    pack_path = harness_root / "tile-packs" / "minimal8" / "pack.json"
    output_root = runtime_families_dir if runtime_families_dir is not None else harness_root / "runtime-families"
    output_paths: list[Path] = []
    for spec in MINIMAL8_RUNTIME_ASSETS:
        catalogue_root = harness_root / "semantic-catalogue" / spec.catalogue_dir
        output_paths.append(
            produce_source_pack_runtime_family_asset(
                pack_path,
                tileset_id=spec.tileset_id,
                tilesheet_id=spec.tilesheet_id,
                resolved_catalogue_path=catalogue_root / "resolved-catalogue.json",
                legacy_semantics_path=catalogue_root / "legacy-tile-semantics.json",
                runtime_families_dir=output_root,
            )
        )
    return tuple(output_paths)


def main() -> None:
    for path in produce_minimal8_runtime_assets():
        print(path)


if __name__ == "__main__":
    main()
