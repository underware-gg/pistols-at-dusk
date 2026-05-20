from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tile_families import (
    ConstructionConfig,
    ConstructionValidationError,
    MetatileConstruction,
    ParametricRunConstruction,
    ParametricRunConstructionConfig,
    TileFamily,
    TileLibraryRegistry,
    TileRecord,
    build_construction,
    compute_non_empty_tile_mask,
    compute_source_layout_coverage,
    detect_source_layout,
)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def make_family_dir(
    root: Path,
    *,
    cluster_ids: list[str],
    sheet_columns: int = 1,
    sheet_rows: int = 1,
    family_id: str = "testfam",
    alias_name: str = "sample.alias",
    directory_name: str = "family",
    construction_id: str | None = None,
    tile_id: str | None = None,
) -> Path:
    family_dir = root / directory_name
    family_dir.mkdir()
    Image.new("RGBA", (sheet_columns * 8, sheet_rows * 8), (0, 0, 0, 255)).save(family_dir / "sheet.png")

    tile_id = tile_id or f"{family_id}:all:0,0"

    write_json(
        family_dir / "family.json",
        {
            "family_id": family_id,
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": [
                {
                    "variant_id": "base",
                    "sheet": "sheet.png",
                    "transparent": "none",
                }
            ],
            "ingestion_spec": "ingestion.json",
        },
    )
    write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
            "regions": [
                {
                    "id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "label": "All sheet content",
                }
            ],
            "clusters": [
                {
                    "id": "sheet.region.cluster_01",
                    "source_region_id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "label": "Only cluster",
                }
            ],
            "ignore_regions": [],
            "collections": [
                {
                    "id": "sheet.region.collection_01",
                    "kind": "connected_component",
                    "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "members": [{"sheet_cell": {"col": 0, "row": 0}}],
                }
            ],
        },
    )
    write_json(
        family_dir / "clusters.json",
        [
            {
                "id": "cluster.valid",
                "scope": "family",
                "members": [tile_id],
            }
        ],
    )
    write_json(
        family_dir / "tiles.json",
        [
            {
                "id": tile_id,
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "map",
                "category": "tile",
                "transparent": False,
                "cluster_ids": cluster_ids,
                "tags": ["semantic:floor"],
                "source_group": "test.group",
                "meaning": "Test floor tile.",
                "meaning_confidence": "confirmed",
                **(
                    {
                        "compose_group": construction_id,
                        "compose_role": "single",
                    }
                    if construction_id is not None
                    else {}
                ),
            }
        ],
    )
    write_json(family_dir / "aliases.json", {alias_name: tile_id})
    if construction_id is not None:
        write_json(
            family_dir / "constructions.json",
            {
                "constructions": [
                    {
                        "id": construction_id,
                        "collection_id": construction_id,
                        "kind": "metatile",
                        "cells": [[{"role": "single"}]],
                    }
                ]
            },
        )
    return family_dir


def load_ingestion_payload(family_dir: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((family_dir / "ingestion.json").read_text(encoding="utf-8")))


def make_duplicate_family_dir(root: Path, *, identical: bool) -> Path:
    family_dir = root / "family"
    family_dir.mkdir()

    image = Image.new("RGBA", (16, 8), (0, 0, 0, 255))
    for y in range(8):
        for x in range(8):
            image.putpixel((x, y), (255, 128, 0, 255))
            image.putpixel((x + 8, y), (255, 128, 0, 255) if identical else (0, 200, 255, 255))
    image.save(family_dir / "sheet.png")

    write_json(
        family_dir / "family.json",
        {
            "family_id": "testfam",
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": [
                {
                    "variant_id": "base",
                    "sheet": "sheet.png",
                    "transparent": "none",
                }
            ],
            "ingestion_spec": "ingestion.json",
        },
    )
    write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 2, "height": 1},
            "regions": [
                {
                    "id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 2, "height": 1},
                    "label": "All sheet content",
                }
            ],
            "clusters": [
                {
                    "id": "sheet.region.cluster_01",
                    "source_region_id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 2, "height": 1},
                    "label": "Only cluster",
                }
            ],
            "collections": [],
        },
    )
    write_json(
        family_dir / "clusters.json",
        [
            {
                "id": "cluster.valid",
                "scope": "family",
                "members": ["testfam:all:0,0", "testfam:all:1,0"],
            }
        ],
    )
    write_json(
        family_dir / "tiles.json",
        [
            {
                "id": "testfam:all:0,0",
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "ui",
                "category": "ui",
                "transparent": False,
                "cluster_ids": ["cluster.valid"],
                "source_group": "test.left",
                "meaning": "Canonical orange connector.",
                "meaning_confidence": "confirmed",
                "usage": "connector",
                "temperature": "warm",
                "tags": ["semantic:connector"],
            },
            {
                "id": "testfam:all:1,0",
                "sheet_col": 1,
                "sheet_row": 0,
                "layer": "ui",
                "category": "ui",
                "transparent": False,
                "exact_duplicate_of": "testfam:all:0,0",
                "cluster_ids": ["cluster.valid"],
                "source_group": "test.right",
            },
        ],
    )
    write_json(
        family_dir / "aliases.json",
        {
            "sample.alias": "testfam:all:0,0",
            "sample.duplicate": "testfam:all:1,0",
        },
    )
    return family_dir


