#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence, Union, cast

from typing_extensions import TypeAlias

from PIL import Image

from prototype_output import create_staging_output_path, publish_staged_output
from _manifest_utils import require_exactly_one
from scene_templates import (
    AsciiOp,
    EntityOp,
    FillOp,
    MaskFillOp,
    RepeatOp,
    ScatterOp,
    SceneEntityRequest,
    SceneLayers,
    SceneOp,
    SceneTemplate,
    expand_data_scene,
    SceneTemplateRuntime,
    StampOp,
    TileRefToken,
    validate_scene_template_input,
)
from tile_library import (
    Construction,
    ConstructionAttachmentSet,
    EntityTemplateRecord,
    FrameCornerSlot,
    LoweredTileCell,
    ParametricFrameConstruction,
    ParametricRunConstruction,
    PlaceableRef,
    RuntimeConstructionCatalog,
    TileGenesis,
    TileRecord,
)
from tile_families import (
    bootstrap_family as bootstrap_tile_family,
)
from source_ingest_ops import (
    scaffold_pattern,
    export_public_tile_pack,
    query_semantic_catalog,
    export_tiled_kit,
)
from layout_core import (
    resize_nearest,
    LayerSpec,
    ViewportSpec,
    LayoutConfig,
    load_layout_config,
    resolve_path,
    parse_hex_colour,
    slugify_identifier,
    ResolvedTile,
    LayoutProject,
    composite_render_spec,
    new_layer,
    place_pattern,
    apply_fill,
    apply_mask_fill,
    apply_scatter,
    apply_ascii,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
DEFAULT_LAYOUTS_DIR = ROOT / "prototypes/minimal8-harness/layouts"
DEFAULT_OUTPUT_DIR = ROOT / "prototypes/minimal8-harness/generated"
DEFAULT_INSPECT_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/inspect"
DEFAULT_SCENE_RUNTIME_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/scene-runtime"
DEFAULT_TILED_KIT_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/tiled-kit"
DEFAULT_REVIEW_PACK_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/review-packs"
DEFAULT_COLLECTION_REVIEW_DIR = ROOT / "prototypes/minimal8-harness/reviews/collections"
DEFAULT_COLLECTION_REVIEW_SCRATCH_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/review-collections"
DEFAULT_PUBLIC_TILE_PACK_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/public-tile-packs"

DEFAULT_LAYER_ORDER = [
    "water",
    "backdrop",
    "terrain",
    "detail",
    "rooms",
    "architecture",
    "island",
    "prefabs_back",
    "ornament",
    "actors",
    "prefabs_front",
    "hud",
]



@dataclass(frozen=True)
class EntityBounds:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class EntityAnchor:
    kind: Literal["top_left"]
    x: int
    y: int


@dataclass(frozen=True)
class EntityTilePlacement:
    tile_id: str
    ref: str
    x: int
    y: int
    compose_role: str | None = None
    walkable: bool | None = None
    blocking: bool | None = None
    affordances: tuple[str, ...] = ()
    flip_x: bool = False
    flip_y: bool = False

    def stamp_ref(self) -> TileRefToken:
        """The ref to emit in a StampOp — a flip-bearing dict token when flipped."""
        if self.flip_x or self.flip_y:
            return {"ref": self.ref, "flip_x": self.flip_x, "flip_y": self.flip_y}
        return self.ref


@dataclass(frozen=True)
class EntityOccupancyCell:
    x: int
    y: int
    relative_x: int
    relative_y: int
    tile_id: str
    compose_role: str | None = None
    walkable: bool | None = None
    blocking: bool | None = None
    affordances: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityInstance:
    entity_id: str
    source_template_id: str
    template: EntityTemplateRecord
    layer: str
    x: int
    y: int
    placement_anchor: EntityAnchor
    bounds: EntityBounds
    params: dict[str, object]
    tiles: tuple[EntityTilePlacement, ...]
    occupied_cells: tuple[EntityOccupancyCell, ...]
    affordance_cells: tuple[EntityOccupancyCell, ...]


@dataclass(frozen=True)
class SceneExpansionResult:
    layers: SceneLayers
    entities: tuple[EntityInstance, ...]


@dataclass(frozen=True)
class LayoutScene:
    layers: list[LayerSpec]
    entities: tuple[EntityInstance, ...]


def pattern_dimensions(project: LayoutProject, ref: TileRefToken, *, default_tileset: str | None) -> tuple[int, int]:
    pattern = project.pattern_from_ref(ref, default_tileset=default_tileset)
    return pattern.width, pattern.height


def centred_pattern_x(
    project: LayoutProject,
    ref: TileRefToken,
    *,
    x: int,
    width: int,
    default_tileset: str | None,
) -> int:
    pattern_width, _ = pattern_dimensions(project, ref, default_tileset=default_tileset)
    return x + max(0, (width - pattern_width) // 2)


def _scene_str(scene: SceneTemplate, key: str, default: str) -> str:
    value = scene.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"Scene field {key!r} must be a string, got {value!r}")
    return value


def _placement_ref(
    tile_library: RuntimeConstructionCatalog,
    construction_id: str,
    tile_id: str,
    variant_id: str | None,
    *,
    context: str,
) -> str:
    if variant_id is None:
        return tile_id
    runtime_tileset_id = tile_library.runtime_tileset_id_for_construction(
        construction_id,
        variant_id=variant_id,
    )
    assert runtime_tileset_id is not None, (
        f"{context} references unknown construction {construction_id!r} "
        f"for variant {variant_id!r} (invariant: construction pre-verified by lookup_construction)"
    )
    return f"{runtime_tileset_id}:{tile_id}"


def _construction_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: Construction,
    construction_id: str,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    if isinstance(construction, ParametricFrameConstruction):
        return _parametric_frame_tile_placements(
            tile_library,
            construction,
            construction_id,
            x,
            y,
            params=params,
            context=context,
            variant_id=variant_id,
        )
    if isinstance(construction, ParametricRunConstruction):
        return _parametric_run_tile_placements(
            tile_library,
            construction,
            construction_id,
            x,
            y,
            params=params,
            context=context,
            variant_id=variant_id,
        )
    placements: list[EntityTilePlacement] = []
    for row_index, row in enumerate(construction.cells):
        for col_index, cell in enumerate(row):
            if cell is not None:
                placements.append(
                    EntityTilePlacement(
                        tile_id=cell.id,
                        ref=_placement_ref(
                            tile_library, construction_id, cell.id, variant_id, context=context
                        ),
                        x=x + col_index,
                        y=y + row_index,
                        compose_role=cell.compose_role,
                        walkable=cell.walkable,
                        blocking=cell.blocking,
                        affordances=cell.affordances,
                    )
                )
    return placements


def _attachment_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    placeable_ref: PlaceableRef,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object],
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    def _resolve_attachment_variant_id(attachment_set: ConstructionAttachmentSet) -> str | None:
        target_description = f"{placeable_ref.kind} {placeable_ref.id!r}"
        if attachment_set.param in params:
            raw_variant_id: object = params[attachment_set.param]
        elif attachment_set.default_variant_id is not None:
            raw_variant_id = attachment_set.default_variant_id
        elif attachment_set.required:
            raise ValueError(
                f"{context} requires attachment param {attachment_set.param!r} "
                f"for {target_description}"
            )
        else:
            return None
        if not isinstance(raw_variant_id, str) or raw_variant_id == "":
            raise ValueError(
                f"{context} attachment param {attachment_set.param!r} for {target_description} "
                "must be a non-empty string"
            )
        return raw_variant_id

    placements: list[EntityTilePlacement] = []
    for attachment_set in tile_library.attachment_sets_for_placeable(placeable_ref):
        raw_variant_id = _resolve_attachment_variant_id(attachment_set)
        if raw_variant_id is None:
            continue
        variant = attachment_set.variant(raw_variant_id)
        if variant is None:
            available = ", ".join(sorted(attachment_set.variants.keys())) or "<none>"
            raise ValueError(
                f"{context} attachment param {attachment_set.param!r} for "
                f"{placeable_ref.kind} {placeable_ref.id!r} "
                f"requested unknown variant {raw_variant_id!r}; available: {available}"
            )
        if tile_library.lookup_placeable(variant.placeable_ref) is None:
            raise ValueError(
                f"{context} attachment set {attachment_set.id!r} references unknown placeable "
                f"{variant.placeable_ref.kind}:{variant.placeable_ref.id!r}"
            )
        placements.extend(
            _base_placeable_tile_placements(
                tile_library,
                variant.placeable_ref,
                x + attachment_set.canvas.x,
                y + attachment_set.canvas.y,
                context=f"{context} attachment {attachment_set.id!r} variant {raw_variant_id!r}",
                params=params,
                variant_id=variant_id,
            )
        )
    return placements


