from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import harness
import tile_families
import source_ingest_ops
import layout_core
from tile_library import PlaceableRef


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Minimal8RuntimeFixture:
    root: Path
    project_path: Path
    family_tileset_id: str
    utility_tileset_id: str
    selected_variant_sheet_path: Path
    deleted_manifest_paths: tuple[Path, ...]


@dataclass(frozen=True)
class Minimal8GoldenState:
    promoted_metadata: object
    construction: object
    resolved_tile: layout_core.ResolvedTile
    tileset: layout_core.GridTileset
    preview_size: tuple[int, int]
    preview_bytes: bytes
    runtime: harness.SceneExpansionResult


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _variant_with_id(variants: list[object], variant_id: str) -> dict[str, object]:
    return next(
        cast(dict[str, object], variant)
        for variant in variants
        if cast(str, cast(dict[str, object], variant)["variant_id"]) == variant_id
    )


def _narrow_manifest_to_selected_variant(
    manifest_path: Path,
    *,
    list_key: str,
    selected_variant_id: str,
    copied_sheet_path: Path,
) -> None:
    payload = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    variants = cast(list[object], payload[list_key])
    selected_variant = _variant_with_id(variants, selected_variant_id)
    selected_variant["sheet"] = os.path.relpath(copied_sheet_path, manifest_path.parent)
    payload[list_key] = [selected_variant]
    _write_json(manifest_path, payload)


def _reject_if_protected_path(candidate: Path, *, protected_paths: frozenset[Path]) -> None:
    resolved = candidate.resolve()
    if resolved in protected_paths:
        raise AssertionError(f"runtime should not reopen deleted manifest {resolved}")


def _capture_minimal8_golden_state(
    project: layout_core.LayoutProject,
    *,
    family_tileset_id: str,
    utility_tileset_id: str,
    ref_token: str,
    construction_id: str,
    tavern_scene: harness.SceneTemplate,
) -> Minimal8GoldenState:
    tile_library = project.tile_library_unit_for_tileset(family_tileset_id)
    assert tile_library is not None
    assert project.tile_library_registry is not None
    construction = project.tile_library_registry.lookup_construction(construction_id)
    assert construction is not None
    resolved_tile = project.family_tile_for_ref(ref_token, tileset_id=utility_tileset_id)
    assert resolved_tile is not None
    tileset = project.get_tileset(family_tileset_id)
    preview = layout_core.render_tile_preview_image(project, resolved_tile)
    runtime = harness.expand_scene_runtime(
        project,
        tavern_scene,
        default_tileset=family_tileset_id,
    )
    return Minimal8GoldenState(
        promoted_metadata=tile_library.promoted_metadata,
        construction=construction,
        resolved_tile=resolved_tile,
        tileset=tileset,
        preview_size=preview.size,
        preview_bytes=preview.tobytes(),
        runtime=runtime,
    )


def _copy_minimal8_runtime_fixture(root: Path) -> Minimal8RuntimeFixture:
    source_root = ROOT / "prototypes" / "minimal8-harness"
    fixture_root = root / "minimal8-harness"
    selected_variant_id = "1bit_colored_bg"
    family_tileset_id = f"minimal8@{selected_variant_id}"
    utility_tileset_id = "utility_land"

    _copy_file(source_root / "project.minimal8.json", fixture_root / "project.minimal8.json")
    _copy_file(
        source_root / "assets" / "utility_land_undercoat.png",
        fixture_root / "assets" / "utility_land_undercoat.png",
    )
    shutil.copytree(source_root / "scene-templates", fixture_root / "scene-templates")
    shutil.copytree(source_root / "scene-rules", fixture_root / "scene-rules")
    shutil.copytree(source_root / "tile-families" / "minimal8" / "derived", fixture_root / "tile-families" / "minimal8" / "derived")

    pack_path = fixture_root / "tile-packs" / "minimal8" / "pack.json"
    tileset_manifest_path = fixture_root / "tile-packs" / "minimal8" / "tilesets" / "minimal8.json"
    tilesheet_manifest_path = fixture_root / "tile-packs" / "minimal8" / "tilesheets" / "main.json"
    family_manifest_path = fixture_root / "tile-families" / "minimal8" / "family.json"
    tiles_manifest_path = fixture_root / "tile-families" / "minimal8" / "tiles.json"
    aliases_manifest_path = fixture_root / "tile-families" / "minimal8" / "aliases.json"
    clusters_manifest_path = fixture_root / "tile-families" / "minimal8" / "clusters.json"
    constructions_manifest_path = fixture_root / "tile-families" / "minimal8" / "constructions.json"
    composite_tiles_manifest_path = fixture_root / "tile-families" / "minimal8" / "composite_tiles.json"
    ingestion_manifest_path = fixture_root / "tile-families" / "minimal8" / "ingestion.json"

    for src_path, dest_path in (
        (source_root / "tile-packs" / "minimal8" / "pack.json", pack_path),
        (source_root / "tile-packs" / "minimal8" / "tilesets" / "minimal8.json", tileset_manifest_path),
        (source_root / "tile-packs" / "minimal8" / "tilesheets" / "main.json", tilesheet_manifest_path),
        (source_root / "tile-families" / "minimal8" / "family.json", family_manifest_path),
        (source_root / "tile-families" / "minimal8" / "tiles.json", tiles_manifest_path),
        (source_root / "tile-families" / "minimal8" / "aliases.json", aliases_manifest_path),
        (source_root / "tile-families" / "minimal8" / "clusters.json", clusters_manifest_path),
        (source_root / "tile-families" / "minimal8" / "constructions.json", constructions_manifest_path),
        (source_root / "tile-families" / "minimal8" / "composite_tiles.json", composite_tiles_manifest_path),
        (source_root / "tile-families" / "minimal8" / "ingestion.json", ingestion_manifest_path),
    ):
        _copy_file(src_path, dest_path)

    project_payload = cast(dict[str, object], json.loads((fixture_root / "project.minimal8.json").read_text(encoding="utf-8")))
    tile_family_specs = cast(list[object], project_payload["tile_families"])
    project_payload["tile_families"] = [
        spec
        for spec in tile_family_specs
        if cast(str, cast(dict[str, object], spec)["family_id"]) == "minimal8"
    ]
    _write_json(fixture_root / "project.minimal8.json", project_payload)

    pack_payload = cast(dict[str, object], json.loads(pack_path.read_text(encoding="utf-8")))
    pack_tilesets = cast(list[object], pack_payload["tilesets"])
    pack_payload["tilesets"] = [
        entry
        for entry in pack_tilesets
        if cast(str, cast(dict[str, object], entry)["tileset_id"]) == "minimal8"
    ]
    _write_json(pack_path, pack_payload)

    tilesheet_payload = cast(dict[str, object], json.loads(tilesheet_manifest_path.read_text(encoding="utf-8")))
    selected_tilesheet_variant = _variant_with_id(
        cast(list[object], tilesheet_payload["render_variants"]),
        selected_variant_id,
    )

    source_variant_sheet_path = (
        (source_root / "tile-packs" / "minimal8" / "tilesheets").resolve()
        / cast(str, selected_tilesheet_variant["sheet"])
    ).resolve()
    copied_variant_sheet_path = fixture_root / "tile-packs" / "minimal8" / "art" / source_variant_sheet_path.name
    _copy_file(source_variant_sheet_path, copied_variant_sheet_path)

    _narrow_manifest_to_selected_variant(
        tilesheet_manifest_path,
        list_key="render_variants",
        selected_variant_id=selected_variant_id,
        copied_sheet_path=copied_variant_sheet_path,
    )
    _narrow_manifest_to_selected_variant(
        family_manifest_path,
        list_key="variants",
        selected_variant_id=selected_variant_id,
        copied_sheet_path=copied_variant_sheet_path,
    )

    return Minimal8RuntimeFixture(
        root=fixture_root,
        project_path=fixture_root / "project.minimal8.json",
        family_tileset_id=family_tileset_id,
        utility_tileset_id=utility_tileset_id,
        selected_variant_sheet_path=copied_variant_sheet_path.resolve(),
        deleted_manifest_paths=(
            pack_path,
            tileset_manifest_path,
            tilesheet_manifest_path,
            family_manifest_path,
            tiles_manifest_path,
            aliases_manifest_path,
            clusters_manifest_path,
            constructions_manifest_path,
            ingestion_manifest_path,
        ),
    )


def _make_override_family_and_project(root: Path) -> tuple[Path, Path]:
    family_dir = root / "family"
    family_dir.mkdir()
    Image.new("RGBA", (8, 16), (0, 0, 0, 255)).save(family_dir / "sheet.png")
    derived_dir = family_dir / "derived"
    derived_dir.mkdir()
    Image.new("RGBA", (8, 8), (255, 0, 255, 255)).save(derived_dir / "override.png")

    _write_json(
        family_dir / "family.json",
        {
            "family_id": "testfam",
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": [{"variant_id": "base", "sheet": "sheet.png", "transparent": "none"}],
            "ingestion_spec": "ingestion.json",
        },
    )
    _write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 1, "height": 2},
            "regions": [{"id": "sheet.region", "bounds": {"x": 0, "y": 0, "width": 1, "height": 2}}],
            "clusters": [{"id": "sheet.region.cluster_01", "source_region_id": "sheet.region", "bounds": {"x": 0, "y": 0, "width": 1, "height": 2}}],
            "collections": [],
        },
    )
    _write_json(
        family_dir / "clusters.json",
        [{"id": "cluster.valid", "scope": "family", "members": ["testfam:derived.override"]}],
    )
    _write_json(
        family_dir / "tiles.json",
        [
            {
                "id": "testfam:derived.override",
                "layer": "ui",
                "category": "ui",
                "transparent": False,
                "image_override": "derived/override.png",
                "cluster_ids": ["cluster.valid"],
                "source_group": "test.derived",
                "meaning": "Derived override tile.",
                "meaning_confidence": "confirmed",
            }
        ],
    )
    _write_json(family_dir / "aliases.json", {"sample.override": "testfam:derived.override"})

    project_path = root / "project.json"
    _write_json(
        project_path,
        {
            "tile_family": {"path": str(family_dir), "variant_id": "base"},
            "scene_templates_dir": str(ROOT / "prototypes/minimal8-harness/scene-templates"),
            "grid": {"tile_width": 8, "tile_height": 8},
            "tilesets": {},
            "aliases": {},
            "patterns": {},
        },
    )
    return family_dir, project_path


def _make_project_with_patterns(
    root: Path,
    *,
    patterns: dict[str, object] | None = None,
) -> Path:
    sheet_path = root / "sheet.png"
    Image.new("RGBA", (16, 8), (1, 2, 3, 255)).save(sheet_path)

    project_path = root / "project.json"
    payload: dict[str, object] = {
        "scene_templates_dir": str(ROOT / "prototypes/minimal8-harness/scene-templates"),
        "grid": {"tile_width": 8, "tile_height": 8},
        "tilesets": {
            "sheet": {
                "sheet": str(sheet_path),
                "transparent": "none",
                "regions": {"all": {"x": 0, "y": 0, "width": 2, "height": 1}},
            }
        },
    }
    if patterns is not None:
        payload["patterns"] = patterns
    _write_json(project_path, payload)
    return project_path


