from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from source_manifest_bridge import load_bridged_tile_family
from tile_families import TileFamily
from tile_library import CellContentInset


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_sheet(
    path: Path,
    *,
    columns: int,
    rows: int,
    tile_width: int = 8,
    tile_height: int = 8,
) -> None:
    Image.new(
        "RGBA",
        (columns * tile_width, rows * tile_height),
        (255, 255, 255, 255),
    ).save(path)


def set_json_value(path: Path, keys: list[object], value: object) -> None:
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


def delete_json_value(path: Path, keys: list[object]) -> None:
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


def set_pack_grid_and_resize_art(pack_path: Path, *, tile_width: int, tile_height: int = 8) -> None:
    set_json_value(pack_path, ["grid", "tile_width"], tile_width)
    set_json_value(pack_path, ["grid", "tile_height"], tile_height)
    write_sheet(
        pack_path.parent / "art" / "overworld.base.png",
        columns=4,
        rows=2,
        tile_width=tile_width,
        tile_height=tile_height,
    )
    write_sheet(
        pack_path.parent / "art" / "overworld.bg.png",
        columns=4,
        rows=2,
        tile_width=tile_width,
        tile_height=tile_height,
    )


def make_bridged_source_pack(root: Path) -> Path:
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

    write_sheet(art_dir / "overworld.base.png", columns=4, rows=2)
    write_sheet(art_dir / "overworld.bg.png", columns=4, rows=2)
    write_json(
        compatibility_root / "family.json",
        {
            "family_id": "demo.overworld",
            "title": "Overworld Atlas",
            "grid": {"tile_width": 8, "tile_height": 8},
            "render_defaults": {"render_step_width": 8, "render_step_height": 8},
            "siblings_share_semantics": True,
            "default_variant_id": "base",
            "notes": ["Legacy overworld compatibility note."],
            "variants": [
                {
                    "variant_id": "base",
                    "sheet": "../art/overworld.base.png",
                    "transparent": "top_left",
                },
                {
                    "variant_id": "bg",
                    "sheet": "../art/overworld.bg.png",
                    "background_mode": "solid",
                },
            ],
            "ingestion_spec": "../ingestion/overworld.json",
        },
    )
    write_json(
        compatibility_root / "clusters.json",
        [{"id": "overworld.cluster", "scope": "family", "members": ["demo.overworld:all:0,0"]}],
    )
    write_json(
        compatibility_root / "tiles.json",
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
        compatibility_root / "aliases.json",
        {"overworld.ground": "demo.overworld:all:0,0"},
    )
    write_json(
        ingestion_dir / "overworld.json",
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
        root / "pack.json",
        {
            "pack_id": "demo-pack",
            "grid": {"tile_width": 8, "tile_height": 8},
            "tilesets": [{"tileset_id": "demo.base", "manifest": "tilesets/base.json"}],
        },
    )
    write_json(
        tilesets_dir / "base.json",
        {
            "tileset_id": "demo.base",
            "title": "Demo Base",
            "module_context": [
                {"axis_id": "theme", "value_id": "default"},
                {"axis_id": "domain", "value_id": "world"},
            ],
            "render_traits": {"background_treatment": "transparent"},
            "logical_tilesheets": [{"tilesheet_id": "overworld", "manifest": "../tilesheets/overworld.json"}],
        },
    )
    write_json(
        tilesheets_dir / "overworld.json",
        {
            "tilesheet_id": "overworld",
            "title": "Overworld Atlas",
            "bounds": {"x": 0, "y": 0, "width": 4, "height": 2},
            "default_variant_id": "base",
            "source_layout": "../ingestion/overworld.json",
            "render_traits": {"alignment_origin": "bottom_left"},
            "notes": ["Legacy overworld compatibility note."],
            "compatibility_family": {
                "root": "../legacy-family",
                "family_id": "demo.overworld",
                "tiles": "tiles.json",
                "aliases": "aliases.json",
                "clusters": "clusters.json",
                "render_step_width": 8,
                "render_step_height": 8,
                "siblings_share_semantics": True,
                "cell_content_inset": {"top": 1, "right": 1},
                "runtime_flippable": False,
                "notes": ["Bridge-only compatibility note that should not leak into TileFamily.notes."],
            },
            "render_variants": [
                {
                    "variant_id": "base",
                    "sheet": "../art/overworld.base.png",
                    "coverage": {"mode": "full"},
                    "transparent": "top_left",
                },
                {
                    "variant_id": "bg",
                    "sheet": "../art/overworld.bg.png",
                    "coverage": {"mode": "full"},
                    "background_mode": "solid",
                },
            ],
        },
    )
    return root / "pack.json"