def _parametric_run_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: ParametricRunConstruction,
    construction_id: str,
    x: int,
    y: int,
    *,
    params: Mapping[str, object] | None,
    context: str,
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    length_param = construction.length_param
    if params is None or length_param not in params:
        raise ValueError(
            f"Construction {construction.id!r} parametric_run requires params[{length_param!r}] ({context})"
        )
    length = int(params[length_param])  # type: ignore[arg-type]
    if length < 2:
        raise ValueError(
            f"Construction {construction.id!r} parametric_run length must be >= 2, got {length} ({context})"
        )
    axis = construction.axis
    placements: list[EntityTilePlacement] = []
    for i in range(length):
        if axis == "x":
            cx, cy = x + i, y
        else:
            cx, cy = x, y + i
        if i == 0:
            tile = construction.start_tile
        elif i == length - 1:
            tile = construction.end_tile
        else:
            tile = construction.repeat_tile
        placements.append(
            EntityTilePlacement(
                tile_id=tile.id,
                ref=_placement_ref(
                    tile_library, construction_id, tile.id, variant_id, context=context
                ),
                x=cx,
                y=cy,
                compose_role=tile.compose_role,
                walkable=tile.walkable,
                blocking=tile.blocking,
                affordances=tile.affordances,
            )
        )
    return placements