def make_image_override_family_dir(root: Path, *, image_size: tuple[int, int] = (8, 8)) -> Path:
    family_dir = root / "family"
    family_dir.mkdir()

    Image.new("RGBA", (8, 16), (0, 0, 0, 255)).save(family_dir / "sheet.png")
    derived_dir = family_dir / "derived"
    derived_dir.mkdir()
    Image.new("RGBA", image_size, (255, 0, 255, 255)).save(derived_dir / "override.png")

    write_json(
        family_dir / "family.json",
        {
            "family_id": "testfam",
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": [
                {
                    "variant_id": "base",
                    "sheet": "sheet.png",
                    "transparent": "none",
                }
            ],
            "ingestion_spec": "ingestion.json",
        },
    )
    write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 1, "height": 2},
            "regions": [
                {
                    "id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 1, "height": 2},
                    "label": "All sheet content",
                }
            ],
            "clusters": [
                {
                    "id": "sheet.region.cluster_01",
                    "source_region_id": "sheet.region",
                    "bounds": {"x": 0, "y": 0, "width": 1, "height": 2},
                    "label": "Only cluster",
                }
            ],
            "collections": [],
        },
    )
    write_json(
        family_dir / "clusters.json",
        [
            {
                "id": "cluster.valid",
                "scope": "family",
                "members": ["testfam:all:0,0", "testfam:derived.override"],
            }
        ],
    )
    write_json(
        family_dir / "tiles.json",
        [
            {
                "id": "testfam:all:0,0",
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "ui",
                "category": "ui",
                "transparent": False,
                "cluster_ids": ["cluster.valid"],
                "source_group": "test.sheet",
                "meaning": "Sheet-backed control tile.",
                "meaning_confidence": "confirmed",
            },
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
            },
        ],
    )
    write_json(
        family_dir / "aliases.json",
        {
            "sample.alias": "testfam:all:0,0",
            "sample.override": "testfam:derived.override",
        },
    )
    return family_dir


class TileFamilyLoadTests(unittest.TestCase):
    def test_load_accepts_valid_cluster_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            family = TileFamily.load(family_dir)
            tile = family.by_alias("sample.alias")
            self.assertEqual(tile.cluster_ids, ("cluster.valid",))
            self.assertIsNotNone(family.source_layout)
            assert family.source_layout is not None
            self.assertEqual(tuple(family.source_layout.source_regions.keys()), ("sheet.region",))
            self.assertEqual(tuple(family.source_layout.source_clusters.keys()), ("sheet.region.cluster_01",))

    def test_query_rejects_ambiguous_cluster_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            family = TileFamily.load(family_dir)

            with self.assertRaisesRegex(TypeError, "semantic_cluster_id"):
                family.query(cluster_id="sheet.region.cluster_01")

            matches = family.query(semantic_cluster_id="cluster.valid")
            self.assertEqual([tile.id for tile in matches], ["testfam:all:0,0"])

    def test_load_rejects_unknown_cluster_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.missing"])
            with self.assertRaisesRegex(ValueError, "unknown cluster"):
                TileFamily.load(family_dir)

    def test_load_resolves_exact_duplicate_tile_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_duplicate_family_dir(Path(temp_dir), identical=True)
            family = TileFamily.load(family_dir)

            canonical = family.by_id("testfam:all:0,0")
            duplicate = family.by_id("testfam:all:1,0")

            self.assertEqual(duplicate.exact_duplicate_of, canonical.id)
            self.assertEqual(duplicate.meaning, canonical.meaning)
            self.assertEqual(duplicate.meaning_confidence, canonical.meaning_confidence)
            self.assertEqual(duplicate.usage, canonical.usage)
            self.assertEqual(duplicate.temperature, canonical.temperature)
            self.assertEqual(duplicate.tags, canonical.tags)
            self.assertEqual(duplicate.source_group, "test.right")
            self.assertEqual(family.canonical_tile_id(duplicate.id), canonical.id)
            self.assertEqual(family.canonical_tile(duplicate).id, canonical.id)
            self.assertTrue(family.ingest_report()["complete"])

    def test_load_resolves_direct_sheet_refs_and_rejects_legacy_region_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_duplicate_family_dir(Path(temp_dir), identical=True)
            family = TileFamily.load(family_dir)

            resolved = family.resolve_ref("testfam:1,0")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.tile_id, "testfam:all:1,0")
            self.assertEqual(resolved.physical_ref, "testfam:1,0")
            self.assertEqual(resolved.variant_ref, "testfam@base:1,0")

            self.assertIsNone(family.resolve_ref("testfam:all:9,9"))
            self.assertIsNone(family.resolve_ref("testfam@base:all:1,0"))

    def test_load_rejects_unknown_exact_duplicate_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_duplicate_family_dir(Path(temp_dir), identical=True)
            tiles_path = family_dir / "tiles.json"
            payload = cast(list[dict[str, object]], json.loads(tiles_path.read_text(encoding="utf-8")))
            payload[1]["exact_duplicate_of"] = "testfam:all:9,9"
            write_json(tiles_path, payload)

            with self.assertRaisesRegex(ValueError, "unknown exact_duplicate_of"):
                TileFamily.load(family_dir)

    def test_load_rejects_non_identical_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_duplicate_family_dir(Path(temp_dir), identical=False)

            with self.assertRaisesRegex(ValueError, "pixels differ"):
                TileFamily.load(family_dir)

    def test_load_supports_image_override_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_image_override_family_dir(Path(temp_dir))
            family = TileFamily.load(family_dir)

            tile = family.by_alias("sample.override")
            self.assertEqual(tile.image_override, "derived/override.png")
            self.assertIsNone(tile.sheet_col)
            self.assertIsNone(tile.sheet_row)
            resolved = family.resolve_ref("sample.override")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertTrue(resolved.variant_ref.endswith("testfam:derived.override"))
            self.assertTrue(resolved.physical_ref.endswith("testfam:derived.override"))
            self.assertIsNotNone(resolved.image_override_path)

    def test_load_rejects_sheet_backed_tile_outside_sheet_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            tiles_path = family_dir / "tiles.json"
            payload = cast(list[dict[str, object]], json.loads(tiles_path.read_text(encoding="utf-8")))
            payload[0]["sheet_col"] = 1
            write_json(tiles_path, payload)

            with self.assertRaisesRegex(ValueError, "outside family sheet bounds"):
                TileFamily.load(family_dir)

    def test_load_accepts_non_cell_sized_image_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_image_override_family_dir(Path(temp_dir), image_size=(12, 10))
            family = TileFamily.load(family_dir)

            tile = family.by_alias("sample.override")
            self.assertEqual(tile.image_override, "derived/override.png")

    def test_load_rejects_declared_missing_ingestion_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            family_manifest = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
            family_manifest["ingestion_spec"] = "missing-ingestion.json"
            write_json(family_dir / "family.json", family_manifest)

            with self.assertRaisesRegex(ValueError, "Declared ingestion spec"):
                TileFamily.load(family_dir)

    def test_load_rejects_duplicate_ingestion_region_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            regions = cast(list[dict[str, object]], ingestion["regions"])
            regions.append(dict(regions[0]))
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "Duplicate ingestion region id"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_region_outside_sheet_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            regions = cast(list[dict[str, object]], ingestion["regions"])
            regions[0]["bounds"] = {"x": 1, "y": 0, "width": 1, "height": 1}
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "falls outside sheet bounds"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_region_area_outside_region_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"], sheet_columns=2, sheet_rows=2)
            ingestion = load_ingestion_payload(family_dir)
            ingestion["sheet_bounds"] = {"x": 0, "y": 0, "width": 2, "height": 2}
            regions = cast(list[dict[str, object]], ingestion["regions"])
            regions[0]["bounds"] = {"x": 0, "y": 0, "width": 1, "height": 1}
            regions[0]["areas"] = [{"x": 1, "y": 0, "width": 1, "height": 1}]
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "area falls outside region bounds"):
                TileFamily.load(family_dir)

    def test_load_rejects_duplicate_ingestion_cluster_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            clusters = cast(list[dict[str, object]], ingestion["clusters"])
            clusters.append(dict(clusters[0]))
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "Duplicate ingestion cluster id"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_cluster_with_unknown_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            clusters = cast(list[dict[str, object]], ingestion["clusters"])
            clusters[0]["source_region_id"] = "missing.region"
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "references unknown ingestion region"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_cluster_outside_parent_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"], sheet_columns=2, sheet_rows=2)
            ingestion = load_ingestion_payload(family_dir)
            ingestion["sheet_bounds"] = {"x": 0, "y": 0, "width": 2, "height": 2}
            clusters = cast(list[dict[str, object]], ingestion["clusters"])
            clusters[0]["bounds"] = {"x": 1, "y": 0, "width": 1, "height": 1}
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "falls outside ingestion region"):
                TileFamily.load(family_dir)

    def test_load_rejects_duplicate_ingestion_ignore_region_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            ingestion["ignore_regions"] = [
                {"id": "ignore.01", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}},
                {"id": "ignore.01", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}},
            ]
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "Duplicate ingestion ignore region id"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_collection_with_unknown_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            collections = cast(list[dict[str, object]], ingestion["collections"])
            collections[0]["members"] = [{"sheet_cell": {"col": 9, "row": 9}}]
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "references unknown member sheet cell"):
                TileFamily.load(family_dir)

    def test_load_rejects_ingestion_collection_member_with_invalid_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion = load_ingestion_payload(family_dir)
            collections = cast(list[dict[str, object]], ingestion["collections"])
            collections[0]["members"] = [{"tile_id": "testfam:all:0,0", "alias": "sample.alias"}]
            write_json(family_dir / "ingestion.json", ingestion)

            with self.assertRaisesRegex(ValueError, "must be exactly one of"):
                TileFamily.load(family_dir)