def write_minimal8_source_wrapper(root: Path) -> Path:
    legacy_root = ROOT / "prototypes/minimal8-harness/tile-families/minimal8"
    family_payload = json.loads((legacy_root / "family.json").read_text(encoding="utf-8"))
    ingestion_payload = json.loads((legacy_root / "ingestion.json").read_text(encoding="utf-8"))
    grid = family_payload["grid"]
    render_defaults = family_payload.get("render_defaults", {})
    variants = family_payload["variants"]
    logical_bounds = ingestion_payload["sheet_bounds"]

    tilesets_dir = root / "tilesets"
    tilesheets_dir = root / "tilesheets"
    tilesets_dir.mkdir(parents=True, exist_ok=True)
    tilesheets_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        root / "pack.json",
        {
            "pack_id": "minimal8-pack",
            "title": "Minimal 8 Pack",
            "grid": grid,
            "tilesets": [{"tileset_id": "minimal8.base", "manifest": "tilesets/base.json"}],
        },
    )
    write_json(
        tilesets_dir / "base.json",
        {
            "tileset_id": "minimal8.base",
            "title": "Minimal 8",
            "module_context": [
                {"axis_id": "theme", "value_id": "minimal8"},
                {"axis_id": "domain", "value_id": "dungeon"},
            ],
            "logical_tilesheets": [{"tilesheet_id": "minimal8.main", "manifest": "../tilesheets/main.json"}],
        },
    )
    write_json(
        tilesheets_dir / "main.json",
        {
            "tilesheet_id": "minimal8.main",
            "title": family_payload.get("title"),
            "bounds": logical_bounds,
            "default_variant_id": family_payload["default_variant_id"],
            "source_layout": str((legacy_root / "ingestion.json").resolve()),
            "compatibility_family": {
                "root": str(legacy_root.resolve()),
                "family_id": family_payload["family_id"],
                "tiles": "tiles.json",
                "aliases": "aliases.json",
                "clusters": "clusters.json",
                "constructions": "constructions.json",
                "runtime_flippable": family_payload.get("runtime_flippable", True),
                **(
                    {"render_step_width": render_defaults["render_step_width"]}
                    if "render_step_width" in render_defaults
                    else {}
                ),
                **(
                    {"render_step_height": render_defaults["render_step_height"]}
                    if "render_step_height" in render_defaults
                    else {}
                ),
                **(
                    {"siblings_share_semantics": family_payload["siblings_share_semantics"]}
                    if "siblings_share_semantics" in family_payload
                    else {}
                ),
                "notes": ["Bridge wrapper for the current Minimal 8 legacy family package."],
            },
            "render_traits": {"alignment_origin": "bottom_left"},
            "render_variants": [
                {
                    "variant_id": variant["variant_id"],
                    "sheet": str((legacy_root / variant["sheet"]).resolve()),
                    "coverage": {"mode": "full"},
                    "transparent": variant.get("transparent"),
                    "palette_family": variant.get("palette_family"),
                    "colorway": variant.get("colorway"),
                    "background_mode": variant.get("background_mode"),
                    "notes": variant.get("notes"),
                }
                for variant in variants
            ],
        },
    )
    return root / "pack.json"


