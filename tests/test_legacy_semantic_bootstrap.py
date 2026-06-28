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
    LEGACY_TILE_SEMANTIC_FIELDS,
    LEGACY_TILE_SEMANTICS_ORIGIN,
    LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
    LegacySemanticBootstrapCollisionError,
    SemanticCollision,
    collision_report_payload,
    bootstrap_legacy_semantic_patch,
    legacy_tile_semantics_from_json,
    write_bootstrap_outputs,
)
from semantic_catalogue_ingest import (
    ResolvedSemanticTile,
    authored_patch_from_json,
    resolve_semantic_catalogue,
    semantic_catalogue_with_identity_from_json,
)
from tile_family_ingest import load_source_tile_family
from tile_library import LegacyTileSemanticRecord


MINIMAL8_HARNESS = ROOT / "prototypes/minimal8-harness"
MINIMAL8_MAIN_CATALOGUE_DIR = MINIMAL8_HARNESS / "semantic-catalogue/minimal8-clean-fields"
MINIMAL8_CHARACTERS_CATALOGUE_DIR = MINIMAL8_HARNESS / "semantic-catalogue/minimal8-characters-clean-fields"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _legacy_record_from_payload(raw: dict[str, object]) -> LegacyTileSemanticRecord:
    facts_payload = cast(dict[str, object], raw["facts"])
    return LegacyTileSemanticRecord(
        tile_id=cast(str, raw["tile_id"]),
        origin=cast(str, raw["origin"]),
        schema_version=cast(int, raw["schema_version"]),
        facts={
            field: tuple(cast(list[str], value)) if isinstance(value, list) else cast(str | None, value)
            for field, value in facts_payload.items()
        },
    )


def _paint_tile(sheet: Image.Image, col: int, colour: tuple[int, int, int, int]) -> None:
    tile = Image.new("RGBA", (8, 8), colour)
    sheet.paste(tile, (col * 8, 0))


def _make_two_tile_family(
    root: Path,
    *,
    base_colours: tuple[tuple[int, int, int, int], tuple[int, int, int, int]],
    alt_colours: tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None = None,
    semantics: tuple[list[str], list[str]] | None = None,
    contrast: tuple[str | None, str | None] = ("high", "high"),
    style: tuple[str | None, str | None] = (None, None),
    usage: tuple[str | None, str | None] = ("floor", "floor"),
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
                "tags": ["semantic:fixture"],
                "cluster_ids": ["cluster.valid"],
                "source_group": "group",
                "semantics": semantics[0] if semantics is not None else ["left"],
                "meaning_confidence": "confirmed",
                "motifs": ["fixture-motif"],
                "noise": "low",
                "temperature": "warm",
                "overlay": "shadow",
                "footprint": "single",
                "orientation": "upright",
                "facing": "south",
                "pose": "idle",
                "meaning": "left legacy meaning",
                "source_notes": "left source note",
                **({"usage": usage[0]} if usage[0] is not None else {}),
                **({"contrast": contrast[0]} if contrast[0] is not None else {}),
                **({"style": style[0]} if style[0] is not None else {}),
            },
            {
                "id": "testfam:all:1,0",
                "sheet_col": 1,
                "sheet_row": 0,
                "layer": "map",
                "category": "tile",
                "transparent": False,
                "tags": ["semantic:fixture"],
                "cluster_ids": ["cluster.valid"],
                "source_group": "group",
                "semantics": semantics[1] if semantics is not None else ["right"],
                "meaning_confidence": "confirmed",
                "motifs": ["fixture-motif"],
                "noise": "low",
                "temperature": "warm",
                "overlay": "shadow",
                "footprint": "single",
                "orientation": "upright",
                "facing": "south",
                "pose": "idle",
                "meaning": "right legacy meaning",
                "source_notes": "right source note",
                **({"usage": usage[1]} if usage[1] is not None else {}),
                **({"contrast": contrast[1]} if contrast[1] is not None else {}),
                **({"style": style[1]} if style[1] is not None else {}),
            },
        ],
    )
    _write_json(family_dir / "aliases.json", {})
    return family_dir


