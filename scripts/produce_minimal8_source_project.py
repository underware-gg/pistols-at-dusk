#!/usr/bin/env python3
"""Regenerate the Minimal 8 source-backed operator project."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from _manifest_utils import require_exactly_one, resolve_path
from produce_minimal8_runtime_assets import HARNESS_ROOT, minimal8_runtime_asset_spec


DEFAULT_RUNTIME_PROJECT = HARNESS_ROOT / "project.minimal8.json"
DEFAULT_SOURCE_PROJECT = HARNESS_ROOT / "project.minimal8.source.json"
DEFAULT_SOURCE_PACK = "./tile-packs/minimal8/pack.json"


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def source_pack_spec_for_minimal8_family(
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


def absolutise_project_paths(payload: dict[str, object], *, base_dir: Path) -> None:
    if "scene_rules_dir" in payload:
        payload["scene_rules_dir"] = str(resolve_path(base_dir, cast(str, payload["scene_rules_dir"])))
    if "scene_templates_dir" in payload:
        payload["scene_templates_dir"] = str(resolve_path(base_dir, cast(str, payload["scene_templates_dir"])))
    for raw_spec in cast(dict[str, object], payload.get("tilesets", {})).values():
        spec = cast(dict[str, object], raw_spec)
        if "sheet" in spec:
            spec["sheet"] = str(resolve_path(base_dir, cast(str, spec["sheet"])))


def write_minimal8_source_pack_project(
    runtime_project_path: Path,
    output_path: Path,
    *,
    source_pack: str | None = None,
    absolutise_paths: bool = True,
) -> Path:
    base_dir = runtime_project_path.parent
    pack_path = source_pack
    if pack_path is None:
        pack_path = str((base_dir / "tile-packs" / "minimal8" / "pack.json").resolve())
    project_payload = cast(dict[str, Any], json.loads(runtime_project_path.read_text(encoding="utf-8")))
    require_exactly_one(
        project_payload,
        "tile_family",
        "tile_families",
        context=f"Runtime project {runtime_project_path}",
    )
    if "tile_families" in project_payload:
        project_payload["tile_families"] = [
            source_pack_spec_for_minimal8_family(
                cast(str, cast(dict[str, Any], raw_spec)["family_id"]),
                variant_id=cast(str, cast(dict[str, Any], raw_spec)["variant_id"]),
                source_pack=pack_path,
            )
            for raw_spec in cast(list[object], project_payload["tile_families"])
        ]
    else:
        spec = cast(dict[str, Any], project_payload["tile_family"])
        project_payload["tile_family"] = source_pack_spec_for_minimal8_family(
            cast(str, spec["family_id"]),
            variant_id=cast(str, spec["variant_id"]),
            source_pack=pack_path,
        )
    if absolutise_paths:
        absolutise_project_paths(project_payload, base_dir=base_dir)
    write_json(output_path, project_payload)
    return output_path


def produce_minimal8_source_project(
    *,
    runtime_project_path: Path = DEFAULT_RUNTIME_PROJECT,
    output_path: Path = DEFAULT_SOURCE_PROJECT,
) -> Path:
    return write_minimal8_source_pack_project(
        runtime_project_path,
        output_path,
        source_pack=DEFAULT_SOURCE_PACK,
        absolutise_paths=False,
    )


def main() -> None:
    print(produce_minimal8_source_project())


if __name__ == "__main__":
    main()