class SourceLayoutDetectionTests(unittest.TestCase):
    def test_detect_source_layout_finds_regions_clusters_and_components(self) -> None:
        image = Image.new("RGBA", (56, 32), (0, 0, 0, 255))
        # Region 1, cluster 1: a 2x2 occupied block away from the top-left
        # background sample tile.
        for row in range(0, 16):
            for col in range(8, 24):
                image.putpixel((col, row), (255, 255, 255, 255))
        # Region 1, cluster 2: a horizontal 1x2 strip lower down.
        for row in range(24, 32):
            for col in range(8, 24):
                image.putpixel((col, row), (255, 0, 0, 255))
        # Region 2, single vertical-strip cluster.
        for row in range(0, 24):
            for col in range(40, 48):
                image.putpixel((col, row), (0, 255, 0, 255))

        detected = detect_source_layout(image=image, tile_width=8, tile_height=8)

        self.assertEqual(len(cast(list[object], detected["regions"])), 2)
        clusters = cast(list[dict[str, object]], detected["clusters"])
        self.assertEqual(len(clusters), 3)
        self.assertIn("source_region_id", clusters[0])
        self.assertNotIn("region_id", clusters[0])
        collections = cast(list[dict[str, object]], detected["collections"])
        self.assertIn("source_cluster_id", collections[0])
        self.assertNotIn("cluster_id", collections[0])
        self.assertTrue(any(len(cast(list[object], collection["members"])) > 1 for collection in collections))


