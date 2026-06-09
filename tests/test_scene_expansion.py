from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import harness
import scene_rules
import scene_templates
from scene_rules import SceneRuleEntityCandidate, SceneRulesetLibrary, SceneRulesetSpec
from tile_library import (
    CompositeTileCell,
    CompositeTileRecord,
    Construction,
    ConstructionAttachmentSet,
    ConstructionAttachmentVariant,
    EntityTemplateRecord,
    FrameCornerSlot,
    FrameSlot,
    MetatileConstruction,
    ParametricFrameConstruction,
    ParametricRunConstruction,
    PlaceableRef,
    TileGenesis,
    TileFamilyVariant,
    TileLibraryPromotedMetadata,
    TileLibraryUnit,
    TileRecord,
    attachment_sets_by_target,
    entity_template_from_construction,
)
from _manifest_utils import GridBounds


PROJECT_PATH = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
SCENE_TEMPLATES_DIR = ROOT / "prototypes/minimal8-harness/scene-templates"
SCENE_RULES_DIR = ROOT / "prototypes/minimal8-harness/scene-rules"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def _scene_template_spec(
    *,
    template_id: str = "sample",
) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "description": f"{template_id} test template",
        "parameters": {
            "x": {"type": "int", "required": True, "description": "Left tile coordinate."},
            "y": {"type": "int", "required": True, "description": "Top tile coordinate."},
            "width": {"type": "int", "required": True, "description": "Width in tiles."},
            "height": {"type": "int", "required": True, "description": "Height in tiles."}
        },
        "ops": []
    }


def _data_scene_template_spec(*, template_id: str = "sample") -> dict[str, Any]:
    return {
        "template_id": template_id,
        "description": f"{template_id} data template",
        "parameters": {
            "x": {"type": "int", "required": True, "description": "Left tile coordinate."},
            "y": {"type": "int", "required": True, "description": "Top tile coordinate."},
            "width": {"type": "int", "required": True, "description": "Width in tiles."},
            "height": {"type": "int", "required": True, "description": "Height in tiles."},
            "room_layer": {"type": "str", "required": False, "description": "Room layer."},
            "door_ref": {"type": "tile_ref", "required": False, "description": "Door ref."},
            "door_y": {"type": "int", "required": False, "description": "Door y."}
        },
        "bindings": {
            "room_layer": {"param": "room_layer", "default": "rooms"},
            "door_ref": {"param": "door_ref", "default": "@door_arch"}
        },
        "ops": [
            {
                "kind": "entity",
                "layer": {"bind": "room_layer"},
                "construction": "ui.frame.gold_room",
                "x": {"param": "x"},
                "y": {"param": "y"},
                "params": {"width": {"param": "width"}, "height": {"param": "height"}}
            },
            {
                "kind": "stamp",
                "layer": "ornament",
                "when_present": "door_ref",
                "ref": {"bind": "door_ref"},
                "x": {
                    "centered_x": {
                        "ref": {"bind": "door_ref"},
                        "x": {"param": "x"},
                        "width": {"param": "width"}
                    }
                },
                "y": {"param": "door_y", "default": {"add": [{"param": "y"}, 2]}}
            }
        ]
    }


def _project_config_with_template_dir(
    template_dir: Path,
    *,
    rules_dir: Path | None = None,
) -> dict[str, Any]:
    config = _read_json(PROJECT_PATH)
    if "tile_family" in config:
        tile_family = cast(dict[str, Any], config["tile_family"])
        if "path" in tile_family:
            tile_family["path"] = str((PROJECT_PATH.parent / cast(str, tile_family["path"])).resolve())
        if "source_pack" in tile_family:
            tile_family["source_pack"] = str(
                (PROJECT_PATH.parent / cast(str, tile_family["source_pack"])).resolve()
            )
    else:
        for raw_spec in cast(list[object], config["tile_families"]):
            tile_family = cast(dict[str, Any], raw_spec)
            if "path" in tile_family:
                tile_family["path"] = str((PROJECT_PATH.parent / cast(str, tile_family["path"])).resolve())
            if "source_pack" in tile_family:
                tile_family["source_pack"] = str(
                    (PROJECT_PATH.parent / cast(str, tile_family["source_pack"])).resolve()
                )
    utility_tileset = cast(dict[str, Any], cast(dict[str, Any], config["tilesets"])["utility_land"])
    utility_tileset["sheet"] = str((PROJECT_PATH.parent / cast(str, utility_tileset["sheet"])).resolve())
    config["scene_templates_dir"] = str(template_dir)
    if rules_dir is None:
        rules_dir = template_dir.parent / "scene-rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
    config["scene_rules_dir"] = str(rules_dir.resolve())
    return config


def _ops(layers: harness.SceneLayers, layer_name: str) -> list[dict[str, object]]:
    """Return ops on a layer as plain dicts so tests can read fields without TypedDict narrowing."""
    return [cast(dict[str, object], op) for op in layers.get(layer_name, [])]


def _ops_with_kind(layers: harness.SceneLayers, layer_name: str, kind: str) -> list[dict[str, object]]:
    return [op for op in _ops(layers, layer_name) if op.get("kind") == kind]


def _stamp_refs(layers: harness.SceneLayers, layer_name: str) -> list[object]:
    return [op.get("ref") for op in _ops_with_kind(layers, layer_name, "stamp")]


def _op_int(op: dict[str, object], key: str) -> int:
    value = op[key]
    assert isinstance(value, int), f"expected int for {key!r}, got {value!r}"
    return value


class SceneTemplateLibraryTests(unittest.TestCase):
    def test_project_loads_default_scene_template_library(self) -> None:
        project = harness.LayoutProject(PROJECT_PATH)
        self.assertTrue(
            {"sanctum", "twin_chambers", "causeway", "tavern"}.issubset(
                set(project.scene_template_library.specs)
            )
        )

    def test_project_loads_default_scene_rules_library(self) -> None:
        project = harness.LayoutProject(PROJECT_PATH)
        tavern = project.scene_ruleset_spec("tavern")

        self.assertIn("back_wall_stock", tavern.catalogues)
        self.assertIn("dining_rect_3x2", tavern.catalogues)
        self.assertIn("dining_square_2x2", tavern.catalogues)

    def test_scene_rule_entity_candidate_loads_canonical_placeable_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)
            _write_json(
                rules_dir / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Placeable entity candidate fixture.",
                    "catalogues": {
                        "entities": [
                            {
                                "id": "tile_entity",
                                "kind": "entity",
                                "weight": 1,
                                "placeable": {"kind": "tile", "id": "tile.a"},
                            }
                        ]
                    },
                },
            )

            library = scene_rules.load_scene_ruleset_library(ROOT, str(rules_dir))

        candidate = library.require("sample").require_catalogue("entities")[0]
        self.assertIsInstance(candidate, SceneRuleEntityCandidate)
        assert isinstance(candidate, SceneRuleEntityCandidate)
        self.assertIsNone(candidate.construction_id)
        self.assertEqual(candidate.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))

    def test_scene_rule_entity_candidate_rejects_both_construction_and_placeable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)
            _write_json(
                rules_dir / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Invalid entity candidate fixture.",
                    "catalogues": {
                        "entities": [
                            {
                                "id": "tile_entity",
                                "kind": "entity",
                                "weight": 1,
                                "construction": "test.fixture",
                                "placeable": {"kind": "tile", "id": "tile.a"},
                            }
                        ]
                    },
                },
            )

            with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
                scene_rules.load_scene_ruleset_library(ROOT, str(rules_dir))

    def test_scene_rule_entity_candidate_rejects_missing_placeable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)
            _write_json(
                rules_dir / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Invalid entity candidate fixture.",
                    "catalogues": {
                        "entities": [
                            {
                                "id": "tile_entity",
                                "kind": "entity",
                                "weight": 1,
                            }
                        ]
                    },
                },
            )

            with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
                scene_rules.load_scene_ruleset_library(ROOT, str(rules_dir))

    def test_loader_rejects_filename_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            _write_json(templates_dir / "sanctum.json", _scene_template_spec(template_id="mismatch"))

            with self.assertRaisesRegex(ValueError, "must match filename stem"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_parameter_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _scene_template_spec(template_id="sample")
            parameters = cast(dict[str, Any], spec["parameters"])
            x_spec = cast(dict[str, Any], parameters["x"])
            x_spec["type"] = "intger"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "has unknown type 'intger'"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_data_op_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            ops[0]["kind"] = "portal"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "unknown kind 'portal'"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_data_op_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            ops[0]["whe_present"] = "door_ref"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "unknown fields: whe_present"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_binding_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            stamp = ops[1]
            stamp["ref"] = {"bind": "missing_ref"}
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "references unknown binding"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_later_binding_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            spec["bindings"] = {
                "water_x": {"bind": "water_margin_x"},
                "water_margin_x": 8,
            }
            spec["ops"] = []
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "before it is declared"):
                scene_templates.load_scene_template_library(ROOT, str(templates_dir))

    def test_scene_templates_dir_override_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            shutil.copytree(SCENE_TEMPLATES_DIR, custom_templates)
            sanctum_path = custom_templates / "sanctum.json"
            sanctum_spec = _read_json(sanctum_path)
            sanctum_spec["description"] = "custom sanctum description"
            _write_json(sanctum_path, sanctum_spec)

            project_path = temp_root / "project.json"
            _write_json(project_path, _project_config_with_template_dir(custom_templates))
            project = harness.LayoutProject(project_path)

            self.assertEqual(
                project.scene_template_spec("sanctum").description,
                "custom sanctum description",
            )

    def test_missing_template_file_causes_expand_scene_to_reject_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            shutil.copytree(SCENE_TEMPLATES_DIR, custom_templates)
            (custom_templates / "tavern.json").unlink()

            project_path = temp_root / "project.json"
            _write_json(project_path, _project_config_with_template_dir(custom_templates))
            project = harness.LayoutProject(project_path)

            with self.assertRaisesRegex(ValueError, "Unknown scene template: tavern"):
                harness.expand_scene(
                    project,
                    {"template": "tavern", "x": 0, "y": 0, "width": 40, "height": 25},
                    default_tileset=project.default_tileset_id(),
                )

    def test_expand_scene_rejects_missing_required_parameter_from_spec(self) -> None:
        project = harness.LayoutProject(PROJECT_PATH)

        with self.assertRaisesRegex(ValueError, "missing required parameter 'height'"):
            harness.expand_scene(
                project,
                {"template": "sanctum", "x": 4, "y": 9, "width": 22},
                default_tileset=project.default_tileset_id(),
            )

    def test_expand_scene_rejects_wrong_parameter_type_from_spec(self) -> None:
        project = harness.LayoutProject(PROJECT_PATH)

        with self.assertRaisesRegex(ValueError, "parameter 'width' must be int"):
            harness.expand_scene(
                project,
                {"template": "sanctum", "x": 4, "y": 9, "width": "wide", "height": 14},
                default_tileset=project.default_tileset_id(),
            )

    def test_data_mode_template_dispatches_with_parameter_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            _write_json(custom_templates / "sample.json", _data_scene_template_spec(template_id="sample"))

            project_path = temp_root / "project.json"
            _write_json(project_path, _project_config_with_template_dir(custom_templates))
            project = harness.LayoutProject(project_path)

            result = harness.expand_scene_runtime(
                project,
                {"template": "sample", "x": 10, "y": 5, "width": 12, "height": 8},
                default_tileset=project.default_tileset_id(),
            )

            frames = [entity for entity in result.entities if entity.layer == "rooms"]
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].x, 10)
            self.assertEqual(frames[0].params.get("width"), 12)

            door_stamps = _ops_with_kind(result.layers, "ornament", "stamp")
            self.assertEqual(len(door_stamps), 1)
            self.assertGreaterEqual(_op_int(door_stamps[0], "x"), 10)
            self.assertLess(_op_int(door_stamps[0], "x"), 22)
            self.assertEqual(_op_int(door_stamps[0], "y"), 7)


class SceneExpressionEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = harness.LayoutProject(PROJECT_PATH)
        self.tileset = self.project.default_tileset_id()

    def _evaluate(
        self,
        expr: object,
        *,
        scene: dict[str, object] | None = None,
        bindings: dict[str, object] | None = None,
    ) -> object:
        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: harness.pattern_dimensions(
                self.project,
                ref,
                default_tileset=self.tileset,
            ),
            centered_pattern_x=lambda ref, x, width: harness.centred_pattern_x(
                self.project,
                ref,
                x=x,
                width=width,
                default_tileset=self.tileset,
            ),
        )
        return scene_templates.evaluate_scene_expr(
            expr,
            scene=scene or {},
            bindings=bindings or {},
            runtime=runtime,
        )

    def test_evaluates_arithmetic_and_binding_operators(self) -> None:
        value = self._evaluate(
            {"add": [{"bind": "base"}, {"mul": [3, 4]}, {"sub": [10, 3]}, {"floordiv": [9, 2]}, {"max": [1, 5, 4]}]},
            bindings={"base": 2},
        )
        self.assertEqual(value, 30)

    def test_evaluates_pattern_helpers(self) -> None:
        ref = "@door_arch"
        width = self._evaluate({"pattern_width": ref})
        height = self._evaluate({"pattern_height": ref})
        expected_width, expected_height = harness.pattern_dimensions(
            self.project,
            ref,
            default_tileset=self.tileset,
        )
        self.assertEqual(width, expected_width)
        self.assertEqual(height, expected_height)

    def test_evaluates_centered_x(self) -> None:
        expr = {"centered_x": {"ref": "@door_arch", "x": {"param": "x"}, "width": {"param": "width"}}}
        value = self._evaluate(expr, scene={"x": 10, "width": 12})
        expected = harness.centred_pattern_x(
            self.project,
            "@door_arch",
            x=10,
            width=12,
            default_tileset=self.tileset,
        )
        self.assertEqual(value, expected)

    def test_evaluates_boolean_and_conditional_operators(self) -> None:
        enabled = self._evaluate({"enabled": {"bind": "inner"}}, bindings={"inner": "gold_ui_frame"})
        disabled = self._evaluate({"enabled": {"bind": "inner"}}, bindings={"inner": False})
        self.assertTrue(enabled)
        self.assertFalse(disabled)
        self.assertTrue(self._evaluate({"eq": ["bridge", "bridge"]}))
        self.assertFalse(self._evaluate({"eq": ["bridge", "left"]}))

        value = self._evaluate(
            {
                "if": {
                    "all": [
                        {"gt": [{"bind": "inner_width"}, 1]},
                        {"enabled": {"bind": "inner"}}
                    ]
                },
                "then": "inner",
                "else": "outer"
            },
            bindings={"inner_width": 6, "inner": "gold_ui_frame"},
        )
        self.assertEqual(value, "inner")

    def test_gt_requires_two_operands_and_all_requires_bools(self) -> None:
        with self.assertRaisesRegex(ValueError, "gt must have exactly two operands"):
            self._evaluate({"gt": [1]})
        with self.assertRaisesRegex(ValueError, "eq must have exactly two operands"):
            self._evaluate({"eq": [1]})
        with self.assertRaisesRegex(ValueError, "must evaluate to a bool"):
            self._evaluate({"all": [1]})

    def test_missing_parameter_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing parameter 'width'"):
            self._evaluate({"param": "width"})

    def test_unknown_binding_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown binding 'missing'"):
            self._evaluate({"bind": "missing"})

    def test_sub_and_floordiv_require_two_operands(self) -> None:
        with self.assertRaisesRegex(ValueError, "sub must have exactly two operands"):
            self._evaluate({"sub": [1]})
        with self.assertRaisesRegex(ValueError, "floordiv must have exactly two operands"):
            self._evaluate({"floordiv": [8]})

    def test_max_requires_operands(self) -> None:
        with self.assertRaisesRegex(ValueError, "max must have at least one operand"):
            self._evaluate({"max": []})

    def test_min_returns_minimum_of_operands(self) -> None:
        self.assertEqual(self._evaluate({"min": [3, 1, 2]}), 1)
        self.assertEqual(self._evaluate({"min": [{"bind": "a"}, 5]}, bindings={"a": 9}), 5)
        self.assertEqual(self._evaluate({"min": [7]}), 7)

    def test_min_requires_operands(self) -> None:
        with self.assertRaisesRegex(ValueError, "min must have at least one operand"):
            self._evaluate({"min": []})

    def test_fill_rows_returns_repeated_pattern(self) -> None:
        rows = self._evaluate({"fill_rows": {"width": 3, "height": 2}})
        self.assertEqual(rows, ["###", "###"])

    def test_fill_rows_evaluates_width_and_height_expressions(self) -> None:
        rows = self._evaluate(
            {"fill_rows": {"width": {"bind": "w"}, "height": {"bind": "h"}}},
            bindings={"w": 4, "h": 1},
        )
        self.assertEqual(rows, ["####"])

    def test_fill_rows_rejects_negative_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "fill_rows width must be non-negative"):
            self._evaluate({"fill_rows": {"width": -1, "height": 2}})
        with self.assertRaisesRegex(ValueError, "fill_rows height must be non-negative"):
            self._evaluate({"fill_rows": {"width": 2, "height": -1}})

    def test_malformed_operator_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "did you mean 'floordiv'"):
            self._evaluate({"floordivv": [8, 2]})
        with self.assertRaisesRegex(ValueError, "unknown or malformed scene expression"):
            self._evaluate({"add": [1, 2], "comment": "x"})


class SanctumSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = harness.LayoutProject(PROJECT_PATH)
        self.tileset = self.project.default_tileset_id()

    def test_emits_outer_frame_and_centred_door(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {"template": "sanctum", "x": 4, "y": 9, "width": 22, "height": 14},
            default_tileset=self.tileset,
        )

        self.assertIn("rooms", result.layers)
        self.assertIn("ornament", result.layers)
        frames = [entity for entity in result.entities if entity.layer == "rooms"]
        self.assertGreaterEqual(len(frames), 1)
        outer_frame = next(entity for entity in frames if entity.x == 4 and entity.y == 9)
        self.assertEqual(outer_frame.template.construction_id, "ui.frame.glyph_stone")
        self.assertEqual(outer_frame.params.get("width"), 22)

        door_stamps = _ops_with_kind(result.layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        self.assertEqual(door_stamps[0].get("ref"), "@door_arch")

    def test_door_ref_empty_string_skips_door(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {"template": "sanctum", "x": 4, "y": 9, "width": 22, "height": 14, "door_ref": ""},
            default_tileset=self.tileset,
        )
        self.assertEqual(_ops_with_kind(layers, "ornament", "stamp"), [])

    def test_custom_layer_names_route_ops(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {
                "template": "sanctum",
                "x": 4,
                "y": 9,
                "width": 22,
                "height": 14,
                "room_layer": "shrine",
                "ornament_layer": "props",
            },
            default_tileset=self.tileset,
        )
        self.assertIn("shrine", layers)
        self.assertIn("props", layers)
        self.assertNotIn("rooms", layers)
        self.assertNotIn("ornament", layers)

    def test_blank_inner_skips_inner_frame_and_targets_outer_room(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {"template": "sanctum", "x": 4, "y": 9, "width": 22, "height": 14, "inner": False},
            default_tileset=self.tileset,
        )

        frames = [entity for entity in result.entities if entity.layer == "rooms"]
        self.assertEqual(len(frames), 1)

        door_stamps = _ops_with_kind(result.layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        expected_x = harness.centred_pattern_x(
            self.project,
            "@door_arch",
            x=4,
            width=22,
            default_tileset=self.tileset,
        )
        self.assertEqual(_op_int(door_stamps[0], "x"), expected_x)


class TwinChambersSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = harness.LayoutProject(PROJECT_PATH)
        self.tileset = self.project.default_tileset_id()

    def test_emits_two_chamber_frames_and_door(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {
                "template": "twin_chambers",
                "x": 11,
                "y": 11,
                "width": 34,
                "height": 10,
                "left_width": 12,
                "bridge_width": 8,
                "right_width": 14,
                "door_target": "right",
            },
            default_tileset=self.tileset,
        )

        frames = [
            entity for entity in result.entities
            if entity.template.construction_id == "ui.frame.gold_room" and entity.layer == "rooms"
        ]
        self.assertGreaterEqual(len(frames), 2)
        x_origins = sorted({entity.x for entity in frames})
        self.assertIn(11, x_origins)
        self.assertIn(11 + 12 + 8, x_origins)

        door_stamps = _ops_with_kind(result.layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        right_x = 11 + 12 + 8
        door_x = _op_int(door_stamps[0], "x")
        self.assertGreaterEqual(door_x, right_x)
        self.assertLess(door_x, right_x + 14)

    def test_bridge_false_skips_bridge_frame(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {
                "template": "twin_chambers",
                "x": 11,
                "y": 11,
                "width": 34,
                "height": 10,
                "left_width": 12,
                "bridge_width": 8,
                "right_width": 14,
                "bridge": False,
            },
            default_tileset=self.tileset,
        )

        frames = [
            entity for entity in result.entities
            if entity.template.construction_id == "ui.frame.gold_room" and entity.layer == "rooms"
        ]
        self.assertEqual(len(frames), 2)

    def test_invalid_dimensions_fail_constraint(self) -> None:
        with self.assertRaisesRegex(ValueError, "failed constraint: Invalid twin_chambers dimensions"):
            harness.expand_scene(
                self.project,
                {
                    "template": "twin_chambers",
                    "x": 11,
                    "y": 11,
                    "width": 10,
                    "height": 10,
                    "left_width": 8,
                    "bridge_width": 8,
                    "right_width": 8,
                },
                default_tileset=self.tileset,
            )


class CausewaySceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = harness.LayoutProject(PROJECT_PATH)
        self.tileset = self.project.default_tileset_id()

    def test_emits_water_island_and_centred_door(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {
                "template": "causeway",
                "x": 26,
                "y": 12,
                "width": 12,
                "height": 8,
                "water_margin_x": 16,
                "water_margin_top": 2,
                "water_margin_bottom": 8,
            },
            default_tileset=self.tileset,
        )

        water_fills = _ops_with_kind(result.layers, "water", "fill")
        self.assertEqual(len(water_fills), 1)
        frames = [
            entity for entity in result.entities
            if entity.template.construction_id == "ui.frame.gold_room" and entity.layer == "island"
        ]
        self.assertGreaterEqual(len(frames), 1)
        outer_frame = next(entity for entity in frames if entity.x == 26 and entity.y == 12)
        self.assertEqual(outer_frame.params.get("width"), 12)
        self.assertEqual(outer_frame.params.get("height"), 8)

        door_stamps = _ops_with_kind(result.layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        door_x = _op_int(door_stamps[0], "x")
        self.assertGreaterEqual(door_x, 26)
        self.assertLess(door_x, 26 + 12)

    def test_disables_optional_stem_and_door_when_blank_or_null(self) -> None:
        result = harness.expand_scene_runtime(
            self.project,
            {
                "template": "causeway",
                "x": 26,
                "y": 12,
                "width": 12,
                "height": 8,
                "stem": False,
                "door_ref": None,
            },
            default_tileset=self.tileset,
        )

        frames = [
            entity for entity in result.entities
            if entity.template.construction_id == "ui.frame.gold_room" and entity.layer == "island"
        ]
        self.assertEqual(len(frames), 1)
        self.assertEqual(_ops_with_kind(result.layers, "ornament", "stamp"), [])

    def test_emits_requested_symbol_count(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {
                "template": "causeway",
                "x": 26,
                "y": 12,
                "width": 12,
                "height": 8,
                "door_ref": None,
                "symbols_ref": "@green_symbols",
                "symbols_count": 3,
            },
            default_tileset=self.tileset,
        )

        symbol_stamps = _ops_with_kind(layers, "ornament", "stamp")
        self.assertEqual(len(symbol_stamps), 3)


class TavernSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = harness.LayoutProject(PROJECT_PATH)
        self.tileset = self.project.default_tileset_id()

    def test_emits_floor_walls_door_and_actors(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {"template": "tavern", "x": 0, "y": 0, "width": 40, "height": 25},
            default_tileset=self.tileset,
        )

        self.assertIn("terrain", layers)
        self.assertIn("architecture", layers)
        self.assertIn("actors", layers)

        terrain_fill_refs = [op.get("ref") for op in _ops_with_kind(layers, "terrain", "fill")]
        self.assertIn("tavern.floor.quiet.base", terrain_fill_refs)

        architecture_fill_refs = [op.get("ref") for op in _ops_with_kind(layers, "architecture", "fill")]
        self.assertIn({"ref": "@tavern_outer_wall_top", "occlusion": "fill_cell"}, architecture_fill_refs)

        architecture_stamps = _stamp_refs(layers, "architecture")
        self.assertIn("indoors.door.small.open", architecture_stamps)
        self.assertIn("indoors.stairs.down", architecture_stamps)
        self.assertNotIn("indoors.stairs.up", architecture_stamps)

        actor_stamps = _stamp_refs(layers, "actors")
        self.assertIn({"ref": "tavern.hero", "underpaint": "indoors.stool", "occlusion": "fill_cell"}, actor_stamps)
        self.assertIn({"ref": "tavern.bartender", "occlusion": "fill_cell"}, actor_stamps)

    def test_runtime_preserves_entity_instances_before_stamp_lowering(self) -> None:
        runtime = harness.expand_scene_runtime(
            self.project,
            {"template": "tavern", "x": 0, "y": 0, "width": 40, "height": 25},
            default_tileset=self.tileset,
        )

        self.assertGreater(len(runtime.entities), 0)
        grand_doors = [
            entity
            for entity in runtime.entities
            if entity.template.placeable_ref == PlaceableRef(kind="composite_tile", id="indoors.door.grand.closed")
        ]
        self.assertEqual(len(grand_doors), 1)
        rect_tables = [
            entity
            for entity in runtime.entities
            if entity.template.construction_id == "indoors.table.kit.rect_3x2"
        ]
        self.assertEqual(len(rect_tables), 1)
        table = rect_tables[0]
        self.assertEqual((table.x, table.y), (11, 19))
        self.assertEqual(table.bounds.width, 3)
        self.assertEqual(table.bounds.height, 2)
        self.assertEqual(table.template.collection_id, "indoors.table.kit")
        self.assertEqual(table.template.placement_anchor, "top_left")
        self.assertEqual(table.placement_anchor.kind, "top_left")
        self.assertEqual((table.placement_anchor.x, table.placement_anchor.y), (11, 19))
        self.assertEqual(len(table.tiles), 6)
        self.assertEqual(len(table.occupied_cells), 6)
        self.assertEqual(len(table.affordance_cells), 6)
        self.assertTrue(all(cell.walkable is None and cell.blocking is None for cell in table.occupied_cells))
        self.assertTrue(all(cell.affordances == ("surface",) for cell in table.affordance_cells))
        communal_tables = [
            entity
            for entity in runtime.entities
            if entity.template.construction_id == "indoors.table.kit.vertical_2x6"
        ]
        self.assertEqual(len(communal_tables), 2)
        communal_positions = {(entity.x, entity.y) for entity in communal_tables}
        self.assertEqual(communal_positions, {(5, 12), (29, 12)})
        self.assertTrue(all((entity.bounds.width, entity.bounds.height) == (2, 6) for entity in communal_tables))
        rect_vertical = next(
            entity
            for entity in runtime.entities
            if entity.template.construction_id == "indoors.table.kit.rect_2x3"
        )
        self.assertEqual((rect_vertical.x, rect_vertical.y), (24, 18))
        self.assertEqual((rect_vertical.bounds.width, rect_vertical.bounds.height), (2, 3))
        self.assertIn("architecture", runtime.layers)


class PopulateSlotsDataSceneTests(unittest.TestCase):
    def test_populate_slots_static_scene_cycles_fail_at_project_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_templates / "loop.json",
                {
                    "template_id": "loop",
                    "description": "Self-referential slot population.",
                    "parameters": {
                        "x": {"type": "int", "required": True, "description": "Anchor x."},
                        "y": {"type": "int", "required": True, "description": "Anchor y."},
                    },
                    "slot_groups": {
                        "g": [{"id": "loop", "x": 0, "y": 0}]
                    },
                    "ops": [
                        {"kind": "populate_slots", "ruleset": "loop", "catalogue": "self", "slot_group": "g", "seed": 1}
                    ],
                },
            )

            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_rules / "loop.json",
                {
                    "ruleset_id": "loop",
                    "description": "Self-looping ruleset.",
                    "catalogues": {
                        "self": [
                            {"id": "self", "kind": "scene", "scene": "loop", "weight": 1}
                        ]
                    },
                },
            )

            project_path = temp_root / "project.json"
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )

            project = harness.LayoutProject(project_path)
            with self.assertRaisesRegex(ValueError, "scene template cycle detected"):
                _ = project.scene_template_library

    def test_populate_slots_dynamic_scene_cycles_fail_during_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_templates / "loop.json",
                {
                    "template_id": "loop",
                    "description": "Param-driven self-referential slot population.",
                    "parameters": {
                        "x": {"type": "int", "required": True, "description": "Anchor x."},
                        "y": {"type": "int", "required": True, "description": "Anchor y."},
                        "ruleset_id": {"type": "str", "required": True, "description": "Ruleset id."},
                    },
                    "slot_groups": {
                        "g": [{"id": "loop", "x": 0, "y": 0}]
                    },
                    "ops": [
                        {
                            "kind": "populate_slots",
                            "ruleset": {"param": "ruleset_id"},
                            "catalogue": "self",
                            "slot_group": "g",
                            "seed": 1,
                        }
                    ],
                },
            )

            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_rules / "loop.json",
                {
                    "ruleset_id": "loop",
                    "description": "Self-looping ruleset.",
                    "catalogues": {
                        "self": [
                            {"id": "self", "kind": "scene", "scene": "loop", "weight": 1}
                        ]
                    },
                },
            )

            project_path = temp_root / "project.json"
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )
            project = harness.LayoutProject(project_path)

            with self.assertRaisesRegex(ValueError, "scene template cycle detected"):
                harness.expand_scene(
                    project,
                    {"template": "loop", "x": 0, "y": 0, "ruleset_id": "loop"},
                    default_tileset=project.default_tileset_id(),
                )

    def test_populate_slots_lowers_stamp_entity_and_scene_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            fragment: dict[str, Any] = {
                "template_id": "fragment",
                "description": "Fragment used by a scene-rule candidate.",
                "parameters": {},
                "ops": [
                    {
                        "kind": "stamp",
                        "layer": "ornament",
                        "ref": "indoors.chair.left",
                        "x": 0,
                        "y": 0,
                    }
                ],
            }
            _write_json(custom_templates / "fragment.json", fragment)
            parent: dict[str, Any] = {
                "template_id": "sample",
                "description": "Scene template using slot-based population.",
                "parameters": {
                    "x": {"type": "int", "required": True, "description": "Anchor x."},
                    "y": {"type": "int", "required": True, "description": "Anchor y."},
                },
                "slot_groups": {
                    "stamp_slots": [{"id": "stamp", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "props"}],
                    "entity_slots": [{"id": "entity", "x": {"add": [{"param": "x"}, 4]}, "y": {"param": "y"}}],
                    "scene_slots": [{"id": "scene", "x": {"add": [{"param": "x"}, 8]}, "y": {"param": "y"}}],
                },
                "ops": [
                    {"kind": "populate_slots", "ruleset": "sample", "catalogue": "stamp_catalogue", "slot_group": "stamp_slots", "seed": 11},
                    {"kind": "populate_slots", "ruleset": "sample", "catalogue": "entity_catalogue", "slot_group": "entity_slots", "seed": 11},
                    {"kind": "populate_slots", "ruleset": "sample", "catalogue": "scene_catalogue", "slot_group": "scene_slots", "seed": 11},
                ],
            }
            _write_json(custom_templates / "sample.json", parent)

            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_rules / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Sample ruleset for populate_slots tests.",
                    "catalogues": {
                        "stamp_catalogue": [
                            {"id": "chair_right", "kind": "stamp", "ref": "indoors.chair.right", "weight": 1}
                        ],
                        "entity_catalogue": [
                            {
                                "id": "square_single",
                                "kind": "entity",
                                "placeable": {"kind": "tile", "id": "minimal8:terrain:3,16"},
                                "layer": "architecture",
                                "weight": 1,
                            }
                        ],
                        "scene_catalogue": [
                            {"id": "fragment", "kind": "scene", "scene": "fragment", "weight": 1}
                        ],
                    },
                },
            )

            project_path = temp_root / "project.json"
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )
            project = harness.LayoutProject(project_path)

            layers = harness.expand_scene(
                project,
                {"template": "sample", "x": 5, "y": 6},
                default_tileset=project.default_tileset_id(),
            )
            runtime = harness.expand_scene_runtime(
                project,
                {"template": "sample", "x": 5, "y": 6},
                default_tileset=project.default_tileset_id(),
            )

            props_stamps = _ops_with_kind(layers, "props", "stamp")
            self.assertEqual(len(props_stamps), 1)
            self.assertEqual(props_stamps[0].get("ref"), "indoors.chair.right")
            self.assertEqual((_op_int(props_stamps[0], "x"), _op_int(props_stamps[0], "y")), (5, 6))

            ornament_stamps = _ops_with_kind(layers, "ornament", "stamp")
            self.assertEqual(len(ornament_stamps), 1)
            self.assertEqual(ornament_stamps[0].get("ref"), "indoors.chair.left")
            self.assertEqual((_op_int(ornament_stamps[0], "x"), _op_int(ornament_stamps[0], "y")), (13, 6))

            entity_positions = {
                (entity.template.placeable_ref, entity.layer, entity.x, entity.y)
                for entity in runtime.entities
            }
            self.assertIn((PlaceableRef(kind="tile", id="minimal8:terrain:3,16"), "architecture", 9, 6), entity_positions)

    def test_populate_slots_is_deterministic_for_same_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_templates / "sample.json",
                {
                    "template_id": "sample",
                    "description": "Deterministic populate_slots test.",
                    "parameters": {
                        "x": {"type": "int", "required": True, "description": "Anchor x."},
                        "y": {"type": "int", "required": True, "description": "Anchor y."},
                    },
                    "slot_groups": {
                        "seats": [
                            {"id": "left", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "props"},
                            {"id": "right", "x": {"add": [{"param": "x"}, 2]}, "y": {"param": "y"}, "layer": "props"},
                        ]
                    },
                    "ops": [
                        {"kind": "populate_slots", "ruleset": "sample", "catalogue": "seats", "slot_group": "seats", "seed": 23}
                    ],
                },
            )

            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_rules / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Weighted seats.",
                    "catalogues": {
                        "seats": [
                            {"id": "chair_right", "kind": "stamp", "ref": "indoors.chair.right", "weight": 1},
                            {"id": "chair_left", "kind": "stamp", "ref": "indoors.chair.left", "weight": 1},
                        ]
                    },
                },
            )

            project_path = temp_root / "project.json"
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )
            project = harness.LayoutProject(project_path)

            first = harness.expand_scene(
                project,
                {"template": "sample", "x": 5, "y": 6},
                default_tileset=project.default_tileset_id(),
            )
            second = harness.expand_scene(
                project,
                {"template": "sample", "x": 5, "y": 6},
                default_tileset=project.default_tileset_id(),
            )

            self.assertEqual(first, second)

    def test_populate_slots_rejects_unknown_ruleset_catalogue_and_slot_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)
            _write_json(
                custom_rules / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Single-catalogue sample ruleset.",
                    "catalogues": {
                        "seats": [
                            {"id": "chair_right", "kind": "stamp", "ref": "indoors.chair.right", "weight": 1}
                        ]
                    },
                },
            )

            project_path = temp_root / "project.json"

            def _project_for_spec(template_spec: dict[str, Any]) -> harness.LayoutProject:
                _write_json(custom_templates / "sample.json", template_spec)
                _write_json(
                    project_path,
                    _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
                )
                return harness.LayoutProject(project_path)

            unknown_ruleset = {
                "template_id": "sample",
                "description": "Unknown ruleset test.",
                "parameters": {"x": {"type": "int", "required": True, "description": "Anchor x."}, "y": {"type": "int", "required": True, "description": "Anchor y."}},
                "slot_groups": {"seats": [{"id": "seat", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "props"}]},
                "ops": [{"kind": "populate_slots", "ruleset": "missing", "catalogue": "seats", "slot_group": "seats", "seed": 1}],
            }
            project = _project_for_spec(unknown_ruleset)
            with self.assertRaisesRegex(ValueError, "Unknown scene ruleset"):
                harness.expand_scene(project, {"template": "sample", "x": 1, "y": 2}, default_tileset=project.default_tileset_id())

            unknown_catalogue = {
                "template_id": "sample",
                "description": "Unknown catalogue test.",
                "parameters": {"x": {"type": "int", "required": True, "description": "Anchor x."}, "y": {"type": "int", "required": True, "description": "Anchor y."}},
                "slot_groups": {"seats": [{"id": "seat", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "props"}]},
                "ops": [{"kind": "populate_slots", "ruleset": "sample", "catalogue": "missing", "slot_group": "seats", "seed": 1}],
            }
            project = _project_for_spec(unknown_catalogue)
            with self.assertRaisesRegex(ValueError, "Unknown scene ruleset catalogue"):
                harness.expand_scene(project, {"template": "sample", "x": 1, "y": 2}, default_tileset=project.default_tileset_id())

            unknown_slot_group = {
                "template_id": "sample",
                "description": "Unknown slot group test.",
                "parameters": {"x": {"type": "int", "required": True, "description": "Anchor x."}, "y": {"type": "int", "required": True, "description": "Anchor y."}},
                "slot_groups": {"seats": [{"id": "seat", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "props"}]},
                "ops": [{"kind": "populate_slots", "ruleset": "sample", "catalogue": "seats", "slot_group": "missing", "seed": 1}],
            }
            project = _project_for_spec(unknown_slot_group)
            with self.assertRaisesRegex(ValueError, "references unknown slot group"):
                harness.expand_scene(project, {"template": "sample", "x": 1, "y": 2}, default_tileset=project.default_tileset_id())

    def test_invalid_raw_coordinate_ruleset_refs_fail_at_project_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            custom_templates = temp_root / "custom-templates"
            custom_templates.mkdir(parents=True, exist_ok=True)
            _write_json(custom_templates / "sample.json", _data_scene_template_spec(template_id="sample"))
            custom_rules = temp_root / "scene-rules"
            custom_rules.mkdir(parents=True, exist_ok=True)

            project_path = temp_root / "project.json"

            _write_json(
                custom_rules / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Invalid explicit coordinate ref.",
                    "catalogues": {
                        "bad": [
                            {"id": "oob_project", "kind": "stamp", "ref": "utility_land#999,999", "weight": 1}
                        ]
                    },
                },
            )
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )
            project = harness.LayoutProject(project_path)
            with self.assertRaisesRegex(ValueError, "references an unknown stamp ref"):
                _ = project.scene_rules_library

            _write_json(
                custom_rules / "sample.json",
                {
                    "ruleset_id": "sample",
                    "description": "Invalid family-backed default coordinate ref.",
                    "catalogues": {
                        "bad": [
                            {"id": "oob_default", "kind": "stamp", "ref": "999,999", "weight": 1}
                        ]
                    },
                },
            )
            _write_json(
                project_path,
                _project_config_with_template_dir(custom_templates, rules_dir=custom_rules),
            )
            project = harness.LayoutProject(project_path)
            with self.assertRaisesRegex(ValueError, "references an unknown stamp ref"):
                _ = project.scene_rules_library


