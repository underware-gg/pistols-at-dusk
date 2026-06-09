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

from _manifest_utils import GridBounds
from seam_matching import MatchPolicy
from tile_library import (
    CellContentInset,
    CompositeTileCell,
    CompositeTileRecord,
    ConstructionAttachmentSet,
    ConstructionAttachmentVariant,
    FixedConstruction,
    FixedConstructionSeamOverride,
    FixedSeamOverrideSide,
    PlaceableRef,
    ParametricFrameConstruction,
    ParametricRunConstruction,
    TileGenesis,
    TileLibraryRegistry,
    TileLibraryPromotedMetadata,
    TileFamilyVariant,
    TileLibraryUnit,
    TileRecord,
    attachment_sets_by_target,
    connection_surface_for_placeable,
    entity_template_from_placeable,
    lower_tile_asset_to_cells,
)
from tile_families import (
    CompositeTileConfig,
    ConstructionConfig,
    ConstructionAttachmentSetConfig,
    ConstructionValidationError,
    ParametricRunConstructionConfig,
    TileFamily,
    build_construction,
    compute_non_empty_tile_mask,
    compute_source_layout_coverage,
    detect_source_layout,
    load_attachment_sets_from_data,
    load_construction_manifest,
    load_composite_tiles_from_data,
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
                        "kind": "fixed",
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


def make_attachment_family_dir(root: Path) -> Path:
    family_dir = root / "family"
    family_dir.mkdir()
    Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(family_dir / "sheet.png")

    write_json(
        family_dir / "family.json",
        {
            "family_id": "testfam",
            "grid": {"tile_width": 8, "tile_height": 8},
            "default_variant_id": "base",
            "variants": [{"variant_id": "base", "sheet": "sheet.png", "transparent": "none"}],
            "ingestion_spec": "ingestion.json",
        },
    )
    write_json(
        family_dir / "ingestion.json",
        {
            "sheet_bounds": {"x": 0, "y": 0, "width": 2, "height": 2},
            "regions": [{"id": "sheet.region", "bounds": {"x": 0, "y": 0, "width": 2, "height": 2}}],
            "clusters": [],
            "ignore_regions": [],
            "collections": [],
        },
    )
    write_json(family_dir / "clusters.json", [])
    write_json(
        family_dir / "tiles.json",
        [
            {
                "id": "testfam:body:0,0",
                "sheet_col": 0,
                "sheet_row": 0,
                "layer": "sprite",
                "category": "character",
                "transparent": True,
                "compose_group": "test.body",
                "compose_role": "base",
                "connects_on": ["east", "south"],
                "cluster_ids": [],
                "source_group": "test",
                "meaning": "Base tile",
                "meaning_confidence": "confirmed",
            },
            {
                "id": "testfam:head:1,0",
                "sheet_col": 1,
                "sheet_row": 0,
                "layer": "sprite",
                "category": "character",
                "transparent": True,
                "compose_group": "test.head.alt",
                "compose_role": "base",
                "connects_on": ["west", "south"],
                "cluster_ids": [],
                "source_group": "test",
                "meaning": "Head tile",
                "meaning_confidence": "confirmed",
            },
            {
                "id": "testfam:big:0,1",
                "sheet_col": 0,
                "sheet_row": 1,
                "layer": "sprite",
                "category": "character",
                "transparent": True,
                "compose_group": "test.big",
                "compose_role": "left",
                "connects_on": ["east"],
                "cluster_ids": [],
                "source_group": "test",
                "meaning": "Big left",
                "meaning_confidence": "confirmed",
            },
            {
                "id": "testfam:big:1,1",
                "sheet_col": 1,
                "sheet_row": 1,
                "layer": "sprite",
                "category": "character",
                "transparent": True,
                "compose_group": "test.big",
                "compose_role": "right",
                "connects_on": ["west"],
                "cluster_ids": [],
                "source_group": "test",
                "meaning": "Big right",
                "meaning_confidence": "confirmed",
            },
        ],
    )
    write_json(family_dir / "aliases.json", {})
    write_json(
        family_dir / "constructions.json",
        {
            "constructions": [
                {
                    "id": "test.body",
                    "collection_id": "test.body",
                    "kind": "fixed",
                    "cells": [[{"role": "base"}]],
                },
                {
                    "id": "test.head.alt",
                    "collection_id": "test.head.alt",
                    "kind": "fixed",
                    "cells": [[{"role": "base"}]],
                    "expose_as_entity": False,
                },
                {
                    "id": "test.big",
                    "collection_id": "test.big",
                    "kind": "fixed",
                    "cells": [[{"role": "left"}, {"role": "right"}]],
                    "expose_as_entity": False,
                },
            ]
        },
    )
    write_json(
        family_dir / "attachments.json",
        {
            "attachment_sets": [
                {
                    "id": "test.body.heads",
                    "param": "head",
                    "required": True,
                    "target_construction_ids": ["test.body"],
                    "canvas": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "variants": [{"id": "alt", "construction_id": "test.head.alt"}],
                }
            ]
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
            self.assertEqual(tile.genesis.cluster_ids, ("cluster.valid",))
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
            self.assertEqual(duplicate.genesis.source_group, "test.right")
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
            self.assertIsNone(tile.genesis.sheet_col)
            self.assertIsNone(tile.genesis.sheet_row)
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

    def test_load_accepts_attachment_manifest_and_projects_entity_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            family = TileFamily.load(family_dir)

            template = family.entity_template("test.body")
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.placeable_kind, "construction")
            self.assertEqual(template.placeable_id, "test.body")
            self.assertEqual(template.construction_id, "test.body")
            self.assertEqual(len(template.attachment_sets), 1)
            self.assertTrue(template.attachment_sets[0].required)
            self.assertEqual(template.attachment_sets[0].variant_ids, ("alt",))
            self.assertEqual([entry.id for entry in family.entity_templates()], ["test.body"])
            attachment_set = family.attachment_sets_for_construction("test.body")[0]
            self.assertEqual(attachment_set.target_placeable_refs, (PlaceableRef.construction("test.body"),))
            variant = attachment_set.variant("alt")
            self.assertIsNotNone(variant)
            assert variant is not None
            self.assertEqual(variant.placeable_ref, PlaceableRef.construction("test.head.alt"))

    def test_load_rejects_non_boolean_expose_as_entity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            constructions = cast(dict[str, object], json.loads((family_dir / "constructions.json").read_text(encoding="utf-8")))
            raw_constructions = cast(list[dict[str, object]], constructions["constructions"])
            raw_constructions[0]["expose_as_entity"] = "yes"
            write_json(family_dir / "constructions.json", constructions)

            with self.assertRaisesRegex(ValueError, "expose_as_entity must be a boolean"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_set_with_empty_param(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["param"] = ""
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "param must be a non-empty string"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_set_with_empty_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["target_construction_ids"] = []
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "target_construction_ids must be a non-empty list"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_set_with_unknown_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["target_construction_ids"] = ["missing.target"]
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "unknown target placeable"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_canvas_outside_target_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["canvas"] = {"x": 1, "y": 0, "width": 1, "height": 1}
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "must stay inside target placeable"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_set_with_no_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["variants"] = []
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "must define at least one variant"):
                TileFamily.load(family_dir)

    def test_load_rejects_duplicate_attachment_variant_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            variants = cast(list[dict[str, object]], attachment_sets[0]["variants"])
            variants.append(dict(variants[0]))
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "duplicate variant id"):
                TileFamily.load(family_dir)

    def test_load_rejects_unknown_attachment_variant_construction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            variants = cast(list[dict[str, object]], attachment_sets[0]["variants"])
            variants[0]["construction_id"] = "missing.variant"
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "references unknown placeable"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_variant_that_exceeds_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            variants = cast(list[dict[str, object]], attachment_sets[0]["variants"])
            variants[0]["construction_id"] = "test.big"
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "exceeds canvas"):
                TileFamily.load(family_dir)

    def test_load_accepts_attachment_default_variant_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["required"] = False
            attachment_sets[0]["default_variant_id"] = "alt"
            write_json(family_dir / "attachments.json", attachments)

            family = TileFamily.load(family_dir)
            attachment_set = family.attachment_sets_for_construction("test.body")[0]
            self.assertFalse(attachment_set.required)
            self.assertEqual(attachment_set.default_variant_id, "alt")

    def test_load_rejects_attachment_default_variant_id_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["default_variant_id"] = ""
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "default_variant_id must be a non-empty string"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_default_variant_id_unknown_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["default_variant_id"] = "missing"
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "must match a declared variant id"):
                TileFamily.load(family_dir)

    def test_load_rejects_attachment_required_non_bool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_attachment_family_dir(Path(temp_dir))
            attachments = cast(dict[str, object], json.loads((family_dir / "attachments.json").read_text(encoding="utf-8")))
            attachment_sets = cast(list[dict[str, object]], attachments["attachment_sets"])
            attachment_sets[0]["required"] = "yes"
            write_json(family_dir / "attachments.json", attachments)

            with self.assertRaisesRegex(ValueError, "required must be a boolean"):
                TileFamily.load(family_dir)

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
        self.assertEqual(report["tile_count"], 1408)
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

    def test_ui_gold_frame_collection_is_tagged_cluster_01(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        assert family.source_layout is not None
        gold_frame = family.source_layout.source_collections["ui.gold_frame"]
        # ui.gold_frame occupies sheet rows 4-6, which fall inside
        # ui.column_4.cluster_01 (rows 4-15), not cluster_02 (rows 17-18).
        self.assertEqual(gold_frame.source_cluster_id, "ui.column_4.cluster_01")

    def test_head_study_spare_03_composite_tile_is_full_2x2(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8-characters")
        composite = family.composite_tiles["head_study.head.spare_03"]
        self.assertEqual(composite.kind, "composite_tile")
        self.assertEqual(composite.width, 2)
        self.assertEqual(composite.height, 2)
        self.assertIsNotNone(composite.cells[1][0])
        self.assertIsNotNone(composite.cells[1][1])
        roles = {
            cell.role
            for row in composite.cells
            for cell in row
            if cell is not None
        }
        self.assertEqual(roles, {"top_left", "top_right", "bottom_left", "bottom_right"})

    def test_ui_border_kits_have_complete_compose_role_bindings(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        roles_by_kit: dict[str, set[str]] = {}
        for tile in family.tiles.values():
            group = tile.compose_group
            if group is not None and group.startswith("ui.frame."):
                self.assertIsNotNone(tile.compose_role, f"{tile.id} has compose_group but no compose_role")
                assert tile.compose_role is not None
                roles_by_kit.setdefault(group, set()).add(tile.compose_role)
        full_frame = {
            "corner_tl", "corner_tr", "corner_bl", "corner_br",
            "edge_top", "edge_bottom", "edge_left", "edge_right", "fill",
        }
        corners_only = {"corner_tl", "corner_tr", "corner_bl", "corner_br"}
        self.assertEqual(roles_by_kit.get("ui.frame.gold.gap"), full_frame)
        self.assertEqual(roles_by_kit.get("ui.frame.gold.smooth"), full_frame)
        self.assertEqual(roles_by_kit.get("ui.frame.less_ornate.gap"), full_frame)
        self.assertEqual(roles_by_kit.get("ui.frame.less_ornate.smooth"), full_frame)
        self.assertEqual(roles_by_kit.get("ui.frame.gold.simple"), corners_only)
        self.assertEqual(roles_by_kit.get("ui.frame.panel.smooth"), corners_only)

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
        self.assertEqual(table.placeable_kind, "construction")
        self.assertEqual(table.placeable_id, "indoors.table.kit.square_2x2")
        self.assertEqual(table.construction_id, "indoors.table.kit.square_2x2")
        self.assertEqual(table.collection_id, "indoors.table.kit")
        self.assertEqual(table.kind, "fixed")
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


_FULL_SEAM: tuple[bool, ...] = (True,) * 8


def _make_tile(
    tile_id: str,
    *,
    family_id: str = "testfam",
    compose_group: str | None = None,
    compose_role: str | None = None,
    connects_on: list[str] | None = None,
    requires_exposed_on: list[str] | None = None,
    seam_profiles: dict[str, tuple[bool, ...]] | None = None,
    affordances: tuple[str, ...] = (),
    state_group: str | None = None,
    animation_group: str | None = None,
) -> TileRecord:
    # Default every side to a fully-painted contact line, so two unspecified tiles
    # butt-join cleanly (equality 1.0); a test that wants a mismatch overrides the
    # relevant side. Mirrors what _attach_seam_profiles produces at family-build.
    profiles: dict[str, tuple[bool, ...]] = {side: _FULL_SEAM for side in ("north", "south", "east", "west")}
    if seam_profiles is not None:
        profiles.update(seam_profiles)
    return TileRecord(
        id=tile_id,
        family_id=family_id,
        layer="map",
        category="tile",
        transparent=False,
        tags=(),
        genesis=TileGenesis(kind="sheet", sheet_col=0, sheet_row=0),
        compose_group=compose_group,
        compose_role=compose_role,
        state_group=state_group,
        animation_group=animation_group,
        connects_on=tuple(connects_on or []),
        seam_profiles=profiles,
        requires_exposed_on=tuple(requires_exposed_on or []),
        affordances=affordances,
    )


def _make_tiles_dict(*tiles: TileRecord) -> dict[str, TileRecord]:
    return {t.id: t for t in tiles}


def _make_runtime_unit(
    *,
    family_id: str,
    tiles: tuple[TileRecord, ...],
    composite_tiles: tuple[CompositeTileRecord, ...] = (),
    attachment_sets: tuple[ConstructionAttachmentSet, ...] = (),
    variant_ids: tuple[str, ...] = ("base",),
) -> TileLibraryUnit:
    attachment_sets_by_id = {attachment_set.id: attachment_set for attachment_set in attachment_sets}
    return TileLibraryUnit(
        family_id=family_id,
        tile_width=8,
        tile_height=8,
        render_step_width=None,
        render_step_height=None,
        default_variant_id="base",
        promoted_metadata=TileLibraryPromotedMetadata(),
        root=Path("."),
        variants={
            variant_id: TileFamilyVariant(
                id=variant_id,
                sheet_path=Path("sheet.png"),
                transparent_mode="none",
            )
            for variant_id in variant_ids
        },
        tiles={tile.id: tile for tile in tiles},
        aliases={},
        tiles_by_sheet_cell_index={},
        constructions={},
        attachment_sets=attachment_sets_by_id,
        attachment_sets_by_target=attachment_sets_by_target(attachment_sets_by_id),
        composite_tiles={composite.id: composite for composite in composite_tiles},
    )


class TileGenesisTests(unittest.TestCase):
    def test_sheet_backed_tile_carries_canonical_sheet_genesis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            unit = TileFamily.load(family_dir).runtime_unit
            genesis = unit.genesis_for("testfam:all:0,0")
            self.assertIsNotNone(genesis)
            assert genesis is not None
            self.assertEqual(genesis.kind, "sheet")
            self.assertEqual((genesis.sheet_col, genesis.sheet_row), (0, 0))
            self.assertEqual(genesis.source_group, "test.group")
            self.assertEqual(genesis.cluster_ids, ("cluster.valid",))
            self.assertIsNone(genesis.derivation)

    def test_genesis_for_alias_resolves_through_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            unit = TileFamily.load(family_dir).runtime_unit
            self.assertEqual(
                unit.genesis_for_alias("sample.alias"),
                unit.genesis_for("testfam:all:0,0"),
            )

    def test_genesis_for_unknown_tile_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            unit = TileFamily.load(family_dir).runtime_unit
            self.assertIsNone(unit.genesis_for("testfam:all:9,9"))

    def test_synthetic_tile_genesis_derives_parent_construction_from_compose_group(self) -> None:
        # Mechanical provenance: a synthetic tile that is a cell of a construction
        # (carries compose_group) records that construction as a parent link, so its
        # genesis is non-empty without authoring prose. Verified against real data.
        fam = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8-characters")
        unit = fam.runtime_unit
        genesis = unit.genesis_for("minimal8.characters:head_study.head.first_full.top_left")
        self.assertIsNotNone(genesis)
        assert genesis is not None
        self.assertEqual(genesis.kind, "synthetic")
        self.assertIn("head_study.head.first_full", genesis.parent_construction_ids)

    def test_synthetic_tile_genesis_explains_derivation(self) -> None:
        record = TileRecord(
            id="testfam:derived.shelf",
            family_id="testfam",
            layer="map",
            category="tile",
            transparent=True,
            tags=(),
            image_override="derived/{variant_id}/shelf.png",
            source_notes="Synthetic middle slice derived from the left endcap tile.",
            genesis=TileGenesis(
                kind="synthetic",
                derivation="image_override",
                authored_notes="Synthetic middle slice derived from the left endcap tile.",
            ),
        )
        assert record.genesis is not None
        self.assertEqual(record.genesis.kind, "synthetic")
        self.assertEqual(record.genesis.derivation, "image_override")
        self.assertIsNone(record.genesis.sheet_col)
        self.assertIn("left endcap", record.genesis.authored_notes or "")


class AttachmentLoaderTests(unittest.TestCase):
    def _constructions(self) -> dict[str, FixedConstruction | ParametricRunConstruction]:
        body = FixedConstruction(
            id="test.body",
            collection_id="test.body",
            cells=((_make_tile("test:body", compose_group="test.body", compose_role="base"),),),
        )
        head = FixedConstruction(
            id="test.head.alt",
            collection_id="test.head.alt",
            cells=((_make_tile("test:head", compose_group="test.head.alt", compose_role="base"),),),
            expose_as_entity=False,
        )
        run = ParametricRunConstruction(
            id="test.run",
            collection_id="test.run",
            axis="x",
            length_param="length",
            start_tile=_make_tile("test:run.start", compose_group="test.run", compose_role="start"),
            repeat_tile=_make_tile("test:run.repeat", compose_group="test.run", compose_role="repeat"),
            end_tile=_make_tile("test:run.end", compose_group="test.run", compose_role="end"),
            expose_as_entity=False,
        )
        return {
            body.id: body,
            head.id: head,
            run.id: run,
        }

    def _placeables(self) -> dict[PlaceableRef, FixedConstruction | ParametricRunConstruction]:
        return {
            PlaceableRef.construction(construction_id): construction
            for construction_id, construction in self._constructions().items()
        }

    def _attachment_config(
        self,
        *,
        target_construction_ids: list[str] | None = None,
        variant_construction_id: str = "test.head.alt",
    ) -> ConstructionAttachmentSetConfig:
        return {
            "id": "test.body.heads",
            "param": "head",
            "target_construction_ids": target_construction_ids or ["test.body"],
            "canvas": {"x": 0, "y": 0, "width": 1, "height": 1},
            "variants": [{"id": "alt", "construction_id": variant_construction_id}],
        }

    def test_loader_rejects_parametric_run_target_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "must reference a fixed placeable, not parametric_run"):
            load_attachment_sets_from_data(
                (self._attachment_config(target_construction_ids=["test.run"]),),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )

    def test_loader_rejects_parametric_run_variant_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "must reference a fixed placeable, not parametric_run"):
            load_attachment_sets_from_data(
                (self._attachment_config(variant_construction_id="test.run"),),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )

    def test_loader_rejects_attachment_set_with_legacy_and_placeable_targets(self) -> None:
        config = self._attachment_config()
        config["target_placeables"] = [{"kind": "construction", "id": "test.body"}]

        with self.assertRaisesRegex(ValueError, "exactly one of target_construction_ids or target_placeables"):
            load_attachment_sets_from_data(
                (config,),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )

    def test_loader_rejects_attachment_set_without_target_identity(self) -> None:
        config = dict(self._attachment_config())
        config.pop("target_construction_ids")

        with self.assertRaisesRegex(ValueError, "exactly one of target_construction_ids or target_placeables"):
            load_attachment_sets_from_data(
                (cast(ConstructionAttachmentSetConfig, config),),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )

    def test_loader_rejects_attachment_variant_with_legacy_and_placeable_fill(self) -> None:
        config = self._attachment_config()
        variants = cast(list[dict[str, object]], config["variants"])
        variants[0]["placeable"] = {"kind": "construction", "id": "test.head.alt"}

        with self.assertRaisesRegex(ValueError, "exactly one of construction_id or placeable"):
            load_attachment_sets_from_data(
                (config,),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )

    def test_loader_rejects_attachment_variant_without_fill_identity(self) -> None:
        config = self._attachment_config()
        variants = cast(list[dict[str, object]], config["variants"])
        variants[0].pop("construction_id")

        with self.assertRaisesRegex(ValueError, "exactly one of construction_id or placeable"):
            load_attachment_sets_from_data(
                (config,),
                attachments_path=Path("attachments.json"),
                placeables=self._placeables(),
            )


class ConstructionLoaderTests(unittest.TestCase):
    def test_table_single_placeables_resolve_to_expected_atomic_tiles(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

        expected_roles = {
            "minimal8:terrain:0,15": "round_single",
            "minimal8:terrain:3,16": "square_single",
        }
        for tile_id, expected_role in expected_roles.items():
            tile = family.tiles[tile_id]
            self.assertEqual(tile.compose_group, "indoors.table.kit")
            self.assertEqual(tile.compose_role, expected_role)

    def test_grand_door_composite_tiles_load_and_validate(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        for composite_id in ("indoors.door.grand.open", "indoors.door.grand.closed"):
            self.assertIsNone(family.lookup_construction(composite_id))
            composite = family.composite_tiles[composite_id]
            self.assertEqual(composite.id, composite_id)
            self.assertEqual(composite.collection_id, composite_id)
            self.assertEqual((composite.width, composite.height), (2, 2))
            top_left = composite.cells[0][0]
            top_right = composite.cells[0][1]
            bottom_left = composite.cells[1][0]
            bottom_right = composite.cells[1][1]
            self.assertIsNotNone(top_left)
            self.assertIsNotNone(top_right)
            self.assertIsNotNone(bottom_left)
            self.assertIsNotNone(bottom_right)
            assert top_left is not None
            assert top_right is not None
            assert bottom_left is not None
            assert bottom_right is not None
            self.assertEqual(top_left.tile.compose_role, "top_left")
            self.assertEqual(top_right.tile.compose_role, "top_right")
            self.assertEqual(bottom_left.tile.compose_role, "bottom_left")
            self.assertEqual(bottom_right.tile.compose_role, "bottom_right")

    def test_lookup_construction_returns_none_for_unknown_id(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        self.assertIsNone(family.lookup_construction("does.not.exist"))

    def test_constructions_mapping_is_frozen(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        with self.assertRaises(TypeError):
            family.constructions["injected"] = FixedConstruction(  # type: ignore[index]
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

    def test_collection_construction_reference_may_resolve_to_composite_tile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])
            ingestion_path = family_dir / "ingestion.json"
            ingestion = cast(dict[str, object], json.loads(ingestion_path.read_text(encoding="utf-8")))
            collections = ingestion["collections"]
            assert isinstance(collections, list)
            assert isinstance(collections[0], dict)
            collections[0]["constructions"] = ["test.composite"]
            write_json(ingestion_path, ingestion)
            tiles_path = family_dir / "tiles.json"
            tiles = cast(list[dict[str, object]], json.loads(tiles_path.read_text(encoding="utf-8")))
            tiles[0]["compose_group"] = "test.composite"
            tiles[0]["compose_role"] = "single"
            write_json(tiles_path, tiles)
            write_json(
                family_dir / "composite_tiles.json",
                {
                    "composite_tiles": [
                        {
                            "id": "test.composite",
                            "collection_id": "test.composite",
                            "cells": [[{"role": "single"}]],
                        }
                    ]
                },
            )

            family = TileFamily.load(family_dir)

            self.assertIn("test.composite", family.composite_tiles)
            self.assertEqual(len(family.constructions), 0)


class CompositeTileLoaderTests(unittest.TestCase):
    def _raw_composite(self) -> dict[str, object]:
        return {
            "id": "test.composite",
            "collection_id": "kit",
            "cells": [[{"role": "single"}]],
        }

    def _tiles(self) -> dict[str, TileRecord]:
        tile = _make_tile("test:single", compose_group="kit", compose_role="single")
        return {tile.id: tile}

    def test_composite_tile_loader_rejects_empty_cells(self) -> None:
        raw = self._raw_composite()
        raw["cells"] = []

        with self.assertRaisesRegex(ValueError, "has no rows"):
            load_composite_tiles_from_data(
                (cast(CompositeTileConfig, raw),),
                family_id="testfam",
                tiles=self._tiles(),
            )

    def test_composite_tile_loader_rejects_ragged_cells(self) -> None:
        raw = self._raw_composite()
        raw["cells"] = [[{"role": "single"}], [{"role": "single"}, {"role": "single"}]]

        with self.assertRaisesRegex(ValueError, "has ragged cells"):
            load_composite_tiles_from_data(
                (cast(CompositeTileConfig, raw),),
                family_id="testfam",
                tiles=self._tiles(),
            )

    def test_composite_tile_loader_rejects_non_dict_cell(self) -> None:
        raw = self._raw_composite()
        raw["cells"] = [[17]]

        with self.assertRaisesRegex(ValueError, "cell must be a dict"):
            load_composite_tiles_from_data(
                (cast(CompositeTileConfig, raw),),
                family_id="testfam",
                tiles=self._tiles(),
            )


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

    def test_runtime_unit_omits_source_layout_ingest_attribute(self) -> None:
        # H3: source_layout is an ingest-only concern. The ingest TileFamily carries it;
        # the runtime library surface (TileLibraryUnit) must not expose it, so runtime
        # scene work cannot reach back into ingest-time layout facts.
        with tempfile.TemporaryDirectory() as temp_dir:
            family_dir = make_family_dir(Path(temp_dir), cluster_ids=["cluster.valid"])

            family = TileFamily.load(family_dir)
            unit = family.runtime_unit

            self.assertTrue(hasattr(family, "source_layout"))
            self.assertFalse(hasattr(unit, "source_layout"))
            self.assertEqual(unit.family_id, family.family_id)

    def test_composite_tile_record_validates_grid_and_lowers_cells(self) -> None:
        tile_a = _make_tile("tile.a", compose_role="body", affordances=("sit",))
        tile_b = _make_tile("tile.b", compose_role="head", affordances=("look",))
        composite = CompositeTileRecord(
            id="character.full",
            family_id="testfam",
            collection_id="characters",
            cells=(
                (CompositeTileCell(tile=tile_a, x=0, y=0),),
                (CompositeTileCell(tile=tile_b, x=0, y=1),),
            ),
        )

        lowered = lower_tile_asset_to_cells(composite)

        self.assertEqual(composite.width, 1)
        self.assertEqual(composite.height, 2)
        self.assertEqual([(cell.tile.id, cell.x, cell.y) for cell in lowered], [("tile.a", 0, 0), ("tile.b", 0, 1)])

    def test_composite_tile_record_rejects_mismatched_cell_coordinates(self) -> None:
        tile = _make_tile("tile.a")

        with self.assertRaisesRegex(ValueError, "cell coordinate must match grid position"):
            CompositeTileRecord(
                id="bad.composite",
                family_id="testfam",
                collection_id="characters",
                cells=((CompositeTileCell(tile=tile, x=1, y=0),),),
            )

    def test_composite_tile_record_rejects_non_rectangular_grid(self) -> None:
        tile = _make_tile("tile.a")

        with self.assertRaisesRegex(ValueError, "rectangular grid"):
            CompositeTileRecord(
                id="bad.composite",
                family_id="testfam",
                collection_id="characters",
                cells=((CompositeTileCell(tile=tile, x=0, y=0),), ()),
            )

    def test_composite_tile_record_rejects_empty_grid(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty rectangular grid"):
            CompositeTileRecord(
                id="bad.composite",
                family_id="testfam",
                collection_id="characters",
                cells=(),
            )

    def test_composite_tile_record_rejects_all_empty_cells(self) -> None:
        with self.assertRaisesRegex(ValueError, "contain at least one tile"):
            CompositeTileRecord(
                id="bad.composite",
                family_id="testfam",
                collection_id="characters",
                cells=((None,),),
            )

    def test_composite_tile_record_rejects_cross_family_cells(self) -> None:
        tile = _make_tile("tile.a", family_id="otherfam")

        with self.assertRaisesRegex(ValueError, "same family"):
            CompositeTileRecord(
                id="bad.composite",
                family_id="testfam",
                collection_id="characters",
                cells=((CompositeTileCell(tile=tile, x=0, y=0),),),
            )

    def test_entity_template_projects_atomic_tile_placeable(self) -> None:
        tile = _make_tile(
            "tile.a",
            compose_role="seat",
            affordances=("sit",),
            state_group="chair",
            animation_group="idle",
        )

        template = entity_template_from_placeable(tile)

        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.id, "tile.a")
        self.assertEqual(template.kind, "tile")
        self.assertEqual(template.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))
        self.assertEqual(template.construction_id, None)
        self.assertEqual(template.footprint.mode, "fixed")
        self.assertEqual(template.footprint.width, 1)
        self.assertEqual(template.footprint.height, 1)
        self.assertEqual(template.compose_roles, ("seat",))
        self.assertEqual(template.affordances, ("sit",))
        self.assertEqual(template.state_groups, ("chair",))
        self.assertEqual(template.animation_groups, ("idle",))

    def test_entity_template_projects_composite_tile_placeable_metadata(self) -> None:
        tile_a = _make_tile("tile.a", compose_role="body", affordances=("stand",), state_group="character")
        tile_b = _make_tile("tile.b", compose_role="head", affordances=("look",), animation_group="blink")
        composite = CompositeTileRecord(
            id="character.full",
            family_id="testfam",
            collection_id="characters",
            cells=(
                (CompositeTileCell(tile=tile_a, x=0, y=0),),
                (CompositeTileCell(tile=tile_b, x=0, y=1),),
            ),
        )

        template = entity_template_from_placeable(composite)

        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.id, "character.full")
        self.assertEqual(template.kind, "composite_tile")
        self.assertEqual(template.placeable_ref, PlaceableRef(kind="composite_tile", id="character.full"))
        self.assertEqual(template.construction_id, None)
        self.assertEqual(template.footprint.mode, "fixed")
        self.assertEqual(template.footprint.width, 1)
        self.assertEqual(template.footprint.height, 2)
        self.assertEqual(template.compose_roles, ("body", "head"))
        self.assertEqual(template.affordances, ("look", "stand"))
        self.assertEqual(template.state_groups, ("character",))
        self.assertEqual(template.animation_groups, ("blink",))

    def test_entity_template_omits_non_exposed_composite_placeable(self) -> None:
        tile = _make_tile("tile.a")
        composite = CompositeTileRecord(
            id="character.head",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile, x=0, y=0),),),
            expose_as_entity=False,
        )
        unit = _make_runtime_unit(family_id="testfam", tiles=(tile,), composite_tiles=(composite,))

        self.assertIsNone(entity_template_from_placeable(composite))
        self.assertEqual(unit.entity_templates(), [])

    def test_runtime_unit_projects_composite_attachment_set_on_entity_template(self) -> None:
        body_tile = _make_tile("body.tile")
        head_tile = _make_tile("head.tile")
        body = CompositeTileRecord(
            id="character.body",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=body_tile, x=0, y=0),),),
        )
        head = CompositeTileRecord(
            id="character.head",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=head_tile, x=0, y=0),),),
            expose_as_entity=False,
        )
        attachment_set = ConstructionAttachmentSet(
            id="character.body.heads",
            param="head",
            canvas=GridBounds(x=0, y=0, width=1, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            variants={
                "alt": ConstructionAttachmentVariant(
                    id="alt",
                    placeable_kind="composite_tile",
                    placeable_id="character.head",
                )
            },
            required=True,
        )
        unit = _make_runtime_unit(
            family_id="testfam",
            tiles=(body_tile, head_tile),
            composite_tiles=(body, head),
            attachment_sets=(attachment_set,),
        )

        template = unit.entity_template_for_placeable(PlaceableRef(kind="composite_tile", id="character.body"))

        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(len(template.attachment_sets), 1)
        self.assertEqual(template.attachment_sets[0].param, "head")
        self.assertEqual(unit.attachment_sets_for_placeable(PlaceableRef(kind="composite_tile", id="character.body")), (attachment_set,))

    def test_attachment_variant_rejects_compatibility_construction_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "construction_id is only valid"):
            ConstructionAttachmentVariant(
                id="bad",
                construction_id="construction.head",
                placeable_kind="composite_tile",
                placeable_id="character.head",
            )

    def test_attachment_variant_requires_placeable_id_for_non_construction_placeable(self) -> None:
        with self.assertRaisesRegex(ValueError, "placeable_id is required"):
            ConstructionAttachmentVariant(
                id="bad",
                placeable_kind="composite_tile",
            )

    def test_attachment_variant_rejects_empty_placeable_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "placeable_id must not be empty"):
            ConstructionAttachmentVariant(
                id="bad",
                placeable_kind="composite_tile",
                placeable_id="",
            )

    def test_attachment_set_rejects_compatibility_target_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "target_construction_ids is only valid"):
            ConstructionAttachmentSet(
                id="bad.targets",
                param="head",
                canvas=GridBounds(x=0, y=0, width=1, height=1),
                variants={
                    "alt": ConstructionAttachmentVariant(
                        id="alt",
                        placeable_kind="composite_tile",
                        placeable_id="character.head",
                    )
                },
                target_construction_ids=("construction.body",),
                target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            )

    def test_attachment_set_requires_target_placeables(self) -> None:
        with self.assertRaisesRegex(ValueError, "target_placeable_refs must not be empty"):
            ConstructionAttachmentSet(
                id="bad.targets",
                param="head",
                canvas=GridBounds(x=0, y=0, width=1, height=1),
                variants={
                    "alt": ConstructionAttachmentVariant(
                        id="alt",
                        placeable_kind="composite_tile",
                        placeable_id="character.head",
                    )
                },
            )

    def test_runtime_unit_rejects_unknown_attachment_target_placeable(self) -> None:
        head_tile = _make_tile("head.tile")
        head = CompositeTileRecord(
            id="character.head",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=head_tile, x=0, y=0),),),
            expose_as_entity=False,
        )
        attachment_set = ConstructionAttachmentSet(
            id="character.body.heads",
            param="head",
            canvas=GridBounds(x=0, y=0, width=1, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="missing.body"),),
            variants={
                "alt": ConstructionAttachmentVariant(
                    id="alt",
                    placeable_kind="composite_tile",
                    placeable_id="character.head",
                )
            },
            required=True,
        )

        with self.assertRaisesRegex(ValueError, "unknown target placeable"):
            _make_runtime_unit(
                family_id="testfam",
                tiles=(head_tile,),
                composite_tiles=(head,),
                attachment_sets=(attachment_set,),
            )

    def test_runtime_unit_rejects_unknown_attachment_fill_placeable(self) -> None:
        body_tile = _make_tile("body.tile")
        body = CompositeTileRecord(
            id="character.body",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=body_tile, x=0, y=0),),),
        )
        attachment_set = ConstructionAttachmentSet(
            id="character.body.heads",
            param="head",
            canvas=GridBounds(x=0, y=0, width=1, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            variants={
                "alt": ConstructionAttachmentVariant(
                    id="alt",
                    placeable_kind="composite_tile",
                    placeable_id="missing.head",
                )
            },
            required=True,
        )

        with self.assertRaisesRegex(ValueError, "references unknown placeable"):
            _make_runtime_unit(
                family_id="testfam",
                tiles=(body_tile,),
                composite_tiles=(body,),
                attachment_sets=(attachment_set,),
            )

    def test_runtime_unit_rejects_composite_attachment_fill_that_exceeds_canvas(self) -> None:
        body_tile = _make_tile("body.tile")
        head_left = _make_tile("head.left")
        head_right = _make_tile("head.right")
        body = CompositeTileRecord(
            id="character.body",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=body_tile, x=0, y=0),),),
        )
        wide_head = CompositeTileRecord(
            id="character.head.wide",
            family_id="testfam",
            collection_id="characters",
            cells=(
                (
                    CompositeTileCell(tile=head_left, x=0, y=0),
                    CompositeTileCell(tile=head_right, x=1, y=0),
                ),
            ),
            expose_as_entity=False,
        )
        attachment_set = ConstructionAttachmentSet(
            id="character.body.heads",
            param="head",
            canvas=GridBounds(x=0, y=0, width=1, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            variants={
                "wide": ConstructionAttachmentVariant(
                    id="wide",
                    placeable_kind="composite_tile",
                    placeable_id="character.head.wide",
                )
            },
            required=True,
        )

        with self.assertRaisesRegex(ValueError, "exceeds canvas"):
            _make_runtime_unit(
                family_id="testfam",
                tiles=(body_tile, head_left, head_right),
                composite_tiles=(body, wide_head),
                attachment_sets=(attachment_set,),
            )

    def test_runtime_unit_rejects_composite_attachment_canvas_outside_target(self) -> None:
        body_tile = _make_tile("body.tile")
        head_tile = _make_tile("head.tile")
        body = CompositeTileRecord(
            id="character.body",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=body_tile, x=0, y=0),),),
        )
        head = CompositeTileRecord(
            id="character.head",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=head_tile, x=0, y=0),),),
            expose_as_entity=False,
        )
        attachment_set = ConstructionAttachmentSet(
            id="character.body.heads",
            param="head",
            canvas=GridBounds(x=1, y=0, width=1, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            variants={
                "alt": ConstructionAttachmentVariant(
                    id="alt",
                    placeable_kind="composite_tile",
                    placeable_id="character.head",
                )
            },
            required=True,
        )

        with self.assertRaisesRegex(ValueError, "must stay inside target placeable"):
            _make_runtime_unit(
                family_id="testfam",
                tiles=(body_tile, head_tile),
                composite_tiles=(body, head),
                attachment_sets=(attachment_set,),
            )

    def test_connection_surface_for_atomic_tile_uses_one_segment_per_side(self) -> None:
        tile = _make_tile(
            "tile.a",
            seam_profiles={
                "north": (True, False),
                "south": (False, True),
                "east": (True, True),
                "west": (False, False),
            },
        )

        surface = connection_surface_for_placeable(tile)

        north = surface.segments("north")
        self.assertEqual(len(north), 1)
        self.assertEqual(north[0].offset, 0)
        self.assertEqual(north[0].local_x, 0)
        self.assertEqual(north[0].local_y, 0)
        self.assertEqual(north[0].tile_id, "tile.a")
        self.assertEqual(north[0].mask, (True, False))

    def test_connection_surface_for_composite_tile_uses_outer_perimeter_only(self) -> None:
        tile_a = _make_tile("tile.a")
        tile_b = _make_tile("tile.b")
        tile_c = _make_tile("tile.c")
        tile_d = _make_tile("tile.d")
        composite = CompositeTileRecord(
            id="block.2x2",
            family_id="testfam",
            collection_id="blocks",
            cells=(
                (CompositeTileCell(tile=tile_a, x=0, y=0), CompositeTileCell(tile=tile_b, x=1, y=0)),
                (CompositeTileCell(tile=tile_c, x=0, y=1), CompositeTileCell(tile=tile_d, x=1, y=1)),
            ),
        )

        surface = connection_surface_for_placeable(composite)

        self.assertEqual([(segment.offset, segment.tile_id) for segment in surface.segments("north")], [(0, "tile.a"), (1, "tile.b")])
        self.assertEqual([(segment.offset, segment.tile_id) for segment in surface.segments("south")], [(0, "tile.c"), (1, "tile.d")])
        self.assertEqual([(segment.offset, segment.tile_id) for segment in surface.segments("west")], [(0, "tile.a"), (1, "tile.c")])
        self.assertEqual([(segment.offset, segment.tile_id) for segment in surface.segments("east")], [(0, "tile.b"), (1, "tile.d")])

    def test_connection_surface_for_sparse_composite_keeps_distinct_local_edges(self) -> None:
        tile_a = _make_tile("tile.a")
        tile_b = _make_tile("tile.b")
        composite = CompositeTileRecord(
            id="sparse.column",
            family_id="testfam",
            collection_id="blocks",
            cells=(
                (CompositeTileCell(tile=tile_a, x=0, y=0),),
                (None,),
                (CompositeTileCell(tile=tile_b, x=0, y=2),),
            ),
        )

        surface = connection_surface_for_placeable(composite)

        self.assertEqual(
            [(segment.offset, segment.local_x, segment.local_y, segment.tile_id) for segment in surface.segments("north")],
            [(0, 0, 0, "tile.a"), (0, 0, 2, "tile.b")],
        )

    def test_registry_resolves_composite_tile_placeables_per_kind(self) -> None:
        tile = _make_tile("shared.id")
        composite = CompositeTileRecord(
            id="shared.id",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile, x=0, y=0),),),
        )
        registry = TileLibraryRegistry.from_units(
            [_make_runtime_unit(family_id="testfam", tiles=(tile,), composite_tiles=(composite,))]
        )

        tile_placeable = registry.lookup_placeable(PlaceableRef(kind="tile", id="shared.id"))
        composite_placeable = registry.lookup_placeable(PlaceableRef(kind="composite_tile", id="shared.id"))

        self.assertIs(tile_placeable, tile)
        self.assertIs(composite_placeable, composite)
        composite_template = registry.entity_template_for_placeable(PlaceableRef(kind="composite_tile", id="shared.id"))
        self.assertIsNotNone(composite_template)
        assert composite_template is not None
        self.assertEqual(composite_template.placeable_ref, PlaceableRef(kind="composite_tile", id="shared.id"))

    def test_registry_rejects_duplicate_composite_tile_ids_per_kind(self) -> None:
        tile_a = _make_tile("tile.a", family_id="family.a")
        tile_b = _make_tile("tile.b", family_id="family.b")
        composite_a = CompositeTileRecord(
            id="character.full",
            family_id="family.a",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile_a, x=0, y=0),),),
        )
        composite_b = CompositeTileRecord(
            id="character.full",
            family_id="family.b",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile_b, x=0, y=0),),),
        )

        with self.assertRaisesRegex(ValueError, "Duplicate composite tile id across tile library units"):
            TileLibraryRegistry.from_units(
                [
                    _make_runtime_unit(family_id="family.a", tiles=(tile_a,), composite_tiles=(composite_a,)),
                    _make_runtime_unit(family_id="family.b", tiles=(tile_b,), composite_tiles=(composite_b,)),
                ]
            )

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

    def test_registry_resolves_attachment_sets_for_construction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            attachment_family = TileFamily.load(make_attachment_family_dir(root))
            other_family = TileFamily.load(
                make_family_dir(
                    root,
                    cluster_ids=["cluster.valid"],
                    family_id="family.other",
                    alias_name="alias.other",
                    directory_name="other_family",
                    construction_id="construction.other",
                )
            )

            registry = TileLibraryRegistry.from_units([attachment_family.runtime_unit, other_family.runtime_unit])

            attachment_sets = registry.attachment_sets_for_construction("test.body")
            self.assertEqual(len(attachment_sets), 1)
            self.assertEqual(attachment_sets[0].param, "head")
            self.assertEqual(registry.attachment_sets_for_construction("missing.construction"), ())

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