def _parametric_frame_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: ParametricFrameConstruction,
    construction_id: str,
    x: int,
    y: int,
    *,
    params: Mapping[str, object] | None,
    context: str,
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    if params is None or construction.width_param not in params or construction.height_param not in params:
        raise ValueError(
            f"Construction {construction.id!r} parametric_frame requires "
            f"params[{construction.width_param!r}] and params[{construction.height_param!r}] ({context})"
        )
    width = int(params[construction.width_param])  # type: ignore[arg-type]
    height = int(params[construction.height_param])  # type: ignore[arg-type]
    if width < construction.min_width or height < construction.min_height:
        raise ValueError(
            f"Construction {construction.id!r} parametric_frame requires width >= {construction.min_width} "
            f"and height >= {construction.min_height}, got {width}x{height} ({context})"
        )

    placements: list[EntityTilePlacement] = []

    def _emit(tile: TileRecord, cx: int, cy: int, *, flip_x: bool = False, flip_y: bool = False) -> None:
        placements.append(
            EntityTilePlacement(
                tile_id=tile.id,
                ref=_placement_ref(tile_library, construction_id, tile.id, variant_id, context=context),
                x=cx,
                y=cy,
                compose_role=tile.compose_role,
                walkable=tile.walkable,
                blocking=tile.blocking,
                affordances=tile.affordances,
                flip_x=flip_x,
                flip_y=flip_y,
            )
        )

    def _place_corner(corner: FrameCornerSlot, anchor_x: int, anchor_y: int) -> None:
        # Place the corner's cells grid at the anchor, applying the slot's flip
        # (mirror the grid order and flip each tile) so one corner's art can
        # derive the other three.
        h, w = corner.height, corner.width
        for r, row in enumerate(corner.cells):
            for c, tile in enumerate(row):
                if tile is None:
                    continue
                dx = (w - 1 - c) if corner.flip_x else c
                dy = (h - 1 - r) if corner.flip_y else r
                _emit(tile, anchor_x + dx, anchor_y + dy, flip_x=corner.flip_x, flip_y=corner.flip_y)

    tl = construction.corners.get("corner_tl")
    tr = construction.corners.get("corner_tr")
    bl = construction.corners.get("corner_bl")
    br = construction.corners.get("corner_br")

    def _w(corner: FrameCornerSlot | None) -> int:
        return corner.width if corner is not None else 0

    def _h(corner: FrameCornerSlot | None) -> int:
        return corner.height if corner is not None else 0

    # Corners are placed once each at the four anchors; absent corners stay blank.
    if tl is not None:
        _place_corner(tl, x, y)
    if tr is not None:
        _place_corner(tr, x + width - tr.width, y)
    if bl is not None:
        _place_corner(bl, x, y + height - bl.height)
    if br is not None:
        _place_corner(br, x + width - br.width, y + height - br.height)

    # Present edges tile between the corner extents at the outer row/col; absent
    # edges stay blank. (fill_mode only affects multi-cell "fat" edges, which are
    # a deferred extension — single-cell v1 edges place one tile per border cell.)
    top = construction.edges.get("edge_top")
    bottom = construction.edges.get("edge_bottom")
    left = construction.edges.get("edge_left")
    right = construction.edges.get("edge_right")
    if top is not None:
        for col in range(x + _w(tl), x + width - _w(tr)):
            _emit(top.tile, col, y, flip_x=top.flip_x, flip_y=top.flip_y)
    if bottom is not None:
        for col in range(x + _w(bl), x + width - _w(br)):
            _emit(bottom.tile, col, y + height - 1, flip_x=bottom.flip_x, flip_y=bottom.flip_y)
    if left is not None:
        for row in range(y + _h(tl), y + height - _h(bl)):
            _emit(left.tile, x, row, flip_x=left.flip_x, flip_y=left.flip_y)
    if right is not None:
        for row in range(y + _h(tr), y + height - _h(br)):
            _emit(right.tile, x + width - 1, row, flip_x=right.flip_x, flip_y=right.flip_y)

    # The interior fills only when the kit declares a fill slot (1-thick kits).
    # Fat-corner kits declare no fill and supply their interior via a fill op.
    if construction.fill is not None:
        for row in range(y + 1, y + height - 1):
            for col in range(x + 1, x + width - 1):
                _emit(construction.fill.tile, col, row)

    return placements


def _entity_anchor(*, x: int, y: int) -> EntityAnchor:
    return EntityAnchor(kind="top_left", x=x, y=y)


def _entity_bounds_from_tile_placements(placements: Sequence[EntityTilePlacement]) -> EntityBounds:
    if not placements:
        return EntityBounds(x=0, y=0, width=0, height=0)
    min_x = min(placement.x for placement in placements)
    max_x = max(placement.x for placement in placements)
    min_y = min(placement.y for placement in placements)
    max_y = max(placement.y for placement in placements)
    return EntityBounds(
        x=min_x,
        y=min_y,
        width=max_x - min_x + 1,
        height=max_y - min_y + 1,
    )


def _entity_occupancy_cells(
    *,
    origin_x: int,
    origin_y: int,
    placements: Sequence[EntityTilePlacement],
) -> tuple[EntityOccupancyCell, ...]:
    return tuple(
        EntityOccupancyCell(
            x=placement.x,
            y=placement.y,
            relative_x=placement.x - origin_x,
            relative_y=placement.y - origin_y,
            tile_id=placement.tile_id,
            compose_role=placement.compose_role,
            walkable=placement.walkable,
            blocking=placement.blocking,
            affordances=placement.affordances,
        )
        for placement in placements
    )


