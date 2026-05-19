from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from source_manifests import GridBounds, GridSize, load_logical_tilesheet_manifest, load_tile_pack_manifest, load_tileset_manifest


@dataclass(frozen=True)
class SourceFixturePaths:
    root: Path
    pack_path: Path
    tileset_path: Path
    tilesheet_path: Path
    source_layout_path: Path
    compatibility_root: Path
    compatibility_tiles_path: Path
    compatibility_aliases_path: Path
    compatibility_clusters_path: Path
    art_dir: Path

def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_sheet(path: Path, *, columns: int, rows: int) -> None:
    Image.new("RGBA", (columns * 8, rows * 8), (255, 255, 255, 255)).save(path)


def write_misaligned_sheet(path: Path, *, width_px: int, height_px: int) -> None:
    Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255)).save(path)


def make_source_pack_fixture(root: Path) -> SourceFixturePaths:
    root.mkdir(parents=True, exist_ok=True)
    tilesets_dir = root / "tilesets"
    tilesheets_dir = root / "tilesheets"
    art_dir = root / "art"
    ingestion_dir = root / "ingestion"
    compatibility_root = root / "legacy-family"
    tilesets_dir.mkdir()
    tilesheets_dir.mkdir()
    art_dir.mkdir()
    ingestion_dir.mkdir()
    compatibility_root.mkdir()

    pack_path = root / "pack.json"
    tileset_path = tilesets_dir / "base.json"
    tilesheet_path = tilesheets_dir / "overworld.json"
    source_layout_path = ingestion_dir / "overworld.json"
    compatibility_tiles_path = compatibility_root / "tiles.json"
    compatibility_aliases_path = compatibility_root / "aliases.json"
    compatibility_clusters_path = compatibility_root / "clusters.json"

    write_sheet(art_dir / "overworld.base.png", columns=4, rows=2)
    write_sheet(art_dir / "overworld.bg.top-row.png", columns=4, rows=1)
    write_json(
        source_layout_path,
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 4, "height": 2},
            "regions": [{"id": "overworld.region", "bounds": {"x": 0, "y": 0, "width": 4, "height": 2}}],
            "clusters": [
                {
                    "id": "overworld.region.cluster_01",
                    "source_region_id": "overworld.region",
                    "bounds": {"x": 0, "y": 0, "width": 4, "height": 2},
                }
            ],
            "collections": [],
        },
    )
    write_json(
        compatibility_clusters_path,
        [
            {
                "id": "overworld.cluster",
                "scope": "family",
                "members": ["demo.overworld:all:0,0"],
            }
        ],
    )
    write_json(
        compatibility_tiles_path,
        [
            {
                "id": "demo.overworld:all:0,0",
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "terrain",
                "category": "ground",
                "transparent": False,
                "cluster_ids": ["overworld.cluster"],
                "source_group": "overworld.ground",
                "meaning": "Ground tile.",
                "meaning_confidence": "confirmed",
            }
        ],
    )
    write_json(
        compatibility_aliases_path,
        {"overworld.ground": "demo.overworld:all:0,0"},
    )

    write_json(
        pack_path,
        {
            "pack_id": "demo-pack",
            "title": "Demo Pack",
            "grid": {"tile_width": 8, "tile_height": 8},
            "provenance": {
                "author": "Demo Artist",
                "licence": "CC0",
                "source_links": ["https://example.test/demo-pack"],
                "naming_conventions": ["tileset ids use demo.<module>"],
                "notes": ["Pack provenance note."],
            },
            "ingest_rules": {
                "tileset_discovery": ["one manifest per module"],
                "tilesheet_classification": ["overworld comes before interiors"],
                "notes": ["Pack ingest rule note."],
            },
            "render_traits": {
                "occupancy_style": "full_cell",
                "gutter_policy": "none",
            },
            "notes": ["Pack-level source note."],
            "tilesets": [
                {
                    "tileset_id": "demo.base",
                    "manifest": "tilesets/base.json",
                }
            ],
        },
    )
    write_json(
        tileset_path,
        {
            "tileset_id": "demo.base",
            "title": "Base tileset",
            "module_context": [
                {"axis_id": "theme", "value_id": "default"},
                {"axis_id": "domain", "value_id": "world", "label": "World"},
            ],
            "render_traits": {"background_treatment": "transparent"},
            "logical_tilesheets": [
                {
                    "tilesheet_id": "overworld",
                    "manifest": "../tilesheets/overworld.json",
                }
            ],
        },
    )
    write_json(
        tilesheet_path,
        {
            "tilesheet_id": "overworld",
            "title": "Overworld atlas",
            "bounds": {"x": 0, "y": 0, "width": 4, "height": 2},
            "default_variant_id": "base",
            "source_layout": "../ingestion/overworld.json",
            "render_traits": {"alignment_origin": "bottom_left"},
            "notes": ["Logical tilesheet note."],
            "compatibility_family": {
                "root": "../legacy-family",
                "family_id": "demo.overworld",
                "tiles": "tiles.json",
                "aliases": "aliases.json",
                "clusters": "clusters.json",
                "render_step_width": 8,
                "render_step_height": 8,
                "siblings_share_semantics": True,
                "notes": ["Compatibility bridge note."],
            },
            "render_variants": [
                {
                    "variant_id": "base",
                    "sheet": "../art/overworld.base.png",
                    "coverage": {"mode": "full"},
                    "transparent": "top_left",
                    "render_traits": {"occlusion_mode": "solid_wall"},
                },
                {
                    "variant_id": "bg",
                    "sheet": "../art/overworld.bg.top-row.png",
                    "coverage": {
                        "mode": "sparse",
                        "bounds": {"x": 0, "y": 0, "width": 4, "height": 1},
                    },
                    "background_mode": "solid",
                },
            ],
        },
    )
    return SourceFixturePaths(
        root=root,
        pack_path=pack_path,
        tileset_path=tileset_path,
        tilesheet_path=tilesheet_path,
        source_layout_path=source_layout_path,
        compatibility_root=compatibility_root,
        compatibility_tiles_path=compatibility_tiles_path,
        compatibility_aliases_path=compatibility_aliases_path,
        compatibility_clusters_path=compatibility_clusters_path,
        art_dir=art_dir,
    )