class FixedConstructionSeamValidationTests(unittest.TestCase):
    def test_fixed_rejects_east_west_seam_mismatch_without_override(self) -> None:
        tl = _make_tile("t:tl", compose_group="kit", compose_role="tl", seam_profiles={"east": _MISMATCH_SEAM})
        tr = _make_tile("t:tr", compose_group="kit", compose_role="tr")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "tl"}, {"role": "tr"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(tl, tr))
        msg = str(ctx.exception)
        self.assertIn("test.fixed", msg)
        self.assertIn("col=0", msg)
        self.assertIn("row=0", msg)
        self.assertIn("seams do not fit", msg)
        self.assertIn("equality=0.500", msg)

    def test_fixed_rejects_south_north_seam_mismatch_without_override(self) -> None:
        top = _make_tile("t:top", compose_group="kit", compose_role="top", seam_profiles={"south": _MISMATCH_SEAM})
        bot = _make_tile("t:bot", compose_group="kit", compose_role="bot")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "top"}],
                [{"role": "bot"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(top, bot))
        msg = str(ctx.exception)
        self.assertIn("test.fixed", msg)
        self.assertIn("col=0, row=0", msg)
        self.assertIn("south", msg)
        self.assertIn("seams do not fit", msg)

    def test_fixed_accepts_mismatch_with_recorded_override(self) -> None:
        left = _make_tile("t:left", compose_group="kit", compose_role="left", seam_profiles={"east": _MISMATCH_SEAM})
        right = _make_tile("t:right", compose_group="kit", compose_role="right")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "left"}, {"role": "right"}],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "Intentional silhouette mismatch.",
                }
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(left, right))
        assert isinstance(construction, FixedConstruction)
        self.assertEqual(len(construction.seam_overrides), 1)
        self.assertEqual(construction.seam_overrides[0].reason, "Intentional silhouette mismatch.")

    def test_fixed_rejects_unnecessary_override_when_seam_fits(self) -> None:
        left = _make_tile("t:left", compose_group="kit", compose_role="left")
        right = _make_tile("t:right", compose_group="kit", compose_role="right")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "left"}, {"role": "right"}],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "Previously mismatched seam.",
                }
            ],
        }
        with self.assertRaisesRegex(ConstructionValidationError, "seam override is unnecessary"):
            build_construction(raw, tiles=_make_tiles_dict(left, right))

    def test_fixed_seam_validation_ignores_connects_on_flags(self) -> None:
        left = _make_tile("t:left", compose_group="kit", compose_role="left", connects_on=[])
        right = _make_tile("t:right", compose_group="kit", compose_role="right", connects_on=[])
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "left"}, {"role": "right"}],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(left, right))
        self.assertEqual(construction.id, "test.fixed")

    def test_fixed_rejects_override_for_non_canonical_side(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": 0, "y": 0},
                        "side": "west",
                        "reason": "Wrong side.",
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "side must be 'east' or 'south'"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_override_with_non_string_side(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": 0, "y": 0},
                        "side": 0,
                        "reason": "Bad side.",
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, r"seam_overrides\[0\]: side must be a string"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_override_without_reason(self) -> None:
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [["."]],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "reason must not be empty"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_override_with_non_string_reason(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": 0, "y": 0},
                        "side": "east",
                        "reason": 0,
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, r"seam_overrides\[0\]: reason must be a string"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_override_with_non_integer_cell_coordinate(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": "0", "y": 0},
                        "side": "east",
                        "reason": "Bad coordinate.",
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "cell x and y must be integers"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_override_with_boolean_cell_coordinate(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": True, "y": 0},
                        "side": "east",
                        "reason": "Bad coordinate.",
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "cell x and y must be integers"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_manifest_override_with_contextual_negative_coordinate(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.fixed",
                "collection_id": "kit",
                "kind": "fixed",
                "cells": [["."]],
                "seam_overrides": [
                    {
                        "cell": {"x": -1, "y": 0},
                        "side": "east",
                        "reason": "Bad coordinate.",
                    }
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, r"seam_overrides\[0\].*coordinates must be non-negative"):
            build_construction(raw, tiles={})

    def test_fixed_rejects_duplicate_override_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate seam override"):
            FixedConstruction(
                id="test.fixed",
                collection_id="kit",
                cells=((None,),),
                seam_overrides=(
                    FixedConstructionSeamOverride(x=0, y=0, side="east", reason="First."),
                    FixedConstructionSeamOverride(x=0, y=0, side="east", reason="Second."),
                ),
            )

    def test_fixed_rejects_override_with_negative_coordinate(self) -> None:
        with self.assertRaisesRegex(ValueError, "coordinates must be non-negative"):
            FixedConstructionSeamOverride(x=-1, y=0, side="east", reason="Bad coordinate.")

    def test_fixed_rejects_override_with_invalid_runtime_side(self) -> None:
        with self.assertRaisesRegex(ValueError, "side must be 'east' or 'south'"):
            FixedConstructionSeamOverride(
                x=0,
                y=0,
                side=cast(FixedSeamOverrideSide, "west"),
                reason="Bad side.",
            )

    def test_fixed_rejects_override_with_blank_runtime_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason must not be empty"):
            FixedConstructionSeamOverride(x=0, y=0, side="east", reason=" ")

    def test_fixed_rejects_override_outside_grid(self) -> None:
        tile = _make_tile("t:tile", compose_group="kit", compose_role="tile")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "tile"}],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 3, "y": 0},
                    "side": "east",
                    "reason": "Outside grid.",
                }
            ],
        }
        with self.assertRaisesRegex(ConstructionValidationError, "outside the fixed construction grid"):
            build_construction(raw, tiles=_make_tiles_dict(tile))

    def test_fixed_rejects_override_for_empty_cell(self) -> None:
        tile = _make_tile("t:tile", compose_group="kit", compose_role="tile")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [".", {"role": "tile"}],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "Empty cell.",
                }
            ],
        }
        with self.assertRaisesRegex(ConstructionValidationError, "references an empty cell"):
            build_construction(raw, tiles=_make_tiles_dict(tile))

    def test_fixed_rejects_override_without_internal_neighbour(self) -> None:
        tile = _make_tile("t:tile", compose_group="kit", compose_role="tile")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "tile"}],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "No neighbour.",
                }
            ],
        }
        with self.assertRaisesRegex(ConstructionValidationError, "does not reference a filled internal neighbour"):
            build_construction(raw, tiles=_make_tiles_dict(tile))

    def test_fixed_rejects_override_with_empty_internal_neighbour(self) -> None:
        tile = _make_tile("t:tile", compose_group="kit", compose_role="tile")
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "tile"}, "."],
            ],
            "seam_overrides": [
                {
                    "cell": {"x": 0, "y": 0},
                    "side": "east",
                    "reason": "Empty neighbour.",
                }
            ],
        }
        with self.assertRaisesRegex(ConstructionValidationError, "does not reference a filled internal neighbour"):
            build_construction(raw, tiles=_make_tiles_dict(tile))