def expand_entity_stamps(
    tile_library: RuntimeConstructionCatalog,
    construction_id: str,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> list[StampOp]:
    return expand_placeable_stamps(
        tile_library,
        PlaceableRef.construction(construction_id),
        x,
        y,
        context=context,
        params=params,
        variant_id=variant_id,
    )


def _fixed_placeable_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    placeable_ref: PlaceableRef,
    lowered_cells: tuple[LoweredTileCell, ...],
    x: int,
    y: int,
    *,
    context: str,
    variant_id: str | None = None,
) -> tuple[EntityTilePlacement, ...]:
    runtime_tileset_id = None
    if variant_id is not None:
        runtime_tileset_id = tile_library.runtime_tileset_id_for_placeable(placeable_ref, variant_id=variant_id)
        if runtime_tileset_id is None:
            raise ValueError(
                f"Unable to resolve runtime tileset for placeable "
                f"{placeable_ref.kind}:{placeable_ref.id!r} ({context})"
            )
    return tuple(
        EntityTilePlacement(
            tile_id=cell.tile.id,
            ref=cell.tile.id if runtime_tileset_id is None else f"{runtime_tileset_id}:{cell.tile.id}",
            x=x + cell.x,
            y=y + cell.y,
            compose_role=cell.role,
            walkable=cell.tile.walkable,
            blocking=cell.tile.blocking,
            affordances=cell.tile.affordances,
        )
        for cell in lowered_cells
    )


def _base_placeable_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    placeable_ref: PlaceableRef,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> tuple[EntityTilePlacement, ...]:
    lowered_cells = tile_library.lower_placeable_to_tile_cells(placeable_ref)
    if lowered_cells is not None:
        return _fixed_placeable_tile_placements(
            tile_library,
            placeable_ref,
            lowered_cells,
            x,
            y,
            context=context,
            variant_id=variant_id,
        )
    if placeable_ref.kind != "construction":
        if tile_library.lookup_placeable(placeable_ref) is None:
            raise ValueError(f"Unknown placeable {placeable_ref.kind}:{placeable_ref.id!r} ({context})")
        raise ValueError(f"Unable to lower placeable {placeable_ref.kind}:{placeable_ref.id!r} ({context})")
    construction = tile_library.lookup_construction(placeable_ref.id)
    if construction is None:
        raise ValueError(f"Unknown construction {placeable_ref.id!r} ({context})")
    return tuple(
        _construction_tile_placements(
            tile_library,
            construction,
            placeable_ref.id,
            x,
            y,
            context=context,
            params={} if params is None else dict(params),
            variant_id=variant_id,
        )
    )


def _placeable_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    placeable_ref: PlaceableRef,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> tuple[EntityTilePlacement, ...]:
    resolved_params = {} if params is None else dict(params)
    placements = list(
        _base_placeable_tile_placements(
            tile_library,
            placeable_ref,
            x,
            y,
            context=context,
            params=resolved_params,
            variant_id=variant_id,
        )
    )
    placements.extend(
        _attachment_tile_placements(
            tile_library,
            placeable_ref,
            x,
            y,
            context=context,
            params=resolved_params,
            variant_id=variant_id,
        )
    )
    return tuple(placements)