class SourceManifestLoadTests(unittest.TestCase):
    def test_load_tile_pack_manifest_builds_hierarchy_and_resolves_render_trait_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))

            pack = load_tile_pack_manifest(fixture.pack_path)

            self.assertEqual(pack.id, "demo-pack")
            self.assertEqual(pack.grid, GridSize(tile_width=8, tile_height=8))
            self.assertEqual(pack.provenance.author, "Demo Artist")
            self.assertEqual(pack.provenance.licence, "CC0")
            self.assertEqual(pack.provenance.source_links, ("https://example.test/demo-pack",))
            self.assertEqual(pack.ingest_rules.tileset_discovery, ("one manifest per module",))
            self.assertEqual(pack.render_traits.occupancy_style, "full_cell")
            self.assertEqual(pack.declared_render_traits.occupancy_style, "full_cell")

            tileset = pack.tileset("demo.base")
            self.assertEqual(tuple(tileset.module_context.keys()), ("theme", "domain"))
            self.assertEqual(tileset.module_context["theme"].value_id, "default")
            self.assertEqual(tileset.declared_render_traits.background_treatment, "transparent")
            self.assertEqual(tileset.render_traits.occupancy_style, "full_cell")
            self.assertEqual(tileset.render_traits.background_treatment, "transparent")

            tilesheet = tileset.logical_tilesheet("overworld")
            self.assertEqual(tilesheet.default_variant_id, "base")
            self.assertIsNotNone(tilesheet.source_layout_path)
            assert tilesheet.source_layout_path is not None
            self.assertEqual(tilesheet.source_layout_path.name, "overworld.json")
            self.assertIsNotNone(tilesheet.compatibility_family)
            assert tilesheet.compatibility_family is not None
            self.assertEqual(tilesheet.compatibility_family.family_id, "demo.overworld")
            self.assertEqual(tilesheet.compatibility_family.paths.root, fixture.compatibility_root.resolve())
            self.assertEqual(tilesheet.compatibility_family.paths.tiles_path, fixture.compatibility_tiles_path.resolve())
            self.assertEqual(tilesheet.compatibility_family.paths.aliases_path, fixture.compatibility_aliases_path.resolve())
            self.assertEqual(tilesheet.compatibility_family.paths.clusters_path, fixture.compatibility_clusters_path.resolve())
            self.assertEqual(tilesheet.compatibility_family.render_step_width, 8)
            self.assertEqual(tilesheet.compatibility_family.render_step_height, 8)
            self.assertTrue(tilesheet.compatibility_family.siblings_share_semantics)
            self.assertEqual(tilesheet.declared_render_traits.alignment_origin, "bottom_left")
            self.assertEqual(tilesheet.render_traits.occupancy_style, "full_cell")
            self.assertEqual(tilesheet.render_traits.background_treatment, "transparent")
            self.assertEqual(tilesheet.render_traits.alignment_origin, "bottom_left")

            base_variant = tilesheet.variant("base")
            self.assertEqual(base_variant.declared_render_traits.occlusion_mode, "solid_wall")
            self.assertEqual(base_variant.render_traits.occupancy_style, "full_cell")
            self.assertEqual(base_variant.render_traits.background_treatment, "transparent")
            self.assertEqual(base_variant.render_traits.alignment_origin, "bottom_left")
            self.assertEqual(base_variant.render_traits.occlusion_mode, "solid_wall")

            sparse_variant = tilesheet.variant("bg")
            self.assertEqual(sparse_variant.coverage.mode, "sparse")
            self.assertEqual(sparse_variant.coverage.areas, (GridBounds(x=0, y=0, width=4, height=1),))
            self.assertEqual(sparse_variant.render_traits.occupancy_style, "full_cell")
            self.assertEqual(sparse_variant.render_traits.background_treatment, "transparent")
            self.assertEqual(sparse_variant.render_traits.alignment_origin, "bottom_left")

    def test_load_tile_pack_manifest_rejects_invalid_manifest_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, str, list[object], object, str]] = [
                (
                    "pack_id",
                    "pack",
                    ["pack_id"],
                    "Demo Pack",
                    r"pack_id must match",
                ),
                (
                    "tileset_ref_id",
                    "pack",
                    ["tilesets", 0, "tileset_id"],
                    "Demo Base",
                    r"tileset_id must match",
                ),
                (
                    "tileset_manifest_id",
                    "tileset",
                    ["tileset_id"],
                    "Demo Base",
                    r"tileset_id must match",
                ),
                (
                    "module_axis_id",
                    "tileset",
                    ["module_context", 0, "axis_id"],
                    "Theme!",
                    r"axis_id must match",
                ),
                (
                    "module_value_id",
                    "tileset",
                    ["module_context", 0, "value_id"],
                    "Default Theme",
                    r"value_id must match",
                ),
                (
                    "tilesheet_manifest_id",
                    "tilesheet",
                    ["tilesheet_id"],
                    "Overworld",
                    r"tilesheet_id must match",
                ),
                (
                    "variant_id",
                    "tilesheet",
                    ["render_variants", 0, "variant_id"],
                    "Base Variant",
                    r"variant_id must match",
                ),
                (
                    "default_variant_id",
                    "tilesheet",
                    ["default_variant_id"],
                    "Base Variant",
                    r"default_variant_id must match",
                ),
                (
                    "compatibility_family_id",
                    "tilesheet",
                    ["compatibility_family", "family_id"],
                    "Demo Overworld",
                    r"family_id must match",
                ),
            ]

            for label, target, keys, value, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    path = {
                        "pack": fixture.pack_path,
                        "tileset": fixture.tileset_path,
                        "tilesheet": fixture.tilesheet_path,
                    }[target]
                    self._set_json_value(path, keys, value)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_tile_pack_manifest(fixture.pack_path)

    def test_load_tile_pack_manifest_reports_missing_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            payload = cast(dict[str, object], read_json(fixture.pack_path))
            tilesets = cast(list[object], payload["tilesets"])
            cast(dict[str, object], tilesets[0]).pop("manifest")
            write_json(fixture.pack_path, payload)

            with self.assertRaisesRegex(ValueError, r"is missing required keys: manifest"):
                load_tile_pack_manifest(fixture.pack_path)

    def test_load_tileset_manifest_rejects_duplicate_module_context_axes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            payload = cast(dict[str, object], read_json(fixture.tileset_path))
            payload["module_context"] = [
                {"axis_id": "theme", "value_id": "default"},
                {"axis_id": "theme", "value_id": "arctic"},
            ]
            write_json(fixture.tileset_path, payload)

            with self.assertRaisesRegex(ValueError, r"module_context declares axis_id 'theme' more than once"):
                load_tileset_manifest(fixture.tileset_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_duplicate_render_variant_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            payload = cast(dict[str, object], read_json(fixture.tilesheet_path))
            render_variants = cast(list[object], payload["render_variants"])
            duplicate = dict(cast(dict[str, object], render_variants[0]))
            render_variants.append(duplicate)
            write_json(fixture.tilesheet_path, payload)

            with self.assertRaisesRegex(ValueError, r"Duplicate render variant_id"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_tileset_manifest_rejects_duplicate_logical_tilesheet_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            payload = cast(dict[str, object], read_json(fixture.tileset_path))
            logical_tilesheets = cast(list[object], payload["logical_tilesheets"])
            duplicate = dict(cast(dict[str, object], logical_tilesheets[0]))
            logical_tilesheets.append(duplicate)
            write_json(fixture.tileset_path, payload)

            with self.assertRaisesRegex(ValueError, r"Duplicate logical tilesheet_id"):
                load_tileset_manifest(fixture.tileset_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_tile_pack_manifest_rejects_duplicate_tileset_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            payload = cast(dict[str, object], read_json(fixture.pack_path))
            tilesets = cast(list[object], payload["tilesets"])
            duplicate = dict(cast(dict[str, object], tilesets[0]))
            tilesets.append(duplicate)
            write_json(fixture.pack_path, payload)

            with self.assertRaisesRegex(ValueError, r"Duplicate tileset_id"):
                load_tile_pack_manifest(fixture.pack_path)

    def test_parent_references_must_match_child_manifest_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            tileset_payload = cast(dict[str, object], read_json(fixture.tileset_path))
            logical_tilesheets = cast(list[object], tileset_payload["logical_tilesheets"])
            cast(dict[str, object], logical_tilesheets[0])["tilesheet_id"] = "other-overworld"
            write_json(fixture.tileset_path, tileset_payload)

            with self.assertRaisesRegex(ValueError, r"expected id 'other-overworld', but manifest declares 'overworld'"):
                load_tileset_manifest(fixture.tileset_path, grid=GridSize(tile_width=8, tile_height=8))

            fixture = make_source_pack_fixture(Path(temp_dir) / "tileset-mismatch")
            pack_payload = cast(dict[str, object], read_json(fixture.pack_path))
            tilesets = cast(list[object], pack_payload["tilesets"])
            cast(dict[str, object], tilesets[0])["tileset_id"] = "demo.other"
            write_json(fixture.pack_path, pack_payload)

            with self.assertRaisesRegex(ValueError, r"expected id 'demo.other', but manifest declares 'demo.base'"):
                load_tile_pack_manifest(fixture.pack_path)

    def test_load_logical_tilesheet_manifest_rejects_unknown_default_variant_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(fixture.tilesheet_path, ["default_variant_id"], "missing")

            with self.assertRaisesRegex(ValueError, r"default_variant_id 'missing' is not defined by render_variants"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_full_coverage_with_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(
                fixture.tilesheet_path,
                ["render_variants", 0, "coverage"],
                {"mode": "full", "bounds": {"x": 0, "y": 0, "width": 4, "height": 2}},
            )

            with self.assertRaisesRegex(ValueError, r"are not allowed when mode is 'full'"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_invalid_coverage_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "coverage"], {"mode": "partial"})

            with self.assertRaisesRegex(ValueError, r"mode must be 'full' or 'sparse'"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_invalid_sparse_coverage_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, object, str]] = [
                (
                    "full_with_areas",
                    {"mode": "full", "areas": [{"x": 0, "y": 0, "width": 1, "height": 1}]},
                    r"are not allowed when mode is 'full'",
                ),
                (
                    "sparse_with_bounds_and_areas",
                    {
                        "mode": "sparse",
                        "bounds": {"x": 0, "y": 0, "width": 4, "height": 1},
                        "areas": [{"x": 0, "y": 0, "width": 1, "height": 1}],
                    },
                    r"cannot define both bounds and areas",
                ),
                (
                    "sparse_with_neither",
                    {"mode": "sparse"},
                    r"\.bounds or .*\.areas is required when mode is 'sparse'",
                ),
                (
                    "sparse_with_empty_areas",
                    {"mode": "sparse", "areas": []},
                    r"areas must define at least one entry",
                ),
            ]

            for label, coverage, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    self._set_json_value(fixture.tilesheet_path, ["render_variants", 1, "coverage"], coverage)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_top_level_loaders_reject_empty_required_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], None], Callable[[SourceFixturePaths], object], str]] = [
                (
                    "render_variants",
                    lambda fixture: self._set_json_value(fixture.tilesheet_path, ["render_variants"], []),
                    lambda fixture: load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"render_variants must define at least one entry",
                ),
                (
                    "logical_tilesheets",
                    lambda fixture: self._set_json_value(fixture.tileset_path, ["logical_tilesheets"], []),
                    lambda fixture: load_tileset_manifest(fixture.tileset_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"logical_tilesheets must define at least one entry",
                ),
                (
                    "tilesets",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["tilesets"], []),
                    lambda fixture: load_tile_pack_manifest(fixture.pack_path),
                    r"tilesets must define at least one entry",
                ),
            ]

            for label, mutate, load_one, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_one(fixture)

    def test_load_logical_tilesheet_manifest_allows_disjoint_sparse_areas_on_full_size_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            write_sheet(fixture.art_dir / "overworld.bg.full.png", columns=4, rows=2)
            self._set_json_value(fixture.tilesheet_path, ["render_variants", 1, "sheet"], "../art/overworld.bg.full.png")
            self._set_json_value(
                fixture.tilesheet_path,
                ["render_variants", 1, "coverage"],
                {
                    "mode": "sparse",
                    "areas": [
                        {"x": 0, "y": 0, "width": 1, "height": 1},
                        {"x": 3, "y": 1, "width": 1, "height": 1},
                    ],
                },
            )

            tilesheet = load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

            self.assertEqual(
                tilesheet.variant("bg").coverage.areas,
                (
                    GridBounds(x=0, y=0, width=1, height=1),
                    GridBounds(x=3, y=1, width=1, height=1),
                ),
            )

    def test_load_logical_tilesheet_manifest_requires_explicit_sparse_coverage_for_smaller_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "sheet"], "../art/overworld.bg.top-row.png")

            with self.assertRaisesRegex(ValueError, r"declare explicit sparse coverage instead"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_sparse_coverage_outside_logical_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(
                fixture.tilesheet_path,
                ["render_variants", 1, "coverage"],
                {
                    "mode": "sparse",
                    "areas": [
                        {"x": 0, "y": 0, "width": 1, "height": 1},
                        {"x": 3, "y": 0, "width": 2, "height": 1},
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, r"must stay inside logical bounds"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_sparse_sheet_dimension_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            self._set_json_value(
                fixture.tilesheet_path,
                ["render_variants", 1, "coverage"],
                {
                    "mode": "sparse",
                    "areas": [
                        {"x": 0, "y": 0, "width": 1, "height": 1},
                        {"x": 3, "y": 1, "width": 1, "height": 1},
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, r"must match either logical bounds 4x2 or a single declared sparse area"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_misaligned_sheet_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            write_misaligned_sheet(fixture.art_dir / "misaligned.png", width_px=30, height_px=16)
            self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "sheet"], "../art/misaligned.png")

            with self.assertRaisesRegex(ValueError, r"is not aligned to 8x8 tiles"):
                load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_invalid_source_layout_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, str, str]] = [
                ("missing", "../ingestion/missing.json", r"source_layout path does not exist"),
                ("directory", "../ingestion", r"source_layout is not a regular file"),
            ]

            for label, source_layout, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    self._set_json_value(fixture.tilesheet_path, ["source_layout"], source_layout)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_rejects_invalid_compatibility_family_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], None], str]] = [
                (
                    "missing_root",
                    lambda fixture: self._set_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "root"],
                        "../missing-legacy-family",
                    ),
                    r"compatibility_family\.root path does not exist",
                ),
                (
                    "root_not_directory",
                    lambda fixture: self._set_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "root"],
                        "../legacy-family/tiles.json",
                    ),
                    r"compatibility_family\.root is not a directory",
                ),
                (
                    "missing_tiles",
                    lambda fixture: self._set_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "tiles"],
                        "missing-tiles.json",
                    ),
                    r"compatibility_family\.tiles path does not exist",
                ),
                (
                    "missing_aliases_key",
                    lambda fixture: self._delete_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "aliases"],
                    ),
                    r"compatibility_family is missing required keys: aliases",
                ),
                (
                    "siblings_share_semantics_not_bool",
                    lambda fixture: self._set_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "siblings_share_semantics"],
                        "yes",
                    ),
                    r"siblings_share_semantics must be a boolean",
                ),
            ]

            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_load_logical_tilesheet_manifest_treats_source_layout_as_opaque_file_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            fixture.source_layout_path.write_text("opaque source layout payload\n", encoding="utf-8")

            tilesheet = load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

            self.assertEqual(tilesheet.source_layout_path, fixture.source_layout_path.resolve())

    def test_load_logical_tilesheet_manifest_wraps_unreadable_image_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], None], str]] = [
                (
                    "missing",
                    lambda fixture: self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "sheet"], "../art/missing.png"),
                    r"could not read image",
                ),
                (
                    "corrupt",
                    lambda fixture: self._make_corrupt_image_fixture(fixture),
                    r"could not read image",
                ),
            ]

            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

    def test_numeric_validation_rejects_zero_negative_and_non_integer_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], None], Callable[[SourceFixturePaths], object], str]] = [
                (
                    "zero_tile_width",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["grid", "tile_width"], 0),
                    lambda fixture: load_tile_pack_manifest(fixture.pack_path),
                    r"tile_width must be > 0",
                ),
                (
                    "negative_bounds_x",
                    lambda fixture: self._set_json_value(fixture.tilesheet_path, ["bounds", "x"], -1),
                    lambda fixture: load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"bounds.x must be >= 0",
                ),
                (
                    "non_integer_tile_width",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["grid", "tile_width"], "8"),
                    lambda fixture: load_tile_pack_manifest(fixture.pack_path),
                    r"tile_width must be an integer",
                ),
                (
                    "non_integer_bounds_x",
                    lambda fixture: self._set_json_value(fixture.tilesheet_path, ["bounds", "x"], "0"),
                    lambda fixture: load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"bounds.x must be an integer",
                ),
                (
                    "zero_compatibility_render_step_width",
                    lambda fixture: self._set_json_value(fixture.tilesheet_path, ["compatibility_family", "render_step_width"], 0),
                    lambda fixture: load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"render_step_width must be > 0",
                ),
                (
                    "non_integer_compatibility_render_step_width",
                    lambda fixture: self._set_json_value(
                        fixture.tilesheet_path,
                        ["compatibility_family", "render_step_width"],
                        "8",
                    ),
                    lambda fixture: load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8)),
                    r"render_step_width must be an integer",
                ),
            ]

            for label, mutate, load_one, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_one(fixture)

    def test_load_tile_pack_manifest_rejects_malformed_pack_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], None], str]] = [
                (
                    "provenance_not_mapping",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["provenance"], "oops"),
                    r"provenance must be a JSON object",
                ),
                (
                    "provenance_source_links_not_array",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["provenance", "source_links"], "https://example.test"),
                    r"provenance\.source_links must be a JSON array",
                ),
                (
                    "ingest_rules_not_mapping",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["ingest_rules"], "oops"),
                    r"ingest_rules must be a JSON object",
                ),
                (
                    "ingest_rules_tilesheet_classification_not_array",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["ingest_rules", "tilesheet_classification"], "oops"),
                    r"ingest_rules\.tilesheet_classification must be a JSON array",
                ),
                (
                    "notes_not_array",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["notes"], "oops"),
                    r"notes must be a JSON array",
                ),
                (
                    "notes_non_string",
                    lambda fixture: self._set_json_value(fixture.pack_path, ["notes"], [123]),
                    r"notes\[0\] must be a non-empty string",
                ),
            ]

            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_tile_pack_manifest(fixture.pack_path)

    def test_load_tile_pack_manifest_wraps_invalid_json_manifest_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[SourceFixturePaths], object]]] = [
                (
                    "invalid_json",
                    lambda fixture: fixture.pack_path.write_text("{not valid json", encoding="utf-8"),
                ),
                (
                    "invalid_utf8",
                    lambda fixture: fixture.pack_path.write_bytes(b"\xff\xfe\x00\x00not utf-8"),
                ),
            ]

            for label, mutate in cases:
                with self.subTest(label=label):
                    fixture = make_source_pack_fixture(Path(temp_dir) / label)
                    mutate(fixture)
                    with self.assertRaisesRegex(ValueError, r"Could not load JSON file .*pack\.json"):
                        load_tile_pack_manifest(fixture.pack_path)

    def test_load_logical_tilesheet_manifest_honours_absolute_sheet_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_source_pack_fixture(Path(temp_dir))
            absolute_sheet = fixture.art_dir / "overworld.base.png"
            self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "sheet"], str(absolute_sheet))

            tilesheet = load_logical_tilesheet_manifest(fixture.tilesheet_path, grid=GridSize(tile_width=8, tile_height=8))

            self.assertEqual(tilesheet.variant("base").sheet_path, absolute_sheet)

    def _set_json_value(self, path: Path, keys: list[object], value: object) -> None:
        payload = read_json(path)
        current: object = payload
        for key in keys[:-1]:
            if isinstance(key, int):
                current = cast(list[object], current)[key]
            else:
                current = cast(dict[str, object], current)[str(key)]
        last_key = keys[-1]
        if isinstance(last_key, int):
            cast(list[object], current)[last_key] = value
        else:
            cast(dict[str, object], current)[str(last_key)] = value
        write_json(path, payload)

    def _delete_json_value(self, path: Path, keys: list[object]) -> None:
        payload = read_json(path)
        current: object = payload
        for key in keys[:-1]:
            if isinstance(key, int):
                current = cast(list[object], current)[key]
            else:
                current = cast(dict[str, object], current)[str(key)]
        last_key = keys[-1]
        if isinstance(last_key, int):
            del cast(list[object], current)[last_key]
        else:
            del cast(dict[str, object], current)[str(last_key)]
        write_json(path, payload)

    def _make_corrupt_image_fixture(self, fixture: SourceFixturePaths) -> None:
        corrupt_path = fixture.art_dir / "corrupt.png"
        corrupt_path.write_text("not a real image\n", encoding="utf-8")
        self._set_json_value(fixture.tilesheet_path, ["render_variants", 0, "sheet"], "../art/corrupt.png")

if __name__ == "__main__":
    unittest.main()