def _load_minimal8_expected_catalogue(
    family_dir: Path,
    *,
    collision_resolutions_path: Path | None = None,
) -> tuple[
    tuple[str, ...],
    tuple[ResolvedSemanticTile, ...],
    tuple[LegacyTileSemanticRecord, ...],
    tuple[SemanticCollision, ...],
]:
    family = load_source_tile_family(family_dir)
    variant_ids = tuple(sorted(family.variants))
    result = bootstrap_legacy_semantic_patch(family, variant_ids=variant_ids, raise_on_collisions=False)
    patches = list(result.authored_patches)
    if collision_resolutions_path is not None:
        resolutions = authored_patch_from_json(collision_resolutions_path.read_text(encoding="utf-8"))
        collision_hashes = {collision.content_hash for collision in result.collisions}
        resolution_hashes = {patch.content_hash for patch in resolutions}
        if resolution_hashes != collision_hashes:
            raise AssertionError(
                f"collision resolutions do not match collisions: "
                f"extra={sorted(resolution_hashes - collision_hashes)} "
                f"missing={sorted(collision_hashes - resolution_hashes)}"
            )
        patches.extend(resolutions)
    return (
        variant_ids,
        resolve_semantic_catalogue(result.detected_base, tuple(patches)),
        result.legacy_semantics,
        result.collisions,
    )


