from __future__ import annotations

import difflib
import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Collection, Literal, Sequence, TypedDict, Union, cast

from typing_extensions import TypeAlias

from scene_rules import (
    SceneRuleCandidate,
    SceneRuleEntityCandidate,
    SceneRuleSceneCandidate,
    SceneRulesetLibrary,
    SceneRuleStampCandidate,
)
from tile_library import PlaceableKind, PlaceableRef


TileRefToken: TypeAlias = Union[str, int, None, dict[str, object], list["TileRefToken"]]


class StampOp(TypedDict):
    kind: Literal["stamp"]
    ref: TileRefToken
    x: int
    y: int


class FillOp(TypedDict):
    kind: Literal["fill"]
    ref: TileRefToken
    x: int
    y: int
    width: int
    height: int


class MaskFillOp(TypedDict):
    kind: Literal["mask_fill"]
    ref: TileRefToken
    x: int
    y: int
    rows: list[str]


class _ScatterOpRequired(TypedDict):
    kind: Literal["scatter"]
    x: int
    y: int
    rows: list[str]


class ScatterOp(_ScatterOpRequired, total=False):
    ref: TileRefToken
    refs: list[TileRefToken]
    density: float
    seed: int


class _RepeatOpRequired(TypedDict):
    kind: Literal["repeat"]
    ref: TileRefToken
    x: int
    y: int
    count: int


class RepeatOp(_RepeatOpRequired, total=False):
    dx: int
    dy: int


class AsciiOp(TypedDict):
    kind: Literal["ascii"]
    x: int
    y: int
    rows: list[str]
    legend: dict[str, TileRefToken]


# spread_stamps has no runtime SceneOp variant. It expands to multiple StampOps
# during scene expansion, so this TypedDict exists to drive the same
# field-validation machinery as the runtime ops above.
class SpreadStampsFields(TypedDict):
    ref: object
    count: object
    start: object
    span: object
    inset: object
    y: object


# entity has no runtime SceneOp variant. It expands to scene-entity requests
# during template expansion, which the harness later resolves into stamps.
class _EntityFieldsRequired(TypedDict):
    construction: object
    x: object
    y: object


class EntityFields(_EntityFieldsRequired, total=False):
    entity_id: object
    params: object
    variant_id: object


# scatter has a runtime SceneOp variant; this TypedDict captures the data-mode
# fields so the field-validation machinery can check them at load time.
class _ScatterDataRequired(TypedDict):
    x: object
    y: object
    rows: object


class ScatterDataFields(_ScatterDataRequired, total=False):
    ref: object
    refs: object
    density: object
    seed: object


# place_scene has no runtime SceneOp variant. It expands to stamps by
# recursively expanding the named sub-scene with a coordinate offset.
class _PlaceSceneFieldsRequired(TypedDict):
    scene: object
    x: object
    y: object


class PlaceSceneFields(_PlaceSceneFieldsRequired, total=False):
    args: object


class _PopulateSlotsFieldsRequired(TypedDict):
    ruleset: object
    catalogue: object
    slot_group: object


class PopulateSlotsFields(_PopulateSlotsFieldsRequired, total=False):
    seed: object
    args: object


class _SceneSlotRequired(TypedDict):
    x: object
    y: object


class SceneSlotFields(_SceneSlotRequired, total=False):
    id: str
    layer: object


# Runtime entity op for hand-authored layouts: unlike the template-mode
# EntityFields above (whose values are expression objects), a layout entity op
# carries pre-resolved plain JSON scalars and expands directly to stamps.
class _EntityOpRequired(TypedDict):
    kind: Literal["entity"]
    construction: str
    x: int
    y: int


class EntityOp(_EntityOpRequired, total=False):
    params: dict[str, object]
    variant_id: str


SceneOp: TypeAlias = Union[StampOp, FillOp, MaskFillOp, ScatterOp, RepeatOp, AsciiOp, EntityOp]
SceneLayers: TypeAlias = dict[str, list[SceneOp]]
SceneTemplate: TypeAlias = dict[str, object]


def _typed_dict_required_fields(typed_dict_cls: type[object], *, exclude: Collection[str] = ()) -> frozenset[str]:
    return frozenset(cast(frozenset[str], getattr(typed_dict_cls, "__required_keys__")) - set(exclude))


def _typed_dict_allowed_fields(typed_dict_cls: type[object], *, exclude: Collection[str] = ()) -> frozenset[str]:
    required = cast(frozenset[str], getattr(typed_dict_cls, "__required_keys__"))
    optional = cast(frozenset[str], getattr(typed_dict_cls, "__optional_keys__"))
    return frozenset((required | optional) - set(exclude))


DEFAULT_SCENE_TEMPLATES_DIRNAME = "scene-templates"
SCENE_PARAMETER_TYPES = frozenset({"int", "float", "str", "bool", "tile_ref", "list[tile_ref]"})
SCENE_DATA_OP_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "fill": _typed_dict_required_fields(FillOp, exclude={"kind"}),
    "stamp": _typed_dict_required_fields(StampOp, exclude={"kind"}),
    "spread_stamps": _typed_dict_required_fields(SpreadStampsFields),
    "entity": _typed_dict_required_fields(_EntityFieldsRequired),
    "scatter": _typed_dict_required_fields(_ScatterDataRequired),
    "place_scene": _typed_dict_required_fields(_PlaceSceneFieldsRequired),
    "populate_slots": _typed_dict_required_fields(_PopulateSlotsFieldsRequired),
}
SCENE_DATA_OP_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "fill": _typed_dict_allowed_fields(FillOp, exclude={"kind"}),
    "stamp": _typed_dict_allowed_fields(StampOp, exclude={"kind"}),
    "spread_stamps": _typed_dict_allowed_fields(SpreadStampsFields),
    "entity": _typed_dict_allowed_fields(EntityFields),
    "scatter": _typed_dict_allowed_fields(ScatterDataFields),
    "place_scene": _typed_dict_allowed_fields(PlaceSceneFields),
    "populate_slots": _typed_dict_allowed_fields(PopulateSlotsFields),
}
SCENE_DATA_OP_KINDS = frozenset(SCENE_DATA_OP_REQUIRED_FIELDS)

@dataclass(frozen=True)
class SceneTemplateParameterSpec:
    parameter_type: str
    required: bool
    description: str


@dataclass(frozen=True)
class SceneTemplateConstraintSpec:
    condition: object
    message: str


def _empty_object_dict() -> dict[str, object]:
    return {}


def _empty_slot_group_dict() -> dict[str, tuple["SceneSlotSpec", ...]]:
    return {}


@dataclass(frozen=True)
class DataSceneOpSpec:
    kind: str
    layer: object
    fields: dict[str, object]
    when_present: str | None = None