class Minimal8FamilyIngestTests(unittest.TestCase):
    def test_minimal8_family_ingest_is_complete(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        report = family.ingest_report()
        self.assertTrue(report["complete"], json.dumps(report, indent=2))
        self.assertEqual(report["tile_count"], 1376)
        self.assertEqual(report["missing_source_group"], [])
        self.assertEqual(report["missing_cluster_ids"], [])
        self.assertEqual(report["missing_meaning"], [])
        self.assertEqual(report["missing_meaning_confidence"], [])
        self.assertIn("confirmed", report["by_meaning_confidence"])
        self.assertIn("tentative", report["by_meaning_confidence"])
        self.assertIsNotNone(family.source_layout)
        assert family.source_layout is not None
        self.assertEqual(len(family.source_layout.source_regions), 4)
        self.assertEqual(len(family.source_layout.source_clusters), 23)
        self.assertEqual(len(family.source_layout.ignored_regions), 0)
        self.assertGreaterEqual(len(family.source_layout.source_collections), 40)
        self.assertIn("ui.gold_frame", family.source_layout.source_collections)
        self.assertIn("character.column_1.01", family.source_layout.source_collections)
        self.assertIn("character.column_5.04", family.source_layout.source_collections)
        table_collection = family.source_layout.source_collections["indoors.table.kit"]
        self.assertTrue(
            {
                "indoors.table.kit.round_single",
                "indoors.table.kit.square_single",
                "indoors.table.kit.horizontal_run",
                "indoors.table.kit.vertical_run",
                "indoors.table.kit.square_2x2",
                "indoors.table.kit.rect_2x3",
                "indoors.table.kit.horizontal_2x6",
                "indoors.table.kit.vertical_2x6",
                "indoors.table.kit.l_top_left",
                "indoors.table.kit.l_top_right",
                "indoors.table.kit.l_bottom_left",
                "indoors.table.kit.l_bottom_right",
            }.issubset(set(table_collection.constructions))
        )

    def test_minimal8_source_layout_coverage_is_complete(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        assert family.source_layout is not None
        variant = family.variant("1bit_colored_bg")
        image = Image.open(variant.sheet_path)
        mask = compute_non_empty_tile_mask(image=image, tile_width=family.tile_width, tile_height=family.tile_height)
        coverage = compute_source_layout_coverage(family.source_layout, mask)

        self.assertEqual(coverage["non_empty_total"], 1088)
        self.assertEqual(coverage["ignored_non_empty"], [])
        self.assertEqual(len(coverage["outside_regions_non_empty"]), 58)
        self.assertEqual(coverage["region_unclustered_non_empty"], [])
        self.assertTrue(coverage["complete"])

    def test_minimal8_ui_connector_duplicates_resolve_to_canonical_tiles(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        top_duplicate = family.by_id("minimal8:ui:12,5")
        top_canonical = family.by_id("minimal8:ui:12,3")
        middle_duplicate = family.by_id("minimal8:ui:3,7")
        middle_canonical = family.by_id("minimal8:ui:1,7")
        non_duplicate = family.by_id("minimal8:ui:2,8")

        self.assertEqual(top_duplicate.exact_duplicate_of, top_canonical.id)
        self.assertEqual(family.canonical_tile(top_duplicate).id, top_canonical.id)
        self.assertEqual(top_duplicate.meaning, top_canonical.meaning)
        self.assertEqual(top_duplicate.meaning_confidence, top_canonical.meaning_confidence)

        self.assertEqual(middle_duplicate.exact_duplicate_of, middle_canonical.id)
        self.assertEqual(family.canonical_tile(middle_duplicate).id, middle_canonical.id)
        self.assertEqual(middle_duplicate.meaning, middle_canonical.meaning)
        self.assertEqual(middle_duplicate.meaning_confidence, middle_canonical.meaning_confidence)

        self.assertIsNone(non_duplicate.exact_duplicate_of)

    def test_minimal8_state_and_animation_metadata_is_loaded(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        switch_off = family.by_id("minimal8:terrain:10,18")
        self.assertEqual(switch_off.state_group, "indoors.switch")
        self.assertEqual(switch_off.state_role, "off")
        self.assertEqual(switch_off.facing, "left")

        torch_frame_3 = family.by_id("minimal8:terrain:7,18")
        self.assertEqual(torch_frame_3.animation_group, "indoors.light.torch")
        self.assertEqual(torch_frame_3.animation_frame, 3)
        self.assertEqual(torch_frame_3.animation_frame_count, 4)

        brazier_frame_2 = family.by_id("minimal8:terrain:14,18")
        self.assertEqual(brazier_frame_2.animation_group, "indoors.brazier")
        self.assertEqual(brazier_frame_2.animation_frame, 2)
        self.assertEqual(brazier_frame_2.animation_frame_count, 2)

        minecart_frame_2 = family.by_id("minimal8:terrain:1,18")
        self.assertEqual(minecart_frame_2.animation_group, "prop.minecart.empty")
        self.assertEqual(minecart_frame_2.animation_frame, 2)
        self.assertEqual(minecart_frame_2.animation_frame_count, 2)

        character_pose = family.by_id("minimal8:characters:1,1")
        self.assertEqual(character_pose.state_group, "character.column_1.01")
        self.assertEqual(character_pose.state_role, "tall_right")
        self.assertEqual(character_pose.facing, "right")
        self.assertEqual(character_pose.pose, "tall")

        small_open_door = family.by_id("minimal8:architecture:6,11")
        self.assertEqual(small_open_door.state_group, "indoors.door.small")
        self.assertEqual(small_open_door.state_role, "open")

        grand_closed_door = family.by_id("minimal8:architecture:2,10")
        self.assertEqual(grand_closed_door.state_group, "indoors.door.grand")
        self.assertEqual(grand_closed_door.state_role, "closed")

        grand_open_door = family.by_id("minimal8:architecture:0,10")
        self.assertEqual(grand_open_door.state_group, "indoors.door.grand")
        self.assertEqual(grand_open_door.state_role, "open")

        table_middle = family.by_id("minimal8:terrain:2,15")
        self.assertEqual(table_middle.compose_group, "indoors.table.kit")
        self.assertEqual(table_middle.connects_on, ("west", "east", "north"))
        self.assertEqual(table_middle.requires_exposed_on, ("south",))

    def test_minimal8_seating_row_keeps_stools_and_beds_distinct(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        self.assertEqual(family.aliases["indoors.stool"], "minimal8:terrain:5,16")
        self.assertEqual(family.aliases["indoors.stool.right"], "minimal8:terrain:5,16")
        self.assertEqual(family.aliases["indoors.stool.left"], "minimal8:terrain:6,16")
        self.assertEqual(family.aliases["indoors.bench.right"], "minimal8:terrain:5,16")
        self.assertEqual(family.aliases["indoors.bench.left"], "minimal8:terrain:6,16")
        self.assertEqual(family.aliases["indoors.bed.vertical"], "minimal8:terrain:8,16")
        self.assertEqual(family.aliases["indoors.bed.horizontal"], "minimal8:terrain:9,16")

        stool_right = family.by_id("minimal8:terrain:5,16")
        stool_left = family.by_id("minimal8:terrain:6,16")
        bed_vertical = family.by_id("minimal8:terrain:8,16")
        bed_horizontal = family.by_id("minimal8:terrain:9,16")

        self.assertEqual(stool_right.semantics, ("furniture", "stool", "seat"))
        self.assertEqual(stool_left.semantics, ("furniture", "stool", "seat"))
        self.assertEqual(stool_right.affordances, ("sit",))
        self.assertEqual(stool_left.affordances, ("sit",))
        self.assertEqual(stool_right.compose_group, "indoors.stool")
        self.assertEqual(stool_left.compose_group, "indoors.stool")
        self.assertEqual(stool_right.alt_uses, ("bench",))
        self.assertEqual(stool_left.alt_uses, ("bench",))

        self.assertEqual(bed_vertical.semantics, ("furniture", "bed"))
        self.assertEqual(bed_horizontal.semantics, ("furniture", "bed"))
        self.assertEqual(bed_vertical.affordances, ("sleep", "rest"))
        self.assertEqual(bed_horizontal.affordances, ("sleep", "rest"))
        self.assertEqual(bed_vertical.compose_group, "indoors.bed")
        self.assertEqual(bed_horizontal.compose_group, "indoors.bed")

    def test_minimal8_actor_aliases_match_the_reviewed_character_sheet_cells(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        expected_aliases = {
            "actor.bartender.nw": "minimal8:characters:7,5",
            "actor.bartender.ne": "minimal8:characters:8,5",
            "actor.bartender.sw": "minimal8:characters:7,6",
            "actor.bartender.se": "minimal8:characters:8,6",
            "actor.red.nw": "minimal8:characters:1,3",
            "actor.red.ne": "minimal8:characters:2,3",
            "actor.red.sw": "minimal8:characters:1,4",
            "actor.red.se": "minimal8:characters:2,4",
            "actor.gold.nw": "minimal8:characters:4,3",
            "actor.gold.ne": "minimal8:characters:5,3",
            "actor.gold.sw": "minimal8:characters:4,4",
            "actor.gold.se": "minimal8:characters:5,4",
            "actor.green.nw": "minimal8:characters:1,9",
            "actor.green.ne": "minimal8:characters:2,9",
            "actor.green.sw": "minimal8:characters:1,10",
            "actor.green.se": "minimal8:characters:2,10",
            "actor.orange.nw": "minimal8:characters:10,3",
            "actor.orange.ne": "minimal8:characters:11,3",
            "actor.orange.sw": "minimal8:characters:10,4",
            "actor.orange.se": "minimal8:characters:11,4",
            "actor.purple.nw": "minimal8:characters:4,7",
            "actor.purple.ne": "minimal8:characters:5,7",
            "actor.purple.sw": "minimal8:characters:4,8",
            "actor.purple.se": "minimal8:characters:5,8",
            "actor.teal.nw": "minimal8:characters:10,5",
            "actor.teal.ne": "minimal8:characters:11,5",
            "actor.teal.sw": "minimal8:characters:10,6",
            "actor.teal.se": "minimal8:characters:11,6",
            "actor.blue.nw": "minimal8:characters:13,5",
            "actor.blue.ne": "minimal8:characters:14,5",
            "actor.blue.sw": "minimal8:characters:13,6",
            "actor.blue.se": "minimal8:characters:14,6",
            "actor.salmon.nw": "minimal8:characters:13,3",
            "actor.salmon.ne": "minimal8:characters:14,3",
            "actor.salmon.sw": "minimal8:characters:13,4",
            "actor.salmon.se": "minimal8:characters:14,4",
        }

        for alias, tile_id in expected_aliases.items():
            self.assertEqual(family.aliases[alias], tile_id, alias)

    def test_generic_reusable_tiles_do_not_carry_tavern_only_tags(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        for tile_id in (
            "minimal8:architecture:1,10",
            "minimal8:architecture:2,10",
            "minimal8:architecture:6,11",
            "minimal8:architecture:7,11",
            "minimal8:architecture:3,15",
            "minimal8:architecture:5,18",
            "minimal8:architecture:0,19",
            "minimal8:characters:4,3",
            "minimal8:icons:2,6",
        ):
            tile = family.by_id(tile_id)
            self.assertNotIn("scene:tavern", tile.tags, tile_id)
            self.assertNotIn("tavern", tile.scenes, tile_id)

    def test_minimal8_constructions_derive_runtime_entity_templates(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        table = family.entity_template("indoors.table.kit.square_2x2")
        self.assertIsNotNone(table)
        assert table is not None
        self.assertEqual(table.collection_id, "indoors.table.kit")
        self.assertEqual(table.kind, "metatile")
        self.assertEqual(table.placement_anchor, "top_left")
        self.assertEqual(table.footprint.mode, "fixed")
        self.assertEqual(table.footprint.width, 2)
        self.assertEqual(table.footprint.height, 2)

        bookcase = family.entity_template("indoors.bookcase.tall.run")
        self.assertIsNotNone(bookcase)
        assert bookcase is not None
        self.assertEqual(bookcase.collection_id, "indoors.bookcase.tall")
        self.assertEqual(bookcase.kind, "parametric_run")
        self.assertEqual(bookcase.placement_anchor, "top_left")
        self.assertEqual(bookcase.footprint.mode, "parametric_run")
        self.assertEqual(bookcase.footprint.axis, "x")
        self.assertEqual(bookcase.footprint.length_param, "length")
        self.assertEqual(bookcase.footprint.minimum_length, 2)

    def test_ingest_report_fails_when_meaning_confidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir: Path = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            tiles_path: Path = family_dir / "tiles.json"
            payload = cast(list[dict[str, object]], json.loads(tiles_path.read_text(encoding="utf-8")))
            del payload[0]["meaning_confidence"]
            write_json(tiles_path, payload)

            family = TileFamily.load(family_dir)
            report = family.ingest_report()

            self.assertFalse(report["complete"])
            self.assertEqual(report["missing_meaning_confidence"], ["testfam:all:0,0"])


def _make_tile(
    tile_id: str,
    *,
    compose_group: str | None = None,
    compose_role: str | None = None,
    connects_on: list[str] | None = None,
    requires_exposed_on: list[str] | None = None,
) -> TileRecord:
    return TileRecord(
        id=tile_id,
        family_id="testfam",
        layer="map",
        category="tile",
        transparent=False,
        tags=(),
        sheet_col=0,
        sheet_row=0,
        compose_group=compose_group,
        compose_role=compose_role,
        connects_on=tuple(connects_on or []),
        requires_exposed_on=tuple(requires_exposed_on or []),
    )


def _make_tiles_dict(*tiles: TileRecord) -> dict[str, TileRecord]:
    return {t.id: t for t in tiles}


class ConstructionLoaderTests(unittest.TestCase):
    def test_grand_door_construction_loads_and_validates(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        for construction_id in ("indoors.door.grand.open", "indoors.door.grand.closed"):
            construction = family.lookup_construction(construction_id)
            self.assertIsNotNone(construction)
            assert construction is not None
            self.assertEqual(construction.id, construction_id)
            self.assertEqual(construction.collection_id, construction_id)
            self.assertIsInstance(construction, MetatileConstruction)
            assert isinstance(construction, MetatileConstruction)
            self.assertEqual(len(construction.cells), 2)
            self.assertEqual(len(construction.cells[0]), 2)
            self.assertEqual(len(construction.cells[1]), 2)
            top_left = construction.cells[0][0]
            top_right = construction.cells[0][1]
            bottom_left = construction.cells[1][0]
            bottom_right = construction.cells[1][1]
            self.assertIsNotNone(top_left)
            self.assertIsNotNone(top_right)
            self.assertIsNotNone(bottom_left)
            self.assertIsNotNone(bottom_right)
        assert top_left is not None
        assert top_right is not None
        assert bottom_left is not None
        assert bottom_right is not None
        self.assertEqual(top_left.compose_role, "top_left")
        self.assertEqual(top_right.compose_role, "top_right")
        self.assertEqual(bottom_left.compose_role, "bottom_left")
        self.assertEqual(bottom_right.compose_role, "bottom_right")

    def test_lookup_construction_returns_none_for_unknown_id(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        self.assertIsNone(family.lookup_construction("does.not.exist"))

    def test_constructions_mapping_is_frozen(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        with self.assertRaises(TypeError):
            family.constructions["injected"] = MetatileConstruction(  # type: ignore[index]
                id="x", collection_id="x", cells=()
            )

    def test_family_without_constructions_file_has_empty_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            family = TileFamily.load(family_dir)
            self.assertEqual(len(family.constructions), 0)
            self.assertIsNone(family.lookup_construction("anything"))

    def test_collection_referencing_unknown_construction_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion_path = family_dir / "ingestion.json"
            ingestion = cast(dict[str, object], json.loads(ingestion_path.read_text(encoding="utf-8")))
            collections = ingestion["collections"]
            assert isinstance(collections, list)
            assert isinstance(collections[0], dict)
            collections[0]["constructions"] = ["missing.construction"]
            write_json(ingestion_path, ingestion)
            with self.assertRaises(ValueError) as ctx:
                TileFamily.load(family_dir)
            self.assertIn("sheet.region.collection_01", str(ctx.exception))
            self.assertIn("missing.construction", str(ctx.exception))


class TileLibraryRegistryTests(unittest.TestCase):
    def test_legacy_family_runtime_unit_defaults_promoted_metadata_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])

            family = TileFamily.load(family_dir)

            promoted_metadata = family.runtime_unit.promoted_metadata
            self.assertIsNone(promoted_metadata.source_pack_id)
            self.assertIsNone(promoted_metadata.source_tileset_id)
            self.assertIsNone(promoted_metadata.source_tilesheet_id)
            self.assertEqual(dict(promoted_metadata.module_context), {})
            self.assertEqual(promoted_metadata.documented_hints, ())

    def test_family_load_rejects_intra_family_alias_tile_id_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(
                Path(temp_dir),
                cluster_ids=["cluster.valid"],
                alias_name="testfam:all:0,0",
            )

            with self.assertRaisesRegex(ValueError, "Alias 'testfam:all:0,0' collides with tile id"):
                TileFamily.load(family_dir)

    def test_registry_over_disjoint_units_preserves_alias_and_construction_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.a",
                    alias_name="alias.a",
                    directory_name="family_a",
                    construction_id="construction.a",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.b",
                    alias_name="alias.b",
                    directory_name="family_b",
                    construction_id="construction.b",
                )
            )

            registry = TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])

            self.assertEqual(registry.unit_ids, ("family.a", "family.b"))
            alias_a_owner = registry.alias_owner("alias.a")
            alias_b_owner = registry.alias_owner("alias.b")
            construction_a = registry.lookup_construction("construction.a")
            construction_b = registry.lookup_construction("construction.b")
            self.assertIsNotNone(alias_a_owner)
            self.assertIsNotNone(alias_b_owner)
            self.assertIsNotNone(construction_a)
            self.assertIsNotNone(construction_b)
            assert alias_a_owner is not None
            assert alias_b_owner is not None
            assert construction_a is not None
            assert construction_b is not None
            self.assertEqual(alias_a_owner.family_id, "family.a")
            self.assertEqual(alias_b_owner.family_id, "family.b")
            self.assertEqual(construction_a.id, "construction.a")
            self.assertEqual(construction_b.id, "construction.b")
            self.assertEqual(registry.unit_for_ref("family.a:0,0"), alias_a_owner)
            self.assertEqual(registry.unit_for_ref("alias.b"), alias_b_owner)
            self.assertEqual(registry.unit_for_ref("family.a:all:0,0"), alias_a_owner)
            self.assertIsNotNone(registry.entity_template("construction.a"))
            self.assertIsNotNone(registry.entity_template("construction.b"))

    def test_registry_rejects_duplicate_unit_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="duplicate.family",
                    directory_name="family_a",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="duplicate.family",
                    directory_name="family_b",
                )
            )

            with self.assertRaisesRegex(ValueError, "Duplicate tile library unit id"):
                TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])

    def test_registry_rejects_duplicate_construction_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.a",
                    directory_name="family_a",
                    construction_id="shared.construction",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.b",
                    directory_name="family_b",
                    construction_id="shared.construction",
                )
            )

            with self.assertRaisesRegex(ValueError, "Duplicate construction id across tile library units"):
                TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])

    def test_registry_rejects_duplicate_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.a",
                    alias_name="shared.alias",
                    directory_name="family_a",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.b",
                    alias_name="shared.alias",
                    directory_name="family_b",
                )
            )

            with self.assertRaisesRegex(ValueError, "Duplicate alias across tile library units"):
                TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])

    def test_registry_rejects_cross_unit_alias_tile_id_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.a",
                    alias_name="shared.ref",
                    directory_name="family_a",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.b",
                    directory_name="family_b",
                    tile_id="shared.ref",
                )
            )

            with self.assertRaisesRegex(ValueError, "Cross-unit ref collision between tile id and alias"):
                TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])

    def test_registry_rejects_duplicate_tile_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_a = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.a",
                    directory_name="family_a",
                    tile_id="shared.tile",
                )
            )
            family_b = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.b",
                    directory_name="family_b",
                    tile_id="shared.tile",
                )
            )

            with self.assertRaisesRegex(ValueError, "Duplicate tile id across tile library units"):
                TileLibraryRegistry.from_units([family_a.runtime_unit, family_b.runtime_unit])


