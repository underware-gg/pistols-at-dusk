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

from legacy_semantic_bootstrap import (
    LegacySemanticBootstrapCollisionError,
    SemanticCollision,
    collision_report_payload,
    bootstrap_legacy_semantic_patch,
    write_bootstrap_outputs,
)
from semantic_catalogue_ingest import resolve_semantic_catalogue
from tile_family_ingest import load_source_tile_family


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _paint_tile(sheet: Image.Image, col: int, colour: tuple[int, int, int, int]) -> None:
    tile = Image.new("RGBA", (8, 8), colour)
    sheet.paste(tile, (col * 8, 0))


def _make_two_tile_family(
    root: Path,
    *,
    base_colours: tuple[tuple[int, int, int, int], tuple[int, int, int, int]],
    alt_colours: tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None = None,
    meanings: tuple[str, str] = ("left", "right"),
    tags: tuple[list[str], list[str]] | None = None,
    source_notes: tuple[str | None, str | None] = (None, None),
) -> Path:
    family_dir = root / "family"
    family_dir.mkdir()
    base_sheet = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
    _paint_tile(base_sheet, 0, base_colours[0])
    _paint_tile(base_sheet, 1, base_colours[1])
    base_sheet.save(family_dir / "base.png")

    variants = [{"variant_id": "base", "sheet": "base.png", "transparent": "none"}]
    if alt_colours is not None:
        alt_sheet = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
        _paint_tile(alt_sheet, 0, alt_colours[0])
        _paint_tile(alt_sheet, 1, alt_colours[1])
        alt_sheet.save(family_dir / "alt.png")
        variants.append({"variant_id": "alt", "sheet": "alt.png", "transparent": "none"})

    _write_json(
        family_dir / "family.json",
        {
            "family_id": "testfam",
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": variants,
            "ingestion_spec": "ingestion.json",
        },
    )
    _write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 2, "height": 1},
            "regions": [{"id": "region", "bounds": {"x": 0, "y": 0, "width": 2, "height": 1}}],
            "clusters": [{"id": "region.cluster", "source_region_id": "region", "bounds": {"x": 0, "y": 0, "width": 2, "height": 1}}],
            "ignore_regions": [],
            "collections": [],
        },
    )
    _write_json(
        family_dir / "clusters.json",
        [
            {
                "id": "cluster.valid",
                "scope": "family",
                "members": ["testfam:all:0,0", "testfam:all:1,0"],
            }
        ],
    )
    _write_json(
        family_dir / "tiles.json",
        [
            {
                "id": "testfam:all:0,0",
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "map",
                "category": "tile",
                "transparent": False,
                "tags": tags[0] if tags is not None else ["semantic:fixture"],
                "cluster_ids": ["cluster.valid"],
                "source_group": "group",
                "meaning": meanings[0],
                "meaning_confidence": "confirmed",
                **({"source_notes": source_notes[0]} if source_notes[0] is not None else {}),
            },
            {
                "id": "testfam:all:1,0",
                "sheet_col": 1,
                "sheet_row": 0,
                "layer": "map",
                "category": "tile",
                "transparent": False,
                "tags": tags[1] if tags is not None else ["semantic:fixture"],
                "cluster_ids": ["cluster.valid"],
                "source_group": "group",
                "meaning": meanings[1],
                "meaning_confidence": "confirmed",
                **({"source_notes": source_notes[1]} if source_notes[1] is not None else {}),
            },
        ],
    )
    _write_json(family_dir / "aliases.json", {})
    return family_dir