def expand_placeable_stamps(
    tile_library: RuntimeConstructionCatalog,
    placeable_ref: PlaceableRef,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> list[StampOp]:
    placements = _placeable_tile_placements(
        tile_library,
        placeable_ref,
        x,
        y,
        context=context,
        params=params,
        variant_id=variant_id,
    )
    return [
        {"kind": "stamp", "ref": placement.stamp_ref(), "x": placement.x, "y": placement.y}
        for placement in placements
    ]


def _resolve_scene_entity_request(
    tile_library: RuntimeConstructionCatalog,
    request: SceneEntityRequest,
) -> EntityInstance:
    placeable_ref = request.placeable_ref
    if tile_library.lookup_placeable(placeable_ref) is None:
        if placeable_ref.kind == "construction":
            raise ValueError(
                f"Unknown construction {placeable_ref.id!r} (scene entity {request.entity_id!r})"
            )
        raise ValueError(
            f"Unknown placeable {placeable_ref.kind}:{placeable_ref.id!r} "
            f"(scene entity {request.entity_id!r})"
        )
    template = tile_library.entity_template_for_placeable(placeable_ref)
    if template is None:
        if placeable_ref.kind == "construction":
            raise ValueError(
                f"Unable to derive entity template for construction {placeable_ref.id!r}"
            )
        raise ValueError(
            f"Unable to derive entity template for placeable {placeable_ref.kind}:{placeable_ref.id!r}"
        )
    params = {} if request.params is None else dict(request.params)
    placements = tuple(
        _placeable_tile_placements(
            tile_library,
            placeable_ref,
            request.x,
            request.y,
            context=f"scene entity {request.entity_id!r}",
            params=params,
            variant_id=request.variant_id,
        )
    )
    occupied_cells = _entity_occupancy_cells(
        origin_x=request.x,
        origin_y=request.y,
        placements=placements,
    )
    return EntityInstance(
        entity_id=request.entity_id,
        source_template_id=request.source_template_id,
        template=template,
        layer=request.layer,
        x=request.x,
        y=request.y,
        placement_anchor=_entity_anchor(x=request.x, y=request.y),
        bounds=_entity_bounds_from_tile_placements(placements),
        params=params,
        tiles=placements,
        occupied_cells=occupied_cells,
        affordance_cells=tuple(cell for cell in occupied_cells if cell.affordances),
    )


def _lower_entity_instance_to_stamp_ops(entity: EntityInstance) -> list[StampOp]:
    return [
        {"kind": "stamp", "ref": placement.stamp_ref(), "x": placement.x, "y": placement.y}
        for placement in entity.tiles
    ]




def expand_scene_runtime(
    project: LayoutProject,
    scene: SceneTemplate,
    *,
    default_tileset: str | None,
) -> SceneExpansionResult:
    template = _scene_str(scene, "template", "")
    if not template:
        raise ValueError("Scene is missing required 'template' field")
    template_spec = project.scene_template_spec(template)
    validate_scene_template_input(scene, template_spec)
    tile_library = project.tile_library_registry

    runtime = SceneTemplateRuntime(
        pattern_dimensions=lambda ref: pattern_dimensions(
            project,
            ref,
            default_tileset=default_tileset,
        ),
        centered_pattern_x=lambda ref, x, width: centred_pattern_x(
            project,
            ref,
            x=x,
            width=width,
            default_tileset=default_tileset,
        ),
        scene_library=project.scene_template_library,
        scene_rules_library=project.scene_rules_library,
    )
    expanded = expand_data_scene(
        scene,
        template_spec,
        runtime=runtime,
    )
    if not expanded.entities:
        resolved_entities = ()
    else:
        if tile_library is None:
            raise ValueError(
                f"entity op requires a tile family; scene template {template_spec.template_id!r} "
                "requested entity constructions but no tile family is loaded"
            )
        resolved_entities = tuple(
            _resolve_scene_entity_request(tile_library, request)
            for request in expanded.entities
        )
    merged_layers: SceneLayers = {
        layer_name: list(ops)
        for layer_name, ops in expanded.layers.items()
    }
    for entity in resolved_entities:
        merged_layers.setdefault(entity.layer, []).extend(_lower_entity_instance_to_stamp_ops(entity))
    return SceneExpansionResult(
        layers=merged_layers,
        entities=resolved_entities,
    )


def expand_scene(project: LayoutProject, scene: SceneTemplate, *, default_tileset: str | None) -> SceneLayers:
    return expand_scene_runtime(project, scene, default_tileset=default_tileset).layers


def layer_sort_key(name: str) -> tuple[int, str]:
    try:
        index = DEFAULT_LAYER_ORDER.index(name)
    except ValueError:
        index = len(DEFAULT_LAYER_ORDER)
    return index, name


def build_layout_scene(
    layout: LayoutConfig,
    project: LayoutProject,
    *,
    default_tileset: str | None,
) -> LayoutScene:
    merged_layers: dict[str, list[SceneOp]] = {}
    entities: list[EntityInstance] = []
    for layer_spec in layout.get("layers", []):
        merged_layers.setdefault(layer_spec["name"], []).extend(layer_spec.get("ops", []))

    for scene in layout.get("scenes", []):
        expanded = expand_scene_runtime(project, scene, default_tileset=default_tileset)
        for layer_name, ops in expanded.layers.items():
            merged_layers.setdefault(layer_name, []).extend(ops)
        entities.extend(expanded.entities)

    return LayoutScene(
        layers=[{"name": name, "ops": merged_layers[name]} for name in sorted(merged_layers.keys(), key=layer_sort_key)],
        entities=tuple(entities),
    )


def build_layout_layers(
    layout: LayoutConfig,
    project: LayoutProject,
    *,
    default_tileset: str | None,
) -> list[LayerSpec]:
    return build_layout_scene(layout, project, default_tileset=default_tileset).layers


def _tile_genesis_payload(genesis: TileGenesis | None) -> dict[str, object] | None:
    if genesis is None:
        return None
    return {
        "kind": genesis.kind,
        "sheet_col": genesis.sheet_col,
        "sheet_row": genesis.sheet_row,
        "source_group": genesis.source_group,
        "cluster_ids": list(genesis.cluster_ids),
        "derivation": genesis.derivation,
        "parent_construction_ids": list(genesis.parent_construction_ids),
        "parent_tile_ids": list(genesis.parent_tile_ids),
        "authored_notes": genesis.authored_notes,
    }


def _entity_instance_payload(
    entity: EntityInstance,
    genesis_lookup: Callable[[str], TileGenesis | None],
) -> dict[str, object]:
    def _occupancy_cell_payload(cell: EntityOccupancyCell) -> dict[str, object]:
        return {
            "tile_id": cell.tile_id,
            "x": cell.x,
            "y": cell.y,
            "relative_x": cell.relative_x,
            "relative_y": cell.relative_y,
            "compose_role": cell.compose_role,
            "walkable": cell.walkable,
            "blocking": cell.blocking,
            "affordances": list(cell.affordances),
        }

    return {
        "id": entity.entity_id,
        "source_template_id": entity.source_template_id,
        "template": entity.template.to_payload(),
        "layer": entity.layer,
        "origin": {"x": entity.x, "y": entity.y},
        "placement_anchor": {
            "kind": entity.placement_anchor.kind,
            "x": entity.placement_anchor.x,
            "y": entity.placement_anchor.y,
        },
        "bounds": {
            "x": entity.bounds.x,
            "y": entity.bounds.y,
            "width": entity.bounds.width,
            "height": entity.bounds.height,
        },
        "params": dict(entity.params),
        "tiles": [
            {
                "tile_id": placement.tile_id,
                "ref": placement.ref,
                "x": placement.x,
                "y": placement.y,
                "compose_role": placement.compose_role,
                "genesis": _tile_genesis_payload(genesis_lookup(placement.tile_id)),
            }
            for placement in entity.tiles
        ],
        "occupancy": {
            "cell_count": len(entity.occupied_cells),
            "cells": [_occupancy_cell_payload(cell) for cell in entity.occupied_cells],
            "blocking_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.blocking is True
            ],
            "walkable_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.walkable is True
            ],
            "unknown_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.walkable is None and cell.blocking is None
            ],
        },
        "affordance_cells": [_occupancy_cell_payload(cell) for cell in entity.affordance_cells],
    }


