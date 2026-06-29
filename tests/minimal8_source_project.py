from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from produce_minimal8_runtime_assets import minimal8_source_pack_spec


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def source_pack_spec_for_minimal8_family(
    family_id: str,
    *,
    variant_id: str,
    source_pack: str,
) -> dict[str, object]:
    return minimal8_source_pack_spec(family_id, variant_id=variant_id, source_pack=source_pack)


def resolve_test_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path).resolve()


def absolutise_project_paths(payload: dict[str, object], *, base_dir: Path) -> None:
    if "scene_rules_dir" in payload:
        payload["scene_rules_dir"] = str(resolve_test_path(base_dir, cast(str, payload["scene_rules_dir"])))
    if "scene_templates_dir" in payload:
        payload["scene_templates_dir"] = str(resolve_test_path(base_dir, cast(str, payload["scene_templates_dir"])))
    for raw_spec in cast(dict[str, object], payload.get("tilesets", {})).values():
        spec = cast(dict[str, object], raw_spec)
        if "sheet" in spec:
            spec["sheet"] = str(resolve_test_path(base_dir, cast(str, spec["sheet"])))


def write_minimal8_source_pack_project(runtime_project_path: Path, output_path: Path) -> Path:
    base_dir = runtime_project_path.parent
    pack_path = str((base_dir / "tile-packs" / "minimal8" / "pack.json").resolve())
    project_payload = cast(dict[str, Any], json.loads(runtime_project_path.read_text(encoding="utf-8")))
    if "tile_families" in project_payload:
        project_payload["tile_families"] = [
            source_pack_spec_for_minimal8_family(
                cast(str, cast(dict[str, Any], raw_spec)["family_id"]),
                variant_id=cast(str, cast(dict[str, Any], raw_spec)["variant_id"]),
                source_pack=pack_path,
            )
            for raw_spec in cast(list[object], project_payload["tile_families"])
        ]
    elif "tile_family" in project_payload:
        spec = cast(dict[str, Any], project_payload["tile_family"])
        project_payload["tile_family"] = source_pack_spec_for_minimal8_family(
            cast(str, spec["family_id"]),
            variant_id=cast(str, spec["variant_id"]),
            source_pack=pack_path,
        )
    absolutise_project_paths(project_payload, base_dir=base_dir)
    write_json(output_path, project_payload)
    return output_path