class SourceManifestBridgeTests(unittest.TestCase):
    def test_bridge_loads_synthetic_pack_into_tile_family_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.family_id, "demo.overworld")
            self.assertEqual(family.title, "Overworld Atlas")
            self.assertEqual(family.default_variant_id, "base")
            self.assertEqual(family.render_step_width, 8)
            self.assertEqual(family.render_step_height, 8)
            self.assertTrue(family.siblings_share_semantics)
            # The cell-content inset is owned by the staged source manifest (ADR 0008).
            self.assertEqual(family.header.cell_content_inset, CellContentInset(top=1, right=1))
            self.assertFalse(family.header.runtime_flippable)
            self.assertFalse(family.runtime_unit.runtime_flippable)
            self.assertEqual(family.notes, ("Legacy overworld compatibility note.",))
            promoted_metadata = family.runtime_unit.promoted_metadata
            self.assertEqual(promoted_metadata.source_pack_id, "demo-pack")
            self.assertEqual(promoted_metadata.source_tileset_id, "demo.base")
            self.assertEqual(promoted_metadata.source_tilesheet_id, "overworld")
            self.assertEqual(tuple(promoted_metadata.module_context.keys()), ("theme", "domain"))
            self.assertEqual(promoted_metadata.module_context["theme"].value_id, "default")
            self.assertEqual(promoted_metadata.module_context["domain"].value_id, "world")
            self.assertEqual(promoted_metadata.render_traits.background_treatment, "transparent")
            self.assertEqual(promoted_metadata.render_traits.alignment_origin, "bottom_left")
            self.assertEqual(promoted_metadata.documented_hints, ("Legacy overworld compatibility note.",))
            self.assertEqual(tuple(family.variants.keys()), ("base", "bg"))
            self.assertEqual(len(family.tiles), 1)
            self.assertEqual(len(family.aliases), 1)
            self.assertEqual(len(family.clusters), 1)
            self.assertIsNotNone(family.source_layout)
            assert family.source_layout is not None
            self.assertEqual(family.source_layout.sheet_bounds.width, 4)
            resolved = family.resolve_ref("overworld.ground")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.tile_id, "demo.overworld:all:0,0")

    def test_bridge_uses_legacy_notes_when_logical_tilesheet_notes_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(pack_path.parent / "tilesheets" / "overworld.json", ["notes"])

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.notes, ("Legacy overworld compatibility note.",))
            self.assertEqual(
                family.runtime_unit.promoted_metadata.documented_hints,
                ("Legacy overworld compatibility note.",),
            )

    def test_bridge_uses_staged_notes_when_legacy_family_notes_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            set_json_value(
                pack_path.parent / "tilesheets" / "overworld.json",
                ["notes"],
                ["Staged overworld note."],
            )
            delete_json_value(pack_path.parent / "legacy-family" / "family.json", ["notes"])

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.notes, ("Staged overworld note.",))
            self.assertEqual(family.runtime_unit.promoted_metadata.documented_hints, ("Staged overworld note.",))

    def test_bridge_uses_legacy_title_when_logical_tilesheet_title_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(pack_path.parent / "tilesheets" / "overworld.json", ["title"])
            set_json_value(pack_path.parent / "tilesets" / "base.json", ["title"], "Outer Tileset Title")
            set_json_value(pack_path.parent / "pack.json", ["title"], "Outer Pack Title")

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.title, "Overworld Atlas")

    def test_bridge_uses_legacy_siblings_share_semantics_when_staged_value_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(
                pack_path.parent / "tilesheets" / "overworld.json",
                ["compatibility_family", "siblings_share_semantics"],
            )

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertTrue(family.siblings_share_semantics)

    def test_bridge_uses_staged_siblings_share_semantics_when_legacy_value_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(pack_path.parent / "legacy-family" / "family.json", ["siblings_share_semantics"])

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertTrue(family.siblings_share_semantics)

    def test_bridge_uses_staged_render_step_defaults_when_legacy_values_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(pack_path.parent / "legacy-family" / "family.json", ["render_defaults"])

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.render_step_width, 8)
            self.assertEqual(family.render_step_height, 8)

    def test_bridge_allows_explicit_empty_staged_notes_to_clear_legacy_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            set_json_value(pack_path.parent / "tilesheets" / "overworld.json", ["notes"], [])

            family = load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

            self.assertEqual(family.notes, ())
            self.assertEqual(family.runtime_unit.promoted_metadata.documented_hints, ())

    def test_bridge_rejects_oversized_staged_cell_content_inset(self) -> None:
        # The dimension check lives in TileFamilyHeader.__post_init__, so the staged
        # bridge path is validated too (not only the legacy family-header path).
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            set_json_value(
                pack_path.parent / "tilesheets" / "overworld.json",
                ["compatibility_family", "cell_content_inset"],
                {"right": 99},
            )
            with self.assertRaisesRegex(ValueError, r"cell_content_inset.*tile width"):
                load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_rejects_non_boolean_runtime_flippable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            set_json_value(
                pack_path.parent / "tilesheets" / "overworld.json",
                ["compatibility_family", "runtime_flippable"],
                "false",
            )

            with self.assertRaisesRegex(ValueError, r"runtime_flippable must be a boolean"):
                load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_rejects_logical_tilesheet_without_compatibility_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            delete_json_value(pack_path.parent / "tilesheets" / "overworld.json", ["compatibility_family"])

            with self.assertRaisesRegex(ValueError, r"does not declare a compatibility_family bridge"):
                load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_rejects_staged_header_mismatches_against_legacy_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[Path], None], str]] = [
                (
                    "pack_grid",
                    lambda pack_path: set_pack_grid_and_resize_art(pack_path, tile_width=16),
                    r"Staged pack grid 16x8 does not match compatibility family grid 8x8",
                ),
                (
                    "family_id",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["compatibility_family", "family_id"],
                        "demo.other",
                    ),
                    r"Staged compatibility family_id 'demo\.other' does not match compatibility family manifest family_id 'demo\.overworld'",
                ),
                (
                    "default_variant_id",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["default_variant_id"],
                        "bg",
                    ),
                    r"Staged default_variant_id 'bg' does not match compatibility family default_variant_id 'base'",
                ),
                (
                    "title",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["title"],
                        "Other Atlas",
                    ),
                    r"Staged logical tilesheet title 'Other Atlas' does not match compatibility family title 'Overworld Atlas'",
                ),
                (
                    "notes",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["notes"],
                        ["Different staged note."],
                    ),
                    r"Staged logical tilesheet notes do not match compatibility family notes",
                ),
                (
                    "render_step_width",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["compatibility_family", "render_step_width"],
                        16,
                    ),
                    r"Staged render_step_width 16 does not match compatibility family render_step_width 8",
                ),
                (
                    "render_step_height",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["compatibility_family", "render_step_height"],
                        16,
                    ),
                    r"Staged render_step_height 16 does not match compatibility family render_step_height 8",
                ),
                (
                    "siblings_share_semantics",
                    lambda pack_path: set_json_value(
                        pack_path.parent / "tilesheets" / "overworld.json",
                        ["compatibility_family", "siblings_share_semantics"],
                        False,
                    ),
                    r"Staged siblings_share_semantics False does not match compatibility family siblings_share_semantics True",
                ),
            ]

            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    pack_path = make_bridged_source_pack(Path(temp_dir) / label)
                    mutate(pack_path)
                    with self.assertRaisesRegex(ValueError, expected):
                        load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_rejects_render_variant_mismatch_against_legacy_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            set_json_value(
                pack_path.parent / "tilesheets" / "overworld.json",
                ["render_variants", 1, "background_mode"],
                "gradient",
            )

            with self.assertRaisesRegex(
                ValueError,
                r"Staged render variants for logical tilesheet 'overworld' do not match compatibility family variants",
            ):
                load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_rejects_source_layout_bounds_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = make_bridged_source_pack(Path(temp_dir))
            ingestion_path = pack_path.parent / "ingestion" / "overworld.json"
            payload = read_json(ingestion_path)
            mapping = cast(dict[str, object], payload)
            mapping["sheet_bounds"] = {"x": 0, "y": 0, "width": 3, "height": 2}
            cast(list[object], mapping["regions"])[0] = {
                "id": "overworld.region",
                "bounds": {"x": 0, "y": 0, "width": 3, "height": 2},
            }
            cast(list[object], mapping["clusters"])[0] = {
                "id": "overworld.region.cluster_01",
                "source_region_id": "overworld.region",
                "bounds": {"x": 0, "y": 0, "width": 3, "height": 2},
            }
            write_json(ingestion_path, mapping)

            with self.assertRaisesRegex(ValueError, r"do not match source_layout sheet bounds"):
                load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

    def test_bridge_wraps_current_minimal8_family_into_equivalent_runtime_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pack_path = write_minimal8_source_wrapper(Path(temp_dir))

            bridged = load_bridged_tile_family(
                pack_path,
                tileset_id="minimal8.base",
                tilesheet_id="minimal8.main",
            )
            legacy = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8")

            self.assertEqual(bridged.family_id, legacy.family_id)
            self.assertEqual(bridged.title, legacy.title)
            self.assertEqual(bridged.tile_width, legacy.tile_width)
            self.assertEqual(bridged.tile_height, legacy.tile_height)
            self.assertEqual(bridged.render_step_width, legacy.render_step_width)
            self.assertEqual(bridged.render_step_height, legacy.render_step_height)
            self.assertEqual(bridged.default_variant_id, legacy.default_variant_id)
            self.assertEqual(bridged.header.runtime_flippable, legacy.header.runtime_flippable)
            self.assertEqual(bridged.runtime_unit.runtime_flippable, legacy.runtime_unit.runtime_flippable)
            self.assertEqual(bridged.notes, legacy.notes)
            self.assertEqual(bridged.variants, legacy.variants)
            self.assertEqual(bridged.tiles, legacy.tiles)
            self.assertEqual(bridged.aliases, legacy.aliases)
            self.assertEqual(bridged.clusters, legacy.clusters)
            self.assertEqual(bridged.tiles_by_sheet_cell, legacy.tiles_by_sheet_cell)
            self.assertEqual(bridged.constructions, legacy.constructions)
            self.assertIsNotNone(bridged.source_layout)
            self.assertIsNotNone(legacy.source_layout)
            assert bridged.source_layout is not None
            assert legacy.source_layout is not None
            self.assertEqual(bridged.source_layout, legacy.source_layout)

            for alias in legacy.aliases:
                with self.subTest(alias=alias):
                    bridged_ref = bridged.resolve_ref(alias)
                    legacy_ref = legacy.resolve_ref(alias)
                    self.assertIsNotNone(bridged_ref)
                    self.assertIsNotNone(legacy_ref)
                    assert bridged_ref is not None
                    assert legacy_ref is not None
                    self.assertEqual(bridged_ref.tile_id, legacy_ref.tile_id)
                    self.assertEqual(bridged_ref.physical_ref, legacy_ref.physical_ref)
                    self.assertEqual(bridged_ref.variant_ref, legacy_ref.variant_ref)

    def test_bridge_wraps_minimal8_characters_family_into_equivalent_runtime_shape(self) -> None:
        pack_path = ROOT / "prototypes/minimal8-harness/tile-packs/minimal8/pack.json"

        bridged = load_bridged_tile_family(
            pack_path,
            tileset_id="characters",
            tilesheet_id="characters",
        )
        legacy = TileFamily.load(ROOT / "prototypes/minimal8-harness/tile-families/minimal8-characters")

        self.assertEqual(bridged.family_id, legacy.family_id)
        self.assertEqual(bridged.title, legacy.title)
        self.assertEqual(bridged.tile_width, legacy.tile_width)
        self.assertEqual(bridged.tile_height, legacy.tile_height)
        self.assertEqual(bridged.render_step_width, legacy.render_step_width)
        self.assertEqual(bridged.render_step_height, legacy.render_step_height)
        self.assertEqual(bridged.default_variant_id, legacy.default_variant_id)
        self.assertEqual(bridged.header.runtime_flippable, legacy.header.runtime_flippable)
        self.assertEqual(bridged.runtime_unit.runtime_flippable, legacy.runtime_unit.runtime_flippable)
        self.assertEqual(bridged.notes, legacy.notes)
        self.assertEqual(bridged.variants, legacy.variants)
        self.assertEqual(bridged.tiles, legacy.tiles)
        self.assertEqual(bridged.aliases, legacy.aliases)
        self.assertEqual(bridged.clusters, legacy.clusters)
        self.assertEqual(bridged.constructions, legacy.constructions)
        self.assertEqual(bridged.source_layout, legacy.source_layout)
        self.assertIsNotNone(bridged.source_layout)
        self.assertIsNotNone(legacy.source_layout)

    def test_bridge_surfaces_catalog_payload_errors_like_tile_family_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases: list[tuple[str, Callable[[Path], None], str]] = [
                (
                    "tile_references_unknown_cluster",
                    lambda compatibility_root: set_json_value(
                        compatibility_root / "tiles.json",
                        [0, "cluster_ids"],
                        ["missing.cluster"],
                    ),
                    r"Tile demo\.overworld:all:0,0 references unknown cluster 'missing\.cluster'",
                ),
                (
                    "alias_points_unknown_tile",
                    lambda compatibility_root: write_json(
                        compatibility_root / "aliases.json",
                        {"overworld.ground": "missing.tile"},
                    ),
                    r"Alias 'overworld\.ground' points at unknown tile id 'missing\.tile'",
                ),
                (
                    "cluster_references_unknown_tile",
                    lambda compatibility_root: set_json_value(
                        compatibility_root / "clusters.json",
                        [0, "members"],
                        ["missing.tile"],
                    ),
                    r"Cluster overworld\.cluster references unknown tile 'missing\.tile'",
                ),
            ]

            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    root = Path(temp_dir) / label
                    pack_path = make_bridged_source_pack(root)
                    compatibility_root = pack_path.parent / "legacy-family"
                    mutate(compatibility_root)

                    with self.assertRaisesRegex(ValueError, expected) as bridge_error:
                        load_bridged_tile_family(pack_path, tileset_id="demo.base", tilesheet_id="overworld")

                    with self.assertRaisesRegex(ValueError, expected) as legacy_error:
                        TileFamily.load(compatibility_root)

                    self.assertEqual(str(bridge_error.exception), str(legacy_error.exception))


if __name__ == "__main__":
    unittest.main()