def _make_tile_record(tile_id: str) -> TileRecord:
    return TileRecord(
        id=tile_id,
        family_id="testfam",
        layer="architecture",
        category="tile",
        transparent=False,
        tags=(),
        genesis=TileGenesis(kind="sheet", sheet_col=0, sheet_row=0),
    )


def _make_placeable_unit(
    *,
    tiles: tuple[TileRecord, ...],
    composite_tiles: tuple[CompositeTileRecord, ...] = (),
    attachment_sets: tuple[ConstructionAttachmentSet, ...] = (),
    variant_ids: tuple[str, ...] = ("base",),
) -> TileLibraryUnit:
    attachment_sets_by_id = {attachment_set.id: attachment_set for attachment_set in attachment_sets}
    return TileLibraryUnit(
        family_id="testfam",
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
        composite_tiles={composite.id: composite for composite in composite_tiles},
        attachment_sets=attachment_sets_by_id,
        attachment_sets_by_target=attachment_sets_by_target(attachment_sets_by_id),
    )


class _FakeFamily:
    def __init__(
        self,
        constructions: dict[str, Construction],
        *,
        attachment_sets: dict[str, tuple[ConstructionAttachmentSet, ...]] | None = None,
    ) -> None:
        self._constructions = constructions
        self._attachment_sets = attachment_sets or {}

    def lookup_construction(self, construction_id: str) -> Construction | None:
        return self._constructions.get(construction_id)

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self._attachment_sets.get(construction_id, ())

    def attachment_sets_for_placeable(self, placeable_ref: PlaceableRef) -> tuple[ConstructionAttachmentSet, ...]:
        if placeable_ref.kind != "construction":
            return ()
        return self.attachment_sets_for_construction(placeable_ref.id)

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        construction = self.lookup_construction(construction_id)
        if construction is None:
            return None
        return entity_template_from_construction(
            construction,
            attachment_sets=self.attachment_sets_for_construction(construction_id),
        )

    def runtime_tileset_id_for_construction(
        self, construction_id: str, *, variant_id: str | None = None
    ) -> str | None:
        if construction_id not in self._constructions:
            return None
        return f"testfam@{variant_id or 'base'}"

    def lookup_placeable(self, placeable_ref: PlaceableRef) -> Construction | None:
        if placeable_ref.kind != "construction":
            return None
        return self.lookup_construction(placeable_ref.id)

    def entity_template_for_placeable(self, placeable_ref: PlaceableRef) -> EntityTemplateRecord | None:
        if placeable_ref.kind != "construction":
            return None
        return self.entity_template(placeable_ref.id)

    def runtime_tileset_id_for_placeable(
        self, placeable_ref: PlaceableRef, *, variant_id: str | None = None
    ) -> str | None:
        if placeable_ref.kind != "construction":
            return None
        return self.runtime_tileset_id_for_construction(placeable_ref.id, variant_id=variant_id)

    def lower_placeable_to_tile_cells(self, placeable_ref: PlaceableRef) -> None:
        return None


def _make_fixture_family() -> _FakeFamily:
    tile_a = _make_tile_record("testfam:all:0,0")
    tile_b = _make_tile_record("testfam:all:1,0")
    construction = MetatileConstruction(
        id="test.fixture.two_cells",
        collection_id="test.fixture",
        cells=(
            (tile_a, None),
            (None, tile_b),
        ),
    )
    return _FakeFamily({"test.fixture.two_cells": construction})


def _make_fixture_family_with_attachment() -> _FakeFamily:
    return _make_configured_fixture_family_with_attachment(required=True)


def _make_configured_fixture_family_with_attachment(
    *,
    required: bool,
    default_variant_id: str | None = None,
) -> _FakeFamily:
    tile_a = _make_tile_record("testfam:all:0,0")
    tile_b = _make_tile_record("testfam:all:1,0")
    base = MetatileConstruction(
        id="test.fixture.body",
        collection_id="test.fixture.body",
        cells=((tile_a,),),
    )
    attachment = MetatileConstruction(
        id="test.fixture.head.alt",
        collection_id="test.fixture.head.alt",
        cells=((tile_b,),),
        expose_as_entity=False,
    )
    attachment_set = ConstructionAttachmentSet(
        id="test.fixture.body.heads",
        param="head",
        target_construction_ids=("test.fixture.body",),
        canvas=GridBounds(x=0, y=0, width=1, height=1),
        variants={
            "alt": ConstructionAttachmentVariant(
                id="alt",
                construction_id="test.fixture.head.alt",
            )
        },
        required=required,
        default_variant_id=default_variant_id,
    )
    return _FakeFamily(
        {
            "test.fixture.body": base,
            "test.fixture.head.alt": attachment,
        },
        attachment_sets={"test.fixture.body": (attachment_set,)},
    )


class EntityOpExpandStampsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.family = _make_fixture_family()

    def test_filled_cells_produce_stamps_at_offset_coordinates(self) -> None:
        stamps = harness.expand_entity_stamps(
            self.family,  # type: ignore[arg-type]
            "test.fixture.two_cells",
            x=4,
            y=2,
            context="test",
        )
        self.assertEqual(len(stamps), 2)
        coords = {(s["x"], s["y"]) for s in stamps}
        self.assertIn((4, 2), coords)
        self.assertIn((5, 3), coords)

    def test_stamp_refs_match_cell_tile_ids(self) -> None:
        stamps = harness.expand_entity_stamps(
            self.family,  # type: ignore[arg-type]
            "test.fixture.two_cells",
            x=0,
            y=0,
            context="test",
        )
        refs = {cast(str, s["ref"]) for s in stamps}
        self.assertEqual(refs, {"testfam:all:0,0", "testfam:all:1,0"})

    def test_empty_cells_produce_no_stamps(self) -> None:
        stamps = harness.expand_entity_stamps(
            self.family,  # type: ignore[arg-type]
            "test.fixture.two_cells",
            x=0,
            y=0,
            context="test",
        )
        self.assertEqual(len(stamps), 2)

    def test_missing_construction_raises_with_id_in_message(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            harness.expand_entity_stamps(
                self.family,  # type: ignore[arg-type]
                "missing.construction.id",
                x=0,
                y=0,
                context="test op 3",
            )
        self.assertIn("missing.construction.id", str(ctx.exception))

    def test_attachment_params_expand_additional_stamps(self) -> None:
        family = _make_fixture_family_with_attachment()

        stamps = harness.expand_entity_stamps(
            family,  # type: ignore[arg-type]
            "test.fixture.body",
            x=3,
            y=4,
            context="test attachment expansion",
            params={"head": "alt"},
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [
                ("testfam:all:0,0", 3, 4),
                ("testfam:all:1,0", 3, 4),
            ],
        )

    def test_missing_optional_attachment_param_uses_default_variant_when_present(self) -> None:
        family = _make_configured_fixture_family_with_attachment(
            required=False,
            default_variant_id="alt",
        )

        stamps = harness.expand_entity_stamps(
            family,  # type: ignore[arg-type]
            "test.fixture.body",
            x=3,
            y=4,
            context="test attachment default",
        )

        self.assertEqual(len(stamps), 2)
        self.assertEqual(cast(str, stamps[1]["ref"]), "testfam:all:1,0")

    def test_missing_optional_attachment_param_skips_overlay_when_no_default(self) -> None:
        family = _make_configured_fixture_family_with_attachment(required=False)

        stamps = harness.expand_entity_stamps(
            family,  # type: ignore[arg-type]
            "test.fixture.body",
            x=3,
            y=4,
            context="test attachment optional",
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [("testfam:all:0,0", 3, 4)],
        )

    def test_scene_entity_request_applies_attachment_params(self) -> None:
        family = _make_fixture_family_with_attachment()

        entity = harness._resolve_scene_entity_request(  # type: ignore[attr-defined]
            family,  # type: ignore[arg-type]
            harness.SceneEntityRequest(
                entity_id="fixture.body",
                source_template_id="fixture",
                construction_id="test.fixture.body",
                layer="actors",
                x=8,
                y=9,
                params={"head": "alt"},
            ),
        )

        self.assertEqual(
            [(placement.ref, placement.x, placement.y) for placement in entity.tiles],
            [("testfam:all:0,0", 8, 9), ("testfam:all:1,0", 8, 9)],
        )
        self.assertEqual(entity.template.placeable_kind, "construction")
        self.assertEqual(entity.template.placeable_id, "test.fixture.body")
        self.assertEqual(entity.template.construction_id, "test.fixture.body")

    def test_scene_entity_request_exposes_canonical_construction_placeable(self) -> None:
        request = harness.SceneEntityRequest(
            entity_id="fixture.body",
            source_template_id="fixture",
            construction_id="test.fixture.body",
            layer="actors",
            x=8,
            y=9,
        )

        self.assertEqual(request.placeable_kind, "construction")
        self.assertEqual(request.placeable_id, "test.fixture.body")
        self.assertEqual(request.placeable_ref, PlaceableRef(kind="construction", id="test.fixture.body"))

    def test_scene_entity_request_allows_non_construction_placeable_without_fake_construction(self) -> None:
        request = harness.SceneEntityRequest(
            entity_id="fixture.tile",
            source_template_id="fixture",
            layer="actors",
            x=8,
            y=9,
            placeable_kind="tile",
            placeable_id="tile.a",
        )

        self.assertIsNone(request.construction_id)
        self.assertEqual(request.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))

    def test_scene_entity_request_defaults_legacy_construction_to_placeable(self) -> None:
        request = harness.SceneEntityRequest(
            entity_id="fixture.body",
            source_template_id="fixture",
            construction_id="test.fixture.body",
            layer="actors",
            x=8,
            y=9,
        )

        self.assertEqual(request.placeable_kind, "construction")
        self.assertEqual(request.placeable_id, "test.fixture.body")

    def test_scene_entity_request_rejects_mismatched_compatibility_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "construction_id is only valid"):
            harness.SceneEntityRequest(
                entity_id="fixture.body",
                source_template_id="fixture",
                construction_id="test.fixture.body",
                layer="actors",
                x=8,
                y=9,
                placeable_kind="construction",
                placeable_id="test.fixture.other",
            )

    def test_scene_entity_request_resolves_atomic_tile_placeable(self) -> None:
        tile = _make_tile_record("tile.a")
        unit = _make_placeable_unit(tiles=(tile,))

        entity = harness._resolve_scene_entity_request(  # type: ignore[attr-defined]
            unit,
            harness.SceneEntityRequest(
                entity_id="fixture.tile",
                source_template_id="fixture",
                layer="actors",
                x=8,
                y=9,
                placeable_kind="tile",
                placeable_id="tile.a",
            ),
        )

        self.assertEqual(entity.template.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))
        self.assertEqual(entity.template.footprint.width, 1)
        self.assertEqual(entity.template.footprint.height, 1)
        self.assertEqual([(placement.ref, placement.x, placement.y) for placement in entity.tiles], [("tile.a", 8, 9)])
        self.assertEqual([(cell.tile_id, cell.relative_x, cell.relative_y) for cell in entity.occupied_cells], [("tile.a", 0, 0)])

    def test_scene_entity_request_resolves_composite_tile_placeable(self) -> None:
        tile_a = _make_tile_record("tile.a")
        tile_b = _make_tile_record("tile.b")
        composite = CompositeTileRecord(
            id="character.full",
            family_id="testfam",
            collection_id="characters",
            cells=(
                (CompositeTileCell(tile=tile_a, x=0, y=0),),
                (CompositeTileCell(tile=tile_b, x=0, y=1),),
            ),
        )
        unit = _make_placeable_unit(tiles=(tile_a, tile_b), composite_tiles=(composite,))

        entity = harness._resolve_scene_entity_request(  # type: ignore[attr-defined]
            unit,
            harness.SceneEntityRequest(
                entity_id="fixture.character",
                source_template_id="fixture",
                layer="actors",
                x=8,
                y=9,
                placeable_kind="composite_tile",
                placeable_id="character.full",
            ),
        )

        self.assertEqual(entity.template.placeable_ref, PlaceableRef(kind="composite_tile", id="character.full"))
        self.assertEqual(entity.template.footprint.width, 1)
        self.assertEqual(entity.template.footprint.height, 2)
        self.assertEqual(
            [(placement.ref, placement.x, placement.y) for placement in entity.tiles],
            [("tile.a", 8, 9), ("tile.b", 8, 10)],
        )
        self.assertEqual(
            [(cell.tile_id, cell.relative_x, cell.relative_y) for cell in entity.occupied_cells],
            [("tile.a", 0, 0), ("tile.b", 0, 1)],
        )

    def test_expand_placeable_stamps_resolves_composite_tile_placeable(self) -> None:
        tile_a = _make_tile_record("tile.a")
        tile_b = _make_tile_record("tile.b")
        composite = CompositeTileRecord(
            id="character.full",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile_a, x=0, y=0), CompositeTileCell(tile=tile_b, x=1, y=0)),),
        )
        unit = _make_placeable_unit(tiles=(tile_a, tile_b), composite_tiles=(composite,))

        stamps = harness.expand_placeable_stamps(
            unit,
            PlaceableRef(kind="composite_tile", id="character.full"),
            x=4,
            y=5,
            context="test composite",
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [("tile.a", 4, 5), ("tile.b", 5, 5)],
        )

    def test_expand_placeable_stamps_resolves_atomic_tile_placeable(self) -> None:
        tile = _make_tile_record("tile.a")
        unit = _make_placeable_unit(tiles=(tile,))

        stamps = harness.expand_placeable_stamps(
            unit,
            PlaceableRef(kind="tile", id="tile.a"),
            x=4,
            y=5,
            context="test tile",
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [("tile.a", 4, 5)],
        )

    def test_expand_placeable_stamps_qualifies_atomic_tile_variant_refs(self) -> None:
        tile = _make_tile_record("tile.a")
        unit = _make_placeable_unit(tiles=(tile,), variant_ids=("base", "night"))

        stamps = harness.expand_placeable_stamps(
            unit,
            PlaceableRef(kind="tile", id="tile.a"),
            x=4,
            y=5,
            context="test tile variant",
            variant_id="night",
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [("testfam@night:tile.a", 4, 5)],
        )

    def test_expand_placeable_stamps_qualifies_composite_tile_variant_refs(self) -> None:
        tile_a = _make_tile_record("tile.a")
        tile_b = _make_tile_record("tile.b")
        composite = CompositeTileRecord(
            id="character.full",
            family_id="testfam",
            collection_id="characters",
            cells=((CompositeTileCell(tile=tile_a, x=0, y=0), CompositeTileCell(tile=tile_b, x=1, y=0)),),
        )
        unit = _make_placeable_unit(
            tiles=(tile_a, tile_b),
            composite_tiles=(composite,),
            variant_ids=("base", "night"),
        )

        stamps = harness.expand_placeable_stamps(
            unit,
            PlaceableRef(kind="composite_tile", id="character.full"),
            x=4,
            y=5,
            context="test composite variant",
            variant_id="night",
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [("testfam@night:tile.a", 4, 5), ("testfam@night:tile.b", 5, 5)],
        )

    def test_expand_placeable_stamps_rejects_unknown_tile_variant_with_context(self) -> None:
        tile = _make_tile_record("tile.a")
        unit = _make_placeable_unit(tiles=(tile,))

        with self.assertRaisesRegex(ValueError, "Unknown variant 'missing'.*placeable tile:'tile.a'"):
            harness.expand_placeable_stamps(
                unit,
                PlaceableRef(kind="tile", id="tile.a"),
                x=4,
                y=5,
                context="test tile variant",
                variant_id="missing",
            )

    def test_expand_placeable_stamps_applies_composite_attachment_fill(self) -> None:
        body_left = _make_tile_record("body.left")
        body_right = _make_tile_record("body.right")
        head_left = _make_tile_record("head.left")
        head_right = _make_tile_record("head.right")
        body = CompositeTileRecord(
            id="character.body",
            family_id="testfam",
            collection_id="characters",
            cells=(
                (None, None),
                (None, None),
                (
                    CompositeTileCell(tile=body_left, x=0, y=2),
                    CompositeTileCell(tile=body_right, x=1, y=2),
                ),
            ),
        )
        head = CompositeTileRecord(
            id="character.head.alt",
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
            canvas=GridBounds(x=0, y=0, width=2, height=1),
            target_placeable_refs=(PlaceableRef(kind="composite_tile", id="character.body"),),
            variants={
                "alt": ConstructionAttachmentVariant(
                    id="alt",
                    placeable_kind="composite_tile",
                    placeable_id="character.head.alt",
                )
            },
            required=True,
        )
        unit = _make_placeable_unit(
            tiles=(body_left, body_right, head_left, head_right),
            composite_tiles=(body, head),
            attachment_sets=(attachment_set,),
        )

        stamps = harness.expand_placeable_stamps(
            unit,
            PlaceableRef(kind="composite_tile", id="character.body"),
            x=4,
            y=5,
            context="test composite attachment",
            params={"head": "alt"},
        )

        self.assertEqual(
            [(cast(str, stamp["ref"]), stamp["x"], stamp["y"]) for stamp in stamps],
            [
                ("body.left", 4, 7),
                ("body.right", 5, 7),
                ("head.left", 4, 5),
                ("head.right", 5, 5),
            ],
        )

    def test_scene_rule_entity_candidate_allows_non_construction_placeable_without_fake_construction(self) -> None:
        candidate = SceneRuleEntityCandidate(
            candidate_id="tile",
            weight=1.0,
            placeable_kind="tile",
            placeable_id="tile.a",
        )

        self.assertIsNone(candidate.construction_id)
        self.assertEqual(candidate.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))

    def test_scene_rule_entity_candidate_defaults_legacy_construction_to_placeable(self) -> None:
        candidate = SceneRuleEntityCandidate(
            candidate_id="body",
            weight=1.0,
            construction_id="test.fixture.body",
        )

        self.assertEqual(candidate.placeable_kind, "construction")
        self.assertEqual(candidate.placeable_id, "test.fixture.body")

    def test_scene_rule_entity_candidate_rejects_mismatched_compatibility_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "construction_id is only valid"):
            SceneRuleEntityCandidate(
                candidate_id="body",
                weight=1.0,
                construction_id="test.fixture.body",
                placeable_kind="construction",
                placeable_id="test.fixture.other",
            )

    def test_scene_entity_request_selects_variant_tileset(self) -> None:
        family = _make_fixture_family()

        def _refs(variant_id: str | None) -> set[str]:
            entity = harness._resolve_scene_entity_request(  # type: ignore[attr-defined]
                family,  # type: ignore[arg-type]
                harness.SceneEntityRequest(
                    entity_id="fixture",
                    source_template_id="fixture",
                    construction_id="test.fixture.two_cells",
                    layer="architecture",
                    x=0,
                    y=0,
                    variant_id=variant_id,
                ),
            )
            return {placement.ref for placement in entity.tiles}

        # Without a variant the placement refs are bare tile ids; with an explicit
        # variant they are prefixed with that variant's runtime tileset id.
        self.assertEqual(_refs(None), {"testfam:all:0,0", "testfam:all:1,0"})
        self.assertEqual(
            _refs("alt"),
            {"testfam@alt:testfam:all:0,0", "testfam@alt:testfam:all:1,0"},
        )