class LegacySemanticBootstrapTests(unittest.TestCase):
    def test_minimal8_durable_catalogue_matches_bootstrap_plus_collision_resolutions(self) -> None:
        variant_ids, expected_records, expected_legacy, collisions = _load_minimal8_expected_catalogue(
            MINIMAL8_HARNESS / "tile-families/minimal8",
            collision_resolutions_path=MINIMAL8_MAIN_CATALOGUE_DIR / "collision-resolutions.json",
        )

        loaded = semantic_catalogue_with_identity_from_json(
            (MINIMAL8_MAIN_CATALOGUE_DIR / "resolved-catalogue.json").read_text(encoding="utf-8")
        )
        loaded_legacy = legacy_tile_semantics_from_json(
            (MINIMAL8_MAIN_CATALOGUE_DIR / "legacy-tile-semantics.json").read_text(encoding="utf-8")
        )

        self.assertEqual(len(variant_ids), 38)
        self.assertEqual(len(collisions), 4)
        self.assertEqual(len(expected_records), 747)
        self.assertEqual(len(expected_legacy), 1408)
        self.assertEqual(loaded.content_identity.variant_ids, variant_ids)
        self.assertEqual(loaded.records, expected_records)
        self.assertEqual(loaded_legacy, expected_legacy)

    def test_minimal8_characters_durable_catalogue_matches_collision_free_bootstrap(self) -> None:
        variant_ids, expected_records, expected_legacy, collisions = _load_minimal8_expected_catalogue(
            MINIMAL8_HARNESS / "tile-families/minimal8-characters",
        )

        loaded = semantic_catalogue_with_identity_from_json(
            (MINIMAL8_CHARACTERS_CATALOGUE_DIR / "resolved-catalogue.json").read_text(encoding="utf-8")
        )
        loaded_legacy = legacy_tile_semantics_from_json(
            (MINIMAL8_CHARACTERS_CATALOGUE_DIR / "legacy-tile-semantics.json").read_text(encoding="utf-8")
        )

        self.assertEqual(len(variant_ids), 9)
        self.assertEqual(len(collisions), 0)
        self.assertEqual(len(expected_records), 63)
        self.assertEqual(len(expected_legacy), 78)
        self.assertEqual(loaded.content_identity.variant_ids, variant_ids)
        self.assertEqual(loaded.records, expected_records)
        self.assertEqual(loaded_legacy, expected_legacy)

    def test_main_collision_resolutions_do_not_apply_to_characters_catalogue(self) -> None:
        character_hashes = {
            record.content_hash
            for record in semantic_catalogue_with_identity_from_json(
                (MINIMAL8_CHARACTERS_CATALOGUE_DIR / "resolved-catalogue.json").read_text(encoding="utf-8")
            ).records
        }
        main_resolution_hashes = {
            patch.content_hash
            for patch in authored_patch_from_json(
                (MINIMAL8_MAIN_CATALOGUE_DIR / "collision-resolutions.json").read_text(encoding="utf-8")
            )
        }

        self.assertEqual(len(main_resolution_hashes), 4)
        self.assertEqual(main_resolution_hashes & character_hashes, set())

    def test_legacy_tile_semantics_loader_rejects_bad_schema_version(self) -> None:
        payload: dict[str, object] = {
            "schema_version": 99,
            "legacy_tile_semantics": [],
        }

        with self.assertRaisesRegex(ValueError, "legacy tile semantics schema_version must be 1"):
            legacy_tile_semantics_from_json(json.dumps(payload))

    def test_legacy_tile_semantics_loader_rejects_duplicate_tile_id(self) -> None:
        record = LegacyTileSemanticRecord(
            tile_id="testfam:all:0,0",
            origin=LEGACY_TILE_SEMANTICS_ORIGIN,
            schema_version=LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
            facts={"tags": ("fixture",)},
        ).to_payload()
        payload: dict[str, object] = {
            "schema_version": 1,
            "legacy_tile_semantics": [record, record],
        }

        with self.assertRaisesRegex(ValueError, "duplicates tile_id 'testfam:all:0,0'"):
            legacy_tile_semantics_from_json(json.dumps(payload))

    def test_legacy_tile_semantics_loader_rejects_bool_schema_version(self) -> None:
        record = LegacyTileSemanticRecord(
            tile_id="testfam:all:0,0",
            origin=LEGACY_TILE_SEMANTICS_ORIGIN,
            schema_version=LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
            facts={},
        ).to_payload()
        record["schema_version"] = True
        payload: dict[str, object] = {
            "schema_version": 1,
            "legacy_tile_semantics": [record],
        }

        with self.assertRaisesRegex(ValueError, "schema_version must be an integer"):
            legacy_tile_semantics_from_json(json.dumps(payload))

    def test_legacy_tile_semantics_loader_rejects_malformed_fact_value(self) -> None:
        record = LegacyTileSemanticRecord(
            tile_id="testfam:all:0,0",
            origin=LEGACY_TILE_SEMANTICS_ORIGIN,
            schema_version=LEGACY_TILE_SEMANTICS_SCHEMA_VERSION,
            facts={},
        ).to_payload()
        cast(dict[str, object], record["facts"])["tags"] = ["valid", 17]
        payload: dict[str, object] = {
            "schema_version": 1,
            "legacy_tile_semantics": [record],
        }

        with self.assertRaisesRegex(ValueError, "facts\\.tags\\[1\\] must be a string"):
            legacy_tile_semantics_from_json(json.dumps(payload))

    def test_bootstrap_preserves_full_legacy_semantic_payload_per_physical_tile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((255, 0, 0, 255), (0, 0, 255, 255)),
                    contrast=("high", "low"),
                    style=("pixel", "flat"),
                    usage=("floor", None),
                )
            )

            result = bootstrap_legacy_semantic_patch(family)

        records = {record.tile_id: record for record in result.legacy_semantics}
        left = records["testfam:all:0,0"]
        right = records["testfam:all:1,0"]
        self.assertEqual(left.origin, LEGACY_TILE_SEMANTICS_ORIGIN)
        self.assertEqual(left.schema_version, LEGACY_TILE_SEMANTICS_SCHEMA_VERSION)
        self.assertEqual(set(left.facts), LEGACY_TILE_SEMANTIC_FIELDS)
        self.assertEqual(set(right.facts), LEGACY_TILE_SEMANTIC_FIELDS)
        self.assertEqual(left.facts["category"], "tile")
        self.assertEqual(left.facts["layer"], "map")
        self.assertEqual(left.facts["tags"], ("semantic:fixture",))
        self.assertEqual(left.facts["semantics"], ("left",))
        self.assertEqual(left.facts["motifs"], ("fixture-motif",))
        self.assertEqual(left.facts["contrast"], "high")
        self.assertEqual(left.facts["style"], "pixel")
        self.assertEqual(left.facts["noise"], "low")
        self.assertEqual(left.facts["temperature"], "warm")
        self.assertEqual(left.facts["usage"], "floor")
        self.assertEqual(left.facts["overlay"], "shadow")
        self.assertEqual(left.facts["footprint"], "single")
        self.assertEqual(left.facts["orientation"], "upright")
        self.assertEqual(left.facts["facing"], "south")
        self.assertEqual(left.facts["pose"], "idle")
        self.assertEqual(left.facts["meaning"], "left legacy meaning")
        self.assertEqual(left.facts["meaning_confidence"], "confirmed")
        self.assertEqual(left.facts["source_notes"], "left source note")
        self.assertEqual(right.facts["meaning"], "right legacy meaning")
        self.assertEqual(right.facts["contrast"], "low")
        self.assertIsNone(right.facts["usage"])

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
        semantic_values = sorted(cast(tuple[str, ...], record.facts["semantics"]) for record in resolved)
        self.assertEqual(semantic_values, [("left",), ("right",)])

    def test_identical_pixels_with_identical_facts_collapse_to_one_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    semantics=(["same"], ["same"]),
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
                    semantics=(["left"], ["right"]),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        self.assertEqual(len(caught.exception.collisions), 1)
        collision = caught.exception.collisions[0]
        self.assertEqual(collision.tile_ids, ("testfam:all:0,0", "testfam:all:1,0"))
        self.assertIn("semantics", collision.differing_fields)
        self.assertEqual(collision.differing_fields["semantics"]['tuple:["left"]'], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["semantics"]['tuple:["right"]'], ("testfam:all:1,0",))

    def test_multi_variant_identity_does_not_false_merge_default_identical_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((40, 40, 40, 255), (40, 40, 40, 255)),
                    alt_colours=((40, 40, 40, 255), (80, 80, 80, 255)),
                    semantics=(["same"], ["same"]),
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
            legacy_payload = json.loads((output_dir / "legacy-tile-semantics.json").read_text(encoding="utf-8"))
            detected_base_exists = (output_dir / "detected-base.json").exists()
            collisions_exists = (output_dir / "bootstrap-collisions.json").exists()

        self.assertEqual(authored_patch["schema_version"], 1)
        self.assertEqual(len(authored_patch["patches"]), 2)
        self.assertTrue(all(patch["content_hash"].startswith("content-sha256:") for patch in authored_patch["patches"]))
        self.assertEqual(legacy_payload["schema_version"], LEGACY_TILE_SEMANTICS_SCHEMA_VERSION)
        legacy_records = tuple(
            _legacy_record_from_payload(cast(dict[str, object], raw_record))
            for raw_record in cast(list[object], legacy_payload["legacy_tile_semantics"])
        )
        self.assertEqual(len(legacy_records), 2)
        self.assertEqual(legacy_records[0].origin, LEGACY_TILE_SEMANTICS_ORIGIN)
        self.assertEqual(legacy_records[0].facts["category"], "tile")
        self.assertEqual(legacy_records[0].facts["tags"], ("semantic:fixture",))
        self.assertEqual(legacy_records[0].facts["source_notes"], "left source note")
        self.assertIsNone(legacy_records[0].facts["style"])
        self.assertTrue(detected_base_exists)
        self.assertTrue(collisions_exists)

    def test_collision_detection_uses_raw_tuple_values_not_rendered_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    semantics=(["a", "b"], ["a, b"]),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        collision = caught.exception.collisions[0]
        self.assertEqual(collision.differing_fields["semantics"]['tuple:["a","b"]'], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["semantics"]['tuple:["a, b"]'], ("testfam:all:1,0",))

    def test_collision_detection_distinguishes_null_from_literal_null_string(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = load_source_tile_family(
                _make_two_tile_family(
                    Path(temp_dir),
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    semantics=(["same"], ["same"]),
                    style=(None, "<null>"),
                )
            )

            with self.assertRaises(LegacySemanticBootstrapCollisionError) as caught:
                bootstrap_legacy_semantic_patch(family)

        collision = caught.exception.collisions[0]
        self.assertEqual(collision.differing_fields["style"]["null"], ("testfam:all:0,0",))
        self.assertEqual(collision.differing_fields["style"]["string:<null>"], ("testfam:all:1,0",))

    def test_write_outputs_serializes_non_empty_collision_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            family = load_source_tile_family(
                _make_two_tile_family(
                    temp_path,
                    base_colours=((12, 12, 12, 255), (12, 12, 12, 255)),
                    semantics=(["left"], ["right"]),
                )
            )
            output_dir = temp_path / "semantic-catalogues" / "main"

            result = bootstrap_legacy_semantic_patch(family, raise_on_collisions=False)
            write_bootstrap_outputs(result, output_dir)

            collisions_payload = json.loads((output_dir / "bootstrap-collisions.json").read_text(encoding="utf-8"))

        self.assertEqual(len(collisions_payload["collisions"]), 1)
        collision = collisions_payload["collisions"][0]
        self.assertEqual(collision["tile_ids"], ["testfam:all:0,0", "testfam:all:1,0"])
        self.assertEqual(collision["differing_fields"]["semantics"]['tuple:["left"]'], ["testfam:all:0,0"])
        self.assertEqual(collision["differing_fields"]["semantics"]['tuple:["right"]'], ["testfam:all:1,0"])

    def test_collision_report_payload_preserves_group_order_and_field_aggregation(self) -> None:
        first = SemanticCollision(
            content_hash="content-sha256:" + "2" * 64,
            tile_ids=("tile.c", "tile.a", "tile.b"),
            differing_fields={
                "meaning": {
                    "string:wall": ("tile.a", "tile.c"),
                    "string:floor": ("tile.b",),
                },
                "semantics": {
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
        self.assertEqual(differing_fields["semantics"]['tuple:["b"]'], ["tile.b", "tile.c"])


if __name__ == "__main__":
    unittest.main()