class LegacySemanticBootstrapTests(unittest.TestCase):
    def test_collision_free_physical_tiles_project_to_content_patches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((255, 0, 0, 255), (0, 0, 255, 255)),
                )
            )

            result = bootstrap_legacy_semantic_patch(family)

        self.assertEqual(len(result.collisions), 0)
        self.assertEqual(len(result.detected_base), 2)
        self.assertEqual(len(result.authored_patches), 2)
        resolved = resolve_semantic_catalogue(result.detected_base, result.authored_patches)
        meanings = sorted(cast(str, record.facts["meaning"]) for record in resolved)
        self.assertEqual(meanings, ["left", "right"])

    def test_identical_pixels_with_identical_facts_collapse_to_one_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    meanings=("same", "same"),
                )
            )

            result = bootstrap_legacy_semantic_patch(family)

        self.assertEqual(len(result.collisions), 0)
        self.assertEqual(len(result.detected_base), 1)
        self.assertEqual(len(result.authored_patches), 1)
        self.assertEqual(
            {physical.tile_id: physical.content_hash for physical in result.physical_tiles}["testfam:all:0,0"],
            {physical.tile_id: physical.content_hash for physical in result.physical_tiles}["testfam:all:1,0"],
        )

    def test_identical_pixels_with_divergent_facts_fail_loud(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    meanings=("left", "right"),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        self.assertEqual(len(caught.exception.collisions), 1)
        collision = caught.exception.collisions[0]
        self.assertEqual(collision.tile_ids, ("testfam:all:0,0", "testfam:all:1,0"))
        self.assertIn("meaning", collision.differing_fields)
        self.assertEqual(collision.differing_fields["meaning"]["string:left"], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["meaning"]["string:right"], ("testfam:all:1,0",))

    def test_multi_variant_identity_does_not_false_merge_default_identical_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((40, 40, 40, 255), (40, 40, 40, 255)),
                    alt_colours=((40, 40, 40, 255), (80, 80, 80, 255)),
                    meanings=("same", "same"),
                )
            )

            result = bootstrap_legacy_semantic_patch(family)

        self.assertEqual(len(result.collisions), 0)
        self.assertEqual(len(result.authored_patches), 2)
        hashes = {physical.content_hash for physical in result.physical_tiles}
        self.assertEqual(len(hashes), 2)

    def test_write_outputs_uses_durable_content_keyed_patch_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            family = load_source_tile_family(
                _make_two_tile_family(
                    temp_path,
                    base_colours=((255, 0, 0, 255), (0, 0, 255, 255)),
                )
            )
            output_dir = temp_path / "semantic-catalogues" / "main"

            result = bootstrap_legacy_semantic_patch(family)
            write_bootstrap_outputs(result, output_dir)

            authored_patch = json.loads((output_dir / "authored-patch.json").read_text(encoding="utf-8"))
            detected_base_exists = (output_dir / "detected-base.json").exists()
            collisions_exists = (output_dir / "bootstrap-collisions.json").exists()

        self.assertEqual(authored_patch["schema_version"], 1)
        self.assertEqual(len(authored_patch["patches"]), 2)
        self.assertTrue(all(patch["content_hash"].startswith("content-sha256:") for patch in authored_patch["patches"]))
        self.assertTrue(detected_base_exists)
        self.assertTrue(collisions_exists)

    def test_collision_detection_uses_raw_tuple_values_not_rendered_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    meanings=("same", "same"),
                    tags=(["a", "b"], ["a, b"]),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        collision = caught.exception.collisions[0]
        self.assertEqual(collision.differing_fields["tags"]['tuple:["a","b"]'], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["tags"]['tuple:["a, b"]'], ("testfam:all:1,0",))

    def test_collision_detection_distinguishes_null_from_literal_null_string(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    meanings=("same", "same"),
                    source_notes=(None, "<null>"),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        collision = caught.exception.collisions[0]
        self.assertEqual(collision.differing_fields["source_notes"]["null"], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["source_notes"]["string:<null>"], ("testfam:all:1,0",))

    def test_write_outputs_serializes_non_empty_collision_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            family = load_source_tile_family(
                _make_two_tile_family(
                    temp_path,
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    meanings=("left", "right"),
                )
            )
            output_dir = temp_path / "semantic-catalogues" / "main"

            result = bootstrap_legacy_semantic_patch(family, raise_on_collisions=False)
            write_bootstrap_outputs(result, output_dir)

            collisions_payload = json.loads((output_dir / "bootstrap-collisions.json").read_text(encoding="utf-8"))

        self.assertEqual(len(collisions_payload["collisions"]), 1)
        collision = collisions_payload["collisions"][0]
        self.assertEqual(collision["tile_ids"], ["testfam:all:0,0", "testfam:all:1,0"])
        self.assertEqual(collision["differing_fields"]["meaning"]["string:left"], ["testfam:all:0,0"])
        self.assertEqual(collision["differing_fields"]["meaning"]["string:right"], ["testfam:all:1,0"])

    def test_collision_report_payload_preserves_group_order_and_field_aggregation(self) -> None:
        first = SemanticCollision(
            content_hash="content-sha256:" + "2" * 64,
            tile_ids=("tile.c", "tile.a", "tile.b"),
            differing_fields={
                "meaning": {
                    "string:wall": ("tile.a", "tile.c"),
                    "string:floor": ("tile.b",),
                },
                "tags": {
                    'tuple:["a"]': ("tile.a",),
                    'tuple:["b"]': ("tile.b", "tile.c"),
                },
            },
        )
        second = SemanticCollision(
            content_hash="content-sha256:" + "1" * 64,
            tile_ids=("tile.z", "tile.y"),
            differing_fields={
                "source_notes": {
                    "null": ("tile.y",),
                    "string:note": ("tile.z",),
                },
            },
        )

        payload = collision_report_payload((first, second))

        collisions = cast(list[dict[str, object]], payload["collisions"])
        self.assertEqual(
            [collision["content_hash"] for collision in collisions],
            ["content-sha256:" + "1" * 64, "content-sha256:" + "2" * 64],
        )
        first_payload = collisions[1]
        self.assertEqual(first_payload["tile_ids"], ["tile.a", "tile.b", "tile.c"])
        differing_fields = cast(dict[str, dict[str, list[str]]], first_payload["differing_fields"])
        self.assertEqual(differing_fields["meaning"]["string:wall"], ["tile.a", "tile.c"])
        self.assertEqual(differing_fields["meaning"]["string:floor"], ["tile.b"])
        self.assertEqual(differing_fields["tags"]['tuple:["b"]'], ["tile.b", "tile.c"])


if __name__ == "__main__":
    unittest.main()