class EntityOpDataSceneTests(unittest.TestCase):
    def _data_scene_with_entity(self, *, template_id: str = "entity_test") -> dict[str, Any]:
        return {
            "template_id": template_id,
            "description": "entity op fixture template",
            "parameters": {
                "x": {"type": "int", "required": True, "description": "Left tile coordinate."},
                "y": {"type": "int", "required": True, "description": "Top tile coordinate."},
            },
            "ops": [
                {
                    "kind": "entity",
                    "layer": "architecture",
                    "construction": "test.fixture.two_cells",
                    "x": {"param": "x"},
                    "y": {"param": "y"},
                }
            ],
        }

    def _make_runtime(self) -> scene_templates.SceneTemplateRuntime:
        return scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
        )

    def test_entity_op_emits_entity_request(self) -> None:
        spec_raw = self._data_scene_with_entity()

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_test", "x": 4, "y": 2},
            spec,
            runtime=runtime,
        )

        self.assertEqual(expanded.layers, {})
        self.assertEqual(len(expanded.entities), 1)
        entity = expanded.entities[0]
        self.assertEqual(entity.construction_id, "test.fixture.two_cells")
        self.assertEqual(entity.layer, "architecture")
        self.assertEqual((entity.x, entity.y), (4, 2))
        self.assertEqual(entity.source_template_id, "entity_test")

    def test_entity_op_forwards_variant_id(self) -> None:
        spec_raw = self._data_scene_with_entity()
        spec_raw["ops"][0]["variant_id"] = "alt"

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_test", "x": 4, "y": 2},
            spec,
            runtime=runtime,
        )

        self.assertEqual(len(expanded.entities), 1)
        self.assertEqual(expanded.entities[0].variant_id, "alt")

    def test_entity_op_defaults_variant_id_to_none(self) -> None:
        spec_raw = self._data_scene_with_entity()

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_test", "x": 4, "y": 2},
            spec,
            runtime=runtime,
        )

        self.assertIsNone(expanded.entities[0].variant_id)

    def test_entity_op_accepts_canonical_placeable_ref(self) -> None:
        spec_raw = self._data_scene_with_entity()
        entity_op = cast(dict[str, object], spec_raw["ops"][0])
        entity_op.pop("construction")
        entity_op["placeable"] = {"kind": "tile", "id": "tile.a"}

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_test", "x": 4, "y": 2},
            spec,
            runtime=runtime,
        )

        entity = expanded.entities[0]
        self.assertIsNone(entity.construction_id)
        self.assertEqual(entity.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))

    def test_entity_op_rejects_both_construction_and_placeable(self) -> None:
        spec_raw = self._data_scene_with_entity()
        cast(dict[str, object], spec_raw["ops"][0])["placeable"] = {"kind": "tile", "id": "tile.a"}

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
                scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

    def test_entity_op_rejects_missing_placeable_identity(self) -> None:
        spec_raw = self._data_scene_with_entity()
        cast(dict[str, object], spec_raw["ops"][0]).pop("construction")

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
                scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

    def test_layout_entity_op_dispatches_canonical_placeable_ref(self) -> None:
        class _Project:
            tile_library_registry = object()

        stamp = {"kind": "stamp", "ref": "tile.a", "x": 2, "y": 3}
        op = {
            "kind": "entity",
            "layer": "architecture",
            "placeable": {"kind": "tile", "id": "tile.a"},
            "x": 2,
            "y": 3,
        }
        project = _Project()

        with patch.object(harness, "expand_placeable_stamps", return_value=[stamp]) as expand_placeable, patch.object(
            harness,
            "_apply_stamp_op",
        ) as apply_stamp:
            harness._apply_entity_op(  # type: ignore[attr-defined]
                [],
                cast(Any, project),
                cast(Any, op),
                default_tileset=None,
            )

        expand_placeable.assert_called_once_with(
            project.tile_library_registry,
            PlaceableRef(kind="tile", id="tile.a"),
            2,
            3,
            context="layout entity op",
            params=None,
            variant_id=None,
        )
        apply_stamp.assert_called_once_with([], cast(Any, project), stamp, default_tileset=None)

    def test_layout_entity_op_rejects_missing_placeable_identity(self) -> None:
        class _Project:
            tile_library_registry = object()

        op = {
            "kind": "entity",
            "layer": "architecture",
            "x": 2,
            "y": 3,
        }

        with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
            harness._apply_entity_op(  # type: ignore[attr-defined]
                [],
                cast(Any, _Project()),
                cast(Any, op),
                default_tileset=None,
            )

    def test_layout_entity_op_rejects_both_construction_and_placeable(self) -> None:
        class _Project:
            tile_library_registry = object()

        op = {
            "kind": "entity",
            "layer": "architecture",
            "construction": "test.fixture.two_cells",
            "placeable": {"kind": "tile", "id": "tile.a"},
            "x": 2,
            "y": 3,
        }

        with self.assertRaisesRegex(ValueError, "exactly one of construction or placeable"):
            harness._apply_entity_op(  # type: ignore[attr-defined]
                [],
                cast(Any, _Project()),
                cast(Any, op),
                default_tileset=None,
            )

    def test_layout_entity_op_rejects_malformed_placeable_ref(self) -> None:
        class _Project:
            tile_library_registry = object()

        for placeable, expected in (
            ("tile.a", "layout entity op placeable must be a JSON object"),
            ({"id": "tile.a"}, "layout entity op placeable kind must be a string"),
            ({"kind": "tile"}, "layout entity op placeable id must be a string"),
        ):
            with self.subTest(placeable=placeable):
                op = {
                    "kind": "entity",
                    "layer": "architecture",
                    "placeable": placeable,
                    "x": 2,
                    "y": 3,
                }

                with self.assertRaisesRegex(ValueError, expected):
                    harness._apply_entity_op(  # type: ignore[attr-defined]
                        [],
                        cast(Any, _Project()),
                        cast(Any, op),
                        default_tileset=None,
                    )

    def test_layout_entity_op_rejects_invalid_placeable_kind(self) -> None:
        class _Project:
            tile_library_registry = object()

        op = {
            "kind": "entity",
            "layer": "architecture",
            "placeable": {"kind": "scene", "id": "scene.a"},
            "x": 2,
            "y": 3,
        }

        with self.assertRaisesRegex(ValueError, "PlaceableRef.kind is invalid"):
            harness._apply_entity_op(  # type: ignore[attr-defined]
                [],
                cast(Any, _Project()),
                cast(Any, op),
                default_tileset=None,
            )

    def test_populate_slots_forwards_candidate_placeable_identity_to_entity_request(self) -> None:
        spec_raw: dict[str, Any] = {
            "template_id": "slot_entity_test",
            "description": "populate_slots entity forwarding fixture",
            "parameters": {
                "x": {"type": "int", "required": True, "description": "Left tile coordinate."},
                "y": {"type": "int", "required": True, "description": "Top tile coordinate."},
            },
            "slot_groups": {
                "targets": [{"id": "target", "x": {"param": "x"}, "y": {"param": "y"}, "layer": "actors"}],
            },
            "ops": [
                {
                    "kind": "populate_slots",
                    "ruleset": "sample",
                    "catalogue": "entities",
                    "slot_group": "targets",
                    "seed": 1,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "slot_entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
            scene_rules_library=SceneRulesetLibrary(
                root=Path("."),
                specs={
                    "sample": SceneRulesetSpec(
                        ruleset_id="sample",
                        description="Synthetic in-memory ruleset.",
                        catalogues={
                            "entities": (
                                SceneRuleEntityCandidate(
                                    candidate_id="tile_candidate",
                                    weight=1.0,
                                    placeable_kind="tile",
                                    placeable_id="tile.a",
                                ),
                            ),
                        },
                    ),
                },
            ),
        )
        expanded = scene_templates.expand_data_scene(
            {"template": "slot_entity_test", "x": 4, "y": 2},
            spec,
            runtime=runtime,
        )

        self.assertEqual(len(expanded.entities), 1)
        entity = expanded.entities[0]
        self.assertIsNone(entity.construction_id)
        self.assertEqual(entity.placeable_kind, "tile")
        self.assertEqual(entity.placeable_id, "tile.a")
        self.assertEqual(entity.placeable_ref, PlaceableRef(kind="tile", id="tile.a"))

    def test_entity_op_preserves_explicit_entity_id(self) -> None:
        spec_raw = self._data_scene_with_entity()
        spec_raw["ops"][0]["entity_id"] = "bar.counter"

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_test", "x": 0, "y": 0},
            spec,
            runtime=runtime,
        )
        self.assertEqual(expanded.entities[0].entity_id, "bar.counter")

    def test_entity_op_forwards_params_to_parametric_run(self) -> None:
        spec_raw: dict[str, Any] = {
            "template_id": "entity_params_test",
            "description": "entity op fixture with params for parametric_run",
            "parameters": {
                "x": {"type": "int", "required": True, "description": "X."},
                "y": {"type": "int", "required": True, "description": "Y."},
                "length": {"type": "int", "required": True, "description": "Run length."},
            },
            "ops": [
                {
                    "kind": "entity",
                    "layer": "architecture",
                    "construction": "test.run",
                    "x": {"param": "x"},
                    "y": {"param": "y"},
                    "params": {"length": {"param": "length"}},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = Path(tmpdir) / "entity_params_test.json"
            _write_json(tpl_path, spec_raw)
            spec = scene_templates._load_scene_template_spec(tpl_path)  # type: ignore[attr-defined]

        runtime = self._make_runtime()
        expanded = scene_templates.expand_data_scene(
            {"template": "entity_params_test", "x": 5, "y": 3, "length": 4},
            spec,
            runtime=runtime,
        )

        self.assertEqual(len(expanded.entities), 1)
        entity = expanded.entities[0]
        self.assertEqual(entity.params, {"length": 4})
        self.assertEqual((entity.x, entity.y), (5, 3))


class ScatterDataModeOpTests(unittest.TestCase):
    def _make_library(self, templates: dict[str, dict[str, Any]]) -> scene_templates.SceneTemplateLibrary:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            for name, spec in templates.items():
                _write_json(templates_dir / f"{name}.json", spec)
            return scene_templates.load_scene_template_library(Path(tmpdir), str(templates_dir))

    def test_scatter_op_emits_to_correct_layer_with_evaluated_fields(self) -> None:
        spec_raw: dict[str, Any] = {
            "template_id": "scatter_test",
            "description": "scatter op fixture",
            "parameters": {
                "scatter_x": {"type": "int", "required": True, "description": "X."},
                "scatter_y": {"type": "int", "required": True, "description": "Y."},
            },
            "bindings": {
                "scatter_density": 0.25,
                "scatter_seed": 42,
            },
            "ops": [
                {
                    "kind": "scatter",
                    "layer": "terrain",
                    "ref": "scatter.tile",
                    "x": {"param": "scatter_x"},
                    "y": {"param": "scatter_y"},
                    "rows": {"fill_rows": {"width": 3, "height": 2}},
                    "density": {"bind": "scatter_density"},
                    "seed": {"bind": "scatter_seed"},
                }
            ],
        }
        library = self._make_library({"scatter_test": spec_raw})
        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
            scene_library=library,
        )
        spec = library.require("scatter_test")
        layers = scene_templates.expand_data_scene(
            {"template": "scatter_test", "scatter_x": 4, "scatter_y": 6},
            spec,
            runtime=runtime,
        ).layers

        scatters = _ops_with_kind(layers, "terrain", "scatter")
        self.assertEqual(len(scatters), 1)
        op = scatters[0]
        self.assertEqual(op.get("ref"), "scatter.tile")
        self.assertEqual(_op_int(op, "x"), 4)
        self.assertEqual(_op_int(op, "y"), 6)
        self.assertEqual(op.get("rows"), ["###", "###"])
        self.assertEqual(op.get("density"), 0.25)
        self.assertEqual(op.get("seed"), 42)


def _make_parametric_family(construction_id: str) -> _FakeFamily:
    construction = ParametricRunConstruction(
        id=construction_id,
        collection_id="test.collection",
        axis="x",
        length_param="length",
        start_tile=_make_tile_record("testfam:all:0,0"),
        repeat_tile=_make_tile_record("testfam:all:1,0"),
        end_tile=_make_tile_record("testfam:all:2,0"),
    )
    return _FakeFamily({construction_id: construction})


class ParametricRunExpansionTests(unittest.TestCase):
    def _expand(self, length: int, x: int = 5, y: int = 3) -> list[Any]:
        family = _make_parametric_family("test.run")
        return harness.expand_entity_stamps(
            family,  # type: ignore[arg-type]
            "test.run",
            x=x,
            y=y,
            context="test",
            params={"length": length},
        )

    def test_length_2_emits_start_then_end(self) -> None:
        stamps = self._expand(length=2, x=10, y=2)
        self.assertEqual(len(stamps), 2)
        self.assertEqual(stamps[0]["ref"], "testfam:all:0,0")
        self.assertEqual(stamps[0]["x"], 10)
        self.assertEqual(stamps[1]["ref"], "testfam:all:2,0")
        self.assertEqual(stamps[1]["x"], 11)

    def test_length_3_emits_start_repeat_end(self) -> None:
        stamps = self._expand(length=3, x=0, y=0)
        self.assertEqual(len(stamps), 3)
        self.assertEqual(stamps[0]["ref"], "testfam:all:0,0")
        self.assertEqual(stamps[1]["ref"], "testfam:all:1,0")
        self.assertEqual(stamps[2]["ref"], "testfam:all:2,0")

    def test_length_18_emits_correct_tile_sequence(self) -> None:
        stamps = self._expand(length=18, x=11, y=8)
        self.assertEqual(len(stamps), 18)
        self.assertEqual(stamps[0]["ref"], "testfam:all:0,0")
        for i in range(1, 17):
            self.assertEqual(stamps[i]["ref"], "testfam:all:1,0")
        self.assertEqual(stamps[17]["ref"], "testfam:all:2,0")
        self.assertEqual(stamps[0]["x"], 11)
        self.assertEqual(stamps[17]["x"], 28)
        self.assertEqual(stamps[0]["y"], 8)

    def test_all_stamps_on_same_row_for_x_axis(self) -> None:
        stamps = self._expand(length=5, x=0, y=7)
        for stamp in stamps:
            self.assertEqual(stamp["y"], 7)
        xs = [stamp["x"] for stamp in stamps]
        self.assertEqual(xs, list(range(0, 5)))

    def test_missing_params_raises(self) -> None:
        family = _make_parametric_family("test.run")
        with self.assertRaises(ValueError) as ctx:
            harness.expand_entity_stamps(
                family,  # type: ignore[arg-type]
                "test.run",
                x=0,
                y=0,
                context="test",
                params=None,
            )
        self.assertIn("test.run", str(ctx.exception))

    def test_length_less_than_2_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._expand(length=1)


class PlaceSceneTests(unittest.TestCase):
    def _make_library(self, templates: dict[str, dict[str, Any]]) -> scene_templates.SceneTemplateLibrary:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            for name, spec in templates.items():
                _write_json(templates_dir / f"{name}.json", spec)
            return scene_templates.load_scene_template_library(Path(tmpdir), str(templates_dir))

    def _sub_scene_spec(self, template_id: str = "sub") -> dict[str, Any]:
        return {
            "template_id": template_id,
            "description": "sub-scene fixture",
            "parameters": {
                "label": {"type": "str", "required": False, "description": "Label passed from parent."}
            },
            "bindings": {
                "label": {"param": "label", "default": "default_label"}
            },
            "ops": [
                {
                    "kind": "stamp",
                    "layer": "sub_layer",
                    "ref": "sub.tile.a",
                    "x": 0,
                    "y": 0
                },
                {
                    "kind": "stamp",
                    "layer": "sub_layer",
                    "ref": "sub.tile.b",
                    "x": 2,
                    "y": 1
                }
            ]
        }

    def _parent_scene_spec(self, sub_id: str = "sub", *, offset_x: int = 5, offset_y: int = 3) -> dict[str, Any]:
        return {
            "template_id": "parent",
            "description": "parent-scene fixture",
            "parameters": {},
            "ops": [
                {
                    "kind": "stamp",
                    "layer": "parent_layer",
                    "ref": "parent.tile",
                    "x": 0,
                    "y": 0
                },
                {
                    "kind": "place_scene",
                    "scene": sub_id,
                    "x": offset_x,
                    "y": offset_y,
                    "args": {}
                }
            ]
        }

    def test_sub_scene_stamps_are_offset_by_parent_position(self) -> None:
        library = self._make_library({"sub": self._sub_scene_spec(), "parent": self._parent_scene_spec()})
        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
            scene_library=library,
        )
        spec = library.require("parent")
        layers = scene_templates.expand_data_scene({"template": "parent"}, spec, runtime=runtime).layers

        self.assertIn("parent_layer", layers)
        self.assertIn("sub_layer", layers)

        parent_stamps = _ops_with_kind(layers, "parent_layer", "stamp")
        self.assertEqual(len(parent_stamps), 1)
        self.assertEqual(parent_stamps[0].get("ref"), "parent.tile")
        self.assertEqual(_op_int(parent_stamps[0], "x"), 0)
        self.assertEqual(_op_int(parent_stamps[0], "y"), 0)

        sub_stamps = _ops_with_kind(layers, "sub_layer", "stamp")
        self.assertEqual(len(sub_stamps), 2)
        coords = {(_op_int(s, "x"), _op_int(s, "y")) for s in sub_stamps}
        self.assertIn((5, 3), coords)
        self.assertIn((7, 4), coords)

    def test_sub_scene_entities_are_offset_by_parent_position(self) -> None:
        sub_spec: dict[str, Any] = {
            "template_id": "sub",
            "description": "sub-scene entity fixture",
            "parameters": {},
            "ops": [
                {
                    "kind": "entity",
                    "layer": "architecture",
                    "construction": "test.fixture.two_cells",
                    "x": 2,
                    "y": 1,
                }
            ],
        }
        parent_spec = self._parent_scene_spec(sub_id="sub", offset_x=5, offset_y=3)
        library = self._make_library({"sub": sub_spec, "parent": parent_spec})
        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
            scene_library=library,
        )
        spec = library.require("parent")
        expanded = scene_templates.expand_data_scene({"template": "parent"}, spec, runtime=runtime)

        self.assertEqual(len(expanded.entities), 1)
        entity = expanded.entities[0]
        self.assertEqual(entity.construction_id, "test.fixture.two_cells")
        self.assertEqual((entity.x, entity.y), (7, 4))

    def test_sub_scene_does_not_see_parent_bindings(self) -> None:
        # Both scenes declare a binding called 'secret', with different values.
        # Sub's binding falls back to its own default (7) when the parameter is
        # not supplied via args. Parent has secret=99. If isolation breaks and
        # parent's binding frame leaked into sub, the stamp x would be 99.
        sub_spec: dict[str, Any] = {
            "template_id": "sub",
            "description": "sub-scene with its own 'secret' binding and default",
            "parameters": {
                "secret": {"type": "int", "required": False, "description": "Sub's own secret."}
            },
            "bindings": {
                "secret": {"param": "secret", "default": 7}
            },
            "ops": [
                {
                    "kind": "stamp",
                    "layer": "sub_layer",
                    "ref": "sub.tile",
                    "x": {"bind": "secret"},
                    "y": 0,
                }
            ]
        }
        parent_spec: dict[str, Any] = {
            "template_id": "parent",
            "description": "parent fixture; has 'secret'=99 but does not pass it",
            "parameters": {},
            "bindings": {
                "secret": 99
            },
            "ops": [
                {
                    "kind": "place_scene",
                    "scene": "sub",
                    "x": 0,
                    "y": 0,
                    "args": {}
                }
            ]
        }
        library = self._make_library({"sub": sub_spec, "parent": parent_spec})
        runtime = scene_templates.SceneTemplateRuntime(
            pattern_dimensions=lambda ref: (1, 1),
            centered_pattern_x=lambda ref, x, width: x,
            scene_library=library,
        )
        spec = library.require("parent")
        layers = scene_templates.expand_data_scene({"template": "parent"}, spec, runtime=runtime).layers

        sub_stamps = _ops_with_kind(layers, "sub_layer", "stamp")
        self.assertEqual(len(sub_stamps), 1)
        self.assertEqual(_op_int(sub_stamps[0], "x"), 7)

    def test_place_scene_cycle_raises_at_load_time(self) -> None:
        alpha_spec: dict[str, Any] = {
            "template_id": "alpha",
            "description": "alpha fixture",
            "parameters": {},
            "ops": [{"kind": "place_scene", "scene": "beta", "x": 0, "y": 0}]
        }
        beta_spec: dict[str, Any] = {
            "template_id": "beta",
            "description": "beta fixture",
            "parameters": {},
            "ops": [{"kind": "place_scene", "scene": "alpha", "x": 0, "y": 0}]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            _write_json(templates_dir / "alpha.json", alpha_spec)
            _write_json(templates_dir / "beta.json", beta_spec)
            with self.assertRaises(ValueError) as ctx:
                scene_templates.load_scene_template_library(Path(tmpdir), str(templates_dir))
            error_msg = str(ctx.exception)
            self.assertIn("cycle", error_msg.lower())
            self.assertIn("alpha", error_msg)
            self.assertIn("beta", error_msg)

    def test_place_scene_self_cycle_raises_at_load_time(self) -> None:
        self_spec: dict[str, Any] = {
            "template_id": "self_ref",
            "description": "self-referencing fixture",
            "parameters": {},
            "ops": [{"kind": "place_scene", "scene": "self_ref", "x": 0, "y": 0}]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            _write_json(templates_dir / "self_ref.json", self_spec)
            with self.assertRaises(ValueError) as ctx:
                scene_templates.load_scene_template_library(Path(tmpdir), str(templates_dir))
            self.assertIn("cycle", str(ctx.exception).lower())


def _make_frame_construction(
    *,
    with_edges: bool = True,
    with_fill: bool = True,
    corners: tuple[str, ...] = ("tl", "tr", "bl", "br"),
    min_width: int = 2,
    min_height: int = 2,
) -> ParametricFrameConstruction:
    def _tile(role: str) -> TileRecord:
        return _make_tile_record(f"testfam:all:{role}")

    corner_map = {f"corner_{c}": FrameCornerSlot(cells=((_tile(f"corner_{c}"),),)) for c in corners}
    edges: dict[str, FrameSlot] = {}
    if with_edges:
        for edge in ("top", "bottom", "left", "right"):
            edges[f"edge_{edge}"] = FrameSlot(tile=_tile(f"edge_{edge}"))
    fill = FrameSlot(tile=_tile("fill")) if with_fill else None
    return ParametricFrameConstruction(
        id="test.frame.kit",
        collection_id="test.frame",
        corners=corner_map,
        edges=edges,
        fill=fill,
        min_width=min_width,
        min_height=min_height,
    )


class FrameOpExpandStampsTests(unittest.TestCase):
    def _expand(self, construction: ParametricFrameConstruction, **params: int) -> dict[tuple[int, int], str]:
        family = _FakeFamily({"test.frame.kit": construction})
        stamps = harness.expand_entity_stamps(
            family,  # type: ignore[arg-type]
            "test.frame.kit",
            x=0,
            y=0,
            context="frame test",
            params=cast("dict[str, object]", params),
        )
        return {(s["x"], s["y"]): cast(str, s["ref"]) for s in stamps}

    def test_full_frame_places_corners_edges_and_fill(self) -> None:
        cells = self._expand(_make_frame_construction(), width=4, height=3)
        self.assertEqual(len(cells), 12)
        # corners
        self.assertEqual(cells[(0, 0)], "testfam:all:corner_tl")
        self.assertEqual(cells[(3, 0)], "testfam:all:corner_tr")
        self.assertEqual(cells[(0, 2)], "testfam:all:corner_bl")
        self.assertEqual(cells[(3, 2)], "testfam:all:corner_br")
        # edges tile between corners
        self.assertEqual(cells[(1, 0)], "testfam:all:edge_top")
        self.assertEqual(cells[(2, 0)], "testfam:all:edge_top")
        self.assertEqual(cells[(1, 2)], "testfam:all:edge_bottom")
        self.assertEqual(cells[(0, 1)], "testfam:all:edge_left")
        self.assertEqual(cells[(3, 1)], "testfam:all:edge_right")
        # interior fill
        self.assertEqual(cells[(1, 1)], "testfam:all:fill")
        self.assertEqual(cells[(2, 1)], "testfam:all:fill")

    def test_minimum_2x2_frame_is_corners_only(self) -> None:
        cells = self._expand(_make_frame_construction(), width=2, height=2)
        self.assertEqual(
            cells,
            {
                (0, 0): "testfam:all:corner_tl",
                (1, 0): "testfam:all:corner_tr",
                (0, 1): "testfam:all:corner_bl",
                (1, 1): "testfam:all:corner_br",
            },
        )

    def test_corner_only_kit_skips_blank_edge_and_fill_slots(self) -> None:
        construction = _make_frame_construction(with_edges=False, with_fill=False)
        cells = self._expand(construction, width=5, height=4)
        self.assertEqual(
            cells,
            {
                (0, 0): "testfam:all:corner_tl",
                (4, 0): "testfam:all:corner_tr",
                (0, 3): "testfam:all:corner_bl",
                (4, 3): "testfam:all:corner_br",
            },
        )

    def test_border_only_frame_leaves_interior_transparent(self) -> None:
        construction = _make_frame_construction(with_fill=False)
        cells = self._expand(construction, width=4, height=4)
        # no fill emitted in the interior; the border still renders
        self.assertNotIn((1, 1), cells)
        self.assertNotIn((2, 2), cells)
        self.assertEqual(cells[(0, 0)], "testfam:all:corner_tl")
        self.assertEqual(cells[(1, 0)], "testfam:all:edge_top")

    def test_below_minimum_dimensions_raise(self) -> None:
        construction = _make_frame_construction(min_width=2, min_height=2)
        with self.assertRaisesRegex(ValueError, "width >= 2"):
            self._expand(construction, width=1, height=3)

    def test_missing_dimension_params_raise(self) -> None:
        construction = _make_frame_construction()
        with self.assertRaisesRegex(ValueError, "requires"):
            self._expand(construction, width=4)

    def test_flip_derived_corners_emit_flipped_stamp_refs(self) -> None:
        tile = _make_tile_record("testfam:all:corner")
        construction = ParametricFrameConstruction(
            id="t.flip",
            collection_id="t.flip",
            corners={
                "corner_tl": FrameCornerSlot(cells=((tile,),)),
                "corner_tr": FrameCornerSlot(cells=((tile,),), flip_x=True),
                "corner_bl": FrameCornerSlot(cells=((tile,),), flip_y=True),
                "corner_br": FrameCornerSlot(cells=((tile,),), flip_x=True, flip_y=True),
            },
            edges={},
        )
        family = _FakeFamily({"t.flip": construction})
        stamps = harness.expand_entity_stamps(
            family, "t.flip", x=0, y=0, context="t", params={"width": 4, "height": 3}  # type: ignore[arg-type]
        )
        by_pos = {(s["x"], s["y"]): s["ref"] for s in stamps}
        self.assertEqual(by_pos[(0, 0)], "testfam:all:corner")  # tl unflipped → plain str
        self.assertEqual(by_pos[(3, 0)], {"ref": "testfam:all:corner", "flip_x": True, "flip_y": False})
        self.assertEqual(by_pos[(0, 2)], {"ref": "testfam:all:corner", "flip_x": False, "flip_y": True})
        self.assertEqual(by_pos[(3, 2)], {"ref": "testfam:all:corner", "flip_x": True, "flip_y": True})

    def test_flip_derived_edges_emit_flipped_stamp_refs(self) -> None:
        corner = _make_tile_record("testfam:all:corner")
        h_edge = _make_tile_record("testfam:all:h")
        v_edge = _make_tile_record("testfam:all:v")
        construction = ParametricFrameConstruction(
            id="t.edgeflip",
            collection_id="t.edgeflip",
            corners={
                "corner_tl": FrameCornerSlot(cells=((corner,),)),
                "corner_tr": FrameCornerSlot(cells=((corner,),), flip_x=True),
                "corner_bl": FrameCornerSlot(cells=((corner,),), flip_y=True),
                "corner_br": FrameCornerSlot(cells=((corner,),), flip_x=True, flip_y=True),
            },
            edges={
                "edge_top": FrameSlot(tile=h_edge),
                "edge_bottom": FrameSlot(tile=h_edge, flip_y=True),  # derives from top
                "edge_left": FrameSlot(tile=v_edge),
                "edge_right": FrameSlot(tile=v_edge, flip_x=True),  # derives from left
            },
        )
        family = _FakeFamily({"t.edgeflip": construction})
        stamps = harness.expand_entity_stamps(
            family, "t.edgeflip", x=0, y=0, context="t", params={"width": 3, "height": 3}  # type: ignore[arg-type]
        )
        by_pos = {(s["x"], s["y"]): s["ref"] for s in stamps}
        self.assertEqual(by_pos[(1, 0)], "testfam:all:h")  # top edge unflipped
        self.assertEqual(by_pos[(1, 2)], {"ref": "testfam:all:h", "flip_x": False, "flip_y": True})  # bottom
        self.assertEqual(by_pos[(0, 1)], "testfam:all:v")  # left edge unflipped
        self.assertEqual(by_pos[(2, 1)], {"ref": "testfam:all:v", "flip_x": True, "flip_y": False})  # right

    def test_fat_2x2_corners_place_blocks_with_flip(self) -> None:
        def t(name: str) -> TileRecord:
            return _make_tile_record(f"testfam:all:{name}")

        def block(*, flip_x: bool = False, flip_y: bool = False) -> FrameCornerSlot:
            return FrameCornerSlot(cells=((t("a"), t("b")), (t("c"), t("d"))), flip_x=flip_x, flip_y=flip_y)

        construction = ParametricFrameConstruction(
            id="t.fat",
            collection_id="t.fat",
            corners={
                "corner_tl": block(),
                "corner_tr": block(flip_x=True),
                "corner_bl": block(flip_y=True),
                "corner_br": block(flip_x=True, flip_y=True),
            },
            edges={},
            min_width=4,
            min_height=4,
        )
        family = _FakeFamily({"t.fat": construction})
        stamps = harness.expand_entity_stamps(
            family, "t.fat", x=0, y=0, context="t", params={"width": 4, "height": 4}  # type: ignore[arg-type]
        )
        by_pos = {(s["x"], s["y"]): s["ref"] for s in stamps}
        # tl block (unflipped) fills its 2x2
        self.assertEqual(by_pos[(0, 0)], "testfam:all:a")
        self.assertEqual(by_pos[(1, 0)], "testfam:all:b")
        self.assertEqual(by_pos[(0, 1)], "testfam:all:c")
        self.assertEqual(by_pos[(1, 1)], "testfam:all:d")
        # tr block anchored at x=2, mirrored on x: column order reversed + each tile flipped_x
        self.assertEqual(by_pos[(2, 0)], {"ref": "testfam:all:b", "flip_x": True, "flip_y": False})
        self.assertEqual(by_pos[(3, 0)], {"ref": "testfam:all:a", "flip_x": True, "flip_y": False})
        # 4 corners x 4 cells, no room for edges/fill at the 4x4 minimum
        self.assertEqual(len(stamps), 16)


if __name__ == "__main__":
    unittest.main()