def export_layout_scene_runtime(layout_path: Path, output_path: Path) -> Path:
    layout_path = layout_path.resolve()
    layout = load_layout_config(layout_path)
    project_path = resolve_path(layout_path.parent, layout["project"])
    project = LayoutProject(project_path)
    default_tileset = layout.get("default_tileset", project.default_tileset_id())
    layout_scene = build_layout_scene(layout, project, default_tileset=default_tileset)

    registry = project.tile_library_registry

    def genesis_lookup(tile_id: str) -> TileGenesis | None:
        return None if registry is None else registry.genesis_for(tile_id)

    payload = {
        "layout": str(layout_path),
        "project": str(project_path),
        "default_tileset": default_tileset,
        "layer_count": len(layout_scene.layers),
        "entity_count": len(layout_scene.entities),
        "layers": [
            {
                "name": layer["name"],
                "op_count": len(layer["ops"]),
                "kinds": sorted({cast(str, op["kind"]) for op in layer["ops"]}),
            }
            for layer in layout_scene.layers
        ],
        "entities": [_entity_instance_payload(entity, genesis_lookup) for entity in layout_scene.entities],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def _apply_stamp_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(StampOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    place_pattern(layer, pattern, op["x"], op["y"])


def _apply_fill_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(FillOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    apply_fill(layer, pattern, op["x"], op["y"], op["width"], op["height"])


def _apply_mask_fill_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(MaskFillOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    apply_mask_fill(layer, pattern, op["x"], op["y"], list(op["rows"]))


def _apply_scatter_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(ScatterOp, op)
    refs = op.get("refs")
    if refs is None:
        single_ref = op.get("ref")
        if single_ref is None:
            raise ValueError("scatter op requires either 'ref' or 'refs'")
        refs = [single_ref]
    patterns = [project.pattern_from_ref(ref, default_tileset=default_tileset) for ref in refs]
    apply_scatter(
        layer,
        patterns,
        op["x"],
        op["y"],
        list(op["rows"]),
        density=float(op.get("density", 0.25)),
        seed=int(op.get("seed", 0)),
    )


def _apply_repeat_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(RepeatOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    dx = op.get("dx", 0)
    dy = op.get("dy", 0)
    for index in range(op["count"]):
        place_pattern(layer, pattern, op["x"] + index * dx, op["y"] + index * dy)


def _apply_entity_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(EntityOp, op)
    tile_library = project.tile_library_registry
    if tile_library is None:
        raise ValueError("layout entity op requires a tile-family-backed project")
    require_exactly_one(op, "construction", "placeable", context="layout entity op")
    if "placeable" in op:
        placeable_ref = PlaceableRef.from_mapping(op["placeable"], context="layout entity op placeable")
    else:
        construction_id = op.get("construction")
        if not isinstance(construction_id, str):
            raise ValueError("layout entity op construction must be a string")
        placeable_ref = PlaceableRef.construction(construction_id)
    stamps = expand_placeable_stamps(
        tile_library,
        placeable_ref,
        op["x"],
        op["y"],
        context="layout entity op",
        params=op.get("params"),
        variant_id=op.get("variant_id"),
    )
    for stamp_op in stamps:
        _apply_stamp_op(layer, project, stamp_op, default_tileset=default_tileset)


def _apply_ascii_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    apply_ascii(layer, project, cast(AsciiOp, op), default_tileset=default_tileset)


# Each handler receives the SceneOp as the union, casts to its specific
# TypedDict variant, and applies it to the layer.
LayerOpHandler: TypeAlias = Callable[
    [list[list[Union[ResolvedTile, None]]], "LayoutProject", SceneOp],
    None,
]


def _make_layer_op_handlers(default_tileset: str | None) -> dict[str, LayerOpHandler]:
    def stamp(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_stamp_op(layer, project, op, default_tileset=default_tileset)

    def fill(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_fill_op(layer, project, op, default_tileset=default_tileset)

    def mask_fill(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_mask_fill_op(layer, project, op, default_tileset=default_tileset)

    def scatter(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_scatter_op(layer, project, op, default_tileset=default_tileset)

    def repeat(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_repeat_op(layer, project, op, default_tileset=default_tileset)

    def ascii_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_ascii_op(layer, project, op, default_tileset=default_tileset)

    def entity(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_entity_op(layer, project, op, default_tileset=default_tileset)

    return {
        "stamp": stamp,
        "fill": fill,
        "mask_fill": mask_fill,
        "scatter": scatter,
        "repeat": repeat,
        "ascii": ascii_op,
        "entity": entity,
    }


def render_layout(layout_path: Path, output_override: Path | None = None) -> Path:
    layout_path = layout_path.resolve()
    layout = load_layout_config(layout_path)
    project_path = resolve_path(layout_path.parent, layout["project"])
    project = LayoutProject(project_path)

    map_spec = layout["map"]
    map_width = map_spec["width"]
    map_height = map_spec["height"]
    background = parse_hex_colour(map_spec.get("background", "#00000000"))
    default_tileset = layout.get("default_tileset", project.default_tileset_id())

    handlers = _make_layer_op_handlers(default_tileset)
    layout_scene = build_layout_scene(layout, project, default_tileset=default_tileset)

    logical_layers: list[list[list[ResolvedTile | None]]] = []
    for layer_spec in layout_scene.layers:
        layer = new_layer(map_width, map_height)
        for op in layer_spec["ops"]:
            kind = op["kind"]
            handler = handlers.get(kind)
            if handler is None:
                raise ValueError(f"Unsupported layer operation: {kind}")
            handler(layer, project, op)
        logical_layers.append(layer)

    full_image = Image.new(
        "RGBA",
        (project.pixel_width_for_tiles(map_width), project.pixel_height_for_tiles(map_height)),
        background,
    )

    for layer in logical_layers:
        for row_index, row in enumerate(layer):
            for col_index, tile in enumerate(row):
                if tile is None:
                    continue
                composite_render_spec(
                    full_image,
                    project.render_spec_for_tile(tile),
                    anchor_left=project.pixel_x_for_tile(col_index),
                    anchor_top=project.pixel_y_for_tile(row_index),
                    background=background,
                )

    viewport: ViewportSpec = layout.get(
        "viewport",
        {"x": 0, "y": 0, "width": map_width, "height": map_height, "units": "tiles", "scale": 1},
    )
    units = viewport.get("units", "tiles")
    if units == "tiles":
        left = project.pixel_x_for_tile(int(viewport.get("x", 0)))
        top = project.pixel_y_for_tile(int(viewport.get("y", 0)))
        width_px = project.pixel_width_for_tiles(int(viewport.get("width", map_width)))
        height_px = project.pixel_height_for_tiles(int(viewport.get("height", map_height)))
    elif units == "pixels":
        left = int(viewport.get("x", 0))
        top = int(viewport.get("y", 0))
        width_px = int(viewport.get("width", project.pixel_width_for_tiles(map_width)))
        height_px = int(viewport.get("height", project.pixel_height_for_tiles(map_height)))
    else:
        raise ValueError(f"Unsupported viewport units: {units}")

    cropped = full_image.crop((left, top, left + width_px, top + height_px))
    scale = int(viewport.get("scale", layout.get("scale", 1)))
    if scale != 1:
        cropped = resize_nearest(cropped, (cropped.width * scale, cropped.height * scale))

    output_path = output_override or resolve_path(layout_path.parent, layout["output"])
    staged_path = create_staging_output_path(output_path)
    try:
        cropped.save(staged_path)
        return publish_staged_output(output_path, staged_path)
    finally:
        if staged_path.exists():
            staged_path.unlink()


def bootstrap_project(
    *,
    sheet_path: Path,
    output_path: Path,
    tile_width: int,
    tile_height: int,
    transparent: str,
    tileset_id: str | None,
) -> Path:
    sheet_path = sheet_path.resolve()
    output_path = output_path.resolve()
    image = Image.open(sheet_path).convert("RGBA")
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError(
            f"Sheet size {image.width}x{image.height} is not divisible by tile size {tile_width}x{tile_height}"
        )
    columns = image.width // tile_width
    rows = image.height // tile_height
    resolved_tileset_id = tileset_id or slugify_identifier(sheet_path.stem)
    relative_sheet = os.path.relpath(sheet_path, output_path.parent)
    data = {
        "grid": {"tile_width": tile_width, "tile_height": tile_height},
        "tilesets": {
            resolved_tileset_id: {
                "sheet": relative_sheet,
                "transparent": transparent,
                "regions": {"all": {"x": 0, "y": 0, "width": columns, "height": rows}},
            }
        },
        "patterns": {},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-based layout engine for sprite sheets / tilesets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render-layout", help="Render one layout JSON file.")
    render_parser.add_argument("layout", type=Path)
    render_parser.add_argument("--output", type=Path, default=None)

    inspect_layout_scene_parser = subparsers.add_parser(
        "inspect-layout-scene",
        help="Export the resolved scene runtime, including first-class entity instances, for one layout JSON file.",
    )
    inspect_layout_scene_parser.add_argument("layout", type=Path)
    inspect_layout_scene_parser.add_argument("--output", type=Path, default=None)

    render_all_parser = subparsers.add_parser("render-all", help="Render all layouts from a directory.")
    render_all_parser.add_argument("layouts_dir", nargs="?", type=Path, default=DEFAULT_LAYOUTS_DIR)

    tiled_parser = subparsers.add_parser("export-tiled-kit", help="Export the selected tileset as a Tiled-ready 8x8 kit.")
    tiled_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    tiled_parser.add_argument("--tileset", required=True)
    tiled_parser.add_argument("--output-dir", type=Path, default=None)

    public_pack_parser = subparsers.add_parser(
        "export-public-tile-pack",
        help="Export an engine-light annotated tile pack with public JSON/CSV metadata and PNG overviews.",
    )
    public_pack_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    public_pack_parser.add_argument("--tileset", required=True)
    public_pack_parser.add_argument("--output-dir", type=Path, default=None)
    public_pack_parser.add_argument("--slug", default=None)
    public_pack_parser.add_argument("--scale", type=int, default=8)

    semantic_query_parser = subparsers.add_parser(
        "query-semantic",
        help="Query the canonical semantic tile metadata for a project tileset.",
    )
    semantic_query_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    semantic_query_parser.add_argument("--tileset", required=True)
    semantic_query_parser.add_argument("--region", default=None)
    semantic_query_parser.add_argument("--category", default=None)
    semantic_query_parser.add_argument("--scene", default=None)
    semantic_query_parser.add_argument("--usage", default=None)
    semantic_query_parser.add_argument("--contrast", default=None)
    semantic_query_parser.add_argument("--temperature", default=None)
    semantic_query_parser.add_argument("--style", default=None)
    semantic_query_parser.add_argument("--orientation", default=None)
    semantic_query_parser.add_argument("--compose-group", default=None)
    semantic_query_parser.add_argument("--compose-role", default=None)
    semantic_query_parser.add_argument("--semantic", action="append", default=[])
    semantic_query_parser.add_argument("--tag", action="append", default=[])
    semantic_query_parser.add_argument("--walkable", choices=["true", "false"], default=None)
    semantic_query_parser.add_argument("--blocking", choices=["true", "false"], default=None)
    semantic_query_parser.add_argument("--alias-prefix", default=None)
    semantic_query_parser.add_argument("--limit", type=int, default=None)

    scaffold_parser = subparsers.add_parser(
        "scaffold-pattern",
        help="Emit a JSON pattern snippet from a selected rectangle of grid cells.",
    )
    scaffold_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    scaffold_parser.add_argument("--tileset", required=True)
    scaffold_parser.add_argument("--name", required=True)
    scaffold_parser.add_argument("--x", type=int, required=True)
    scaffold_parser.add_argument("--y", type=int, required=True)
    scaffold_parser.add_argument("--width", type=int, required=True)
    scaffold_parser.add_argument("--height", type=int, required=True)
    scaffold_parser.add_argument("--trim", action="store_true")

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-project",
        help="Create a starter project spec from any grid-aligned spritesheet.",
    )
    bootstrap_parser.add_argument("sheet", type=Path)
    bootstrap_parser.add_argument("output", type=Path)
    bootstrap_parser.add_argument("--tile-width", type=int, default=8)
    bootstrap_parser.add_argument("--tile-height", type=int, default=8)
    bootstrap_parser.add_argument("--transparent", default="top_left", choices=["top_left", "none"])
    bootstrap_parser.add_argument("--tileset-id", default=None)

    bootstrap_family_parser = subparsers.add_parser(
        "bootstrap-family",
        help="Create a starter tile-family package from any grid-aligned spritesheet.",
    )
    bootstrap_family_parser.add_argument("sheet", type=Path)
    bootstrap_family_parser.add_argument("output_dir", type=Path)
    bootstrap_family_parser.add_argument("--tile-width", type=int, default=8)
    bootstrap_family_parser.add_argument("--tile-height", type=int, default=8)
    bootstrap_family_parser.add_argument("--transparent", default="top_left", choices=["top_left", "none"])
    bootstrap_family_parser.add_argument("--family-id", default=None)
    bootstrap_family_parser.add_argument("--variant-id", default="default")

    args = parser.parse_args()

    if args.command == "render-layout":
        print(render_layout(args.layout, args.output))
    elif args.command == "inspect-layout-scene":
        output_path = args.output or (DEFAULT_SCENE_RUNTIME_DIR / f"{args.layout.stem}.scene_runtime.json")
        print(export_layout_scene_runtime(args.layout, output_path))
    elif args.command == "render-all":
        for layout_path in sorted(args.layouts_dir.glob("*.json")):
            print(render_layout(layout_path))
    elif args.command == "export-tiled-kit":
        output_dir = args.output_dir or (DEFAULT_TILED_KIT_DIR / args.tileset)
        print(export_tiled_kit(args.project, args.tileset, output_dir))
    elif args.command == "export-public-tile-pack":
        output_dir = args.output_dir
        if output_dir is None:
            slug = args.slug or slugify_identifier(args.tileset)
            output_dir = DEFAULT_PUBLIC_TILE_PACK_DIR / slug
        print(export_public_tile_pack(args.project, args.tileset, output_dir, scale=args.scale))
    elif args.command == "query-semantic":
        walkable = None if args.walkable is None else args.walkable == "true"
        blocking = None if args.blocking is None else args.blocking == "true"
        print(
            json.dumps(
                query_semantic_catalog(
                    args.project,
                    args.tileset,
                    region=args.region,
                    category=args.category,
                    scene=args.scene,
                    usage=args.usage,
                    contrast=args.contrast,
                    temperature=args.temperature,
                    style=args.style,
                    orientation=args.orientation,
                    compose_group=args.compose_group,
                    compose_role=args.compose_role,
                    semantics_all=args.semantic,
                    tags_all=args.tag,
                    walkable=walkable,
                    blocking=blocking,
                    alias_prefix=args.alias_prefix,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
    elif args.command == "scaffold-pattern":
        print(
            json.dumps(
                {
                    args.name: json.loads(
                        scaffold_pattern(
                            args.project,
                            tileset_id=args.tileset,
                            name=args.name,
                            x=args.x,
                            y=args.y,
                            width=args.width,
                            height=args.height,
                            trim=args.trim,
                        )
                    )
                },
                indent=2,
            )
        )
    elif args.command == "bootstrap-project":
        print(
            bootstrap_project(
                sheet_path=args.sheet,
                output_path=args.output,
                tile_width=args.tile_width,
                tile_height=args.tile_height,
                transparent=args.transparent,
                tileset_id=args.tileset_id,
            )
        )
    elif args.command == "bootstrap-family":
        family_id = args.family_id or slugify_identifier(args.sheet.stem)
        print(
            bootstrap_tile_family(
                sheet_path=args.sheet,
                output_dir=args.output_dir,
                tile_width=args.tile_width,
                tile_height=args.tile_height,
                transparent=args.transparent,
                family_id=family_id,
                variant_id=args.variant_id,
            )
        )


if __name__ == "__main__":
    main()