# A contact line whose painted run is neither equal nor complementary to a fully
# painted facing edge: equality 0.5, complement 0.5, so the exact policy rejects it.
_MISMATCH_SEAM: tuple[bool, ...] = (True, True, True, True, False, False, False, False)


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
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "top"}],
                [{"role": "bot"}],
            ],
        }
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(top, bot))
        msg = str(ctx.exception)
        self.assertIn("test.fixed", msg)
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
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "top"}],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(top))
        assert isinstance(construction, FixedConstruction)
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
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "left"}, {"role": "right"}],
                [".", "."],
            ],
        }
        construction = build_construction(raw, tiles=_make_tiles_dict(left, right))
        assert isinstance(construction, FixedConstruction)
        self.assertIsNone(construction.cells[1][0])


class ConstructionRoleBindingTests(unittest.TestCase):
    def test_construction_manifest_rejects_unknown_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "constructions.json"
            write_json(
                path,
                {
                    "constructions": [
                        {
                            "id": "test.bad",
                            "collection_id": "kit",
                            "kind": "metatile",
                            "cells": [["."]],
                        }
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "unsupported construction kind 'metatile'"):
                load_construction_manifest(path)

    def test_build_construction_rejects_unknown_kind(self) -> None:
        raw = cast(
            ConstructionConfig,
            {
                "id": "test.bad",
                "collection_id": "kit",
                "kind": "metatile",
                "cells": [["."]],
            },
        )

        with self.assertRaisesRegex(ValueError, "unsupported kind 'metatile'"):
            build_construction(raw, tiles={})

    def test_role_binding_multiple_matches_raises(self) -> None:
        t1 = _make_tile("t:tile1", compose_group="kit", compose_role="body", connects_on=[])
        t2 = _make_tile("t:tile2", compose_group="kit", compose_role="body", connects_on=[])
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "body"}],
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            build_construction(raw, tiles=_make_tiles_dict(t1, t2))
        msg = str(ctx.exception)
        self.assertIn("test.fixed", msg)
        self.assertIn("body", msg)
        self.assertIn("multiple", msg)

    def test_role_binding_no_match_raises(self) -> None:
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                [{"role": "ghost_role"}],
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            build_construction(raw, tiles={})
        msg = str(ctx.exception)
        self.assertIn("test.fixed", msg)
        self.assertIn("ghost_role", msg)
        self.assertIn("no tile found", msg)

    def test_role_binding_dot_cell_resolves_to_none(self) -> None:
        raw: ConstructionConfig = {
            "id": "test.fixed",
            "collection_id": "kit",
            "kind": "fixed",
            "cells": [
                ["."],
            ],
        }
        construction = build_construction(raw, tiles={})
        assert isinstance(construction, FixedConstruction)
        self.assertIsNone(construction.cells[0][0])