class ConstructionValidationAdjacencyTests(unittest.TestCase):
    def test_adjacency_violation_east_missing_from_left_cell(self) -> None:
        tl = _make_tile("t:tl", compose_group="kit", compose_role="tl", connects_on=[])
        tr = _make_tile("t:tr", compose_group="kit", compose_role="tr", connects_on=["west"])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "tl"}, {"role": "tr"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(tl, tr))
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("col=0", msg)
        self.assertIn("row=0", msg)

    def test_adjacency_violation_west_missing_from_right_cell(self) -> None:
        tl = _make_tile("t:tl", compose_group="kit", compose_role="tl", connects_on=["east"])
        tr = _make_tile("t:tr", compose_group="kit", compose_role="tr", connects_on=[])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "tl"}, {"role": "tr"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(tl, tr))
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("col=1", msg)
        self.assertIn("row=0", msg)

    def test_adjacency_north_south_violation(self) -> None:
        top = _make_tile("t:top", compose_group="kit", compose_role="top", connects_on=["south"])
        bot = _make_tile("t:bot", compose_group="kit", compose_role="bot", connects_on=[])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "top"}],
                [{"role": "bot"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(top, bot))
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("col=0, row=1", msg)

    def test_valid_adjacency_passes(self) -> None:
        tl = _make_tile("t:tl", compose_group="kit", compose_role="tl", connects_on=["east", "south"])
        tr = _make_tile("t:tr", compose_group="kit", compose_role="tr", connects_on=["west", "south"])
        bl = _make_tile("t:bl", compose_group="kit", compose_role="bl", connects_on=["north", "east"])
        br = _make_tile("t:br", compose_group="kit", compose_role="br", connects_on=["north", "west"])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "tl"}, {"role": "tr"}],
                [{"role": "bl"}, {"role": "br"}],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(tl, tr, bl, br))
        self.assertEqual(construction.id, "test.metatile")


