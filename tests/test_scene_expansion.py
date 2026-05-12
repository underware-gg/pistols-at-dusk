from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import minimal8_harness as harness
import scene_templates
from tile_families import MetatileConstruction, ParametricRunConstruction, TileRecord


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
                "kind": "box",
                "layer": {"bind": "room_layer"},
                "style": "gold_ui_frame",
                "x": {"param": "x"},
                "y": {"param": "y"},
                "width": {"param": "width"},
                "height": {"param": "height"}
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
    tile_family = cast(dict[str, Any], config["tile_family"])
    tile_family["path"] = str((PROJECT_PATH.parent / cast(str, tile_family["path"])).resolve())
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

    def test_loader_rejects_filename_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            _write_json(templates_dir / "sanctum.json", _scene_template_spec(template_id="mismatch"))

            with self.assertRaisesRegex(ValueError, "must match filename stem"):
                harness.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_parameter_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _scene_template_spec(template_id="sample")
            parameters = cast(dict[str, Any], spec["parameters"])
            x_spec = cast(dict[str, Any], parameters["x"])
            x_spec["type"] = "intger"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "has unknown type 'intger'"):
                harness.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_data_op_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            ops[0]["kind"] = "portal"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "unknown kind 'portal'"):
                harness.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_data_op_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            ops[0]["whe_present"] = "door_ref"
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "unknown fields: whe_present"):
                harness.load_scene_template_library(ROOT, str(templates_dir))

    def test_loader_rejects_unknown_binding_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            spec = _data_scene_template_spec(template_id="sample")
            ops = cast(list[dict[str, Any]], spec["ops"])
            stamp = ops[1]
            stamp["ref"] = {"bind": "missing_ref"}
            _write_json(templates_dir / "sample.json", spec)

            with self.assertRaisesRegex(ValueError, "references unknown binding"):
                harness.load_scene_template_library(ROOT, str(templates_dir))

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
                harness.load_scene_template_library(ROOT, str(templates_dir))

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

            layers = harness.expand_scene(
                project,
                {"template": "sample", "x": 10, "y": 5, "width": 12, "height": 8},
                default_tileset=project.default_tileset_id(),
            )

            boxes = _ops_with_kind(layers, "rooms", "box")
            self.assertEqual(len(boxes), 1)
            self.assertEqual(_op_int(boxes[0], "x"), 10)
            self.assertEqual(_op_int(boxes[0], "width"), 12)

            door_stamps = _ops_with_kind(layers, "ornament", "stamp")
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
        enabled = self._evaluate({"enabled": {"bind": "inner_style"}}, bindings={"inner_style": "gold_ui_frame"})
        disabled = self._evaluate({"enabled": {"bind": "inner_style"}}, bindings={"inner_style": ""})
        self.assertTrue(enabled)
        self.assertFalse(disabled)
        self.assertTrue(self._evaluate({"eq": ["bridge", "bridge"]}))
        self.assertFalse(self._evaluate({"eq": ["bridge", "left"]}))

        value = self._evaluate(
            {
                "if": {
                    "all": [
                        {"gt": [{"bind": "inner_width"}, 1]},
                        {"enabled": {"bind": "inner_style"}}
                    ]
                },
                "then": "inner",
                "else": "outer"
            },
            bindings={"inner_width": 6, "inner_style": "gold_ui_frame"},
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

    def test_emits_outer_box_and_centred_door(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {"template": "sanctum", "x": 4, "y": 9, "width": 22, "height": 14},
            default_tileset=self.tileset,
        )

        self.assertIn("rooms", layers)
        self.assertIn("ornament", layers)
        boxes = _ops_with_kind(layers, "rooms", "box")
        self.assertGreaterEqual(len(boxes), 1)
        self.assertEqual(_op_int(boxes[0], "x"), 4)
        self.assertEqual(_op_int(boxes[0], "width"), 22)

        door_stamps = _ops_with_kind(layers, "ornament", "stamp")
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

    def test_blank_inner_style_skips_inner_box_and_targets_outer_room(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {"template": "sanctum", "x": 4, "y": 9, "width": 22, "height": 14, "inner_style": ""},
            default_tileset=self.tileset,
        )

        boxes = _ops_with_kind(layers, "rooms", "box")
        self.assertEqual(len(boxes), 1)

        door_stamps = _ops_with_kind(layers, "ornament", "stamp")
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

    def test_emits_two_chamber_boxes_and_door(self) -> None:
        layers = harness.expand_scene(
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

        boxes = _ops_with_kind(layers, "rooms", "box")
        self.assertGreaterEqual(len(boxes), 2)
        x_origins = sorted({_op_int(box, "x") for box in boxes})
        self.assertIn(11, x_origins)
        self.assertIn(11 + 12 + 8, x_origins)

        door_stamps = _ops_with_kind(layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        right_x = 11 + 12 + 8
        door_x = _op_int(door_stamps[0], "x")
        self.assertGreaterEqual(door_x, right_x)
        self.assertLess(door_x, right_x + 14)

    def test_blank_bridge_style_skips_bridge_box(self) -> None:
        layers = harness.expand_scene(
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
                "bridge_style": "",
            },
            default_tileset=self.tileset,
        )

        boxes = _ops_with_kind(layers, "rooms", "box")
        self.assertEqual(len(boxes), 2)

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
        layers = harness.expand_scene(
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

        water_fills = _ops_with_kind(layers, "water", "fill")
        self.assertEqual(len(water_fills), 1)
        boxes = _ops_with_kind(layers, "island", "box")
        self.assertGreaterEqual(len(boxes), 1)
        outer_box = next(
            box for box in boxes if _op_int(box, "x") == 26 and _op_int(box, "y") == 12
        )
        self.assertEqual(_op_int(outer_box, "width"), 12)
        self.assertEqual(_op_int(outer_box, "height"), 8)

        door_stamps = _ops_with_kind(layers, "ornament", "stamp")
        self.assertEqual(len(door_stamps), 1)
        door_x = _op_int(door_stamps[0], "x")
        self.assertGreaterEqual(door_x, 26)
        self.assertLess(door_x, 26 + 12)

    def test_disables_optional_stem_and_door_when_blank_or_null(self) -> None:
        layers = harness.expand_scene(
            self.project,
            {
                "template": "causeway",
                "x": 26,
                "y": 12,
                "width": 12,
                "height": 8,
                "stem_style": "",
                "door_ref": None,
            },
            default_tileset=self.tileset,
        )

        boxes = _ops_with_kind(layers, "island", "box")
        self.assertEqual(len(boxes), 1)
        self.assertEqual(_ops_with_kind(layers, "ornament", "stamp"), [])

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
        self.assertIn("@indoors_door_grand_closed", architecture_stamps)
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

            with self.assertRaisesRegex(ValueError, "scene template cycle detected"):
                harness.LayoutProject(project_path)

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
                                "construction": "indoors.table.kit.square_single",
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
                (entity.template.construction_id, entity.layer, entity.x, entity.y)
                for entity in runtime.entities
            }
            self.assertIn(("indoors.table.kit.square_single", "architecture", 9, 6), entity_positions)

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
            with self.assertRaisesRegex(ValueError, "references an unknown stamp ref"):
                harness.LayoutProject(project_path)

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
            with self.assertRaisesRegex(ValueError, "references an unknown stamp ref"):
                harness.LayoutProject(project_path)


def _make_tile_record(tile_id: str) -> TileRecord:
    return TileRecord(
        id=tile_id,
        family_id="testfam",
        layer="architecture",
        category="tile",
        transparent=False,
        tags=(),
        sheet_col=0,
        sheet_row=0,
    )


class _FakeFamily:
    def __init__(self, constructions: dict[str, MetatileConstruction | ParametricRunConstruction]) -> None:
        self._constructions = constructions

    def lookup_construction(self, construction_id: str) -> MetatileConstruction | ParametricRunConstruction | None:
        return self._constructions.get(construction_id)


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
            return harness.load_scene_template_library(Path(tmpdir), str(templates_dir))

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
            return harness.load_scene_template_library(Path(tmpdir), str(templates_dir))

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
                harness.load_scene_template_library(Path(tmpdir), str(templates_dir))
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
                harness.load_scene_template_library(Path(tmpdir), str(templates_dir))
            self.assertIn("cycle", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