class ParametricRunValidationTests(unittest.TestCase):
    def _make_run_tiles(
        self,
        *,
        start_seams: dict[str, tuple[bool, ...]] | None = None,
        repeat_seams: dict[str, tuple[bool, ...]] | None = None,
        end_seams: dict[str, tuple[bool, ...]] | None = None,
    ) -> dict[str, TileRecord]:
        start = _make_tile("t:start", compose_group="kit", compose_role="start_role", seam_profiles=start_seams)
        repeat = _make_tile("t:repeat", compose_group="kit", compose_role="repeat_role", seam_profiles=repeat_seams)
        end = _make_tile("t:end", compose_group="kit", compose_role="end_role", seam_profiles=end_seams)
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
        # Fully-painted tiles fit on the start|repeat, repeat|repeat, repeat|end seams.
        tiles = self._make_run_tiles()
        construction = build_construction(self._raw_run(), tiles=tiles)
        self.assertEqual(construction.id, "test.run")
        self.assertIsInstance(construction, ParametricRunConstruction)
        assert isinstance(construction, ParametricRunConstruction)
        self.assertEqual(construction.axis, "x")
        self.assertEqual(construction.length_param, "length")
        self.assertIsNotNone(construction.start_tile)
        self.assertIsNotNone(construction.repeat_tile)
        self.assertIsNotNone(construction.end_tile)

    def test_start_to_repeat_seam_mismatch_fails(self) -> None:
        tiles = self._make_run_tiles(start_seams={"east": _MISMATCH_SEAM})
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("start_role to repeat_role", str(ctx.exception))

    def test_repeat_to_repeat_seam_mismatch_fails(self) -> None:
        # start|repeat fits (start.east full vs repeat.west full); the repeat tile's
        # own forward seam does not match its backward seam.
        tiles = self._make_run_tiles(repeat_seams={"east": _MISMATCH_SEAM})
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("repeat_role to repeat_role", str(ctx.exception))

    def test_repeat_to_end_seam_mismatch_fails(self) -> None:
        tiles = self._make_run_tiles(end_seams={"west": _MISMATCH_SEAM})
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=tiles)
        self.assertIn("repeat_role to end_role", str(ctx.exception))

    def test_interlocking_run_passes_via_complement_matcher(self) -> None:
        # A tab/slot run where each forward edge is the complement of the backward
        # edge it abuts: the complement matcher (D6) accepts it though equality would not.
        top: tuple[bool, ...] = (True, True, True, True, False, False, False, False)
        bottom: tuple[bool, ...] = (False, False, False, False, True, True, True, True)
        tiles = self._make_run_tiles(
            start_seams={"east": bottom},
            repeat_seams={"west": top, "east": bottom},
            end_seams={"west": top},
        )
        construction = build_construction(self._raw_run(), tiles=tiles)
        self.assertEqual(construction.id, "test.run")

    def test_run_rejects_mismatch_even_when_connects_on_declared(self) -> None:
        # Headline of the flip: declaring the connecting direction in connects_on on
        # both pieces (what the old validator required and accepted) is no longer
        # sufficient - the seam check rejects pieces whose silhouettes do not tile.
        start = _make_tile(
            "t:start", compose_group="kit", compose_role="start_role",
            connects_on=["east"], seam_profiles={"east": _MISMATCH_SEAM},
        )
        repeat = _make_tile("t:repeat", compose_group="kit", compose_role="repeat_role", connects_on=["west", "east"])
        end = _make_tile("t:end", compose_group="kit", compose_role="end_role", connects_on=["west"])
        # The retired connects_on membership check would have passed:
        self.assertIn("east", start.connects_on)
        self.assertIn("west", repeat.connects_on)
        with self.assertRaises(ConstructionValidationError) as ctx:
            build_construction(self._raw_run(), tiles=_make_tiles_dict(start, repeat, end))
        self.assertIn("start_role to repeat_role", str(ctx.exception))

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