@dataclass(frozen=True)
class SceneTemplateSpec:
    template_id: str
    description: str
    parameters: dict[str, SceneTemplateParameterSpec]
    bindings: dict[str, object] = field(default_factory=_empty_object_dict)
    constraints: tuple[SceneTemplateConstraintSpec, ...] = ()
    slot_groups: dict[str, tuple["SceneSlotSpec", ...]] = field(default_factory=_empty_slot_group_dict)
    data_ops: tuple[DataSceneOpSpec, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneTemplateLibrary:
    root: Path
    specs: dict[str, SceneTemplateSpec]

    def require(self, template_id: str) -> SceneTemplateSpec:
        try:
            return self.specs[template_id]
        except KeyError as exc:
            available = ", ".join(sorted(self.specs)) or "<none>"
            raise ValueError(
                f"Unknown scene template: {template_id}. Available templates: {available}"
            ) from exc


class SceneTemplateParameterSpecConfig(TypedDict):
    type: str
    required: bool
    description: str


class SceneTemplateConstraintSpecConfig(TypedDict):
    condition: object
    message: str


class SceneTemplateSpecConfig(TypedDict, total=False):
    template_id: str
    description: str
    parameters: dict[str, SceneTemplateParameterSpecConfig]
    bindings: dict[str, object]
    constraints: list[SceneTemplateConstraintSpecConfig]
    slot_groups: dict[str, list[SceneSlotFields]]
    ops: list[dict[str, object]]
    notes: list[str]


@dataclass(frozen=True)
class SceneTemplateRuntime:
    pattern_dimensions: Callable[[TileRefToken], tuple[int, int]]
    centered_pattern_x: Callable[[TileRefToken, int, int], int]
    scene_library: "SceneTemplateLibrary | None" = None
    scene_rules_library: "SceneRulesetLibrary | None" = None


@dataclass(frozen=True)
class SceneSlotSpec:
    slot_id: str
    x: object
    y: object
    layer: object | None = None


def _empty_scene_layers() -> SceneLayers:
    return cast(SceneLayers, {})


@dataclass(frozen=True)
class SceneEntityRequest:
    entity_id: str
    source_template_id: str
    layer: str
    x: int
    y: int
    construction_id: str | None = None
    params: dict[str, object] | None = None
    variant_id: str | None = None
    placeable_kind: PlaceableKind = "construction"
    placeable_id: str | None = None

    def __post_init__(self) -> None:
        resolved_placeable_id = self.placeable_id
        if resolved_placeable_id is None and self.construction_id is not None:
            resolved_placeable_id = self.construction_id
        if resolved_placeable_id is None:
            raise ValueError("SceneEntityRequest.placeable_id is required when construction_id is absent")
        if self.construction_id is not None and (
            self.placeable_kind != "construction" or self.construction_id != resolved_placeable_id
        ):
            raise ValueError(
                "SceneEntityRequest.construction_id is only valid for matching construction placeables"
            )
        object.__setattr__(self, "placeable_id", resolved_placeable_id)

    @property
    def placeable_ref(self) -> PlaceableRef:
        placeable_id = self.placeable_id
        if placeable_id is None:
            raise RuntimeError("SceneEntityRequest.placeable_id was not normalised")
        return PlaceableRef(kind=self.placeable_kind, id=placeable_id)


@dataclass(frozen=True)
class ExpandedDataScene:
    layers: SceneLayers = field(default_factory=_empty_scene_layers)
    entities: tuple[SceneEntityRequest, ...] = ()


@dataclass(frozen=True)
class SceneEvalContext:
    scene: SceneTemplate
    bindings: dict[str, object]
    runtime: SceneTemplateRuntime


SceneExprHandler = Callable[[dict[str, object], SceneEvalContext], object]
SceneExprChildrenGetter = Callable[[dict[str, object]], Sequence[object]]


@dataclass(frozen=True)
class SceneExpressionOperatorSpec:
    required_keys: frozenset[str]
    allowed_keys: frozenset[str]
    handler: SceneExprHandler
    child_expressions: SceneExprChildrenGetter


def evenly_spaced_origins(
    *,
    start: int,
    span: int,
    item_width: int,
    count: int,
    inset: int = 0,
) -> list[int]:
    if count <= 0:
        return []
    left = start + inset
    right = start + span - inset - item_width
    if count == 1 or right <= left:
        return [start + max(0, (span - item_width) // 2)]
    step = (right - left) / (count - 1)
    return [int(round(left + step * index)) for index in range(count)]


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def _require_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    return cast(list[object], value)


def _require_string(value: object, *, context: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    if not allow_empty and value == "":
        raise ValueError(f"{context} must not be empty")
    return value


def _require_bool(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _require_string_list(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list of strings")
    items = cast(list[object], value)
    strings: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{context} must be a list of strings")
        strings.append(item)
    return tuple(strings)


def _resolve_path(base: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base / path).resolve()


def _load_scene_template_parameter_spec(
    name: str,
    raw_spec: object,
    *,
    context: str,
) -> SceneTemplateParameterSpec:
    spec = _require_mapping(raw_spec, context=f"{context} parameter {name!r}")
    parameter_type = _require_string(spec.get("type"), context=f"{context} parameter {name!r} type")
    if parameter_type not in SCENE_PARAMETER_TYPES:
        expected = ", ".join(sorted(SCENE_PARAMETER_TYPES))
        raise ValueError(
            f"{context} parameter {name!r} has unknown type {parameter_type!r}; "
            f"expected one of: {expected}"
        )
    return SceneTemplateParameterSpec(
        parameter_type=parameter_type,
        required=_require_bool(spec.get("required"), context=f"{context} parameter {name!r} required"),
        description=_require_string(
            spec.get("description"),
            context=f"{context} parameter {name!r} description",
            allow_empty=True,
        ),
    )


def _load_data_scene_op_spec(index: int, raw_spec: object, *, context: str) -> DataSceneOpSpec:
    spec = _require_mapping(raw_spec, context=f"{context} op[{index}]")
    kind = _require_string(spec.get("kind"), context=f"{context} op[{index}] kind")
    if kind not in SCENE_DATA_OP_KINDS:
        expected = ", ".join(sorted(SCENE_DATA_OP_KINDS))
        raise ValueError(
            f"{context} op[{index}] has unknown kind {kind!r}; expected one of: {expected}"
        )
    # place_scene and populate_slots emit into nested scene/entity/stamp structures;
    # no parent layer is required on the op itself.
    if kind not in {"place_scene", "populate_slots"} and "layer" not in spec:
        raise ValueError(f"{context} op[{index}] is missing required field 'layer'")
    when_present_raw = spec.get("when_present")
    when_present = (
        None
        if when_present_raw is None
        else _require_string(when_present_raw, context=f"{context} op[{index}] when_present")
    )
    excluded = (
        {"kind", "when_present"}
        if kind in {"place_scene", "populate_slots"}
        else {"kind", "layer", "when_present"}
    )
    fields = {key: value for key, value in spec.items() if key not in excluded}
    unknown = sorted(set(fields) - SCENE_DATA_OP_ALLOWED_FIELDS[kind])
    if unknown:
        raise ValueError(f"{context} op[{index}] kind {kind!r} has unknown fields: {', '.join(unknown)}")
    missing = sorted(SCENE_DATA_OP_REQUIRED_FIELDS[kind] - fields.keys())
    if missing:
        raise ValueError(
            f"{context} op[{index}] kind {kind!r} is missing required fields: {', '.join(missing)}"
        )
    layer: object = spec.get("layer")
    return DataSceneOpSpec(kind=kind, layer=layer, fields=fields, when_present=when_present)


def _load_scene_template_constraint_spec(
    index: int,
    raw_spec: object,
    *,
    context: str,
) -> SceneTemplateConstraintSpec:
    spec = _require_mapping(raw_spec, context=f"{context} constraint[{index}]")
    if "condition" not in spec:
        raise ValueError(f"{context} constraint[{index}] is missing required field 'condition'")
    return SceneTemplateConstraintSpec(
        condition=spec["condition"],
        message=_require_string(spec.get("message"), context=f"{context} constraint[{index}] message"),
    )


def _load_scene_slot_spec(
    group_name: str,
    index: int,
    raw_spec: object,
    *,
    context: str,
) -> SceneSlotSpec:
    spec = _require_mapping(raw_spec, context=f"{context} slot_groups[{group_name!r}][{index}]")
    required = {"x", "y"}
    missing = sorted(required - spec.keys())
    if missing:
        raise ValueError(
            f"{context} slot_groups[{group_name!r}][{index}] is missing required fields: {', '.join(missing)}"
        )
    allowed = {"id", "x", "y", "layer"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError(
            f"{context} slot_groups[{group_name!r}][{index}] has unknown fields: {', '.join(unknown)}"
        )
    slot_id_raw = spec.get("id")
    slot_id = (
        _require_string(slot_id_raw, context=f"{context} slot_groups[{group_name!r}][{index}] id")
        if slot_id_raw is not None
        else f"{group_name}.{index}"
    )
    return SceneSlotSpec(
        slot_id=slot_id,
        x=spec["x"],
        y=spec["y"],
        layer=spec.get("layer"),
    )


def _collect_scene_expr_bind_refs(expr: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(expr, dict):
        mapping = cast(dict[str, object], expr)
        if set(mapping) == {"bind"} and isinstance(mapping.get("bind"), str):
            refs.add(cast(str, mapping["bind"]))
        for value in _scene_expression_child_values(mapping):
            refs.update(_collect_scene_expr_bind_refs(value))
    elif isinstance(expr, list):
        for item in cast(list[object], expr):
            refs.update(_collect_scene_expr_bind_refs(item))
    return refs


def _validate_scene_template_data_references(
    path: Path,
    *,
    bindings: dict[str, object],
    constraints: Sequence[SceneTemplateConstraintSpec],
    slot_groups: dict[str, tuple[SceneSlotSpec, ...]],
    data_ops: Sequence[DataSceneOpSpec],
) -> None:
    all_binding_names = set(bindings)
    known_binding_names: set[str] = set()
    for binding_name, expr in bindings.items():
        refs = sorted(_collect_scene_expr_bind_refs(expr))
        for ref_name in refs:
            if ref_name not in all_binding_names:
                raise ValueError(f"{path} binding {binding_name!r} references unknown binding {ref_name!r}")
            if ref_name not in known_binding_names:
                raise ValueError(
                    f"{path} binding {binding_name!r} references {ref_name!r} before it is declared "
                    f"(bindings can only refer to earlier bindings)"
                )
        known_binding_names.add(binding_name)

    for index, constraint_spec in enumerate(constraints):
        missing = sorted(_collect_scene_expr_bind_refs(constraint_spec.condition) - all_binding_names)
        if missing:
            raise ValueError(
                f"{path} constraint[{index}] references unknown binding(s): {', '.join(missing)}"
            )

    for group_name, slot_specs in slot_groups.items():
        for index, slot_spec in enumerate(slot_specs):
            slot_bind_refs = _collect_scene_expr_bind_refs(slot_spec.x)
            slot_bind_refs.update(_collect_scene_expr_bind_refs(slot_spec.y))
            if slot_spec.layer is not None:
                slot_bind_refs.update(_collect_scene_expr_bind_refs(slot_spec.layer))
            missing = sorted(slot_bind_refs - all_binding_names)
            if missing:
                raise ValueError(
                    f"{path} slot_groups[{group_name!r}][{index}] references unknown binding(s): "
                    f"{', '.join(missing)}"
                )

    for index, op_spec in enumerate(data_ops):
        if op_spec.when_present is not None and op_spec.when_present not in all_binding_names:
            raise ValueError(f"{path} op[{index}] when_present references unknown binding {op_spec.when_present!r}")
        op_bind_refs = _collect_scene_expr_bind_refs(op_spec.layer)
        for field_expr in op_spec.fields.values():
            op_bind_refs.update(_collect_scene_expr_bind_refs(field_expr))
        missing = sorted(op_bind_refs - all_binding_names)
        if missing:
            raise ValueError(f"{path} op[{index}] references unknown binding(s): {', '.join(missing)}")


def _load_scene_template_spec(path: Path) -> SceneTemplateSpec:
    raw = _require_mapping(load_json(path), context=str(path))
    template_id = _require_string(raw.get("template_id"), context=f"{path} template_id")
    if path.stem != template_id:
        raise ValueError(f"{path} template_id {template_id!r} must match filename stem {path.stem!r}")

    parameters_raw = _require_mapping(raw.get("parameters"), context=f"{path} parameters")
    parameters = {
        parameter_name: _load_scene_template_parameter_spec(parameter_name, parameter_spec, context=str(path))
        for parameter_name, parameter_spec in parameters_raw.items()
    }
    bindings_raw = raw.get("bindings", {})
    bindings = _require_mapping(bindings_raw, context=f"{path} bindings")
    constraints_raw = raw.get("constraints", [])
    if not isinstance(constraints_raw, list):
        raise ValueError(f"{path} must define constraints as a list when present")
    constraints = tuple(
        _load_scene_template_constraint_spec(index, constraint_raw, context=str(path))
        for index, constraint_raw in enumerate(cast(list[object], constraints_raw))
    )
    slot_groups_raw = raw.get("slot_groups", {})
    slot_groups_mapping = _require_mapping(slot_groups_raw, context=f"{path} slot_groups")
    slot_groups: dict[str, tuple[SceneSlotSpec, ...]] = {}
    seen_slot_ids: set[str] = set()
    for group_name, group_raw in slot_groups_mapping.items():
        group_list = _require_list(group_raw, context=f"{path} slot_groups[{group_name!r}]")
        slot_specs = tuple(
            _load_scene_slot_spec(group_name, index, slot_raw, context=str(path))
            for index, slot_raw in enumerate(group_list)
        )
        for slot_spec in slot_specs:
            if slot_spec.slot_id in seen_slot_ids:
                raise ValueError(f"{path} defines duplicate slot id {slot_spec.slot_id!r}")
            seen_slot_ids.add(slot_spec.slot_id)
        slot_groups[group_name] = slot_specs
    ops_raw = raw.get("ops")
    if not isinstance(ops_raw, list):
        raise ValueError(f"{path} must define ops as a list")
    data_ops = tuple(
        _load_data_scene_op_spec(index, op_raw, context=str(path))
        for index, op_raw in enumerate(cast(list[object], ops_raw))
    )
    _validate_scene_template_data_references(
        path,
        bindings=bindings,
        constraints=constraints,
        slot_groups=slot_groups,
        data_ops=data_ops,
    )
    notes_raw = raw.get("notes", [])
    notes = _require_string_list(notes_raw, context=f"{path} notes")
    return SceneTemplateSpec(
        template_id=template_id,
        description=_require_string(raw.get("description"), context=f"{path} description", allow_empty=True),
        parameters=parameters,
        bindings=bindings,
        constraints=constraints,
        slot_groups=slot_groups,
        data_ops=data_ops,
        notes=notes,
    )


def _collect_place_scene_refs(spec: SceneTemplateSpec) -> list[str]:
    refs: list[str] = []
    for op_spec in spec.data_ops:
        if op_spec.kind == "place_scene":
            scene_field = op_spec.fields.get("scene")
            if isinstance(scene_field, str):
                refs.append(scene_field)
    return refs


def _collect_static_scene_rule_scene_refs(
    spec: SceneTemplateSpec,
    *,
    scene_rules_library: SceneRulesetLibrary,
) -> list[str]:
    refs: list[str] = []
    for op_spec in spec.data_ops:
        if op_spec.kind != "populate_slots":
            continue
        ruleset_field = op_spec.fields.get("ruleset")
        catalogue_field = op_spec.fields.get("catalogue")
        if not isinstance(ruleset_field, str) or not isinstance(catalogue_field, str):
            continue
        ruleset = scene_rules_library.specs.get(ruleset_field)
        if ruleset is None:
            continue
        candidates = ruleset.catalogues.get(catalogue_field)
        if candidates is None:
            continue
        refs.extend(
            candidate.scene_id
            for candidate in candidates
            if isinstance(candidate, SceneRuleSceneCandidate)
        )
    return refs


def detect_scene_template_cycles(
    specs: dict[str, SceneTemplateSpec],
    *,
    scene_rules_library: SceneRulesetLibrary | None = None,
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(template_id: str, path: list[str]) -> None:
        if template_id in visiting:
            cycle_start = path.index(template_id)
            cycle_path = " -> ".join(path[cycle_start:] + [template_id])
            raise ValueError(f"scene template cycle detected: {cycle_path}")
        if template_id in visited:
            return
        visiting.add(template_id)
        spec = specs.get(template_id)
        if spec is not None:
            refs = list(_collect_place_scene_refs(spec))
            if scene_rules_library is not None:
                refs.extend(_collect_static_scene_rule_scene_refs(spec, scene_rules_library=scene_rules_library))
            for ref_id in refs:
                if ref_id not in specs:
                    raise ValueError(
                        f"Scene template {template_id!r} references unknown template {ref_id!r}"
                    )
                dfs(ref_id, path + [template_id])
        visiting.discard(template_id)
        visited.add(template_id)

    for template_id in specs:
        if template_id not in visited:
            dfs(template_id, [])


def load_scene_template_library(
    base_dir: Path,
    raw_dir: str | None,
) -> SceneTemplateLibrary:
    templates_dir = (
        _resolve_path(base_dir, raw_dir)
        if raw_dir is not None
        else (base_dir / DEFAULT_SCENE_TEMPLATES_DIRNAME).resolve()
    )
    if not templates_dir.exists():
        if raw_dir is not None:
            raise ValueError(f"Configured scene_templates_dir does not exist: {templates_dir}")
        return SceneTemplateLibrary(root=templates_dir, specs={})
    if not templates_dir.is_dir():
        raise ValueError(f"scene_templates_dir must be a directory: {templates_dir}")

    specs: dict[str, SceneTemplateSpec] = {}
    for path in sorted(templates_dir.glob("*.json")):
        spec = _load_scene_template_spec(path)
        if spec.template_id in specs:
            raise ValueError(f"Duplicate scene template id {spec.template_id!r} in {templates_dir}")
        specs[spec.template_id] = spec
    detect_scene_template_cycles(specs)
    return SceneTemplateLibrary(root=templates_dir, specs=specs)


def _is_tile_ref_token(value: object) -> bool:
    if value is None or isinstance(value, (str, int)):
        return True
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return all(isinstance(key, str) for key in mapping.keys())
    if isinstance(value, list):
        items = cast(list[object], value)
        return all(_is_tile_ref_token(item) for item in items)
    return False


def _matches_scene_parameter_type(value: object, parameter_type: str) -> bool:
    if parameter_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if parameter_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if parameter_type == "str":
        return isinstance(value, str)
    if parameter_type == "bool":
        return isinstance(value, bool)
    if parameter_type == "tile_ref":
        return _is_tile_ref_token(value)
    if parameter_type == "list[tile_ref]":
        if not isinstance(value, list):
            return False
        items = cast(list[object], value)
        return all(_is_tile_ref_token(item) for item in items)
    raise AssertionError(f"unreachable scene parameter type: {parameter_type!r}")


def validate_scene_template_input(scene: SceneTemplate, template_spec: SceneTemplateSpec) -> None:
    template_id = template_spec.template_id
    for parameter_name, parameter_spec in template_spec.parameters.items():
        if parameter_spec.required and parameter_name not in scene:
            raise ValueError(
                f"Scene template {template_id!r} is missing required parameter {parameter_name!r}"
            )
        if parameter_name not in scene:
            continue
        value = scene[parameter_name]
        if not _matches_scene_parameter_type(value, parameter_spec.parameter_type):
            raise ValueError(
                f"Scene template {template_id!r} parameter {parameter_name!r} must be "
                f"{parameter_spec.parameter_type}, got {value!r}"
            )


def _scene_optional_value_enabled_after_defaults(value: object) -> bool:
    # None, False, and "" disable optional branches after defaults have been
    # applied.
    return value is not None and value is not False and value != ""


def _scene_expr_number(value: object, *, context: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{context} must evaluate to a number, got {value!r}")
    return value


def _scene_expr_int_value(value: object, *, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{context} must evaluate to an int, got {value!r}")
    return value


def _scene_expr_str_value(value: object, *, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must evaluate to a string, got {value!r}")
    return value


def _scene_expr_tile_ref_value(value: object, *, context: str) -> TileRefToken:
    if not _is_tile_ref_token(value):
        raise ValueError(f"{context} must evaluate to a tile ref, got {value!r}")
    return cast(TileRefToken, value)


def _scene_expr_bool_value(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must evaluate to a bool, got {value!r}")
    return value


def _scene_expr_optional_child(mapping: dict[str, object], key: str) -> tuple[object, ...]:
    return () if key not in mapping else (mapping[key],)


def _scene_expr_list_children(mapping: dict[str, object], key: str) -> tuple[object, ...]:
    value = mapping.get(key)
    if isinstance(value, list):
        return tuple(cast(list[object], value))
    return () if value is None else (value,)


def _scene_expr_centered_x_children(mapping: dict[str, object]) -> tuple[object, ...]:
    centered_spec = mapping.get("centered_x")
    if not isinstance(centered_spec, dict):
        return () if centered_spec is None else (centered_spec,)
    centered_mapping = cast(dict[str, object], centered_spec)
    children = [centered_mapping[name] for name in ("ref", "x", "width") if name in centered_mapping]
    # Fall back to all values so bind-ref scanning still sees partial or
    # malformed centered_x payloads before evaluation raises on them.
    return tuple(children or centered_mapping.values())


def _evaluate_scene_expr(expr: object, ctx: SceneEvalContext) -> object:
    if isinstance(expr, dict):
        mapping = cast(dict[str, object], expr)
        operator_spec = _scene_expression_operator_spec(mapping)
        if operator_spec is not None:
            return operator_spec.handler(mapping, ctx)
        keys = set(mapping)
        if len(keys) == 1:
            candidate = next(iter(keys))
            suggestion = difflib.get_close_matches(
                candidate,
                sorted(SCENE_EXPRESSION_OPERATORS),
                n=1,
                cutoff=0.8,
            )
            if suggestion:
                raise ValueError(
                    f"unknown scene expression operator {candidate!r}; did you mean {suggestion[0]!r}?"
                )
        if not SCENE_EXPRESSION_OPERATORS.isdisjoint(keys):
            raise ValueError(f"unknown or malformed scene expression: {mapping!r}")
        return {key: _evaluate_scene_expr(value, ctx) for key, value in mapping.items()}
    if isinstance(expr, list):
        return [_evaluate_scene_expr(item, ctx) for item in cast(list[object], expr)]
    return expr


def _evaluate_scene_expr_int(expr: object, ctx: SceneEvalContext, *, context: str) -> int:
    return _scene_expr_int_value(_evaluate_scene_expr(expr, ctx), context=context)


def _evaluate_scene_expr_tile_ref(expr: object, ctx: SceneEvalContext, *, context: str) -> TileRefToken:
    return _scene_expr_tile_ref_value(_evaluate_scene_expr(expr, ctx), context=context)


def _evaluate_scene_expr_bool(expr: object, ctx: SceneEvalContext, *, context: str) -> bool:
    return _scene_expr_bool_value(_evaluate_scene_expr(expr, ctx), context=context)


def _evaluate_scene_expr_operands(
    mapping: dict[str, object],
    operator_name: str,
    ctx: SceneEvalContext,
) -> list[object]:
    return [
        _evaluate_scene_expr(operand, ctx)
        for operand in _require_list(mapping.get(operator_name), context=f"scene expression {operator_name}")
    ]


def _evaluate_scene_expr_binary_operands(
    mapping: dict[str, object],
    operator_name: str,
    ctx: SceneEvalContext,
) -> tuple[object, object]:
    operands = _evaluate_scene_expr_operands(mapping, operator_name, ctx)
    if len(operands) != 2:
        raise ValueError(f"scene expression {operator_name} must have exactly two operands")
    return operands[0], operands[1]


def _eval_param_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    parameter_name = _require_string(mapping.get("param"), context="scene expression param")
    if parameter_name in ctx.scene:
        return ctx.scene[parameter_name]
    if "default" in mapping:
        return _evaluate_scene_expr(mapping["default"], ctx)
    raise ValueError(f"Scene expression references missing parameter {parameter_name!r}")


def _eval_bind_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    binding_name = _require_string(mapping.get("bind"), context="scene expression bind")
    if binding_name not in ctx.bindings:
        raise ValueError(f"Scene expression references unknown binding {binding_name!r}")
    return ctx.bindings[binding_name]


def _eval_add_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    total: int | float = 0
    for operand in _evaluate_scene_expr_operands(mapping, "add", ctx):
        total += _scene_expr_number(operand, context="scene expression add")
    return total


def _eval_sub_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    left, right = _evaluate_scene_expr_binary_operands(mapping, "sub", ctx)
    return _scene_expr_number(left, context="scene expression sub") - _scene_expr_number(
        right,
        context="scene expression sub",
    )


def _eval_mul_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    product: int | float = 1
    for operand in _evaluate_scene_expr_operands(mapping, "mul", ctx):
        product *= _scene_expr_number(operand, context="scene expression mul")
    return product


def _eval_floordiv_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    left, right = _evaluate_scene_expr_binary_operands(mapping, "floordiv", ctx)
    return _scene_expr_int_value(left, context="scene expression floordiv") // _scene_expr_int_value(
        right,
        context="scene expression floordiv",
    )


def _eval_max_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    operands = _evaluate_scene_expr_operands(mapping, "max", ctx)
    if not operands:
        raise ValueError("scene expression max must have at least one operand")
    return max(_scene_expr_number(operand, context="scene expression max") for operand in operands)


def _eval_min_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    operands = _evaluate_scene_expr_operands(mapping, "min", ctx)
    if not operands:
        raise ValueError("scene expression min must have at least one operand")
    return min(_scene_expr_number(operand, context="scene expression min") for operand in operands)


def _eval_fill_rows_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    spec = _require_mapping(mapping["fill_rows"], context="scene expression fill_rows")
    width = _evaluate_scene_expr_int(spec.get("width"), ctx, context="scene expression fill_rows width")
    height = _evaluate_scene_expr_int(spec.get("height"), ctx, context="scene expression fill_rows height")
    if width < 0:
        raise ValueError(f"scene expression fill_rows width must be non-negative, got {width}")
    if height < 0:
        raise ValueError(f"scene expression fill_rows height must be non-negative, got {height}")
    row = "#" * width
    return [row] * height


def _eval_fill_rows_children(mapping: dict[str, object]) -> tuple[object, ...]:
    spec = mapping.get("fill_rows")
    if not isinstance(spec, dict):
        return () if spec is None else (spec,)
    spec_mapping = cast(dict[str, object], spec)
    return tuple(spec_mapping[name] for name in ("width", "height") if name in spec_mapping)


def _eval_gt_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    left, right = _evaluate_scene_expr_binary_operands(mapping, "gt", ctx)
    return _scene_expr_number(left, context="scene expression gt") > _scene_expr_number(
        right,
        context="scene expression gt",
    )


def _eval_eq_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    left, right = _evaluate_scene_expr_binary_operands(mapping, "eq", ctx)
    return left == right


def _eval_all_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    return all(
        _scene_expr_bool_value(operand, context="scene expression all")
        for operand in _evaluate_scene_expr_operands(mapping, "all", ctx)
    )


def _eval_enabled_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    return _scene_optional_value_enabled_after_defaults(_evaluate_scene_expr(mapping["enabled"], ctx))


def _eval_if_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    condition = _evaluate_scene_expr_bool(mapping["if"], ctx, context="scene expression if")
    return _evaluate_scene_expr(mapping["then"] if condition else mapping["else"], ctx)


def _eval_pattern_width_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    ref = _evaluate_scene_expr_tile_ref(mapping["pattern_width"], ctx, context="scene expression pattern_width")
    width, _height = ctx.runtime.pattern_dimensions(ref)
    return width


def _eval_pattern_height_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    ref = _evaluate_scene_expr_tile_ref(mapping["pattern_height"], ctx, context="scene expression pattern_height")
    _width, height = ctx.runtime.pattern_dimensions(ref)
    return height


def _eval_centered_x_expr(mapping: dict[str, object], ctx: SceneEvalContext) -> object:
    centered_spec = _require_mapping(mapping["centered_x"], context="scene expression centered_x")
    ref = _evaluate_scene_expr_tile_ref(centered_spec.get("ref"), ctx, context="scene expression centered_x ref")
    x = _evaluate_scene_expr_int(centered_spec.get("x"), ctx, context="scene expression centered_x x")
    width = _evaluate_scene_expr_int(centered_spec.get("width"), ctx, context="scene expression centered_x width")
    return ctx.runtime.centered_pattern_x(ref, x, width)


SCENE_EXPRESSION_SPECS: dict[str, SceneExpressionOperatorSpec] = {
    "param": SceneExpressionOperatorSpec(
        required_keys=frozenset({"param"}),
        allowed_keys=frozenset({"param", "default"}),
        handler=_eval_param_expr,
        child_expressions=lambda mapping: _scene_expr_optional_child(mapping, "default"),
    ),
    "bind": SceneExpressionOperatorSpec(
        required_keys=frozenset({"bind"}),
        allowed_keys=frozenset({"bind"}),
        handler=_eval_bind_expr,
        child_expressions=lambda _mapping: (),
    ),
    "add": SceneExpressionOperatorSpec(
        required_keys=frozenset({"add"}),
        allowed_keys=frozenset({"add"}),
        handler=_eval_add_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "add"),
    ),
    "sub": SceneExpressionOperatorSpec(
        required_keys=frozenset({"sub"}),
        allowed_keys=frozenset({"sub"}),
        handler=_eval_sub_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "sub"),
    ),
    "mul": SceneExpressionOperatorSpec(
        required_keys=frozenset({"mul"}),
        allowed_keys=frozenset({"mul"}),
        handler=_eval_mul_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "mul"),
    ),
    "floordiv": SceneExpressionOperatorSpec(
        required_keys=frozenset({"floordiv"}),
        allowed_keys=frozenset({"floordiv"}),
        handler=_eval_floordiv_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "floordiv"),
    ),
    "max": SceneExpressionOperatorSpec(
        required_keys=frozenset({"max"}),
        allowed_keys=frozenset({"max"}),
        handler=_eval_max_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "max"),
    ),
    "min": SceneExpressionOperatorSpec(
        required_keys=frozenset({"min"}),
        allowed_keys=frozenset({"min"}),
        handler=_eval_min_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "min"),
    ),
    "fill_rows": SceneExpressionOperatorSpec(
        required_keys=frozenset({"fill_rows"}),
        allowed_keys=frozenset({"fill_rows"}),
        handler=_eval_fill_rows_expr,
        child_expressions=_eval_fill_rows_children,
    ),
    "gt": SceneExpressionOperatorSpec(
        required_keys=frozenset({"gt"}),
        allowed_keys=frozenset({"gt"}),
        handler=_eval_gt_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "gt"),
    ),
    "eq": SceneExpressionOperatorSpec(
        required_keys=frozenset({"eq"}),
        allowed_keys=frozenset({"eq"}),
        handler=_eval_eq_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "eq"),
    ),
    "all": SceneExpressionOperatorSpec(
        required_keys=frozenset({"all"}),
        allowed_keys=frozenset({"all"}),
        handler=_eval_all_expr,
        child_expressions=lambda mapping: _scene_expr_list_children(mapping, "all"),
    ),
    "enabled": SceneExpressionOperatorSpec(
        required_keys=frozenset({"enabled"}),
        allowed_keys=frozenset({"enabled"}),
        handler=_eval_enabled_expr,
        child_expressions=lambda mapping: _scene_expr_optional_child(mapping, "enabled"),
    ),
    "if": SceneExpressionOperatorSpec(
        required_keys=frozenset({"if", "then", "else"}),
        allowed_keys=frozenset({"if", "then", "else"}),
        handler=_eval_if_expr,
        child_expressions=lambda mapping: (
            mapping["if"],
            mapping["then"],
            mapping["else"],
        ),
    ),
    "pattern_width": SceneExpressionOperatorSpec(
        required_keys=frozenset({"pattern_width"}),
        allowed_keys=frozenset({"pattern_width"}),
        handler=_eval_pattern_width_expr,
        child_expressions=lambda mapping: _scene_expr_optional_child(mapping, "pattern_width"),
    ),
    "pattern_height": SceneExpressionOperatorSpec(
        required_keys=frozenset({"pattern_height"}),
        allowed_keys=frozenset({"pattern_height"}),
        handler=_eval_pattern_height_expr,
        child_expressions=lambda mapping: _scene_expr_optional_child(mapping, "pattern_height"),
    ),
    "centered_x": SceneExpressionOperatorSpec(
        required_keys=frozenset({"centered_x"}),
        allowed_keys=frozenset({"centered_x"}),
        handler=_eval_centered_x_expr,
        child_expressions=_scene_expr_centered_x_children,
    ),
}
SCENE_EXPRESSION_OPERATORS = frozenset(SCENE_EXPRESSION_SPECS)


def _scene_expression_operator_spec(mapping: dict[str, object]) -> SceneExpressionOperatorSpec | None:
    keys = frozenset(mapping)
    for operator_name, spec in SCENE_EXPRESSION_SPECS.items():
        if operator_name in mapping and spec.required_keys <= keys <= spec.allowed_keys:
            return spec
    return None


def _scene_expression_child_values(mapping: dict[str, object]) -> tuple[object, ...]:
    operator_spec = _scene_expression_operator_spec(mapping)
    if operator_spec is None:
        return tuple(mapping.values())
    return tuple(operator_spec.child_expressions(mapping))


def evaluate_scene_expr(
    expr: object,
    *,
    scene: SceneTemplate,
    bindings: dict[str, object],
    runtime: SceneTemplateRuntime,
) -> object:
    return _evaluate_scene_expr(expr, SceneEvalContext(scene=scene, bindings=bindings, runtime=runtime))


def _resolve_scene_template_bindings(
    scene: SceneTemplate,
    template_spec: SceneTemplateSpec,
    *,
    runtime: SceneTemplateRuntime,
) -> dict[str, object]:
    bindings: dict[str, object] = {}
    for name, expr in template_spec.bindings.items():
        bindings[name] = evaluate_scene_expr(expr, scene=scene, bindings=bindings, runtime=runtime)
    return bindings


def _shift_scene_op(op: SceneOp, *, dx: int, dy: int) -> SceneOp:
    shifted: dict[str, object] = dict(op)
    shifted["x"] = cast(int, shifted["x"]) + dx
    shifted["y"] = cast(int, shifted["y"]) + dy
    return cast(SceneOp, shifted)


def _shift_scene_entity(entity: SceneEntityRequest, *, dx: int, dy: int) -> SceneEntityRequest:
    return SceneEntityRequest(
        entity_id=entity.entity_id,
        source_template_id=entity.source_template_id,
        layer=entity.layer,
        x=entity.x + dx,
        y=entity.y + dy,
        construction_id=entity.construction_id,
        params=None if entity.params is None else dict(entity.params),
        variant_id=entity.variant_id,
        placeable_kind=entity.placeable_kind,
        placeable_id=entity.placeable_id,
    )


def _scene_slot_group(
    template_spec: SceneTemplateSpec,
    group_name: str,
) -> tuple[SceneSlotSpec, ...]:
    try:
        return template_spec.slot_groups[group_name]
    except KeyError as exc:
        available = ", ".join(sorted(template_spec.slot_groups)) or "<none>"
        raise ValueError(
            f"Scene template {template_spec.template_id!r} references unknown slot group "
            f"{group_name!r}. Available slot groups: {available}"
        ) from exc


def _slot_seed_value(
    *,
    seed: int,
    ruleset_id: str,
    catalogue_id: str,
    slot_group_id: str,
    slot_id: str,
) -> int:
    payload = f"{seed}:{ruleset_id}:{catalogue_id}:{slot_group_id}:{slot_id}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _choose_scene_rule_candidate(
    candidates: Sequence[SceneRuleCandidate],
    *,
    seed: int,
    ruleset_id: str,
    catalogue_id: str,
    slot_group_id: str,
    slot_id: str,
) -> SceneRuleCandidate:
    rng = random.Random(
        _slot_seed_value(
            seed=seed,
            ruleset_id=ruleset_id,
            catalogue_id=catalogue_id,
            slot_group_id=slot_group_id,
            slot_id=slot_id,
        )
    )
    total = sum(candidate.weight for candidate in candidates)
    threshold = rng.random() * total
    running = 0.0
    for candidate in candidates:
        running += candidate.weight
        if threshold < running:
            return candidate
    return candidates[-1]


def _slot_layer_or_candidate_layer(
    *,
    slot_layer: str | None,
    candidate_layer: str | None,
    context: str,
) -> str:
    resolved = candidate_layer if candidate_layer is not None else slot_layer
    if resolved is None:
        raise ValueError(f"{context} requires a layer but neither the slot nor candidate defines one")
    return resolved


def _scene_op_from_fields(kind: str, fields: dict[str, object]) -> SceneOp:
    if kind == "stamp":
        return cast(StampOp, {"kind": "stamp", **fields})
    if kind == "fill":
        return cast(FillOp, {"kind": "fill", **fields})
    raise AssertionError(f"unreachable data scene op kind: {kind!r}")


def expand_data_scene(
    scene: SceneTemplate,
    template_spec: SceneTemplateSpec,
    *,
    runtime: SceneTemplateRuntime,
    _scope: tuple[str, ...] | None = None,
    _template_stack: tuple[str, ...] = (),
) -> ExpandedDataScene:
    scope = (template_spec.template_id,) if _scope is None else _scope
    if template_spec.template_id in _template_stack:
        cycle_start = _template_stack.index(template_spec.template_id)
        cycle_path = " -> ".join((*_template_stack[cycle_start:], template_spec.template_id))
        raise ValueError(f"scene template cycle detected: {cycle_path}")
    template_stack = (*_template_stack, template_spec.template_id)
    bindings = _resolve_scene_template_bindings(scene, template_spec, runtime=runtime)
    for constraint_spec in template_spec.constraints:
        condition = _evaluate_scene_expr_bool(
            constraint_spec.condition,
            SceneEvalContext(scene=scene, bindings=bindings, runtime=runtime),
            context=f"scene template {template_spec.template_id!r} constraint",
        )
        if not condition:
            raise ValueError(
                f"Scene template {template_spec.template_id!r} failed constraint: {constraint_spec.message}"
            )
    scene_layers: SceneLayers = {}
    scene_entities: list[SceneEntityRequest] = []
    for op_index, op_spec in enumerate(template_spec.data_ops):
        op_scope = (*scope, f"op_{op_index}")
        if op_spec.when_present is not None:
            if op_spec.when_present not in bindings:
                raise ValueError(
                    f"Scene template {template_spec.template_id!r} references unknown binding "
                    f"{op_spec.when_present!r} in when_present"
                )
            if not _scene_optional_value_enabled_after_defaults(bindings[op_spec.when_present]):
                continue

        if op_spec.kind == "place_scene":
            sub_scene_id = _scene_expr_str_value(
                evaluate_scene_expr(op_spec.fields["scene"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} place_scene scene",
            )
            offset_x = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["x"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} place_scene x",
            )
            offset_y = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["y"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} place_scene y",
            )
            if runtime.scene_library is None:
                raise ValueError(
                    f"Scene template {template_spec.template_id!r} uses place_scene op but "
                    f"no scene_library is available in the runtime"
                )
            sub_spec = runtime.scene_library.require(sub_scene_id)
            args_expr = op_spec.fields.get("args", {})
            args_raw = _require_mapping(
                evaluate_scene_expr(args_expr, scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} place_scene args",
            )
            sub_scene: SceneTemplate = {"template": sub_scene_id, **args_raw}
            sub_expansion = expand_data_scene(
                sub_scene,
                sub_spec,
                runtime=runtime,
                _scope=(*op_scope, f"place_scene_{sub_scene_id}"),
                _template_stack=template_stack,
            )
            for sub_layer, sub_ops in sub_expansion.layers.items():
                for sub_op in sub_ops:
                    shifted = _shift_scene_op(sub_op, dx=offset_x, dy=offset_y)
                    scene_layers.setdefault(sub_layer, []).append(shifted)
            for sub_entity in sub_expansion.entities:
                scene_entities.append(_shift_scene_entity(sub_entity, dx=offset_x, dy=offset_y))
            continue

        if op_spec.kind == "populate_slots":
            if runtime.scene_rules_library is None:
                raise ValueError(
                    f"Scene template {template_spec.template_id!r} uses populate_slots op but "
                    "no scene_rules_library is available in the runtime"
                )
            ruleset_id = _scene_expr_str_value(
                evaluate_scene_expr(op_spec.fields["ruleset"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} populate_slots ruleset",
            )
            catalogue_id = _scene_expr_str_value(
                evaluate_scene_expr(op_spec.fields["catalogue"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} populate_slots catalogue",
            )
            slot_group_id = _scene_expr_str_value(
                evaluate_scene_expr(op_spec.fields["slot_group"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} populate_slots slot_group",
            )
            op_args: dict[str, object] = {}
            if "args" in op_spec.fields:
                op_args = _require_mapping(
                    evaluate_scene_expr(op_spec.fields["args"], scene=scene, bindings=bindings, runtime=runtime),
                    context=f"scene template {template_spec.template_id!r} populate_slots args",
                )
            seed = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields.get("seed", 0), scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} populate_slots seed",
            )
            ruleset = runtime.scene_rules_library.require(ruleset_id)
            candidates = ruleset.require_catalogue(catalogue_id)
            slot_group = _scene_slot_group(template_spec, slot_group_id)
            for slot_index, slot_spec in enumerate(slot_group):
                slot_x = _scene_expr_int_value(
                    evaluate_scene_expr(slot_spec.x, scene=scene, bindings=bindings, runtime=runtime),
                    context=(
                        f"scene template {template_spec.template_id!r} slot_group "
                        f"{slot_group_id!r} slot {slot_spec.slot_id!r} x"
                    ),
                )
                slot_y = _scene_expr_int_value(
                    evaluate_scene_expr(slot_spec.y, scene=scene, bindings=bindings, runtime=runtime),
                    context=(
                        f"scene template {template_spec.template_id!r} slot_group "
                        f"{slot_group_id!r} slot {slot_spec.slot_id!r} y"
                    ),
                )
                slot_layer = (
                    None
                    if slot_spec.layer is None
                    else _scene_expr_str_value(
                        evaluate_scene_expr(slot_spec.layer, scene=scene, bindings=bindings, runtime=runtime),
                        context=(
                            f"scene template {template_spec.template_id!r} slot_group "
                            f"{slot_group_id!r} slot {slot_spec.slot_id!r} layer"
                        ),
                    )
                )
                chosen = _choose_scene_rule_candidate(
                    candidates,
                    seed=seed,
                    ruleset_id=ruleset_id,
                    catalogue_id=catalogue_id,
                    slot_group_id=slot_group_id,
                    slot_id=slot_spec.slot_id,
                )
                chosen_scope = (*op_scope, f"slot_{slot_index}", chosen.candidate_id)
                if isinstance(chosen, SceneRuleStampCandidate):
                    layer = _slot_layer_or_candidate_layer(
                        slot_layer=slot_layer,
                        candidate_layer=chosen.layer,
                        context=(
                            f"scene ruleset {ruleset_id!r} catalogue {catalogue_id!r} "
                            f"candidate {chosen.candidate_id!r}"
                        ),
                    )
                    scene_layers.setdefault(layer, []).append(
                        {"kind": "stamp", "ref": chosen.ref, "x": slot_x, "y": slot_y}
                    )
                    continue
                if isinstance(chosen, SceneRuleEntityCandidate):
                    layer = _slot_layer_or_candidate_layer(
                        slot_layer=slot_layer,
                        candidate_layer=chosen.layer,
                        context=(
                            f"scene ruleset {ruleset_id!r} catalogue {catalogue_id!r} "
                            f"candidate {chosen.candidate_id!r}"
                        ),
                    )
                    scene_entities.append(
                        SceneEntityRequest(
                            entity_id=".".join((*chosen_scope, "entity")),
                            source_template_id=template_spec.template_id,
                            layer=layer,
                            x=slot_x,
                            y=slot_y,
                            construction_id=chosen.construction_id,
                            params=None if chosen.params is None else dict(chosen.params),
                            placeable_kind=chosen.placeable_kind,
                            placeable_id=chosen.placeable_id,
                        )
                    )
                    continue
                if runtime.scene_library is None:
                    raise ValueError(
                        f"Scene template {template_spec.template_id!r} uses scene rules scene candidate "
                        "but no scene_library is available in the runtime"
                    )
                sub_spec = runtime.scene_library.require(chosen.scene_id)
                merged_args = dict(chosen.args or {})
                merged_args.update(op_args)
                sub_scene: SceneTemplate = {"template": chosen.scene_id, **merged_args}
                sub_expansion = expand_data_scene(
                    sub_scene,
                    sub_spec,
                    runtime=runtime,
                    _scope=(*chosen_scope, f"scene_{chosen.scene_id}"),
                    _template_stack=template_stack,
                )
                for sub_layer, sub_ops in sub_expansion.layers.items():
                    for sub_op in sub_ops:
                        shifted = _shift_scene_op(sub_op, dx=slot_x, dy=slot_y)
                        scene_layers.setdefault(sub_layer, []).append(shifted)
                for sub_entity in sub_expansion.entities:
                    scene_entities.append(_shift_scene_entity(sub_entity, dx=slot_x, dy=slot_y))
                continue
            continue

        layer = _scene_expr_str_value(
            evaluate_scene_expr(op_spec.layer, scene=scene, bindings=bindings, runtime=runtime),
            context=f"scene template {template_spec.template_id!r} op layer",
        )
        if op_spec.kind == "spread_stamps":
            ref = _scene_expr_tile_ref_value(
                evaluate_scene_expr(op_spec.fields["ref"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps ref",
            )
            count = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["count"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps count",
            )
            start = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["start"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps start",
            )
            span = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["span"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps span",
            )
            inset = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["inset"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps inset",
            )
            y = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["y"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} spread_stamps y",
            )
            symbol_width, _symbol_height = runtime.pattern_dimensions(ref)
            for stamp_x in evenly_spaced_origins(
                start=start,
                span=span,
                item_width=symbol_width,
                count=count,
                inset=inset,
            ):
                stamp_op: StampOp = {"kind": "stamp", "ref": ref, "x": stamp_x, "y": y}
                scene_layers.setdefault(layer, []).append(stamp_op)
            continue

        if op_spec.kind == "entity":
            construction_id = _scene_expr_str_value(
                evaluate_scene_expr(op_spec.fields["construction"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} entity construction",
            )
            x = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["x"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} entity x",
            )
            y = _scene_expr_int_value(
                evaluate_scene_expr(op_spec.fields["y"], scene=scene, bindings=bindings, runtime=runtime),
                context=f"scene template {template_spec.template_id!r} entity y",
            )
            entity_params: dict[str, object] | None = None
            if "params" in op_spec.fields:
                raw_params = evaluate_scene_expr(
                    op_spec.fields["params"],
                    scene=scene,
                    bindings=bindings,
                    runtime=runtime,
                )
                entity_params = _require_mapping(
                    raw_params,
                    context=f"scene template {template_spec.template_id!r} entity params",
                )
            entity_variant_id: str | None = None
            raw_variant_id = op_spec.fields.get("variant_id")
            if raw_variant_id is not None:
                entity_variant_id = _scene_expr_str_value(
                    evaluate_scene_expr(raw_variant_id, scene=scene, bindings=bindings, runtime=runtime),
                    context=f"scene template {template_spec.template_id!r} entity variant_id",
                )
            raw_entity_id = op_spec.fields.get("entity_id")
            entity_id = (
                _scene_expr_str_value(
                    evaluate_scene_expr(raw_entity_id, scene=scene, bindings=bindings, runtime=runtime),
                    context=f"scene template {template_spec.template_id!r} entity entity_id",
                )
                if raw_entity_id is not None
                else ".".join((*op_scope, "entity"))
            )
            scene_entities.append(
                SceneEntityRequest(
                    entity_id=entity_id,
                    source_template_id=template_spec.template_id,
                    construction_id=construction_id,
                    layer=layer,
                    x=x,
                    y=y,
                    params=None if entity_params is None else dict(entity_params),
                    variant_id=entity_variant_id,
                    placeable_kind="construction",
                    placeable_id=construction_id,
                )
            )
            continue

        if op_spec.kind == "scatter":
            scatter_fields = {
                field_name: evaluate_scene_expr(field_expr, scene=scene, bindings=bindings, runtime=runtime)
                for field_name, field_expr in op_spec.fields.items()
            }
            scatter_op = cast(ScatterOp, {"kind": "scatter", **scatter_fields})
            scene_layers.setdefault(layer, []).append(scatter_op)
            continue

        op_fields = {
            field_name: evaluate_scene_expr(field_expr, scene=scene, bindings=bindings, runtime=runtime)
            for field_name, field_expr in op_spec.fields.items()
        }
        scene_layers.setdefault(layer, []).append(_scene_op_from_fields(op_spec.kind, op_fields))
    return ExpandedDataScene(
        layers=scene_layers,
        entities=tuple(scene_entities),
    )