def _make_minimal_family_dir(
    root: Path,
    *,
    directory_name: str,
    family_id: str,
    tile_width: int = 8,
    tile_height: int = 8,
    render_step_width: int | None = None,
    render_step_height: int | None = None,
) -> Path:
    family_dir = root / directory_name
    family_dir.mkdir()
    Image.new("RGBA", (tile_width, tile_height), (0, 0, 0, 255)).save(family_dir / "sheet.png")
    tile_id = f"{family_id}:all:0,0"
    family_payload: dict[str, object] = {
        "family_id": family_id,
        "grid": {"tile_width": tile_width, "tile_height": tile_height},
        "default_variant_id": "base",
        "variants": [{"variant_id": "base", "sheet": "sheet.png", "transparent": "none"}],
        "ingestion_spec": "ingestion.json",
    }
    render_defaults: dict[str, int] = {}
    if render_step_width is not None:
        render_defaults["render_step_width"] = render_step_width
    if render_step_height is not None:
        render_defaults["render_step_height"] = render_step_height
    if render_defaults:
        family_payload["render_defaults"] = render_defaults
    _write_json(
        family_dir / "family.json",
        family_payload,
    )
    _write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
            "regions": [{"id": "sheet.region", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}}],
            "clusters": [{"id": "sheet.region.cluster_01", "source_region_id": "sheet.region", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}}],
            "collections": [],
        },
    )
    _write_json(
        family_dir / "clusters.json",
        [{"id": "cluster.valid", "scope": "family", "members": [tile_id]}],
    )
    _write_json(
        family_dir / "tiles.json",
        [
            {
                "id": tile_id,
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "map",
                "category": "tile",
                "transparent": False,
                "cluster_ids": ["cluster.valid"],
                "source_group": "test.group",
                "meaning": "Test tile.",
                "meaning_confidence": "confirmed",
            }
        ],
    )
    _write_json(family_dir / "aliases.json", {f"{family_id}.alias": tile_id})
    return family_dir


def _make_minimal_source_pack(
    root: Path,
    *,
    directory_name: str,
    pack_id: str,
    tileset_id: str,
    tilesheet_id: str,
    family_id: str,
) -> Path:
    compatibility_dir = _make_minimal_family_dir(
        root,
        directory_name=f"{directory_name}_compatibility",
        family_id=family_id,
        render_step_width=8,
        render_step_height=8,
    )
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(compatibility_dir / "sheet.alt.png")
    family_payload = json.loads((compatibility_dir / "family.json").read_text(encoding="utf-8"))
    family_payload["siblings_share_semantics"] = True
    cast(list[object], family_payload["variants"]).append(
        {"variant_id": "alt", "sheet": "sheet.alt.png", "transparent": "none"}
    )
    _write_json(compatibility_dir / "family.json", family_payload)

    pack_root = root / directory_name
    tilesets_dir = pack_root / "tilesets"
    tilesheets_dir = pack_root / "tilesheets"
    tilesets_dir.mkdir(parents=True)
    tilesheets_dir.mkdir()

    compatibility_root = f"../../{compatibility_dir.name}"
    _write_json(
        pack_root / "pack.json",
        {
            "pack_id": pack_id,
            "grid": {"tile_width": 8, "tile_height": 8},
            "tilesets": [{"tileset_id": tileset_id, "manifest": "tilesets/base.json"}],
        },
    )
    _write_json(
        tilesets_dir / "base.json",
        {
            "tileset_id": tileset_id,
            "logical_tilesheets": [{"tilesheet_id": tilesheet_id, "manifest": "../tilesheets/main.json"}],
        },
    )
    _write_json(
        tilesheets_dir / "main.json",
        {
            "tilesheet_id": tilesheet_id,
            "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
            "default_variant_id": "base",
            "source_layout": f"{compatibility_root}/ingestion.json",
            "compatibility_family": {
                "root": compatibility_root,
                "family_id": family_id,
                "tiles": "tiles.json",
                "aliases": "aliases.json",
                "clusters": "clusters.json",
                "render_step_width": 8,
                "render_step_height": 8,
                "siblings_share_semantics": True,
            },
            "render_variants": [
                {
                    "variant_id": "base",
                    "sheet": f"{compatibility_root}/sheet.png",
                    "coverage": {"mode": "full"},
                    "transparent": "none",
                },
                {
                    "variant_id": "alt",
                    "sheet": f"{compatibility_root}/sheet.alt.png",
                    "coverage": {"mode": "full"},
                    "transparent": "none",
                },
            ],
        },
    )
    return pack_root / "pack.json"


def _make_multi_family_project(
    root: Path,
    *,
    default_tileset: str | None,
) -> Path:
    family_a = _make_minimal_family_dir(root, directory_name="family_a", family_id="family.a")
    family_b = _make_minimal_family_dir(root, directory_name="family_b", family_id="family.b")
    project_path = root / "project.json"
    payload: dict[str, object] = {
        "tile_families": [
            {"path": str(family_a), "variant_id": "base"},
            {"path": str(family_b), "variant_id": "base"},
        ],
        "grid": {"tile_width": 8, "tile_height": 8},
        "tilesets": {},
        "aliases": {},
        "patterns": {},
    }
    if default_tileset is not None:
        payload["default_tileset"] = default_tileset
    _write_json(project_path, payload)
    return project_path


def _make_composite_tileset_project(root: Path) -> Path:
    sheet_path = root / "sheet.png"
    sheet = Image.new("RGBA", (32, 8), (0, 0, 0, 0))
    for y in range(8):
        for x in range(8):
            sheet.putpixel((x, y), (10, 20, 200, 255))
    for y in range(8):
        for x in range(16, 24):
            sheet.putpixel((x, y), (220, 40, 60, 255))
    sheet.putpixel((12, 4), (250, 240, 40, 255))
    for x in range(24, 32):
        sheet.putpixel((x, 0), (40, 220, 120, 255))
        sheet.putpixel((x, 7), (40, 220, 120, 255))
    for y in range(8):
        sheet.putpixel((24, y), (40, 220, 120, 255))
        sheet.putpixel((31, y), (40, 220, 120, 255))
    sheet.save(sheet_path)

    project_path = root / "project.json"
    _write_json(
        project_path,
        {
            "grid": {"tile_width": 8, "tile_height": 8},
            "tilesets": {
                "sample": {
                    "sheet": str(sheet_path),
                    "transparent": "none",
                    "catalog_scope": "all",
                    "regions": {"all": {"x": 0, "y": 0, "width": 4, "height": 1}},
                }
            },
            "aliases": {
                "sample.overlay.with_underpaint": {"ref": "1,0", "underpaint": "0,0"},
                "sample.overlay.flipped": {"ref": "1,0", "underpaint": "0,0", "flip_x": True},
                "sample.overlay.with_offset": {
                    "ref": "1,0",
                    "underpaint": "0,0",
                    "offset_left": 1,
                    "offset_bottom": 1,
                },
                "sample.overlay.offset_flipped": {
                    "ref": "1,0",
                    "underpaint": "0,0",
                    "offset_left": 1,
                    "offset_bottom": 1,
                    "flip_x": True,
                },
                "sample.overlay.overflow_right": {"ref": "1,0", "offset_left": 4},
                "sample.overlay.fill_cell": {"ref": "1,0", "occlusion": "fill_cell"},
                "sample.overlay.fill_holes": {"ref": "3,0", "occlusion": "fill_holes"},
            },
            "patterns": {},
        },
    )
    return project_path