class ConstructionValidationExposureTests(unittest.TestCase):
    def test_exposure_violation_south_neighbour_is_filled(self) -> None:
        top = _make_tile(
            "t:top",
            compose_group="kit",
            compose_role="top",
            connects_on=["south"],
            requires_exposed_on=["south"],
        )
        bot = _make_tile("t:bot", compose_group="kit", compose_role="bot", connects_on=["north"])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "top"}],
                [{"role": "bot"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(top, bot))
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("requires_exposed_on", msg)
        self.assertIn("col=0, row=0", msg)
        self.assertIn("col=0, row=1", msg)

    def test_exposure_edge_of_construction_is_allowed(self) -> None:
        top = _make_tile(
            "t:top",
            compose_group="kit",
            compose_role="top",
            connects_on=[],
            requires_exposed_on=["south"],
        )
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "top"}],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(top))
        assert isinstance(construction, MetatileConstruction)
        self.assertIsNotNone(construction.cells[0][0])

    def test_exposure_empty_cell_neighbour_is_allowed(self) -> None:
        left = _make_tile(
            "t:left",
            compose_group="kit",
            compose_role="left",
            connects_on=["east"],
            requires_exposed_on=["south"],
        )
        right = _make_tile("t:right", compose_group="kit", compose_role="right", connects_on=["west"])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "left"}, {"role": "right"}],
                [".", "."],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(left, right))
        assert isinstance(construction, MetatileConstruction)
        self.assertIsNone(construction.cells[1][0])