class ParametricFrameConstructionBuildTests(unittest.TestCase):
    def _frame_tiles(self) -> dict[str, TileRecord]:
        group = "ui.frame.gold.smooth"
        return _make_tiles_dict(
            _make_tile("t:tl", compose_group=group, compose_role="corner_tl"),
            _make_tile("t:tr", compose_group=group, compose_role="corner_tr"),
            _make_tile("t:bl", compose_group=group, compose_role="corner_bl"),
            _make_tile("t:br", compose_group=group, compose_role="corner_br"),
            _make_tile("t:top", compose_group=group, compose_role="edge_top"),
            _make_tile("t:bottom", compose_group=group, compose_role="edge_bottom"),
            _make_tile("t:left", compose_group=group, compose_role="edge_left"),
            _make_tile("t:right", compose_group=group, compose_role="edge_right"),
            _make_tile("t:fill", compose_group=group, compose_role="fill"),
        )

    def _full_raw(self) -> dict[str, object]:
        return {
            "id": "ui.frame.gold.smooth",
            "collection_id": "ui.frame.gold.smooth",
            "kind": "parametric_frame",
            "corners": ["tl", "tr", "bl", "br"],
            "edges": {
                "top": {"fill_mode": "repeat"},
                "bottom": {"fill_mode": "repeat"},
                "left": {"fill_mode": "repeat"},
                "right": {"fill_mode": "repeat"},
            },
            "fill": {"fill_mode": "repeat"},
        }

    def test_build_raises_on_non_mapping_edge_slot(self) -> None:
        raw = self._full_raw()
        edges = cast("dict[str, object]", raw["edges"])
        edges["top"] = "repeat"  # wrong shape — must be a mapping
        with self.assertRaisesRegex(ValueError, "edge_top"):
            build_construction(raw, tiles=self._frame_tiles())  # type: ignore[arg-type]

    def test_build_resolves_all_nine_slots(self) -> None:
        construction = build_construction(self._full_raw(), tiles=self._frame_tiles())  # type: ignore[arg-type]
        assert isinstance(construction, ParametricFrameConstruction)
        self.assertEqual(construction.kind, "parametric_frame")
        self.assertEqual(construction.id, "ui.frame.gold.smooth")
        self.assertEqual(construction.corners["corner_tl"].tiles()[0].id, "t:tl")
        self.assertEqual(construction.corners["corner_br"].tiles()[0].id, "t:br")
        self.assertEqual(set(construction.corners), {"corner_tl", "corner_tr", "corner_bl", "corner_br"})
        self.assertEqual(construction.edges["edge_top"].tile.id, "t:top")
        self.assertEqual(construction.edges["edge_top"].fill_mode, "repeat")
        self.assertEqual(set(construction.edges), {"edge_top", "edge_bottom", "edge_left", "edge_right"})
        self.assertIsNotNone(construction.fill)
        assert construction.fill is not None
        self.assertEqual(construction.fill.tile.id, "t:fill")
        self.assertEqual(construction.fill.fill_mode, "repeat")
        self.assertEqual(construction.min_width, 2)
        self.assertEqual(construction.min_height, 2)

    def test_build_defaults_expose_as_entity_to_true(self) -> None:
        # The renderer/footprint/entity paths now support parametric_frame, so a
        # built frame defaults to a materialisable entity like other kinds.
        construction = build_construction(self._full_raw(), tiles=self._frame_tiles())  # type: ignore[arg-type]
        assert isinstance(construction, ParametricFrameConstruction)
        self.assertTrue(construction.expose_as_entity)

    def test_build_resolves_width_and_height_params_with_defaults(self) -> None:
        construction = build_construction(self._full_raw(), tiles=self._frame_tiles())  # type: ignore[arg-type]
        assert isinstance(construction, ParametricFrameConstruction)
        self.assertEqual(construction.width_param, "width")
        self.assertEqual(construction.height_param, "height")

    def test_minimal8_gold_smooth_loads_as_full_parametric_frame(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        construction = family.lookup_construction("ui.frame.gold.smooth")
        self.assertIsNotNone(construction)
        assert isinstance(construction, ParametricFrameConstruction)
        self.assertTrue(construction.expose_as_entity)
        self.assertEqual(set(construction.corners), {"corner_tl", "corner_tr", "corner_bl", "corner_br"})
        self.assertEqual(set(construction.edges), {"edge_top", "edge_bottom", "edge_left", "edge_right"})
        self.assertIsNotNone(construction.fill)

    def test_minimal8_panel_smooth_loads_as_corner_only_parametric_frame(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        construction = family.lookup_construction("ui.frame.panel.smooth")
        self.assertIsNotNone(construction)
        assert isinstance(construction, ParametricFrameConstruction)
        self.assertEqual(set(construction.corners), {"corner_tl", "corner_tr", "corner_bl", "corner_br"})
        self.assertEqual(dict(construction.edges), {})
        self.assertIsNone(construction.fill)


class SeamProfileDerivationTests(unittest.TestCase):
    def test_top_left_gutter_resolves_to_null_seams_on_north_and_east(self) -> None:
        # A tile that keys its top row and right column to the sheet background
        # (top_left transparent mode) leaves an L-shaped painted body. Seam
        # derivation must normalise first, so the gutter reads as "no seam".
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
            key = (255, 0, 0, 255)
            paint = (0, 0, 255, 255)
            image = Image.new("RGBA", (8, 8), paint)
            for x in range(8):
                image.putpixel((x, 0), key)  # top row -> keyed to transparent
            for y in range(8):
                image.putpixel((7, y), key)  # right column -> keyed to transparent
            image.save(family_dir / "sheet.png")
            family_json = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
            cast(list[dict[str, object]], family_json["variants"])[0]["transparent"] = "top_left"
            write_json(family_dir / "family.json", family_json)

            family = TileFamily.load(family_dir)
            tile = family.tiles["testfam:all:0,0"]
            assert tile.seam_profiles is not None
            # north (top row L->R) and east (right col T->B) are pure gutter -> null
            self.assertEqual(tile.seam_profiles["north"], (False,) * 8)
            self.assertEqual(tile.seam_profiles["east"], (False,) * 8)
            # south (bottom row L->R): painted except the gutter pixel at x=7
            self.assertEqual(tile.seam_profiles["south"], (True,) * 7 + (False,))
            # west (left col T->B): gutter pixel at y=0, painted below
            self.assertEqual(tile.seam_profiles["west"], (False,) + (True,) * 7)

    def test_invalid_family_inset_value_fails_with_context(self) -> None:
        # A bad inset at the manifest boundary must fail loudly, not silently flatten to 0.
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
            family_json = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
            family_json["cell_content_inset"] = {"right": [1]}  # not an int
            write_json(family_dir / "family.json", family_json)
            with self.assertRaisesRegex(ValueError, "cell_content_inset"):
                TileFamily.load(family_dir)

    def test_negative_family_inset_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
            family_json = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
            family_json["cell_content_inset"] = {"top": -1}
            write_json(family_dir / "family.json", family_json)
            with self.assertRaisesRegex(ValueError, "non-negative"):
                TileFamily.load(family_dir)

    def _gutter_family(self, tmp: str) -> Path:
        """A family whose sheet has a 1px top+right keyed gutter (top_left mode)."""
        family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
        key = (255, 0, 0, 255)
        paint = (0, 0, 255, 255)
        image = Image.new("RGBA", (8, 8), paint)
        for x in range(8):
            image.putpixel((x, 0), key)  # top gutter
        for y in range(8):
            image.putpixel((7, y), key)  # right gutter
        image.save(family_dir / "sheet.png")
        family_json = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
        cast(list[dict[str, object]], family_json["variants"])[0]["transparent"] = "top_left"
        family_json["cell_content_inset"] = {"top": 1, "right": 1}
        write_json(family_dir / "family.json", family_json)
        return family_dir

    def test_family_cell_content_inset_reads_content_box_edge(self) -> None:
        # With a declared family gutter (top=1, right=1), seam derivation reads the
        # content-box edge, so the guttered north/east sides carry content (ADR 0008).
        with tempfile.TemporaryDirectory() as tmp:
            tile = TileFamily.load(self._gutter_family(tmp)).tiles["testfam:all:0,0"]
            assert tile.seam_profiles is not None
            self.assertEqual(tile.seam_profiles["east"], (False,) + (True,) * 7)  # col 6, below top gutter
            self.assertEqual(tile.seam_profiles["north"], (True,) * 7 + (False,))  # row 1, minus right gutter

    def test_per_tile_inset_override_beats_family_default(self) -> None:
        # A full-bleed tile can override the family gutter back to inset 0 (literal edge).
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = self._gutter_family(tmp)
            tiles = cast(list[dict[str, object]], json.loads((family_dir / "tiles.json").read_text(encoding="utf-8")))
            tiles[0]["cell_content_inset"] = {"top": 0, "right": 0}
            write_json(family_dir / "tiles.json", tiles)
            tile = TileFamily.load(family_dir).tiles["testfam:all:0,0"]
            assert tile.seam_profiles is not None
            # override -> literal edges -> the gutter reads as null again
            self.assertEqual(tile.seam_profiles["east"], (False,) * 8)
            self.assertEqual(tile.seam_profiles["north"], (False,) * 8)

    def test_adjacent_gutter_tiles_match_via_matchpolicy_through_inset(self) -> None:
        # End-to-end (ADR 0008 headline): two horizontally adjacent guttered tiles
        # whose content edges meet. Reading at the content-box edge makes A.east
        # (inset 1) compare content-to-content with B.west (literal); at the literal
        # cell edge A.east would be the null gutter and the pair would fail to match.
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = Path(tmp) / "adj"
            family_dir.mkdir()
            key = (255, 0, 0, 255)
            paint = (0, 0, 255, 255)
            image = Image.new("RGBA", (16, 8), paint)
            for x in range(16):
                image.putpixel((x, 0), key)  # shared top gutter
            for y in range(8):
                image.putpixel((7, y), key)  # cell-0 right gutter
                image.putpixel((15, y), key)  # cell-1 right gutter
            image.save(family_dir / "sheet.png")
            write_json(family_dir / "family.json", {
                "family_id": "adjfam",
                "grid": {"tile_width": 8, "tile_height": 8},
                "default_variant_id": "base",
                "variants": [{"variant_id": "base", "sheet": "sheet.png", "transparent": "top_left"}],
                "cell_content_inset": {"top": 1, "right": 1},
            })
            write_json(family_dir / "aliases.json", {})
            write_json(family_dir / "clusters.json", [])
            common = {"layer": "map", "category": "tile", "transparent": False, "meaning_confidence": "confirmed"}
            write_json(family_dir / "tiles.json", [
                {"id": "adjfam:all:0,0", "sheet_col": 0, "sheet_row": 0, **common},
                {"id": "adjfam:all:1,0", "sheet_col": 1, "sheet_row": 0, **common},
            ])

            fam = TileFamily.load(family_dir)
            a, b = fam.tiles["adjfam:all:0,0"], fam.tiles["adjfam:all:1,0"]
            assert a.seam_profiles is not None and b.seam_profiles is not None
            policy = MatchPolicy()
            self.assertTrue(any(a.seam_profiles["east"]))  # content edge, not the null gutter
            self.assertTrue(policy.fits(a.seam_profiles["east"], b.seam_profiles["west"]))
            # the literal cell edge (the all-null gutter) would NOT have matched B.west
            self.assertFalse(policy.fits((False,) * 8, b.seam_profiles["west"]))

    def test_oversized_inset_fails_with_manifest_context(self) -> None:
        # M2: a declared inset that cannot fit the tile fails with a manifest-path message.
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
            family_json = cast(dict[str, object], json.loads((family_dir / "family.json").read_text(encoding="utf-8")))
            family_json["cell_content_inset"] = {"right": 8}  # == tile width, out of range
            write_json(family_dir / "family.json", family_json)
            with self.assertRaisesRegex(ValueError, "cell_content_inset.*tile width"):
                TileFamily.load(family_dir)

    def test_image_override_tile_derives_masks_from_override_pixels(self) -> None:
        # Synthetic (image_override) tiles take the override branch of
        # _tile_occupancy_grid: genuine alpha, no background keying.
        with tempfile.TemporaryDirectory() as tmp:
            family_dir = make_family_dir(Path(tmp), cluster_ids=["cluster.valid"])
            override = Image.new("RGBA", (8, 8), (0, 0, 0, 0))  # transparent body
            for y in range(8):
                override.putpixel((0, y), (10, 20, 30, 255))  # paint the left column only
            (family_dir / "derived").mkdir()
            override.save(family_dir / "derived" / "synth.png")
            tiles = cast(list[dict[str, object]], json.loads((family_dir / "tiles.json").read_text(encoding="utf-8")))
            tiles.append({
                "id": "testfam:synth:override",
                "image_override": "derived/synth.png",
                "layer": "map",
                "category": "tile",
                "transparent": True,
                "cluster_ids": [],
                "tags": ["semantic:synthetic"],
                "source_group": "test.group",
                "meaning": "Synthetic override tile.",
                "meaning_confidence": "confirmed",
            })
            write_json(family_dir / "tiles.json", tiles)

            family = TileFamily.load(family_dir)
            tile = family.tiles["testfam:synth:override"]
            assert tile.seam_profiles is not None
            self.assertEqual(tile.seam_profiles["west"], (True,) * 8)  # painted left column
            self.assertEqual(tile.seam_profiles["east"], (False,) * 8)  # transparent right column
            self.assertEqual(tile.seam_profiles["north"], (True,) + (False,) * 7)  # top row: only x=0 painted
            self.assertEqual(tile.seam_profiles["south"], (True,) + (False,) * 7)

    def test_minimal8_tiles_carry_four_eight_long_masks(self) -> None:
        family = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")
        tile = next(iter(family.tiles.values()))
        assert tile.seam_profiles is not None
        self.assertEqual(set(tile.seam_profiles), {"north", "south", "east", "west"})
        for mask in tile.seam_profiles.values():
            self.assertEqual(len(mask), 8)


class CellContentInsetParseTests(unittest.TestCase):
    def test_valid_mapping(self) -> None:
        self.assertEqual(CellContentInset.from_mapping({"top": 1, "right": 2}), CellContentInset(top=1, right=2))

    def test_none_is_flush_default(self) -> None:
        self.assertEqual(CellContentInset.from_mapping(None), CellContentInset())

    def test_bool_value_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "integer"):
            CellContentInset.from_mapping({"top": True})

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            CellContentInset.from_mapping({"middle": 1})

    def test_non_mapping_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CellContentInset.from_mapping([1, 2])


if __name__ == "__main__":
    unittest.main()