class LayoutProjectLazyTilesetTests(unittest.TestCase):
    def test_family_variants_are_instantiated_lazily(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"

        calls: list[str] = []
        original_init = layout_core.GridTileset.__init__

        def wrapped_init(
            self: layout_core.GridTileset,
            tileset_id: str,
            *,
            sheet_path: Path,
            tile_width: int,
            tile_height: int,
            margin: int = 0,
            spacing: int = 0,
            transparent_mode: str = "top_left",
            catalog_scope: str = "regions",
            regions: dict[str, layout_core.GridRegionBounds] | None = None,
        ) -> None:
            calls.append(tileset_id)
            original_init(
                self,
                tileset_id,
                sheet_path=sheet_path,
                tile_width=tile_width,
                tile_height=tile_height,
                margin=margin,
                spacing=spacing,
                transparent_mode=transparent_mode,
                catalog_scope=catalog_scope,
                regions=regions,
            )

        with patch.object(layout_core.GridTileset, "__init__", new=wrapped_init):
            project = layout_core.LayoutProject(project_path)
            self.assertEqual(calls, ["utility_land"])

            default_tileset_id = project.default_tileset_id()
            self.assertTrue(project.has_tileset(default_tileset_id))
            self.assertNotIn(default_tileset_id, project.tilesets)

            first_default = project.get_tileset(default_tileset_id)
            self.assertIn(default_tileset_id, project.tilesets)
            self.assertEqual(calls[-1], default_tileset_id)

            second_default = project.get_tileset(default_tileset_id)
            self.assertIs(first_default, second_default)
            self.assertEqual(calls.count(default_tileset_id), 1)

            other_variant_id = next(
                tileset_id
                for tileset_id in project.family_variant_tileset_ids()
                if tileset_id != default_tileset_id
            )
            self.assertNotIn(other_variant_id, project.tilesets)
            project.get_tileset(other_variant_id)
            self.assertEqual(calls.count(other_variant_id), 1)

    def test_get_tileset_lists_available_ids_for_unknown_lookup(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        with self.assertRaisesRegex(KeyError, "Available tilesets"):
            project.get_tileset("missing.tileset")

    def test_project_supports_multiple_tile_families_with_explicit_default_tileset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_multi_family_project(
                Path(temp_dir),
                default_tileset="family.b@base",
            )

            project = layout_core.LayoutProject(project_path)

            self.assertEqual(project.default_tileset_id(), "family.b@base")
            self.assertEqual(project.family_variant_tileset_ids(), ["family.a@base", "family.b@base"])
            self.assertIsNotNone(project.tile_library_registry)
            assert project.tile_library_registry is not None
            self.assertEqual(project.tile_library_registry.unit_ids, ("family.a", "family.b"))
            self.assertIsNotNone(project.tile_library_unit_for_tileset("family.a@base"))
            self.assertIsNotNone(project.tile_library_unit_for_tileset("family.b@base"))
            self.assertIsNotNone(project.source_family_for_tileset("family.a@base"))
            self.assertIsNotNone(project.source_family_for_tileset("family.b@base"))
            resolved_alias = project.resolve_tile("family.a.alias", default_tileset="family.b@base")
            self.assertEqual(resolved_alias.tileset_id, "family.a@base")
            self.assertEqual(resolved_alias.family_tile_id, "family.a:all:0,0")
            resolved_physical = project.resolve_tile("family.a:0,0", default_tileset="family.b@base")
            self.assertEqual(resolved_physical.tileset_id, "family.a@base")
            self.assertEqual(resolved_physical.family_tile_id, "family.a:all:0,0")
            project.validate_ref_without_loading("family.a.alias", default_tileset="family.b@base")
            project.validate_ref_without_loading("family.a:0,0", default_tileset="family.b@base")
            with self.assertRaisesRegex(ValueError, "Unsupported tile reference syntax"):
                project.validate_ref_without_loading("missing.alias", default_tileset="family.b@base")

    def test_legacy_path_project_loads_source_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {
                        "path": str(ROOT / "prototypes/minimal8-harness/tile-families/minimal8"),
                        "variant_id": "1bit_colored_bg",
                    },
                    "grid": {"render_step_width": 8, "render_step_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            project = layout_core.LayoutProject(project_path)
            family = project.source_family_for_tileset("minimal8@1bit_colored_bg")

            self.assertIsNotNone(family)
            assert family is not None
            self.assertIsNotNone(family.source_layout)
            assert family.source_layout is not None
            self.assertIn("ui.gold_frame", family.source_layout.source_collections)

    def test_project_supports_source_pack_tile_family_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack_path = _make_minimal_source_pack(
                root,
                directory_name="source_pack",
                pack_id="pack.one",
                tileset_id="family.one",
                tilesheet_id="main",
                family_id="family.one",
            )
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {
                        "source_pack": str(pack_path),
                        "tileset_id": "family.one",
                        "tilesheet_id": "main",
                        "family_id": "family.one",
                        "variant_id": "alt",
                    },
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            project = layout_core.LayoutProject(project_path)

            self.assertEqual(project.default_tileset_id(), "family.one@alt")
            self.assertEqual(
                set(project.family_variant_tileset_ids()),
                {"family.one@base", "family.one@alt"},
            )
            tile_library = project.tile_library_unit_for_tileset("family.one@alt")
            self.assertIsNotNone(tile_library)
            assert tile_library is not None
            self.assertEqual(tile_library.promoted_metadata.source_pack_id, "pack.one")
            self.assertEqual(tile_library.promoted_metadata.source_tileset_id, "family.one")
            self.assertEqual(tile_library.promoted_metadata.source_tilesheet_id, "main")
            resolved = project.resolve_tile("family.one.alias")
            self.assertEqual(resolved.tileset_id, "family.one@alt")
            self.assertEqual(resolved.family_tile_id, "family.one:all:0,0")

    def test_runtime_scene_work_stays_self_sufficient_after_manifest_files_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _copy_minimal8_runtime_fixture(Path(temp_dir))
            tavern_scene = cast(
                harness.SceneTemplate,
                {"template": "tavern", "x": 0, "y": 0, "width": 40, "height": 25},
            )
            construction_id = "indoors.bookcase.tall.run"
            ref_token = "minimal8:terrain:0,15"

            golden_project = layout_core.LayoutProject(fixture.project_path)
            golden = _capture_minimal8_golden_state(
                golden_project,
                family_tileset_id=fixture.family_tileset_id,
                utility_tileset_id=fixture.utility_tileset_id,
                ref_token=ref_token,
                construction_id=construction_id,
                tavern_scene=tavern_scene,
            )

            project = layout_core.LayoutProject(fixture.project_path)
            self.assertNotIn(fixture.family_tileset_id, project.tilesets)
            for manifest_path in fixture.deleted_manifest_paths:
                manifest_path.unlink()

            protected_paths = frozenset(path.resolve() for path in fixture.deleted_manifest_paths)
            original_path_open: Any = Path.open
            original_open: Any = builtins.open

            def guarded_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
                _reject_if_protected_path(self, protected_paths=protected_paths)
                return original_path_open(self, *args, **kwargs)

            def guarded_open(
                file: Any,
                *args: Any,
                **kwargs: Any,
            ) -> Any:
                if isinstance(file, str):
                    _reject_if_protected_path(Path(file), protected_paths=protected_paths)
                elif isinstance(file, Path):
                    _reject_if_protected_path(file, protected_paths=protected_paths)
                return original_open(file, *args, **kwargs)

            with patch.object(Path, "open", new=guarded_path_open), patch("builtins.open", new=guarded_open):
                tile_library = project.tile_library_unit_for_tileset(fixture.family_tileset_id)
                self.assertIsNotNone(tile_library)
                assert tile_library is not None
                self.assertEqual(tile_library.promoted_metadata, golden.promoted_metadata)
                self.assertEqual(tile_library.promoted_metadata.source_pack_id, "minimal8")
                self.assertEqual(tile_library.promoted_metadata.source_tileset_id, "minimal8")
                self.assertEqual(tile_library.promoted_metadata.source_tilesheet_id, "main")
                self.assertEqual(dict(tile_library.promoted_metadata.module_context), {})
                self.assertEqual(tile_library.promoted_metadata.render_traits.alignment_origin, "bottom_left")

                self.assertIsNotNone(project.tile_library_registry)
                assert project.tile_library_registry is not None
                post_construction = project.tile_library_registry.lookup_construction(construction_id)
                self.assertEqual(post_construction, golden.construction)

                project.validate_ref_without_loading(
                    ref_token,
                    default_tileset=fixture.utility_tileset_id,
                )
                resolved = project.family_tile_for_ref(
                    ref_token,
                    tileset_id=fixture.utility_tileset_id,
                )
                self.assertEqual(resolved, golden.resolved_tile)
                assert resolved is not None

                post_tileset = project.get_tileset(fixture.family_tileset_id)
                self.assertEqual(post_tileset.id, golden.tileset.id)
                self.assertEqual(post_tileset.sheet_path, fixture.selected_variant_sheet_path)
                self.assertEqual(post_tileset.sheet_path, golden.tileset.sheet_path)
                self.assertEqual(post_tileset.columns, golden.tileset.columns)
                self.assertEqual(post_tileset.rows, golden.tileset.rows)
                self.assertEqual(post_tileset.tile_count, golden.tileset.tile_count)
                self.assertIn(fixture.family_tileset_id, project.tilesets)

                preview = layout_core.render_tile_preview_image(project, resolved)
                self.assertEqual(preview.size, golden.preview_size)
                self.assertEqual(preview.tobytes(), golden.preview_bytes)

                runtime = harness.expand_scene_runtime(
                    project,
                    tavern_scene,
                    default_tileset=fixture.family_tileset_id,
                )
                self.assertEqual(runtime, golden.runtime)

    def test_project_rejects_unknown_default_tileset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_multi_family_project(
                Path(temp_dir),
                default_tileset="missing@base",
            )

            with self.assertRaisesRegex(ValueError, "Configured default_tileset 'missing@base' is unknown"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_multiple_tile_families_without_explicit_default_tileset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_multi_family_project(Path(temp_dir), default_tileset=None)

            with self.assertRaisesRegex(ValueError, "must define default_tileset"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_both_tile_family_and_tile_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_dir = _make_minimal_family_dir(root, directory_name="family", family_id="family.one")
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {"path": str(family_dir), "variant_id": "base"},
                    "tile_families": [{"path": str(family_dir), "variant_id": "base"}],
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "either tile_family or tile_families, not both"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_tile_family_config_with_path_and_source_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_dir = _make_minimal_family_dir(root, directory_name="family", family_id="family.one")
            pack_path = _make_minimal_source_pack(
                root,
                directory_name="source_pack",
                pack_id="pack.one",
                tileset_id="family.one",
                tilesheet_id="main",
                family_id="family.one",
            )
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {
                        "path": str(family_dir),
                        "source_pack": str(pack_path),
                        "tileset_id": "family.one",
                        "tilesheet_id": "main",
                        "variant_id": "alt",
                    },
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "either path or source_pack, not both"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_source_pack_config_without_tileset_and_tilesheet_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack_path = _make_minimal_source_pack(
                root,
                directory_name="source_pack",
                pack_id="pack.one",
                tileset_id="family.one",
                tilesheet_id="main",
                family_id="family.one",
            )
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {
                        "source_pack": str(pack_path),
                        "variant_id": "alt",
                    },
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "must define tileset_id and tilesheet_id"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_tile_family_config_without_path_or_source_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_family": {
                        "family_id": "family.one",
                        "variant_id": "base",
                    },
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "must define path or source_pack"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_empty_tile_family_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_dir = _make_minimal_family_dir(root, directory_name="family", family_id="family.one")
            for empty_spec in ("", None):
                project_path = root / "project.json"
                _write_json(
                    project_path,
                    {
                        "tile_families": [
                            empty_spec,
                            {"path": str(family_dir), "variant_id": "base"},
                        ],
                        "default_tileset": "family.one@base",
                        "grid": {"tile_width": 8, "tile_height": 8},
                        "tilesets": {},
                        "aliases": {},
                        "patterns": {},
                    },
                )

                with self.subTest(empty_spec=empty_spec):
                    with self.assertRaisesRegex(ValueError, r"tile_families\[0\] must not be empty"):
                        layout_core.LayoutProject(project_path)

    def test_project_rejects_mismatched_loaded_tile_widths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = _make_minimal_family_dir(root, directory_name="family_a", family_id="family.a", tile_width=8)
            family_b = _make_minimal_family_dir(root, directory_name="family_b", family_id="family.b", tile_width=16)
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_families": [
                        {"path": str(family_a), "variant_id": "base"},
                        {"path": str(family_b), "variant_id": "base"},
                    ],
                    "default_tileset": "family.a@base",
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "same tile_width"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_mismatched_loaded_tile_heights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = _make_minimal_family_dir(root, directory_name="family_a", family_id="family.a", tile_height=8)
            family_b = _make_minimal_family_dir(root, directory_name="family_b", family_id="family.b", tile_height=16)
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_families": [
                        {"path": str(family_a), "variant_id": "base"},
                        {"path": str(family_b), "variant_id": "base"},
                    ],
                    "default_tileset": "family.a@base",
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "same tile_height"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_mismatched_loaded_render_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = _make_minimal_family_dir(
                root,
                directory_name="family_a",
                family_id="family.a",
                render_step_width=8,
            )
            family_b = _make_minimal_family_dir(
                root,
                directory_name="family_b",
                family_id="family.b",
                render_step_width=12,
            )
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_families": [
                        {"path": str(family_a), "variant_id": "base"},
                        {"path": str(family_b), "variant_id": "base"},
                    ],
                    "default_tileset": "family.a@base",
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "same render_step_width"):
                layout_core.LayoutProject(project_path)

    def test_project_rejects_mismatched_loaded_render_step_heights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = _make_minimal_family_dir(
                root,
                directory_name="family_a",
                family_id="family.a",
                render_step_height=8,
            )
            family_b = _make_minimal_family_dir(
                root,
                directory_name="family_b",
                family_id="family.b",
                render_step_height=12,
            )
            project_path = root / "project.json"
            _write_json(
                project_path,
                {
                    "tile_families": [
                        {"path": str(family_a), "variant_id": "base"},
                        {"path": str(family_b), "variant_id": "base"},
                    ],
                    "default_tileset": "family.a@base",
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {},
                    "aliases": {},
                    "patterns": {},
                },
            )

            with self.assertRaisesRegex(ValueError, "same render_step_height"):
                layout_core.LayoutProject(project_path)

    def test_expand_scene_rejects_unknown_template(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        with self.assertRaisesRegex(ValueError, "Unknown scene template"):
            harness.expand_scene(
                project,
                {"template": "missing", "x": 0, "y": 0, "width": 1, "height": 1},
                default_tileset=project.default_tileset_id(),
            )

    def test_validate_family_ingest_reports_complete_minimal8_family(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        report = source_ingest_ops.validate_family_ingest(layout_core.LayoutProject(project_path), "minimal8@1bit_colored_bg")

        self.assertTrue(report["complete"])
        self.assertEqual(report["tile_count"], 1408)
        self.assertEqual(report["missing_source_group"], [])
        self.assertEqual(report["missing_cluster_ids"], [])
        self.assertEqual(report["missing_meaning"], [])
        self.assertEqual(report["missing_meaning_confidence"], [])

    def test_minimal8_uses_true_8x8_placement_and_bottom_left_default_anchor(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)
        family = project.source_family_for_tileset("minimal8@1bit_colored_bg")
        tile_library = project.tile_library_unit_for_tileset("minimal8@1bit_colored_bg")

        self.assertIsNotNone(family)
        self.assertIsNotNone(tile_library)
        assert family is not None
        assert tile_library is not None
        self.assertEqual(project.grid_width, 8)
        self.assertEqual(project.grid_height, 8)
        self.assertEqual(project.render_step_width, 8)
        self.assertEqual(project.render_step_height, 8)
        self.assertEqual(family.render_step_width, 8)
        self.assertEqual(family.render_step_height, 8)
        self.assertEqual(tile_library.render_step_width, 8)
        self.assertEqual(tile_library.render_step_height, 8)

        resolved = project.family_tile_for_ref("minimal8:terrain:0,15", tileset_id="minimal8@1bit_colored_bg")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        image = project.image_for_tile(resolved)
        self.assertEqual(image.getbbox(), (0, 1, 7, 8))

    def test_runtime_tile_library_unit_resolves_refs_without_reaching_through_tile_family(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        tile_library = project.tile_library_unit_for_tileset("minimal8@1bit_colored_bg")

        self.assertIsNotNone(tile_library)
        assert tile_library is not None
        resolved = tile_library.resolve_ref("minimal8:terrain:0,15", variant_id="1bit_colored_bg")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.tile_id, "minimal8:terrain:0,15")
        self.assertEqual(tile_library.runtime_tileset_id("1bit_colored_bg"), "minimal8@1bit_colored_bg")

    def test_tile_library_unit_tile_record_returns_none_for_missing_tile(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        tile_library = project.tile_library_unit_for_tileset("minimal8@1bit_colored_bg")

        self.assertIsNotNone(tile_library)
        assert tile_library is not None
        self.assertIsNone(tile_library.tile_record("missing.tile"))

    def test_runtime_hot_path_does_not_need_source_family_access(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        def forbid_source_family_access(tileset_id: str) -> tile_families.TileFamily | None:
            raise AssertionError(f"runtime should not require source family access for {tileset_id}")

        project.source_family_for_tileset = forbid_source_family_access  # type: ignore[method-assign]

        resolved = project.family_tile_for_ref("minimal8:terrain:0,15", tileset_id="minimal8@1bit_colored_bg")
        self.assertIsNotNone(resolved)
        project.validate_ref_without_loading(
            "minimal8:terrain:0,15",
            default_tileset="minimal8@1bit_colored_bg",
        )
        runtime = harness.expand_scene_runtime(
            project,
            {"template": "tavern", "x": 0, "y": 0, "width": 40, "height": 25},
            default_tileset="minimal8@1bit_colored_bg",
        )
        self.assertGreater(len(runtime.entities), 0)

    def test_minimal8_actor_aliases_resolve_to_visible_character_tiles(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        actor_aliases = [
            "actor.bartender.nw",
            "actor.bartender.ne",
            "actor.bartender.sw",
            "actor.bartender.se",
            "actor.red.nw",
            "actor.red.ne",
            "actor.red.sw",
            "actor.red.se",
            "actor.gold.nw",
            "actor.gold.ne",
            "actor.gold.sw",
            "actor.gold.se",
            "actor.green.nw",
            "actor.green.ne",
            "actor.green.sw",
            "actor.green.se",
            "actor.orange.nw",
            "actor.orange.ne",
            "actor.orange.sw",
            "actor.orange.se",
            "actor.purple.nw",
            "actor.purple.ne",
            "actor.purple.sw",
            "actor.purple.se",
            "actor.teal.nw",
            "actor.teal.ne",
            "actor.teal.sw",
            "actor.teal.se",
            "actor.blue.nw",
            "actor.blue.ne",
            "actor.blue.sw",
            "actor.blue.se",
            "actor.salmon.nw",
            "actor.salmon.ne",
            "actor.salmon.sw",
            "actor.salmon.se",
        ]

        for alias in actor_aliases:
            resolved = project.resolve_tile(alias, default_tileset="minimal8@1bit_colored_bg")
            spec = project.render_spec_for_tile(resolved)
            self.assertIsNotNone(spec.image.getbbox(), alias)

    def test_audit_family_semantic_usage_reports_current_reference_surface(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        report = source_ingest_ops.audit_family_semantic_usage(layout_core.LayoutProject(project_path), "minimal8@1bit_colored_bg")

        self.assertEqual(report["tileset"], "minimal8@1bit_colored_bg")
        self.assertGreater(report["total_references"], 0)
        self.assertGreater(report["total_resolved_family_tiles"], 0)
        self.assertIn("confirmed", report["by_meaning_confidence"])

    def test_detect_family_source_layout_exports_detected_regions(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "detected"
            source_ingest_ops.detect_family_source_layout(layout_core.LayoutProject(project_path), "minimal8@1bit_colored_bg", output_dir)
            payload = json.loads((output_dir / "source_layout.detected.json").read_text(encoding="utf-8"))

        self.assertEqual(len(payload["regions"]), 4)
        self.assertEqual(len(payload["clusters"]), 23)
        self.assertGreater(len(payload["collections"]), 0)

    def test_render_pattern_image_supports_family_image_override_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)
            pattern = project.pattern_from_ref("sample.override")
            resolved = pattern.cells[0][0]

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertIsNotNone(resolved.image_override_path)

            image = layout_core.render_pattern_image(project, pattern)
            self.assertEqual(image.size, (8, 8))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 255, 255))

    def test_family_image_override_ref_has_no_fake_sheet_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)

            resolved = project.family_tile_for_ref("sample.override", tileset_id="testfam@base")

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertIsNone(resolved.index)
            self.assertEqual(resolved.family_tile_id, "testfam:derived.override")
            self.assertEqual(project.image_for_tile(resolved).size, (8, 8))

    def test_composite_tile_ref_precomposes_underpaint_before_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_composite_tileset_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)

            resolved = project.resolve_tile("sample.overlay.with_underpaint", default_tileset="sample")
            image = project.image_for_tile(resolved)

            self.assertEqual(image.getpixel((0, 0)), (10, 20, 200, 255))
            self.assertEqual(image.getpixel((4, 4)), (250, 240, 40, 255))

    def test_composite_tile_ref_flips_underpaint_and_foreground_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_composite_tileset_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)

            resolved = project.resolve_tile("sample.overlay.flipped", default_tileset="sample")
            image = project.image_for_tile(resolved)

            self.assertEqual(image.getpixel((7, 0)), (10, 20, 200, 255))
            self.assertEqual(image.getpixel((3, 4)), (250, 240, 40, 255))

    def test_composite_tile_ref_supports_bottom_left_overlay_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_composite_tileset_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)

            resolved = project.resolve_tile("sample.overlay.with_offset", default_tileset="sample")
            spec = project.render_spec_for_tile(resolved)
            image = spec.image

            self.assertEqual(spec.origin_x, 0)
            self.assertEqual(spec.origin_y, -1)
            self.assertEqual(image.size, (9, 9))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(image.getpixel((0, 7)), (10, 20, 200, 255))
            self.assertEqual(image.getpixel((5, 4)), (250, 240, 40, 255))

    def test_flipped_composite_tile_ref_mirrors_overlay_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_composite_tileset_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)

            resolved = project.resolve_tile("sample.overlay.offset_flipped", default_tileset="sample")
            spec = project.render_spec_for_tile(resolved)
            image = spec.image

            self.assertEqual(spec.origin_x, -1)
            self.assertEqual(spec.origin_y, -1)
            self.assertEqual(image.size, (9, 9))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(image.getpixel((8, 1)), (10, 20, 200, 255))
            self.assertEqual(image.getpixel((7, 7)), (10, 20, 200, 255))
            self.assertEqual(image.getpixel((3, 4)), (250, 240, 40, 255))

    def test_render_layer_image_allows_single_tile_overflow_into_neighbour_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_path = _make_composite_tileset_project(temp_path)
            layout_path = temp_path / "layout.json"
            _write_json(
                layout_path,
                {
                    "project": str(project_path),
                    "default_tileset": "sample",
                    "map": {"width": 2, "height": 1, "background": "#102030"},
                    "output": "out.png",
                    "layers": [
                        {"name": "actors", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "sample.overlay.overflow_right"}]}
                    ],
                },
            )

            output = harness.render_layout(layout_path)
            image = Image.open(output).convert("RGBA")

            self.assertEqual(image.size, (16, 8))
            self.assertEqual(image.getpixel((8, 4)), (250, 240, 40, 255))
            self.assertEqual(image.getpixel((9, 4)), (16, 32, 48, 255))

    def test_render_pattern_image_expands_to_include_visible_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_composite_tileset_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)
            resolved = project.resolve_tile("sample.overlay.overflow_right", default_tileset="sample")
            pattern = layout_core.Pattern(width=1, height=1, cells=((resolved,),))

            image = layout_core.render_pattern_image(project, pattern, snap_to_grid=True)

            self.assertEqual(image.size, (12, 8))
            self.assertEqual(image.getpixel((8, 4)), (250, 240, 40, 255))

    def test_legged_table_underpaint_adds_extra_bottom_overlay_offset(self) -> None:
        project = layout_core.LayoutProject(ROOT / "prototypes/minimal8-harness/project.minimal8.json")

        resolved = project.resolve_tile(
            {
                "ref": "prop.tankard",
                "underpaint": "indoors.table.round",
                "offset_left": 1,
                "offset_bottom": 1,
            },
            default_tileset="minimal8@1bit_colored_bg",
        )

        self.assertEqual(resolved.overlay_offset_x, 1)
        self.assertEqual(resolved.overlay_offset_y, -3)

    def test_non_legged_table_underpaint_keeps_base_bottom_overlay_offset(self) -> None:
        project = layout_core.LayoutProject(ROOT / "prototypes/minimal8-harness/project.minimal8.json")

        resolved = project.resolve_tile(
            {
                "ref": "prop.tankard",
                "underpaint": "indoors.table.vertical.top",
                "offset_left": 1,
                "offset_bottom": 1,
            },
            default_tileset="minimal8@1bit_colored_bg",
        )

        self.assertEqual(resolved.overlay_offset_x, 1)
        self.assertEqual(resolved.overlay_offset_y, -1)

    def test_non_transparent_family_tiles_default_to_fill_cell_occlusion(self) -> None:
        project = layout_core.LayoutProject(ROOT / "prototypes/minimal8-harness/project.minimal8.json")

        wall = project.resolve_tile("tavern.wall.c", default_tileset="minimal8@1bit_colored_bg")
        wall_mask = project.occlusion_mask_for_tile(wall)
        self.assertIsNotNone(wall_mask)
        assert wall_mask is not None
        self.assertEqual(wall_mask.getbbox(), (0, 0, 8, 8))

        table = project.resolve_tile("indoors.table.vertical.top", default_tileset="minimal8@1bit_colored_bg")
        table_mask = project.occlusion_mask_for_tile(table)
        self.assertIsNotNone(table_mask)
        assert table_mask is not None
        self.assertEqual(table_mask.getbbox(), (0, 0, 8, 8))

        prop = project.resolve_tile("prop.tankard.original", default_tileset="minimal8@1bit_colored_bg")
        self.assertIsNone(project.occlusion_mask_for_tile(prop))

    def test_composite_underpaint_preserves_support_tile_occlusion(self) -> None:
        project = layout_core.LayoutProject(ROOT / "prototypes/minimal8-harness/project.minimal8.json")

        resolved = project.resolve_tile(
            {
                "ref": "indoors.light.torch.frame_2",
                "underpaint": "minimal8:architecture:2,14",
                "occlusion": "fill_holes",
            },
            default_tileset="minimal8@1bit_colored_bg",
        )

        mask = project.occlusion_mask_for_tile(resolved)
        self.assertIsNotNone(mask)
        assert mask is not None
        self.assertEqual(mask.getbbox(), (0, 0, 8, 8))
        self.assertEqual(mask.getpixel((0, 0)), 255)
        self.assertEqual(mask.getpixel((7, 0)), 255)
        self.assertEqual(mask.getpixel((0, 7)), 255)
        self.assertEqual(mask.getpixel((7, 7)), 255)
        with tempfile.TemporaryDirectory() as temp_dir:
            layout_path = Path(temp_dir) / "layout.json"
            _write_json(
                layout_path,
                {
                    "project": str(ROOT / "prototypes/minimal8-harness/project.minimal8.json"),
                    "default_tileset": "minimal8@1bit_colored_bg",
                    "map": {"width": 1, "height": 1, "background": "#010203"},
                    "output": "out.png",
                    "layers": [
                        {"name": "terrain", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "tavern.floor.a"}]},
                        {"name": "ornament", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": {
                            "ref": "indoors.light.torch.frame_2",
                            "underpaint": "minimal8:architecture:2,14",
                            "occlusion": "fill_holes",
                        }}]},
                    ],
                },
            )

            output = harness.render_layout(layout_path)
            image = Image.open(output).convert("RGBA")
            self.assertEqual(image.getpixel((0, 0)), (1, 2, 3, 255))

    def test_fill_cell_occlusion_blocks_lower_layers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_path = _make_composite_tileset_project(temp_path)
            layout_path = temp_path / "layout.json"
            _write_json(
                layout_path,
                {
                    "project": str(project_path),
                    "default_tileset": "sample",
                    "map": {"width": 1, "height": 1, "background": "#102030"},
                    "output": "out.png",
                    "layers": [
                        {"name": "terrain", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "2,0"}]},
                        {
                            "name": "actors",
                            "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "sample.overlay.fill_cell"}],
                        },
                    ],
                },
            )

            output = harness.render_layout(layout_path)
            image = Image.open(output).convert("RGBA")

            self.assertEqual(image.getpixel((4, 4)), (250, 240, 40, 255))
            self.assertEqual(image.getpixel((0, 0)), (16, 32, 48, 255))

    def test_fill_holes_occlusion_blocks_lower_layers_inside_interior_holes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_path = _make_composite_tileset_project(temp_path)
            layout_path = temp_path / "layout.json"
            _write_json(
                layout_path,
                {
                    "project": str(project_path),
                    "default_tileset": "sample",
                    "map": {"width": 1, "height": 1, "background": "#102030"},
                    "output": "out.png",
                    "layers": [
                        {"name": "terrain", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "2,0"}]},
                        {
                            "name": "actors",
                            "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "sample.overlay.fill_holes"}],
                        },
                    ],
                },
            )

            output = harness.render_layout(layout_path)
            image = Image.open(output).convert("RGBA")

            self.assertEqual(image.getpixel((0, 0)), (40, 220, 120, 255))
            self.assertEqual(image.getpixel((4, 4)), (16, 32, 48, 255))

    def test_audit_family_semantic_usage_counts_synthetic_family_layout_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            layouts_dir = Path(temp_dir) / "layouts"
            layouts_dir.mkdir()
            _write_json(
                layouts_dir / "override_layout.json",
                {
                    "project": str(project_path),
                    "map": {"width": 1, "height": 1},
                    "output": "out.png",
                    "layers": [{"name": "terrain", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "sample.override"}]}],
                },
            )

            report = source_ingest_ops.audit_family_semantic_usage(
                layout_core.LayoutProject(project_path),
                "testfam@base",
                layouts_dir=layouts_dir,
            )

            self.assertEqual(report["total_resolved_family_tiles"], 2)
            self.assertEqual(report["flagged_references"], 0)

    def test_apply_ascii_places_tiles_and_ignores_blank_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)
            layer = layout_core.new_layer(3, 2)

            layout_core.apply_ascii(
                layer,
                project,
                {
                    "kind": "ascii",
                    "x": 0,
                    "y": 0,
                    "legend": {"#": "sample.override"},
                    "rows": ["# .", "..#"],
                },
                default_tileset=project.default_tileset_id(),
            )

            self.assertIsNotNone(layer[0][0])
            self.assertIsNone(layer[0][1])
            self.assertIsNone(layer[0][2])
            self.assertIsNone(layer[1][0])
            self.assertIsNone(layer[1][1])
            self.assertIsNotNone(layer[1][2])
            assert layer[0][0] is not None
            self.assertEqual(layer[0][0].family_tile_id, "testfam:derived.override")

    def test_apply_ascii_rejects_unknown_legend_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)
            layer = layout_core.new_layer(1, 1)

            with self.assertRaisesRegex(ValueError, "ASCII legend missing entry"):
                layout_core.apply_ascii(
                    layer,
                    project,
                    {
                        "kind": "ascii",
                        "x": 0,
                        "y": 0,
                        "legend": {},
                        "rows": ["#"],
                    },
                    default_tileset=project.default_tileset_id(),
                )

    def test_family_backed_raw_tileset_coords_use_hash_syntax(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        resolved = project.resolve_tile("minimal8@1bit_colored_bg#20,24")
        self.assertEqual(resolved.tileset_id, "minimal8@1bit_colored_bg")
        self.assertEqual(
            project.get_tileset("minimal8@1bit_colored_bg").col_row_from_index(resolved.require_index()),
            (20, 24),
        )

        tracked = project.resolve_tile("minimal8@1bit_colored_bg:44,12")
        self.assertEqual(tracked.family_tile_id, "minimal8:characters:7,11")

        with self.assertRaisesRegex(ValueError, "must use `minimal8@1bit_colored_bg#20,24`"):
            project.resolve_tile("minimal8@1bit_colored_bg:20,24")

    def test_family_backed_variant_qualified_semantic_refs_resolve_cleanly(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        alias_resolved = project.resolve_tile("minimal8@1bit_colored_bg:indoors.table.long.left")
        self.assertEqual(alias_resolved.tileset_id, "minimal8@1bit_colored_bg")
        self.assertEqual(alias_resolved.family_tile_id, "minimal8:terrain:1,15")

        stable_id_resolved = project.resolve_tile("minimal8@1bit_colored_bg:minimal8:terrain:1,15")
        self.assertEqual(stable_id_resolved.tileset_id, "minimal8@1bit_colored_bg")
        self.assertEqual(stable_id_resolved.family_tile_id, "minimal8:terrain:1,15")
        self.assertEqual(alias_resolved.require_index(), stable_id_resolved.require_index())

    def test_minimal8_table_constructions_encode_single_table_shapes(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)
        family = project.source_family_for_tileset("minimal8@1bit_colored_bg")
        assert family is not None

        def role(cell: object) -> str | None:
            from tile_library import TileRecord
            if not isinstance(cell, TileRecord):
                return None
            return cell.compose_role

        from tile_library import FixedConstruction

        square = family.lookup_construction("indoors.table.kit.square_2x2")
        assert square is not None
        assert isinstance(square, FixedConstruction)
        self.assertEqual(len(square.cells), 2)
        self.assertEqual(len(square.cells[0]), 2)
        self.assertEqual(role(square.cells[0][0]), "vertical_top_end")
        self.assertEqual(role(square.cells[1][0]), "vertical_bottom_end")

        horizontal = family.lookup_construction("indoors.table.kit.horizontal_2x6")
        assert horizontal is not None
        assert isinstance(horizontal, FixedConstruction)
        self.assertEqual(len(horizontal.cells), 2)
        self.assertEqual(len(horizontal.cells[0]), 6)
        self.assertTrue(all(role(cell) == "vertical_top_end" for cell in horizontal.cells[0]))
        self.assertTrue(all(role(cell) == "vertical_bottom_end" for cell in horizontal.cells[1]))

        vertical = family.lookup_construction("indoors.table.kit.vertical_2x6")
        assert vertical is not None
        assert isinstance(vertical, FixedConstruction)
        self.assertEqual(len(vertical.cells), 6)
        self.assertEqual(len(vertical.cells[0]), 2)
        self.assertTrue(all(role(cell) == "vertical_top_end" for cell in vertical.cells[0]))
        self.assertTrue(all(role(cell) == "vertical_bottom_end" for cell in vertical.cells[-1]))
        for row in vertical.cells[1:-1]:
            self.assertTrue(all(role(cell) == "vertical_middle" for cell in row))

        rect_vertical = family.lookup_construction("indoors.table.kit.rect_2x3")
        assert rect_vertical is not None
        assert isinstance(rect_vertical, FixedConstruction)
        self.assertEqual(len(rect_vertical.cells), 3)
        self.assertEqual(len(rect_vertical.cells[0]), 2)
        self.assertTrue(all(role(cell) == "vertical_top_end" for cell in rect_vertical.cells[0]))
        self.assertTrue(all(role(cell) == "vertical_bottom_end" for cell in rect_vertical.cells[-1]))
        self.assertTrue(all(role(cell) == "vertical_middle" for cell in rect_vertical.cells[1]))

        top_left = family.lookup_construction("indoors.table.kit.l_top_left")
        assert top_left is not None
        assert isinstance(top_left, FixedConstruction)
        self.assertEqual(len(top_left.cells), 3)
        self.assertEqual(len(top_left.cells[0]), 3)
        self.assertEqual(role(top_left.cells[0][0]), "vertical_middle")
        self.assertEqual(role(top_left.cells[0][1]), "horizontal_middle")
        self.assertEqual(role(top_left.cells[0][2]), "horizontal_right_end")
        self.assertIsNone(top_left.cells[1][1])
        self.assertIsNone(top_left.cells[2][2])

        top_right = family.lookup_construction("indoors.table.kit.l_top_right")
        assert top_right is not None
        assert isinstance(top_right, FixedConstruction)
        self.assertEqual(role(top_right.cells[0][0]), "horizontal_left_end")
        self.assertEqual(role(top_right.cells[0][1]), "horizontal_middle")
        self.assertEqual(role(top_right.cells[0][2]), "vertical_middle")

        bottom_right = family.lookup_construction("indoors.table.kit.l_bottom_right")
        assert bottom_right is not None
        assert isinstance(bottom_right, FixedConstruction)
        self.assertEqual(len(bottom_right.cells), 3)
        self.assertEqual(len(bottom_right.cells[0]), 3)
        self.assertEqual(role(bottom_right.cells[2][0]), "horizontal_left_end")
        self.assertEqual(role(bottom_right.cells[2][1]), "horizontal_middle")
        self.assertEqual(role(bottom_right.cells[2][2]), "vertical_bottom_end")
        self.assertIsNone(bottom_right.cells[0][0])
        self.assertIsNone(bottom_right.cells[1][1])

    def test_project_patterns_are_the_active_named_pattern_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = _make_project_with_patterns(
                Path(temp_dir),
                patterns={
                    "sample_corner": {
                        "tileset": "sheet",
                        "rows": [["0,0", "1,0"]],
                    }
                },
            )

            project = layout_core.LayoutProject(project_path)
            pattern = project.pattern_from_ref("@sample_corner")

            self.assertEqual(project.pattern_names(), ["sample_corner"])
            self.assertEqual(pattern.width, 2)
            self.assertEqual(pattern.height, 1)

    def test_project_rejects_legacy_metatiles_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            Image.new("RGBA", (16, 8), (1, 2, 3, 255)).save(temp_root / "sheet.png")
            project_path = temp_root / "project.json"
            _write_json(
                project_path,
                {
                    "scene_templates_dir": str(ROOT / "prototypes/minimal8-harness/scene-templates"),
                    "grid": {"tile_width": 8, "tile_height": 8},
                    "tilesets": {
                        "sheet": {
                            "sheet": str(temp_root / "sheet.png"),
                            "transparent": "none",
                            "regions": {"all": {"x": 0, "y": 0, "width": 2, "height": 1}},
                        }
                    },
                    "metatiles": {
                        "legacy_corner": {
                            "tileset": "sheet",
                            "rows": [["0,0", "1,0"]],
                        }
                    }
                },
            )

            with self.assertRaisesRegex(
                ValueError,
                "metatiles",
            ):
                layout_core.LayoutProject(project_path)

    def test_minimal8_grand_open_door_resolves_as_composite_tile(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        with self.assertRaisesRegex(ValueError, "Unknown pattern: indoors_door_grand_open"):
            project.pattern_from_ref("@indoors_door_grand_open")

        family = project.source_family_for_tileset("minimal8@1bit_colored_bg")
        assert family is not None
        self.assertIsNone(family.lookup_construction("indoors.door.grand.open"))
        composite = family.composite_tiles["indoors.door.grand.open"]
        self.assertEqual(composite.collection_id, "indoors.door.grand.open")
        self.assertEqual((composite.width, composite.height), (2, 2))

    def test_minimal8_overworld_land_undercoat_resolves_as_alias(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        resolved = project.resolve_tile("overworld_land_undercoat")
        tileset = project.get_tileset(resolved.tileset_id)
        self.assertEqual(resolved.tileset_id, "utility_land")
        self.assertEqual(tileset.col_row_from_index(resolved.require_index()), (0, 0))

        with self.assertRaisesRegex(ValueError, "Unknown pattern: overworld_land_undercoat"):
            project.pattern_from_ref("@overworld_land_undercoat")

    def test_minimal8_overworld_route_node_resolves_as_alias(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        resolved = project.resolve_tile("overworld_route_node")
        tileset = project.get_tileset(resolved.tileset_id)
        self.assertEqual(resolved.tileset_id, "minimal8@1bit_colored_bg")
        self.assertEqual(tileset.col_row_from_index(resolved.require_index()), (20, 12))

        with self.assertRaisesRegex(ValueError, "Unknown pattern: overworld_route_node"):
            project.pattern_from_ref("@overworld_route_node")

    def test_export_layout_scene_runtime_preserves_resolved_entities(self) -> None:
        layout_path = ROOT / "prototypes/minimal8-harness/layouts/fool_and_flintlock.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "fool_and_flintlock.scene_runtime.json"
            harness.export_layout_scene_runtime(layout_path, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["entity_count"], len(payload["entities"]))
        self.assertGreater(payload["entity_count"], 0)
        placeables = {entity["template"]["placeable_id"]: entity for entity in payload["entities"]}
        self.assertIn("indoors.table.kit.rect_3x2", placeables)
        table = placeables["indoors.table.kit.rect_3x2"]
        self.assertEqual(table["template"]["collection_id"], "indoors.table.kit")
        self.assertEqual(table["template"]["placement_anchor"], "top_left")
        self.assertEqual(table["placement_anchor"]["kind"], "top_left")
        self.assertEqual(table["bounds"]["width"], 3)
        self.assertEqual(table["bounds"]["height"], 2)
        self.assertEqual(table["occupancy"]["cell_count"], 6)
        self.assertEqual(len(table["occupancy"]["cells"]), 6)
        self.assertEqual(table["occupancy"]["blocking_cells"], [])
        self.assertEqual(len(table["occupancy"]["unknown_cells"]), 6)
        self.assertEqual(len(table["affordance_cells"]), 6)

    def test_export_layout_scene_runtime_emits_per_stamp_genesis(self) -> None:
        layout_path = ROOT / "prototypes/minimal8-harness/layouts/fool_and_flintlock.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "fool_and_flintlock.scene_runtime.json"
            harness.export_layout_scene_runtime(layout_path, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        placeables = {entity["template"]["placeable_id"]: entity for entity in payload["entities"]}
        table = placeables["indoors.table.kit.rect_3x2"]
        self.assertTrue(table["tiles"])
        for placement in table["tiles"]:
            self.assertIn("genesis", placement)
            genesis = placement["genesis"]
            self.assertIsNotNone(genesis)
            self.assertIn(genesis["kind"], {"sheet", "synthetic"})
            if genesis["kind"] == "sheet":
                self.assertIsNotNone(genesis["sheet_col"])
                self.assertIsNotNone(genesis["sheet_row"])
            else:
                self.assertIsNotNone(genesis["derivation"])

    def test_entity_instance_tracks_occupied_cells_separately_from_bounds(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)
        tile_library = project.tile_library_unit_for_tileset("minimal8@1bit_colored_bg")
        self.assertIsNotNone(tile_library)
        assert tile_library is not None

        entity = harness._resolve_scene_entity_request(  # type: ignore[attr-defined]
            tile_library,
            harness.SceneEntityRequest(
                entity_id="fixture.l_table",
                source_template_id="fixture",
                construction_id="indoors.table.kit.l_top_left",
                layer="architecture",
                x=10,
                y=20,
            ),
        )

        self.assertEqual(entity.bounds.width, 3)
        self.assertEqual(entity.bounds.height, 3)
        self.assertEqual(len(entity.occupied_cells), 5)
        occupied = {(cell.relative_x, cell.relative_y) for cell in entity.occupied_cells}
        self.assertEqual(occupied, {(0, 0), (1, 0), (2, 0), (0, 1), (0, 2)})
        self.assertEqual(len(entity.affordance_cells), 5)

    def test_pattern_catalog_previews_use_grid_aligned_dimensions(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        project = layout_core.LayoutProject(project_path)

        catalog = {
            entry["name"]: entry
            for entry in source_ingest_ops.build_pattern_catalog(project, tileset_id="minimal8@1bit_colored_bg")
        }

        self.assertEqual(catalog["temple_maze_corner"]["width_pixels"], 24)
        self.assertEqual(catalog["temple_maze_corner"]["height_pixels"], 24)
        self.assertEqual(catalog["gold_ui_corner"]["width_pixels"], 16)
        self.assertEqual(catalog["gold_ui_corner"]["height_pixels"], 16)

    def test_export_collection_review_pack_writes_repo_friendly_feedback_files(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir) / "collection-review"
            scratch_dir = Path(temp_dir) / "collection-review-scratch"
            round_one_dir = source_ingest_ops.export_collection_review_pack(
                layout_core.LayoutProject(project_path),
                "minimal8@1bit_colored_bg",
                root_dir,
                scale=2,
                scratch_output_root=scratch_dir,
            )
            round_two_dir = source_ingest_ops.export_collection_review_pack(
                layout_core.LayoutProject(project_path),
                "minimal8@1bit_colored_bg",
                root_dir,
                scale=2,
                scratch_output_root=scratch_dir,
            )
            manifest = json.loads((round_one_dir / "manifest.json").read_text(encoding="utf-8"))
            round_readme = (round_one_dir / "README.md").read_text(encoding="utf-8")
            series_readme = (root_dir / "README.md").read_text(encoding="utf-8")
            series = json.loads((root_dir / "series.json").read_text(encoding="utf-8"))

            self.assertEqual(round_one_dir.name, "round_001")
            self.assertEqual(round_two_dir.name, "round_002")
            self.assertEqual(manifest["tileset"], "minimal8@1bit_colored_bg")
            self.assertEqual(manifest["collection_count"], 48)
            self.assertIn("This pack is intended to be edited and committed.", round_readme)
            self.assertIn("multiple committed rounds of collection feedback", series_readme)
            self.assertEqual(series["round_count"], 2)
            first_collection = manifest["collections"][0]
            self.assertIn("source_region_id", first_collection)
            self.assertIn("source_cluster_id", first_collection)
            self.assertNotIn("region_id", first_collection)
            self.assertNotIn("cluster_id", first_collection)
            self.assertTrue((round_one_dir / first_collection["feedback_file"]).exists())
            self.assertTrue((round_one_dir / first_collection["preview"]).exists())
            self.assertTrue((scratch_dir / "round_001" / "overview.png").exists())
            self.assertTrue((scratch_dir / "round_001" / "sheet_overlay.png").exists())
            self.assertTrue((scratch_dir / "round_001" / "README.md").exists())
            collection_ids = {collection["id"] for collection in manifest["collections"]}
            self.assertIn("character.column_1.01", collection_ids)
            self.assertIn("character.column_5.04", collection_ids)
            self.assertIn("ui.gold_frame", collection_ids)
            self.assertIn("ui.frame.ornate_gap_3x3", collection_ids)
            self.assertIn("ui.separator_runs", collection_ids)

    def test_export_collection_review_pack_migrates_legacy_single_round_root(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir) / "collection-review"
            root_dir.mkdir(parents=True, exist_ok=False)
            (root_dir / "images").mkdir()
            (root_dir / "collections").mkdir()
            (root_dir / "manifest.json").write_text('{"collection_count": 1}\n', encoding="utf-8")
            (root_dir / "README.md").write_text("# Legacy Collection Review Pack\n", encoding="utf-8")
            (root_dir / "images" / "legacy.png").write_bytes(b"legacy")
            (root_dir / "collections" / "legacy.md").write_text("# Legacy\n", encoding="utf-8")

            round_two_dir = source_ingest_ops.export_collection_review_pack(layout_core.LayoutProject(project_path), "minimal8@1bit_colored_bg", root_dir, scale=2)
            migrated_round_one_dir = root_dir / "rounds" / "round_001"

            self.assertTrue((migrated_round_one_dir / "manifest.json").exists())
            self.assertTrue((migrated_round_one_dir / "README.md").exists())
            self.assertTrue((migrated_round_one_dir / "images" / "legacy.png").exists())
            self.assertTrue((migrated_round_one_dir / "collections" / "legacy.md").exists())
            self.assertEqual(round_two_dir.name, "round_002")

    def test_export_public_tile_pack_writes_shareable_metadata_and_images(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = source_ingest_ops.export_public_tile_pack(
                project_path,
                "minimal8@1bit_colored_bg",
                Path(temp_dir) / "public-pack",
                scale=2,
            )

            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            tiles = json.loads((output_dir / "tiles.json").read_text(encoding="utf-8"))
            tile_clusters = json.loads((output_dir / "tile_clusters.json").read_text(encoding="utf-8"))
            source_regions = json.loads((output_dir / "source_regions.json").read_text(encoding="utf-8"))
            source_collections = json.loads((output_dir / "source_collections.json").read_text(encoding="utf-8"))
            constructions = json.loads((output_dir / "constructions.json").read_text(encoding="utf-8"))
            composite_tiles = json.loads((output_dir / "composite_tiles.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["tileset"], "minimal8@1bit_colored_bg")
            self.assertEqual(manifest["family_id"], "minimal8")
            self.assertEqual(manifest["art_convention"]["dominant_anchor"], "bottom_left")
            self.assertEqual(manifest["art_convention"]["dominant_gutter_edges"], ["top", "right"])
            self.assertLess(manifest["art_convention"]["sample_count"], manifest["counts"]["preview_tiles"])
            self.assertEqual(manifest["counts"]["tiles"], len(tiles))
            self.assertEqual(manifest["counts"]["tile_clusters"], len(tile_clusters))
            self.assertEqual(manifest["counts"]["source_regions"], len(source_regions))
            self.assertEqual(manifest["counts"]["source_collections"], len(source_collections))
            self.assertEqual(manifest["counts"]["constructions"], len(constructions))
            self.assertEqual(manifest["counts"]["composite_tiles"], len(composite_tiles))
            self.assertTrue((output_dir / "tiles.csv").exists())
            self.assertTrue((output_dir / "README.md").exists())
            self.assertTrue((output_dir / "images" / "sheet_annotated.png").exists())
            self.assertTrue((output_dir / "images" / "tiles_contact_sheet.png").exists())
            self.assertTrue((output_dir / "images" / "collections_contact_sheet.png").exists())
            self.assertTrue((output_dir / "images" / "constructions_contact_sheet.png").exists())
            self.assertIn("provenance", tiles[0])
            self.assertIn("source_layout", tiles[0])
            self.assertIn("compose", tiles[0])
            sheet_backed_tile = next(tile for tile in tiles if tile["sheet"] is not None)
            self.assertRegex(sheet_backed_tile["provenance"]["physical_ref"], r"^minimal8:\d+,\d+$")
            self.assertRegex(sheet_backed_tile["provenance"]["variant_ref"], r"^minimal8@1bit_colored_bg:\d+,\d+$")
            synthetic_tile = next(tile for tile in tiles if tile["id"] == "minimal8:derived.indoors.bookcase.middle")
            self.assertEqual(synthetic_tile["provenance"]["kind"], "synthetic")
            self.assertIsNone(synthetic_tile["sheet"])
            self.assertIsNone(synthetic_tile["source_layout"])
            table_collection = next(collection for collection in source_collections if collection["id"] == "indoors.table.kit")
            self.assertIn("indoors.table.kit.horizontal_run", table_collection["constructions"])
            horizontal_run = next(construction for construction in constructions if construction["id"] == "indoors.table.kit.horizontal_run")
            self.assertEqual(horizontal_run["kind"], "parametric_run")
            self.assertEqual(horizontal_run["start"]["role"], "horizontal_left_end")
            self.assertEqual(horizontal_run["preview_length"], 4)
            self.assertEqual(horizontal_run["preview"], "images/constructions/indoors_table_kit_horizontal_run.png")
            table_l = next(construction for construction in constructions if construction["id"] == "indoors.table.kit.l_top_left")
            self.assertEqual(table_l["kind"], "fixed")
            self.assertEqual(
                table_l["seam_overrides"],
                [
                    {
                        "cell": {"x": 0, "y": 0},
                        "side": "east",
                        "reason": "Table-leg silhouette intentionally differs across this L-shape contact.",
                    }
                ],
            )
            door = next(composite for composite in composite_tiles if composite["id"] == "indoors.door.grand.closed")
            self.assertEqual(door["kind"], "composite_tile")
            self.assertEqual(door["shape"], {"width": 2, "height": 2})
            self.assertEqual(door["cells"][0][0]["role"], "top_left")
            self.assertEqual(door["cells"][0][0]["tile_id"], "minimal8:architecture:2,10")

    def test_export_public_tile_pack_clears_stale_output_files(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "public-pack"
            source_ingest_ops.export_public_tile_pack(
                project_path,
                "minimal8@1bit_colored_bg",
                output_dir,
                scale=2,
            )
            stale_file = output_dir / "stale.txt"
            stale_file.write_text("stale\n", encoding="utf-8")
            stale_constructions = output_dir / "constructions.json"
            stale_constructions_content = "{}\n"
            stale_constructions.write_text(stale_constructions_content, encoding="utf-8")

            source_ingest_ops.export_public_tile_pack(
                project_path,
                "minimal8@1bit_colored_bg",
                output_dir,
                scale=2,
            )

            self.assertFalse(stale_file.exists())
            # constructions.json is now legitimately present (family has constructions);
            # verify the stale content was cleared rather than persisted.
            if stale_constructions.exists():
                actual = stale_constructions.read_text(encoding="utf-8")
                self.assertNotEqual(actual, stale_constructions_content)

    def test_render_layout_supports_pixel_viewports_for_scene_layouts(self) -> None:
        source_layout_path = ROOT / "prototypes/minimal8-harness/layouts/scene_template_showcase.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            layout = json.loads(source_layout_path.read_text(encoding="utf-8"))
            layout["project"] = str(ROOT / "prototypes/minimal8-harness/project.minimal8.json")
            layout["viewport"] = {
                "x": 64,
                "y": 32,
                "width": 96,
                "height": 64,
                "units": "pixels",
                "scale": 2,
            }
            layout["output"] = "ignored.png"
            layout_path = temp_root / "pixel_viewport_layout.json"
            output_path = temp_root / "pixel_viewport.png"
            _write_json(layout_path, layout)

            rendered_path = harness.render_layout(layout_path, output_path)

            self.assertEqual(rendered_path, output_path)
            self.assertTrue(output_path.exists())
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (192, 128))

    def test_render_layout_supports_entity_op(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        construction_id = "indoors.table.kit.square_2x2"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project = layout_core.LayoutProject(project_path)
            registry = project.tile_library_registry
            assert registry is not None
            stamps = harness.expand_entity_stamps(registry, construction_id, 3, 2, context="test")
            self.assertTrue(stamps, "fixture construction should expand to stamps")

            base_map = {"width": 10, "height": 8, "background": "#00000000"}
            entity_layout = {
                "project": str(project_path),
                "map": base_map,
                "layers": [
                    {"name": "main", "ops": [
                        {"kind": "entity", "construction": construction_id, "x": 3, "y": 2}
                    ]}
                ],
                "output": "ignored.png",
            }
            stamp_layout = {
                "project": str(project_path),
                "map": base_map,
                "layers": [{"name": "main", "ops": list(stamps)}],
                "output": "ignored.png",
            }
            entity_path = temp_root / "entity.json"
            stamp_path = temp_root / "stamp.json"
            _write_json(entity_path, entity_layout)
            _write_json(stamp_path, stamp_layout)

            entity_out = temp_root / "entity.png"
            stamp_out = temp_root / "stamp.png"
            harness.render_layout(entity_path, entity_out)
            harness.render_layout(stamp_path, stamp_out)

            with Image.open(entity_out).convert("RGBA") as rendered, Image.open(stamp_out).convert("RGBA") as expected:
                self.assertEqual(rendered.size, expected.size)
                self.assertEqual(rendered.tobytes(), expected.tobytes())
                self.assertIsNotNone(rendered.getbbox(), "entity op should place visible tiles")

    def test_render_layout_renders_island_overlook(self) -> None:
        layout_path = ROOT / "prototypes/minimal8-harness/layouts/island_overlook.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "island_overlook.png"

            rendered_path = harness.render_layout(layout_path, output_path)

            self.assertEqual(rendered_path, output_path)
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1248, 832))

    def test_render_layout_renders_polychrome_temple_courtyard(self) -> None:
        layout_path = ROOT / "prototypes/minimal8-harness/layouts/polychrome_temple_courtyard.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "polychrome_temple_courtyard.png"

            rendered_path = harness.render_layout(layout_path, output_path)

            self.assertEqual(rendered_path, output_path)
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (960, 640))

    def test_render_layout_rejects_unknown_layer_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            layout_path = Path(temp_dir) / "bad_op.json"
            _write_json(
                layout_path,
                {
                    "project": str(project_path),
                    "map": {"width": 1, "height": 1},
                    "output": "out.png",
                    "layers": [{"name": "terrain", "ops": [{"kind": "mystery"}]}],
                },
            )

            with self.assertRaisesRegex(ValueError, "Unsupported layer operation"):
                harness.render_layout(layout_path)

    def test_render_layout_rejects_unknown_viewport_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            layout_path = Path(temp_dir) / "bad_viewport.json"
            _write_json(
                layout_path,
                {
                    "project": str(project_path),
                    "map": {"width": 1, "height": 1},
                    "output": "out.png",
                    "layers": [{"name": "terrain", "ops": [{"kind": "stamp", "x": 0, "y": 0, "ref": "sample.override"}]}],
                    "viewport": {"x": 0, "y": 0, "width": 8, "height": 8, "units": "frobs"},
                },
            )

            with self.assertRaisesRegex(ValueError, "Unsupported viewport units"):
                harness.render_layout(layout_path)

    def test_query_semantic_catalog_filters_by_region_and_alias_prefix(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"

        results = source_ingest_ops.query_semantic_catalog(
            project_path,
            "minimal8@1bit_colored_bg",
            region="tileset.column_2",
            alias_prefix="indoors.bookcase",
        )

        self.assertEqual(
            [entry["id"] for entry in results],
            [
                "minimal8:terrain:8,15",
                "minimal8:terrain:9,15",
                "minimal8:terrain:10,15",
            ],
        )
        for entry in results:
            self.assertTrue(any(alias.startswith("indoors.bookcase") for alias in entry["aliases"]))

    def test_export_semantic_review_pack_writes_filtered_assets_and_notes(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = source_ingest_ops.export_semantic_review_pack(
                layout_core.LayoutProject(project_path),
                "minimal8@1bit_colored_bg",
                Path(temp_dir) / "semantic-review",
                alias_prefix="indoors.bookcase",
                scale=2,
            )
            payload = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
            index_md = (output_dir / "index.md").read_text(encoding="utf-8")
            review_notes = (output_dir / "review_notes.md").read_text(encoding="utf-8")

            expected_aliases = [
                "indoors.bookcase.single",
                "indoors.bookcase.left",
                "indoors.bookcase.right",
                "indoors.bookcase.middle",
            ]

            self.assertEqual(payload["exported_count"], 4)
            self.assertEqual(payload["unresolved_count"], 0)
            self.assertEqual(
                [entry["primary_alias"] for entry in payload["entries"]],
                expected_aliases,
            )
            self.assertTrue((output_dir / "contact_sheet.png").exists())
            self.assertIn("# Semantic Review Pack", index_md)
            self.assertIn("# Review Notes", review_notes)
            for entry in payload["entries"]:
                self.assertTrue((output_dir / entry["file"]).exists())
            for alias in expected_aliases:
                self.assertIn(alias, index_md)
                self.assertIn(alias, review_notes)

    def test_inspect_tile_edges_falls_back_to_catalog_when_no_architecture_tiles_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, project_path = _make_override_family_and_project(Path(temp_dir))
            project = layout_core.LayoutProject(project_path)
            output_dir = Path(temp_dir) / "tile-edge-inspection"
            output_dir.mkdir()

            source_ingest_ops.inspect_tile_edges(project, "testfam@base", output_dir)
            payload = json.loads((output_dir / "tile_edges.json").read_text(encoding="utf-8"))

            self.assertGreaterEqual(len(payload), 1)
            self.assertTrue(all(entry.get("layer") != "architecture" for entry in payload))
            self.assertTrue(all("edge_contact_score" in entry for entry in payload))
            self.assertTrue((output_dir / "seam_candidate_tiles.png").exists())

    def test_inspect_family_exports_catalog_and_visual_diagnostics(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = source_ingest_ops.inspect_family(
                layout_core.LayoutProject(project_path),
                "minimal8@1bit_colored_bg",
                Path(temp_dir) / "family-inspection",
            )
            file_names = {path.name for path in output_dir.iterdir()}
            catalog = json.loads((output_dir / "catalog.json").read_text(encoding="utf-8"))
            tile_edges = json.loads((output_dir / "tile_edges.json").read_text(encoding="utf-8"))
            coverage = json.loads((output_dir / "source_layout.coverage.json").read_text(encoding="utf-8"))
            source_layout_guide = Image.open(output_dir / "source_layout.guide.png").convert("RGBA")
            sheet_grid = Image.open(output_dir / "sheet_grid.png").convert("RGBA")

            self.assertTrue(
                {
                    "catalog.json",
                    "sheet_grid.png",
                    "non_empty_tiles.png",
                    "tile_edges.json",
                    "seam_candidate_tiles.png",
                    "patterns.json",
                    "source_layout.json",
                    "source_layout.guide.png",
                    "source_layout.detected.json",
                    "source_layout.coverage.json",
                    "clusters.json",
                    "semantic_catalog.json",
                }.issubset(file_names)
            )
            self.assertGreater(len(catalog), 0)
            self.assertGreater(len(tile_edges), 0)
            self.assertTrue(coverage["complete"])
            self.assertGreater(source_layout_guide.width, sheet_grid.width)
            self.assertGreater(source_layout_guide.height, sheet_grid.height)
            guide_pixels = source_layout_guide.load()
            assert guide_pixels is not None
            self.assertTrue(
                any(
                    guide_pixels[x, y] == source_ingest_ops.SOURCE_LAYOUT_REGION_COLOURS[0]
                    for y in range(source_layout_guide.height)
                    for x in range(source_layout_guide.width)
                )
            )
            self.assertTrue(
                any(
                    guide_pixels[x, y] == source_ingest_ops.SOURCE_LAYOUT_CLUSTER_COLOUR
                    for y in range(source_layout_guide.height)
                    for x in range(source_layout_guide.width)
                )
            )

    def test_export_tiled_kit_writes_tiled_ready_assets_and_catalogues(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = source_ingest_ops.export_tiled_kit(
                project_path,
                "minimal8@1bit_colored_bg",
                Path(temp_dir) / "tiled-kit",
            )

            starter_map = json.loads((output_dir / "starter_c64_room.tmj").read_text(encoding="utf-8"))
            cells_catalog = json.loads((output_dir / "cells_catalog.json").read_text(encoding="utf-8"))
            patterns_catalog = json.loads((output_dir / "patterns_catalog.json").read_text(encoding="utf-8"))
            semantic_catalog = json.loads((output_dir / "semantic_catalog.json").read_text(encoding="utf-8"))

            self.assertTrue((output_dir / "cells.tsx").exists())
            self.assertTrue((output_dir / "patterns.tsx").exists())
            self.assertTrue((output_dir / "README.md").exists())
            self.assertTrue((output_dir / "cells").is_dir())
            self.assertTrue((output_dir / "patterns").is_dir())
            self.assertEqual(starter_map["tilewidth"], 8)
            self.assertEqual(starter_map["tileheight"], 8)
            self.assertEqual(len(starter_map["tilesets"]), 2)
            self.assertEqual(starter_map["tilesets"][1]["firstgid"], 1089)
            self.assertEqual(len(cells_catalog), 1088)
            self.assertGreater(len(patterns_catalog), 0)
            self.assertGreater(len(semantic_catalog), 0)

    def test_export_tiled_kit_clears_stale_outputs(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "tiled-kit"
            source_ingest_ops.export_tiled_kit(project_path, "minimal8@1bit_colored_bg", output_dir)
            (output_dir / "tiles").mkdir()
            stale_cell = output_dir / "cells" / "stale.txt"
            stale_cell.write_text("stale\n", encoding="utf-8")
            stale_readme = output_dir / "README.md"
            stale_readme.write_text("stale\n", encoding="utf-8")

            source_ingest_ops.export_tiled_kit(project_path, "minimal8@1bit_colored_bg", output_dir)

            self.assertFalse((output_dir / "tiles").exists())
            self.assertFalse(stale_cell.exists())
            self.assertIn("# Tiled Kit", stale_readme.read_text(encoding="utf-8"))

    def test_bootstrap_project_writes_grid_aligned_project_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            sheet_path = temp_root / "sheet.png"
            Image.new("RGBA", (16, 8), (1, 2, 3, 255)).save(sheet_path)
            output_path = temp_root / "project.json"

            written_path = harness.bootstrap_project(
                sheet_path=sheet_path,
                output_path=output_path,
                tile_width=8,
                tile_height=8,
                transparent="none",
                tileset_id=None,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(written_path, output_path.resolve())
            self.assertEqual(payload["grid"], {"tile_width": 8, "tile_height": 8})
            self.assertIn("sheet", payload["tilesets"])
            self.assertEqual(payload["tilesets"]["sheet"]["regions"]["all"], {"x": 0, "y": 0, "width": 2, "height": 1})
            self.assertEqual(payload["patterns"], {})
            self.assertNotIn("metatiles", payload)

    def test_bootstrap_project_rejects_non_divisible_sheet_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            sheet_path = temp_root / "sheet.png"
            Image.new("RGBA", (10, 8), (1, 2, 3, 255)).save(sheet_path)

            with self.assertRaisesRegex(ValueError, "is not divisible by tile size"):
                harness.bootstrap_project(
                    sheet_path=sheet_path,
                    output_path=temp_root / "project.json",
                    tile_width=8,
                    tile_height=8,
                    transparent="none",
                    tileset_id="custom",
                )

    def test_main_query_semantic_prints_filtered_json(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
        stdout = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "harness.py",
                "query-semantic",
                str(project_path),
                "--tileset",
                "minimal8@1bit_colored_bg",
                "--alias-prefix",
                "indoors.bookcase",
                "--limit",
                "2",
            ],
        ), redirect_stdout(stdout):
            harness.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(len(payload), 2)
        self.assertTrue(all(any(alias.startswith("indoors.bookcase") for alias in entry["aliases"]) for entry in payload))

    def test_characters_project_loads_bridged_family_without_runtime_scene_libraries(self) -> None:
        project = layout_core.LayoutProject(
            ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        )

        self.assertEqual(project.default_tileset_id(), "minimal8.characters@2bit_colored")
        family = project.source_family_for_tileset(project.default_tileset_id())
        self.assertIsNotNone(family)
        assert family is not None
        self.assertEqual(family.family_id, "minimal8.characters")
        self.assertEqual(family.default_variant_id, "2bit_colored")
        self.assertEqual(family.tile_width, 8)
        self.assertEqual(family.tile_height, 8)
        self.assertIsNotNone(family.source_layout)

        shared_body_ref = PlaceableRef(kind="composite_tile", id="head_study.character.shared_body")
        self.assertIsNone(family.lookup_construction("head_study.character.shared_body"))
        self.assertIsNotNone(family.lookup_placeable(shared_body_ref))

        attachment_sets = family.attachment_sets_for_placeable(shared_body_ref)
        self.assertEqual(len(attachment_sets), 1)
        attachment_set = attachment_sets[0]
        self.assertEqual(attachment_set.param, "head")
        self.assertEqual(
            tuple(sorted(attachment_set.variants.keys())),
            (
                "first_full",
                "shared_alt",
                "spare_01",
                "spare_02",
                "spare_03",
                "spare_04",
                "spare_05",
            ),
        )

        template = family.entity_template_for_placeable(shared_body_ref)
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.id, "head_study.character.shared_body")
        self.assertEqual(template.placeable_kind, "composite_tile")
        self.assertEqual(template.placeable_id, "head_study.character.shared_body")
        self.assertIsNone(template.construction_id)
        self.assertEqual(len(template.attachment_sets), 1)
        self.assertEqual(template.attachment_sets[0].param, "head")
        self.assertTrue(template.attachment_sets[0].required)
        self.assertIsNone(template.attachment_sets[0].default_variant_id)
        self.assertEqual(template.attachment_sets[0].canvas.width, 2)
        self.assertEqual(template.attachment_sets[0].canvas.height, 2)

        self.assertIsNone(family.entity_template_for_placeable(PlaceableRef(kind="composite_tile", id="head_study.head.shared_alt")))

    def test_characters_head_attachment_expands_requested_variant(self) -> None:
        project = layout_core.LayoutProject(
            ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        )
        tile_library = project.tile_library_unit_for_tileset("minimal8.characters@2bit_colored")
        self.assertIsNotNone(tile_library)
        assert tile_library is not None

        stamps = harness.expand_placeable_stamps(
            tile_library,
            PlaceableRef(kind="composite_tile", id="head_study.character.shared_body"),
            x=5,
            y=7,
            context="test characters shared body",
            params={"head": "shared_alt"},
        )

        refs = [cast(str, stamp["ref"]) for stamp in stamps]
        self.assertEqual(len(stamps), 6)
        self.assertEqual(
            refs,
            [
                "minimal8.characters:head_study.shared_body.bottom_left",
                "minimal8.characters:head_study.shared_body.bottom_right",
                "minimal8.characters:head_study.head.shared_alt.top_left",
                "minimal8.characters:head_study.head.shared_alt.top_right",
                "minimal8.characters:head_study.head.shared_alt.bottom_left",
                "minimal8.characters:head_study.head.shared_alt.bottom_right",
            ],
        )
        self.assertEqual(
            [(stamp["x"], stamp["y"]) for stamp in stamps],
            [(5, 9), (6, 9), (5, 7), (6, 7), (5, 8), (6, 8)],
        )

    def test_characters_head_attachment_requires_explicit_variant(self) -> None:
        project = layout_core.LayoutProject(
            ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        )
        tile_library = project.tile_library_unit_for_tileset("minimal8.characters@2bit_colored")
        self.assertIsNotNone(tile_library)
        assert tile_library is not None

        with self.assertRaisesRegex(ValueError, "requires attachment param 'head'"):
            harness.expand_placeable_stamps(
                tile_library,
                PlaceableRef(kind="composite_tile", id="head_study.character.shared_body"),
                x=0,
                y=0,
                context="test characters shared body",
            )

    def test_characters_head_attachment_rejects_unknown_variant(self) -> None:
        project = layout_core.LayoutProject(
            ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        )
        tile_library = project.tile_library_unit_for_tileset("minimal8.characters@2bit_colored")
        self.assertIsNotNone(tile_library)
        assert tile_library is not None

        with self.assertRaisesRegex(ValueError, "requested unknown variant 'missing'"):
            harness.expand_placeable_stamps(
                tile_library,
                PlaceableRef(kind="composite_tile", id="head_study.character.shared_body"),
                x=0,
                y=0,
                context="test characters shared body",
                params={"head": "missing"},
            )

    def test_characters_head_attachment_rejects_empty_variant_param(self) -> None:
        project = layout_core.LayoutProject(
            ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        )
        tile_library = project.tile_library_unit_for_tileset("minimal8.characters@2bit_colored")
        self.assertIsNotNone(tile_library)
        assert tile_library is not None

        with self.assertRaisesRegex(ValueError, "must be a non-empty string"):
            harness.expand_placeable_stamps(
                tile_library,
                PlaceableRef(kind="composite_tile", id="head_study.character.shared_body"),
                x=0,
                y=0,
                context="test characters shared body",
                params={"head": ""},
            )

    def test_export_public_tile_pack_includes_attachment_metadata_in_entity_templates(self) -> None:
        project_path = ROOT / "prototypes/minimal8-harness/project.minimal8.characters.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = source_ingest_ops.export_public_tile_pack(
                project_path,
                "minimal8.characters@2bit_colored",
                Path(temp_dir) / "characters-public-pack",
                scale=2,
            )

            entity_templates = json.loads((output_dir / "entity_templates.json").read_text(encoding="utf-8"))
            shared_body = next(
                entry for entry in entity_templates if entry["id"] == "head_study.character.shared_body"
            )

            composite_tiles = json.loads((output_dir / "composite_tiles.json").read_text(encoding="utf-8"))
            exported_shared_body = next(
                entry for entry in composite_tiles if entry["id"] == "head_study.character.shared_body"
            )

            self.assertEqual(exported_shared_body["kind"], "composite_tile")
            self.assertEqual(exported_shared_body["shape"], {"width": 2, "height": 3})
            self.assertEqual(shared_body["placeable_kind"], "composite_tile")
            self.assertEqual(shared_body["placeable_id"], "head_study.character.shared_body")
            self.assertNotIn("construction_id", shared_body)
            self.assertEqual(len(shared_body["attachment_sets"]), 1)
            self.assertEqual(shared_body["attachment_sets"][0]["param"], "head")
            self.assertTrue(shared_body["attachment_sets"][0]["required"])
            self.assertIsNone(shared_body["attachment_sets"][0]["default_variant_id"])

if __name__ == "__main__":
    unittest.main()