class ConstructionRoleBindingTests(unittest.TestCase):
    def test_role_binding_multiple_matches_raises(self) -> None:
        t1 = _make_tile("t:tile1", compose_group="kit", compose_role="body", connects_on=[])
        t2 = _make_tile("t:tile2", compose_group="kit", compose_role="body", connects_on=[])
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "body"}],
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(t1, t2))
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("body", msg)
        self.assertIn("multiple", msg)

    def test_role_binding_no_match_raises(self) -> None:
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                [{"role": "ghost_role"}],
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            build_construction(raw, tiles={})
        msg = str(ctx.exception)
        self.assertIn("test.metatile", msg)
        self.assertIn("ghost_role", msg)
        self.assertIn("no tile found", msg)

    def test_role_binding_dot_cell_resolves_to_none(self) -> None:
        raw: ConstructionConfig = {
            "id": "test.metatile",
            "collection_id": "kit",
            "kind": "metatile",
            "cells": [
                ["."],
            ],
        }
        construction = build_construction(raw, tiles={})
        assert isinstance(construction, MetatileConstruction)
        self.assertIsNone(construction.cells[0][0])


class ParametricRunValidationTests(unittest.TestCase):
    def _make_run_tiles(
        self,
        *,
        start_connects: list[str],
        repeat_connects: list[str],
        end_connects: list[str],
    ) -> dict[str, TileRecord]:
        start = _make_tile("t:start", compose_group="kit", compose_role="start_role", connects_on=start_connects)
        repeat = _make_tile("t:repeat", compose_group="kit", compose_role="repeat_role", connects_on=repeat_connects)
        end = _make_tile("t:end", compose_group="kit", compose_role="end_role", connects_on=end_connects)
        return _make_tiles_dict(start, repeat, end)

    def _raw_run(self) -> ParametricRunConstructionConfig:
        return {
            "id": "test.run",
            "collection_id": "kit",
            "kind": "parametric_run",
            "axis": "x",
            "length_param": "length",
            "start_role": "start_role",
            "repeat_role": "repeat_role",
            "end_role": "end_role",
        }

    def test_valid_parametric_run_loads(self) -> None:
        tiles = self._make_run_tiles(
            start_connects=["east"],
            repeat_connects=["west", "east"],
            end_connects=["west"],
        )
        raw = self._raw_run()
        construction = build_construction(raw, tiles=tiles)
        self.assertEqual(construction.id, "test.run")
        self.assertIsInstance(construction, ParametricRunConstruction)
        assert isinstance(construction, ParametricRunConstruction)
        self.assertEqual(construction.axis, "x")
        self.assertEqual(construction.length_param, "length")
        self.assertIsNotNone(construction.start_tile)
        self.assertIsNotNone(construction.repeat_tile)
        self.assertIsNotNone(construction.end_tile)

    def test_start_missing_forward_direction_fails(self) -> None:
        tiles = self._make_run_tiles(
            start_connects=[],
            repeat_connects=["west", "east"],
            end_connects=["west"],
        )
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("start_role", str(ctx.exception))
        self.assertIn("east", str(ctx.exception))

    def test_repeat_missing_backward_direction_fails(self) -> None:
        tiles = self._make_run_tiles(
            start_connects=["east"],
            repeat_connects=["east"],
            end_connects=["west"],
        )
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("repeat_role", str(ctx.exception))
        self.assertIn("west", str(ctx.exception))

    def test_repeat_missing_forward_direction_fails(self) -> None:
        tiles = self._make_run_tiles(
            start_connects=["east"],
            repeat_connects=["west"],
            end_connects=["west"],
        )
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("repeat_role", str(ctx.exception))
        self.assertIn("east", str(ctx.exception))

    def test_end_missing_backward_direction_fails(self) -> None:
        tiles = self._make_run_tiles(
            start_connects=["east"],
            repeat_connects=["west", "east"],
            end_connects=[],
        )
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("end_role", str(ctx.exception))
        self.assertIn("west", str(ctx.exception))

    def test_minimal8_horizontal_run_construction_loads_as_parametric_run(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        construction = family.lookup_construction("indoors.table.kit.horizontal_run")
        self.assertIsNotNone(construction)
        assert construction is not None
        self.assertIsInstance(construction, ParametricRunConstruction)
        assert isinstance(construction, ParametricRunConstruction)
        self.assertEqual(construction.axis, "x")
        self.assertIsNotNone(construction.start_tile)
        self.assertIsNotNone(construction.repeat_tile)
        self.assertIsNotNone(construction.end_tile)

    def test_minimal8_counter_and_bookcase_runs_load_as_parametric_runs(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        for construction_id in ("indoors.counter.low.run", "indoors.bookcase.tall.run"):
            construction = family.lookup_construction(construction_id)
            self.assertIsNotNone(construction)
            assert construction is not None
            self.assertIsInstance(construction, ParametricRunConstruction)
            assert isinstance(construction, ParametricRunConstruction)
            self.assertEqual(construction.axis, "x")
            self.assertIsNotNone(construction.start_tile)
            self.assertIsNotNone(construction.repeat_tile)
            self.assertIsNotNone(construction.end_tile)


if __name__ == "__main__":
    unittest.main()
