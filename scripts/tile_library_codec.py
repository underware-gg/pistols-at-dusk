#!/usr/bin/env python3
"""Runtime tile-library asset codec.

Serializes and deserializes the stable runtime ``TileLibraryUnit`` model.
This module is runtime-layer code: it depends on ``tile_library`` records and
shared manifest helpers, and it must not import ingest modules.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Mapping, Protocol, TypeVar, cast

from _manifest_utils import GridBounds, as_int, require_list, require_mapping
from tile_metadata import ModuleContextValue, RenderTraits
from tile_library import (
    CellContentInset,
    CompositeTileCell,
    CompositeTileRecord,
    Construction,
    ConstructionAttachmentSet,
    ConstructionAttachmentVariant,
    FixedConstruction,
    FixedConstructionSeamOverride,
    FixedSeamOverrideSide,
    FrameCornerSlot,
    FrameSlot,
    ParametricFrameConstruction,
    ParametricRunConstruction,
    PlaceableRef,
    SheetCell,
    TileClusterRecord,
    TileFamilyVariant,
    TileGenesis,
    TileLibraryPromotedMetadata,
    TileLibraryUnit,
    TileRecord,
    attachment_sets_by_target,
    index_tiles_by_sheet_cell,
)


RUNTIME_LIBRARY_SCHEMA_VERSION = 1


def _as_str(value: object, *, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _as_int(value: object, *, context: str) -> int:
    return as_int(value, context=context)


def _as_bool(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _as_optional_str(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, context=context)


def _as_optional_bool(value: object, *, context: str) -> bool | None:
    if value is None:
        return None
    return _as_bool(value, context=context)


def _as_optional_int(value: object, *, context: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, context=context)


def _as_string_tuple(value: object, *, context: str) -> tuple[str, ...]:
    return tuple(_as_str(item, context=f"{context}[{index}]") for index, item in enumerate(require_list(value, context=context)))


class _RecordWithId(Protocol):
    @property
    def id(self) -> str:
        ...


_Record_co = TypeVar("_Record_co", bound=_RecordWithId, covariant=True)
_Record = TypeVar("_Record", bound=_RecordWithId)


class _RecordFactory(Protocol[_Record_co]):
    def __call__(self, raw: object, *, context: str) -> _Record_co:
        ...


def _records_by_id(
    raw: object,
    factory: _RecordFactory[_Record],
    *,
    context: str,
) -> dict[str, _Record]:
    records: dict[str, _Record] = {}
    for index, raw_record in enumerate(require_list(raw, context=context)):
        record = factory(raw_record, context=f"{context}[{index}]")
        if record.id in records:
            raise ValueError(f"{context}[{index}] duplicates id {record.id!r}")
        records[record.id] = record
    return records


def _cell_content_inset_payload(inset: CellContentInset | None) -> dict[str, object] | None:
    if inset is None:
        return None
    return inset.to_payload()


def _cell_content_inset_from_payload(raw: object, *, context: str) -> CellContentInset | None:
    if raw is None:
        return None
    return CellContentInset.from_mapping(raw, context=context)


def _module_context_payload(module_context: Mapping[str, ModuleContextValue]) -> dict[str, object]:
    return {
        axis_id: {
            "axis_id": value.axis_id,
            "value_id": value.value_id,
            "label": value.label,
            "notes": value.notes,
        }
        for axis_id, value in sorted(module_context.items())
    }


def _module_context_from_payload(raw: object, *, context: str) -> dict[str, ModuleContextValue]:
    mapping = require_mapping(raw, context=context)
    values: dict[str, ModuleContextValue] = {}
    for axis_id, raw_value in mapping.items():
        value_mapping = require_mapping(raw_value, context=f"{context}.{axis_id}")
        values[axis_id] = ModuleContextValue(
            axis_id=_as_str(value_mapping.get("axis_id"), context=f"{context}.{axis_id}.axis_id"),
            value_id=_as_str(value_mapping.get("value_id"), context=f"{context}.{axis_id}.value_id"),
            label=_as_optional_str(value_mapping.get("label"), context=f"{context}.{axis_id}.label"),
            notes=_as_optional_str(value_mapping.get("notes"), context=f"{context}.{axis_id}.notes"),
        )
    return values


def _render_traits_payload(render_traits: RenderTraits) -> dict[str, object]:
    return {
        "occupancy_style": render_traits.occupancy_style,
        "gutter_policy": render_traits.gutter_policy,
        "background_treatment": render_traits.background_treatment,
        "alignment_origin": render_traits.alignment_origin,
        "occlusion_mode": render_traits.occlusion_mode,
    }


def _render_traits_from_payload(raw: object, *, context: str) -> RenderTraits:
    mapping = require_mapping(raw, context=context)
    return RenderTraits(
        occupancy_style=_as_optional_str(mapping.get("occupancy_style"), context=f"{context}.occupancy_style"),
        gutter_policy=_as_optional_str(mapping.get("gutter_policy"), context=f"{context}.gutter_policy"),
        background_treatment=_as_optional_str(
            mapping.get("background_treatment"),
            context=f"{context}.background_treatment",
        ),
        alignment_origin=_as_optional_str(mapping.get("alignment_origin"), context=f"{context}.alignment_origin"),
        occlusion_mode=_as_optional_str(mapping.get("occlusion_mode"), context=f"{context}.occlusion_mode"),
    )


def _promoted_metadata_payload(metadata: TileLibraryPromotedMetadata) -> dict[str, object]:
    return {
        "source_pack_id": metadata.source_pack_id,
        "source_tileset_id": metadata.source_tileset_id,
        "source_tilesheet_id": metadata.source_tilesheet_id,
        "module_context": _module_context_payload(metadata.module_context),
        "render_traits": _render_traits_payload(metadata.render_traits),
        "documented_hints": list(metadata.documented_hints),
    }


def _promoted_metadata_from_payload(raw: object, *, context: str) -> TileLibraryPromotedMetadata:
    mapping = require_mapping(raw, context=context)
    return TileLibraryPromotedMetadata(
        source_pack_id=_as_optional_str(mapping.get("source_pack_id"), context=f"{context}.source_pack_id"),
        source_tileset_id=_as_optional_str(mapping.get("source_tileset_id"), context=f"{context}.source_tileset_id"),
        source_tilesheet_id=_as_optional_str(
            mapping.get("source_tilesheet_id"),
            context=f"{context}.source_tilesheet_id",
        ),
        module_context=_module_context_from_payload(mapping.get("module_context", {}), context=f"{context}.module_context"),
        render_traits=_render_traits_from_payload(mapping.get("render_traits", {}), context=f"{context}.render_traits"),
        documented_hints=_as_string_tuple(mapping.get("documented_hints", []), context=f"{context}.documented_hints"),
    )


def _tile_genesis_payload(genesis: TileGenesis) -> dict[str, object]:
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


def _tile_genesis_from_payload(raw: object, *, context: str) -> TileGenesis:
    mapping = require_mapping(raw, context=context)
    sheet_col_raw = mapping.get("sheet_col")
    sheet_row_raw = mapping.get("sheet_row")
    return TileGenesis(
        kind=_as_str(mapping.get("kind"), context=f"{context}.kind"),
        sheet_col=None if sheet_col_raw is None else _as_int(sheet_col_raw, context=f"{context}.sheet_col"),
        sheet_row=None if sheet_row_raw is None else _as_int(sheet_row_raw, context=f"{context}.sheet_row"),
        source_group=_as_optional_str(mapping.get("source_group"), context=f"{context}.source_group"),
        cluster_ids=_as_string_tuple(mapping.get("cluster_ids", []), context=f"{context}.cluster_ids"),
        derivation=_as_optional_str(mapping.get("derivation"), context=f"{context}.derivation"),
        parent_construction_ids=_as_string_tuple(
            mapping.get("parent_construction_ids", []),
            context=f"{context}.parent_construction_ids",
        ),
        parent_tile_ids=_as_string_tuple(mapping.get("parent_tile_ids", []), context=f"{context}.parent_tile_ids"),
        authored_notes=_as_optional_str(mapping.get("authored_notes"), context=f"{context}.authored_notes"),
    )


def _seam_profiles_payload(seam_profiles: dict[str, tuple[bool, ...]] | None) -> dict[str, object] | None:
    if seam_profiles is None:
        return None
    return {side: list(values) for side, values in sorted(seam_profiles.items())}


def _seam_profiles_from_payload(raw: object, *, context: str) -> dict[str, tuple[bool, ...]] | None:
    if raw is None:
        return None
    mapping = require_mapping(raw, context=context)
    profiles: dict[str, tuple[bool, ...]] = {}
    for side, raw_values in mapping.items():
        values = require_list(raw_values, context=f"{context}.{side}")
        profiles[side] = tuple(_as_bool(value, context=f"{context}.{side}[{index}]") for index, value in enumerate(values))
    return profiles


def _sheet_cell_payload(cell: SheetCell) -> dict[str, object]:
    return {"col": cell.col, "row": cell.row}


def _sheet_cell_from_payload(raw: object, *, context: str) -> SheetCell:
    mapping = require_mapping(raw, context=context)
    return SheetCell(
        col=_as_int(mapping.get("col"), context=f"{context}.col"),
        row=_as_int(mapping.get("row"), context=f"{context}.row"),
    )


def _tile_record_payload(tile: TileRecord) -> dict[str, object]:
    return {
        "id": tile.id,
        "family_id": tile.family_id,
        "layer": tile.layer,
        "category": tile.category,
        "transparent": tile.transparent,
        "tags": list(tile.tags),
        "genesis": _tile_genesis_payload(tile.genesis),
        "exact_duplicate_of": tile.exact_duplicate_of,
        "variant_assets": {variant_id: address for variant_id, address in sorted(tile.variant_assets.items())},
        "variant_atlas_cells": {
            variant_id: _sheet_cell_payload(cell)
            for variant_id, cell in sorted(tile.variant_atlas_cells.items())
        },
        "aliases": list(tile.aliases),
        "walkable": tile.walkable,
        "blocking": tile.blocking,
        "scenes": list(tile.scenes),
        "semantics": list(tile.semantics),
        "motifs": list(tile.motifs),
        "noise": tile.noise,
        "contrast": tile.contrast,
        "temperature": tile.temperature,
        "usage": tile.usage,
        "style": tile.style,
        "overlay": tile.overlay,
        "footprint": tile.footprint,
        "orientation": tile.orientation,
        "facing": tile.facing,
        "pose": tile.pose,
        "compose_group": tile.compose_group,
        "compose_role": tile.compose_role,
        "state_group": tile.state_group,
        "state_role": tile.state_role,
        "animation_group": tile.animation_group,
        "animation_frame": tile.animation_frame,
        "animation_frame_count": tile.animation_frame_count,
        "connects_on": list(tile.connects_on),
        "seam_profiles": _seam_profiles_payload(tile.seam_profiles),
        "cell_content_inset": _cell_content_inset_payload(tile.cell_content_inset),
        "requires_exposed_on": list(tile.requires_exposed_on),
        "affordances": list(tile.affordances),
        "alt_uses": list(tile.alt_uses),
        "meaning": tile.meaning,
        "meaning_confidence": tile.meaning_confidence,
        "source_notes": tile.source_notes,
    }


def _tile_record_from_payload(raw: object, *, context: str) -> TileRecord:
    mapping = require_mapping(raw, context=context)
    return TileRecord(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        family_id=_as_str(mapping.get("family_id"), context=f"{context}.family_id"),
        layer=_as_str(mapping.get("layer"), context=f"{context}.layer"),
        category=_as_str(mapping.get("category"), context=f"{context}.category"),
        transparent=_as_bool(mapping.get("transparent"), context=f"{context}.transparent"),
        tags=_as_string_tuple(mapping.get("tags", []), context=f"{context}.tags"),
        genesis=_tile_genesis_from_payload(mapping.get("genesis"), context=f"{context}.genesis"),
        exact_duplicate_of=_as_optional_str(mapping.get("exact_duplicate_of"), context=f"{context}.exact_duplicate_of"),
        variant_assets={
            _as_str(variant_id, context=f"{context}.variant_assets key"): _as_str(
                address,
                context=f"{context}.variant_assets.{variant_id}",
            )
            for variant_id, address in require_mapping(
                mapping.get("variant_assets", {}),
                context=f"{context}.variant_assets",
            ).items()
        },
        variant_atlas_cells={
            _as_str(variant_id, context=f"{context}.variant_atlas_cells key"): _sheet_cell_from_payload(
                cell,
                context=f"{context}.variant_atlas_cells.{variant_id}",
            )
            for variant_id, cell in require_mapping(
                mapping.get("variant_atlas_cells", {}),
                context=f"{context}.variant_atlas_cells",
            ).items()
        },
        aliases=_as_string_tuple(mapping.get("aliases", []), context=f"{context}.aliases"),
        walkable=_as_optional_bool(mapping.get("walkable"), context=f"{context}.walkable"),
        blocking=_as_optional_bool(mapping.get("blocking"), context=f"{context}.blocking"),
        scenes=_as_string_tuple(mapping.get("scenes", []), context=f"{context}.scenes"),
        semantics=_as_string_tuple(mapping.get("semantics", []), context=f"{context}.semantics"),
        motifs=_as_string_tuple(mapping.get("motifs", []), context=f"{context}.motifs"),
        noise=_as_optional_str(mapping.get("noise"), context=f"{context}.noise"),
        contrast=_as_optional_str(mapping.get("contrast"), context=f"{context}.contrast"),
        temperature=_as_optional_str(mapping.get("temperature"), context=f"{context}.temperature"),
        usage=_as_optional_str(mapping.get("usage"), context=f"{context}.usage"),
        style=_as_optional_str(mapping.get("style"), context=f"{context}.style"),
        overlay=_as_optional_str(mapping.get("overlay"), context=f"{context}.overlay"),
        footprint=_as_optional_str(mapping.get("footprint"), context=f"{context}.footprint"),
        orientation=_as_optional_str(mapping.get("orientation"), context=f"{context}.orientation"),
        facing=_as_optional_str(mapping.get("facing"), context=f"{context}.facing"),
        pose=_as_optional_str(mapping.get("pose"), context=f"{context}.pose"),
        compose_group=_as_optional_str(mapping.get("compose_group"), context=f"{context}.compose_group"),
        compose_role=_as_optional_str(mapping.get("compose_role"), context=f"{context}.compose_role"),
        state_group=_as_optional_str(mapping.get("state_group"), context=f"{context}.state_group"),
        state_role=_as_optional_str(mapping.get("state_role"), context=f"{context}.state_role"),
        animation_group=_as_optional_str(mapping.get("animation_group"), context=f"{context}.animation_group"),
        animation_frame=_as_optional_int(mapping.get("animation_frame"), context=f"{context}.animation_frame"),
        animation_frame_count=_as_optional_int(
            mapping.get("animation_frame_count"),
            context=f"{context}.animation_frame_count",
        ),
        connects_on=_as_string_tuple(mapping.get("connects_on", []), context=f"{context}.connects_on"),
        seam_profiles=_seam_profiles_from_payload(mapping.get("seam_profiles"), context=f"{context}.seam_profiles"),
        cell_content_inset=_cell_content_inset_from_payload(
            mapping.get("cell_content_inset"),
            context=f"{context}.cell_content_inset",
        ),
        requires_exposed_on=_as_string_tuple(
            mapping.get("requires_exposed_on", []),
            context=f"{context}.requires_exposed_on",
        ),
        affordances=_as_string_tuple(mapping.get("affordances", []), context=f"{context}.affordances"),
        alt_uses=_as_string_tuple(mapping.get("alt_uses", []), context=f"{context}.alt_uses"),
        meaning=_as_optional_str(mapping.get("meaning"), context=f"{context}.meaning"),
        meaning_confidence=_as_optional_str(mapping.get("meaning_confidence"), context=f"{context}.meaning_confidence"),
        source_notes=_as_optional_str(mapping.get("source_notes"), context=f"{context}.source_notes"),
    )


def _tile_id(tile: TileRecord | None) -> str | None:
    return None if tile is None else tile.id


def _tile_from_id(tiles: Mapping[str, TileRecord], tile_id: str, *, context: str) -> TileRecord:
    tile = tiles.get(tile_id)
    if tile is None:
        raise ValueError(f"{context} references unknown tile {tile_id!r}")
    return tile


def _tile_grid_payload(cells: tuple[tuple[TileRecord | None, ...], ...]) -> list[list[str | None]]:
    return [[_tile_id(tile) for tile in row] for row in cells]


def _tile_grid_from_payload(
    raw: object,
    *,
    tiles: Mapping[str, TileRecord],
    context: str,
) -> tuple[tuple[TileRecord | None, ...], ...]:
    rows: list[tuple[TileRecord | None, ...]] = []
    for row_index, raw_row in enumerate(require_list(raw, context=context)):
        cells: list[TileRecord | None] = []
        for col_index, raw_cell in enumerate(require_list(raw_row, context=f"{context}[{row_index}]")):
            if raw_cell is None:
                cells.append(None)
            else:
                tile_id = _as_str(raw_cell, context=f"{context}[{row_index}][{col_index}]")
                cells.append(_tile_from_id(tiles, tile_id, context=f"{context}[{row_index}][{col_index}]"))
        rows.append(tuple(cells))
    return tuple(rows)


def _fixed_seam_override_payload(override: FixedConstructionSeamOverride) -> dict[str, object]:
    return {
        "cell": {"x": override.x, "y": override.y},
        "side": override.side,
        "reason": override.reason,
    }


def _fixed_seam_override_from_payload(raw: object, *, context: str) -> FixedConstructionSeamOverride:
    mapping = require_mapping(raw, context=context)
    cell = require_mapping(mapping.get("cell"), context=f"{context}.cell")
    return FixedConstructionSeamOverride(
        x=_as_int(cell.get("x"), context=f"{context}.cell.x"),
        y=_as_int(cell.get("y"), context=f"{context}.cell.y"),
        side=cast(FixedSeamOverrideSide, _as_str(mapping.get("side"), context=f"{context}.side")),
        reason=_as_str(mapping.get("reason"), context=f"{context}.reason"),
    )


def _frame_slot_payload(slot: FrameSlot) -> dict[str, object]:
    return {
        "tile_id": slot.tile.id,
        "fill_mode": slot.fill_mode,
        "flip_x": slot.flip_x,
        "flip_y": slot.flip_y,
    }


def _frame_slot_from_payload(raw: object, *, tiles: Mapping[str, TileRecord], context: str) -> FrameSlot:
    mapping = require_mapping(raw, context=context)
    tile_id = _as_str(mapping.get("tile_id"), context=f"{context}.tile_id")
    return FrameSlot(
        tile=_tile_from_id(tiles, tile_id, context=context),
        fill_mode=_as_str(mapping.get("fill_mode", "repeat"), context=f"{context}.fill_mode"),
        flip_x=_as_bool(mapping.get("flip_x", False), context=f"{context}.flip_x"),
        flip_y=_as_bool(mapping.get("flip_y", False), context=f"{context}.flip_y"),
    )


def _frame_corner_payload(corner: FrameCornerSlot) -> dict[str, object]:
    return {
        "cells": _tile_grid_payload(corner.cells),
        "flip_x": corner.flip_x,
        "flip_y": corner.flip_y,
    }


def _frame_corner_from_payload(raw: object, *, tiles: Mapping[str, TileRecord], context: str) -> FrameCornerSlot:
    mapping = require_mapping(raw, context=context)
    return FrameCornerSlot(
        cells=_tile_grid_from_payload(mapping.get("cells"), tiles=tiles, context=f"{context}.cells"),
        flip_x=_as_bool(mapping.get("flip_x", False), context=f"{context}.flip_x"),
        flip_y=_as_bool(mapping.get("flip_y", False), context=f"{context}.flip_y"),
    )


def _construction_payload(construction: Construction) -> dict[str, object]:
    if isinstance(construction, ParametricRunConstruction):
        return {
            "kind": "parametric_run",
            "id": construction.id,
            "collection_id": construction.collection_id,
            "axis": construction.axis,
            "length_param": construction.length_param,
            "start_tile_id": construction.start_tile.id,
            "repeat_tile_id": construction.repeat_tile.id,
            "end_tile_id": construction.end_tile.id,
            "expose_as_entity": construction.expose_as_entity,
        }
    if isinstance(construction, ParametricFrameConstruction):
        payload: dict[str, object] = {
            "kind": "parametric_frame",
            "id": construction.id,
            "collection_id": construction.collection_id,
            "corners": {
                key: _frame_corner_payload(value)
                for key, value in sorted(construction.corners.items())
            },
            "edges": {
                key: _frame_slot_payload(value)
                for key, value in sorted(construction.edges.items())
            },
            "fill": None if construction.fill is None else _frame_slot_payload(construction.fill),
            "min_width": construction.min_width,
            "min_height": construction.min_height,
            "width_param": construction.width_param,
            "height_param": construction.height_param,
            "expose_as_entity": construction.expose_as_entity,
        }
        return payload
    return {
        "kind": "fixed",
        "id": construction.id,
        "collection_id": construction.collection_id,
        "cells": _tile_grid_payload(construction.cells),
        "seam_overrides": [_fixed_seam_override_payload(override) for override in construction.seam_overrides],
        "expose_as_entity": construction.expose_as_entity,
    }


def _construction_from_payload(
    raw: object,
    *,
    tiles: Mapping[str, TileRecord],
    context: str,
) -> Construction:
    mapping = require_mapping(raw, context=context)
    kind = _as_str(mapping.get("kind"), context=f"{context}.kind")
    construction_id = _as_str(mapping.get("id"), context=f"{context}.id")
    collection_id = _as_str(mapping.get("collection_id"), context=f"{context}.collection_id")
    expose_as_entity = _as_bool(mapping.get("expose_as_entity", True), context=f"{context}.expose_as_entity")
    if kind == "parametric_run":
        return ParametricRunConstruction(
            id=construction_id,
            collection_id=collection_id,
            axis=cast(Literal["x", "y"], _as_str(mapping.get("axis"), context=f"{context}.axis")),
            length_param=_as_str(mapping.get("length_param"), context=f"{context}.length_param"),
            start_tile=_tile_from_id(
                tiles,
                _as_str(mapping.get("start_tile_id"), context=f"{context}.start_tile_id"),
                context=f"{context}.start_tile_id",
            ),
            repeat_tile=_tile_from_id(
                tiles,
                _as_str(mapping.get("repeat_tile_id"), context=f"{context}.repeat_tile_id"),
                context=f"{context}.repeat_tile_id",
            ),
            end_tile=_tile_from_id(
                tiles,
                _as_str(mapping.get("end_tile_id"), context=f"{context}.end_tile_id"),
                context=f"{context}.end_tile_id",
            ),
            expose_as_entity=expose_as_entity,
        )
    if kind == "parametric_frame":
        corners = {
            key: _frame_corner_from_payload(value, tiles=tiles, context=f"{context}.corners.{key}")
            for key, value in require_mapping(mapping.get("corners", {}), context=f"{context}.corners").items()
        }
        edges = {
            key: _frame_slot_from_payload(value, tiles=tiles, context=f"{context}.edges.{key}")
            for key, value in require_mapping(mapping.get("edges", {}), context=f"{context}.edges").items()
        }
        fill_raw = mapping.get("fill")
        return ParametricFrameConstruction(
            id=construction_id,
            collection_id=collection_id,
            corners=corners,
            edges=edges,
            fill=None if fill_raw is None else _frame_slot_from_payload(fill_raw, tiles=tiles, context=f"{context}.fill"),
            min_width=_as_int(mapping.get("min_width", 2), context=f"{context}.min_width"),
            min_height=_as_int(mapping.get("min_height", 2), context=f"{context}.min_height"),
            width_param=_as_str(mapping.get("width_param", "width"), context=f"{context}.width_param"),
            height_param=_as_str(mapping.get("height_param", "height"), context=f"{context}.height_param"),
            expose_as_entity=expose_as_entity,
        )
    if kind != "fixed":
        raise ValueError(f"{context}.kind must be fixed, parametric_run, or parametric_frame")
    return FixedConstruction(
        id=construction_id,
        collection_id=collection_id,
        cells=_tile_grid_from_payload(mapping.get("cells"), tiles=tiles, context=f"{context}.cells"),
        seam_overrides=tuple(
            _fixed_seam_override_from_payload(value, context=f"{context}.seam_overrides[{index}]")
            for index, value in enumerate(require_list(mapping.get("seam_overrides", []), context=f"{context}.seam_overrides"))
        ),
        expose_as_entity=expose_as_entity,
    )


def _composite_tile_payload(composite: CompositeTileRecord) -> dict[str, object]:
    return {
        "id": composite.id,
        "family_id": composite.family_id,
        "collection_id": composite.collection_id,
        "tags": list(composite.tags),
        "expose_as_entity": composite.expose_as_entity,
        "placement_anchor": composite.placement_anchor,
        "cells": [
            [
                None if cell is None else {"tile_id": cell.tile.id, "role": cell.role}
                for cell in row
            ]
            for row in composite.cells
        ],
    }


def _composite_tile_from_payload(
    raw: object,
    *,
    tiles: Mapping[str, TileRecord],
    context: str,
) -> CompositeTileRecord:
    mapping = require_mapping(raw, context=context)
    rows: list[tuple[CompositeTileCell | None, ...]] = []
    for row_index, raw_row in enumerate(require_list(mapping.get("cells"), context=f"{context}.cells")):
        row: list[CompositeTileCell | None] = []
        for col_index, raw_cell in enumerate(require_list(raw_row, context=f"{context}.cells[{row_index}]")):
            if raw_cell is None:
                row.append(None)
                continue
            cell_mapping = require_mapping(raw_cell, context=f"{context}.cells[{row_index}][{col_index}]")
            tile_id = _as_str(cell_mapping.get("tile_id"), context=f"{context}.cells[{row_index}][{col_index}].tile_id")
            row.append(
                CompositeTileCell(
                    tile=_tile_from_id(tiles, tile_id, context=f"{context}.cells[{row_index}][{col_index}]"),
                    x=col_index,
                    y=row_index,
                    role=_as_optional_str(cell_mapping.get("role"), context=f"{context}.cells[{row_index}][{col_index}].role"),
                )
            )
        rows.append(tuple(row))
    return CompositeTileRecord(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        family_id=_as_str(mapping.get("family_id"), context=f"{context}.family_id"),
        collection_id=_as_str(mapping.get("collection_id"), context=f"{context}.collection_id"),
        cells=tuple(rows),
        tags=_as_string_tuple(mapping.get("tags", []), context=f"{context}.tags"),
        expose_as_entity=_as_bool(mapping.get("expose_as_entity", True), context=f"{context}.expose_as_entity"),
        placement_anchor=cast(Literal["top_left"], _as_str(mapping.get("placement_anchor", "top_left"), context=f"{context}.placement_anchor")),
    )


def _attachment_variant_payload(variant: ConstructionAttachmentVariant) -> dict[str, object]:
    return {
        "id": variant.id,
        "placeable": variant.placeable_ref.to_payload(),
        "label": variant.label,
        "notes": variant.notes,
    }


def _attachment_variant_from_payload(raw: object, *, context: str) -> ConstructionAttachmentVariant:
    mapping = require_mapping(raw, context=context)
    placeable_ref = PlaceableRef.from_mapping(mapping.get("placeable"), context=f"{context}.placeable")
    return ConstructionAttachmentVariant(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        placeable_kind=placeable_ref.kind,
        placeable_id=placeable_ref.id,
        label=_as_optional_str(mapping.get("label"), context=f"{context}.label"),
        notes=_as_optional_str(mapping.get("notes"), context=f"{context}.notes"),
    )


def _attachment_set_payload(attachment_set: ConstructionAttachmentSet) -> dict[str, object]:
    return {
        "id": attachment_set.id,
        "param": attachment_set.param,
        "canvas": attachment_set.canvas.to_payload(),
        "target_placeables": [target_ref.to_payload() for target_ref in attachment_set.target_placeable_refs],
        "required": attachment_set.required,
        "default_variant_id": attachment_set.default_variant_id,
        "label": attachment_set.label,
        "notes": attachment_set.notes,
        "variants": [
            _attachment_variant_payload(variant)
            for variant in sorted(attachment_set.variants.values(), key=lambda item: item.id)
        ],
    }


def _attachment_set_from_payload(raw: object, *, context: str) -> ConstructionAttachmentSet:
    mapping = require_mapping(raw, context=context)
    variants = _records_by_id(
        mapping.get("variants"),
        _attachment_variant_from_payload,
        context=f"{context}.variants",
    )
    return ConstructionAttachmentSet(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        param=_as_str(mapping.get("param"), context=f"{context}.param"),
        canvas=GridBounds.from_payload(mapping.get("canvas"), context=f"{context}.canvas"),
        variants=variants,
        target_placeable_refs=tuple(
            PlaceableRef.from_mapping(raw_ref, context=f"{context}.target_placeables[{index}]")
            for index, raw_ref in enumerate(require_list(mapping.get("target_placeables"), context=f"{context}.target_placeables"))
        ),
        required=_as_bool(mapping.get("required", False), context=f"{context}.required"),
        default_variant_id=_as_optional_str(mapping.get("default_variant_id"), context=f"{context}.default_variant_id"),
        label=_as_optional_str(mapping.get("label"), context=f"{context}.label"),
        notes=_as_optional_str(mapping.get("notes"), context=f"{context}.notes"),
    )


def _cluster_payload(cluster: TileClusterRecord) -> dict[str, object]:
    return {
        "id": cluster.id,
        "scope": cluster.scope,
        "members": list(cluster.members),
        "kind_guess": cluster.kind_guess,
        "evidence": list(cluster.evidence),
        "source_label": cluster.source_label,
        "source_notes": cluster.source_notes,
    }


def _cluster_from_payload(raw: object, *, context: str) -> TileClusterRecord:
    mapping = require_mapping(raw, context=context)
    return TileClusterRecord(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        scope=_as_str(mapping.get("scope"), context=f"{context}.scope"),
        members=_as_string_tuple(mapping.get("members", []), context=f"{context}.members"),
        kind_guess=_as_optional_str(mapping.get("kind_guess"), context=f"{context}.kind_guess"),
        evidence=_as_string_tuple(mapping.get("evidence", []), context=f"{context}.evidence"),
        source_label=_as_optional_str(mapping.get("source_label"), context=f"{context}.source_label"),
        source_notes=_as_optional_str(mapping.get("source_notes"), context=f"{context}.source_notes"),
    )


def _variant_payload(variant: TileFamilyVariant) -> dict[str, object]:
    return {
        "id": variant.id,
        "transparent_mode": variant.transparent_mode,
        "palette_family": variant.palette_family,
        "colorway": variant.colorway,
        "background_mode": variant.background_mode,
        "notes": variant.notes,
        "grid_columns": variant.grid_columns,
        "grid_rows": variant.grid_rows,
        "atlas_path": None if variant.atlas_path is None else str(variant.atlas_path),
        "atlas_columns": variant.atlas_columns,
        "atlas_rows": variant.atlas_rows,
    }


def _variant_from_payload(raw: object, *, context: str) -> TileFamilyVariant:
    mapping = require_mapping(raw, context=context)
    grid_columns = _as_int(mapping.get("grid_columns"), context=f"{context}.grid_columns")
    grid_rows = _as_int(mapping.get("grid_rows"), context=f"{context}.grid_rows")
    atlas_path = Path(_as_str(mapping.get("atlas_path"), context=f"{context}.atlas_path"))
    atlas_columns = _as_int(mapping.get("atlas_columns"), context=f"{context}.atlas_columns")
    atlas_rows = _as_int(mapping.get("atlas_rows"), context=f"{context}.atlas_rows")
    return TileFamilyVariant(
        id=_as_str(mapping.get("id"), context=f"{context}.id"),
        sheet_path=None,
        transparent_mode=_as_str(mapping.get("transparent_mode"), context=f"{context}.transparent_mode"),
        palette_family=_as_optional_str(mapping.get("palette_family"), context=f"{context}.palette_family"),
        colorway=_as_optional_str(mapping.get("colorway"), context=f"{context}.colorway"),
        background_mode=_as_optional_str(mapping.get("background_mode"), context=f"{context}.background_mode"),
        notes=_as_optional_str(mapping.get("notes"), context=f"{context}.notes"),
        grid_columns=grid_columns,
        grid_rows=grid_rows,
        atlas_path=atlas_path,
        atlas_columns=atlas_columns,
        atlas_rows=atlas_rows,
    )


def _require_variant_coverage(
    variant_ids: set[str],
    declared_variant_ids: set[str],
    *,
    tile_id: str,
    field_name: str,
) -> None:
    missing_variant_ids = sorted(declared_variant_ids - variant_ids)
    unknown_variant_ids = sorted(variant_ids - declared_variant_ids)
    if missing_variant_ids:
        raise ValueError(
            f"runtime library.tiles.{tile_id}.{field_name} is missing variants: "
            f"{', '.join(missing_variant_ids)}"
        )
    if unknown_variant_ids:
        raise ValueError(
            f"runtime library.tiles.{tile_id}.{field_name} references unknown variants: "
            f"{', '.join(unknown_variant_ids)}"
        )


def tile_library_unit_to_payload(unit: TileLibraryUnit) -> dict[str, object]:
    return {
        "schema_version": RUNTIME_LIBRARY_SCHEMA_VERSION,
        "family": {
            "family_id": unit.family_id,
            "root": str(unit.root),
            "tile_width": unit.tile_width,
            "tile_height": unit.tile_height,
            "render_step_width": unit.render_step_width,
            "render_step_height": unit.render_step_height,
            "default_variant_id": unit.default_variant_id,
            "runtime_flippable": unit.runtime_flippable,
            "promoted_metadata": _promoted_metadata_payload(unit.promoted_metadata),
        },
        "variants": [_variant_payload(variant) for variant in sorted(unit.variants.values(), key=lambda item: item.id)],
        "clusters": [_cluster_payload(cluster) for cluster in sorted(unit.clusters.values(), key=lambda item: item.id)],
        "tiles": [_tile_record_payload(tile) for tile in sorted(unit.tiles.values(), key=lambda item: item.id)],
        "aliases": {alias: target for alias, target in sorted(unit.aliases.items())},
        "constructions": [
            _construction_payload(construction)
            for construction in sorted(unit.constructions.values(), key=lambda item: item.id)
        ],
        "composite_tiles": [
            _composite_tile_payload(composite)
            for composite in sorted(unit.composite_tiles.values(), key=lambda item: item.id)
        ],
        "attachment_sets": [
            _attachment_set_payload(attachment_set)
            for attachment_set in sorted(unit.attachment_sets.values(), key=lambda item: item.id)
        ],
    }


def tile_library_unit_to_json(unit: TileLibraryUnit) -> str:
    return json.dumps(tile_library_unit_to_payload(unit), indent=2, sort_keys=True) + "\n"


def tile_library_unit_from_payload(raw: object) -> TileLibraryUnit:
    payload = require_mapping(raw, context="runtime library")
    schema_version = _as_int(payload.get("schema_version"), context="runtime library.schema_version")
    if schema_version != RUNTIME_LIBRARY_SCHEMA_VERSION:
        raise ValueError(
            f"runtime library schema_version must be {RUNTIME_LIBRARY_SCHEMA_VERSION}, got {schema_version}"
        )
    family = require_mapping(payload.get("family"), context="runtime library.family")
    variants = _records_by_id(payload.get("variants"), _variant_from_payload, context="runtime library.variants")
    clusters = _records_by_id(payload.get("clusters"), _cluster_from_payload, context="runtime library.clusters")
    tiles = _records_by_id(payload.get("tiles"), _tile_record_from_payload, context="runtime library.tiles")
    aliases = {
        _as_str(alias, context="runtime library.aliases key"): _as_str(target, context=f"runtime library.aliases.{alias}")
        for alias, target in require_mapping(payload.get("aliases", {}), context="runtime library.aliases").items()
    }
    for alias in aliases:
        if alias in tiles:
            raise ValueError(f"runtime library.aliases key {alias!r} collides with a tile id")
    for alias, target in aliases.items():
        if target not in tiles:
            raise ValueError(f"runtime library.aliases.{alias} points at unknown tile id {target!r}")
    for cluster in clusters.values():
        for member_id in cluster.members:
            if member_id not in tiles:
                raise ValueError(
                    f"runtime library.clusters.{cluster.id}.members references unknown tile id {member_id!r}"
                )
    for tile in tiles.values():
        declared_variant_ids = set(variants)
        _require_variant_coverage(
            set(tile.variant_assets),
            declared_variant_ids,
            tile_id=tile.id,
            field_name="variant_assets",
        )
        _require_variant_coverage(
            set(tile.variant_atlas_cells),
            declared_variant_ids,
            tile_id=tile.id,
            field_name="variant_atlas_cells",
        )
        for variant_id, cell in tile.variant_atlas_cells.items():
            variant = variants[variant_id]
            if variant.atlas_columns is None or variant.atlas_rows is None:
                raise ValueError(f"runtime library.variants.{variant_id} is missing atlas dimensions")
            if not (0 <= cell.col < variant.atlas_columns and 0 <= cell.row < variant.atlas_rows):
                raise ValueError(
                    f"runtime library.tiles.{tile.id}.variant_atlas_cells.{variant_id} is outside atlas bounds: "
                    f"({cell.col}, {cell.row}) not within {variant.atlas_columns}x{variant.atlas_rows}"
                )
        for cluster_id in tile.genesis.cluster_ids:
            if cluster_id not in clusters:
                raise ValueError(
                    f"runtime library.tiles.{tile.id}.genesis.cluster_ids references unknown cluster {cluster_id!r}"
                )
        if tile.exact_duplicate_of is not None:
            if tile.exact_duplicate_of == tile.id:
                raise ValueError(f"runtime library.tiles.{tile.id}.exact_duplicate_of must not reference itself")
            if tile.exact_duplicate_of not in tiles:
                raise ValueError(
                    f"runtime library.tiles.{tile.id}.exact_duplicate_of references unknown tile id "
                    f"{tile.exact_duplicate_of!r}"
                )
            # TODO(IRS Phase 2/3): move exact_duplicate_of cycle detection into the shared
            # family/runtime referential validator. Runtime resolution already fails
            # loudly on cycles; this loader currently matches the ingest twin's
            # shallow referential check.

    def _construction_record_from_payload(raw: object, *, context: str) -> Construction:
        return _construction_from_payload(raw, tiles=tiles, context=context)

    def _composite_tile_record_from_payload(raw: object, *, context: str) -> CompositeTileRecord:
        return _composite_tile_from_payload(raw, tiles=tiles, context=context)

    constructions = _records_by_id(
        payload.get("constructions"),
        _construction_record_from_payload,
        context="runtime library.constructions",
    )
    composite_tiles = _records_by_id(
        payload.get("composite_tiles"),
        _composite_tile_record_from_payload,
        context="runtime library.composite_tiles",
    )
    attachment_sets = _records_by_id(
        payload.get("attachment_sets"),
        _attachment_set_from_payload,
        context="runtime library.attachment_sets",
    )
    default_variant_id = _as_str(family.get("default_variant_id"), context="runtime library.family.default_variant_id")
    if default_variant_id not in variants:
        raise ValueError(f"runtime library.family.default_variant_id references unknown variant {default_variant_id!r}")
    tiles_by_sheet_cell_index = index_tiles_by_sheet_cell(tiles, context="runtime library.tiles")
    return TileLibraryUnit(
        family_id=_as_str(family.get("family_id"), context="runtime library.family.family_id"),
        tile_width=_as_int(family.get("tile_width"), context="runtime library.family.tile_width"),
        tile_height=_as_int(family.get("tile_height"), context="runtime library.family.tile_height"),
        render_step_width=_as_optional_int(
            family.get("render_step_width"),
            context="runtime library.family.render_step_width",
        ),
        render_step_height=_as_optional_int(
            family.get("render_step_height"),
            context="runtime library.family.render_step_height",
        ),
        default_variant_id=default_variant_id,
        runtime_flippable=_as_bool(family.get("runtime_flippable"), context="runtime library.family.runtime_flippable"),
        promoted_metadata=_promoted_metadata_from_payload(
            family.get("promoted_metadata", {}),
            context="runtime library.family.promoted_metadata",
        ),
        root=Path(_as_str(family.get("root"), context="runtime library.family.root")),
        variants=variants,
        clusters=clusters,
        tiles=tiles,
        aliases=aliases,
        tiles_by_sheet_cell_index=tiles_by_sheet_cell_index,
        constructions=constructions,
        composite_tiles=composite_tiles,
        attachment_sets=attachment_sets,
        attachment_sets_by_target=attachment_sets_by_target(attachment_sets),
    )


def tile_library_unit_from_json(text: str) -> TileLibraryUnit:
    return tile_library_unit_from_payload(json.loads(text))
