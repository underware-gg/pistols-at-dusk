#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field, fields
from difflib import get_close_matches
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Protocol, TypedDict, Union, cast

from typing_extensions import NotRequired, TypeAlias

from PIL import Image

from _manifest_utils import GridBounds, bounds_inside as _bounds_inside, check_required_keys, load_json, require_list, require_mapping, resolve_path
from compatibility_family import CompatibilityFamilyPaths
from tile_metadata import ModuleContextValue, RenderTraits

PHYSICAL_TILE_RE = re.compile(r"^(?P<family>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$")
VARIANT_TILE_RE = re.compile(
    r"^(?P<family>[a-z0-9_.-]+)@(?P<variant>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$"
)
SHEET_CELL_RE = re.compile(r"^sheet:(?P<col>\d+),(?P<row>\d+)$")
DEFAULT_TRANSPARENT_MODE = "top_left"


class FamilyGridConfig(TypedDict):
    tile_width: int
    tile_height: int


class FamilyRenderDefaultsConfig(TypedDict, total=False):
    render_step_width: int
    render_step_height: int


class FamilyVariantConfig(TypedDict):
    variant_id: str
    sheet: str
    transparent: NotRequired[str]
    palette_family: NotRequired[str]
    colorway: NotRequired[str]
    background_mode: NotRequired[str]
    notes: NotRequired[str]


class FamilyManifest(TypedDict):
    family_id: str
    grid: FamilyGridConfig
    variants: list[FamilyVariantConfig]
    title: NotRequired[str]
    render_defaults: NotRequired[FamilyRenderDefaultsConfig]
    siblings_share_semantics: NotRequired[bool]
    notes: NotRequired[list[str]]
    default_variant_id: NotRequired[str]
    ingestion_spec: NotRequired[str]


class IngestionBoundsConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int


class SourceLayoutRegionConfig(TypedDict):
    id: str
    bounds: IngestionBoundsConfig
    areas: NotRequired[list[IngestionBoundsConfig]]
    label: NotRequired[str]
    notes: NotRequired[str]
    ingest_tiles: NotRequired[bool]


class SourceLayoutClusterConfig(TypedDict):
    id: str
    source_region_id: str
    bounds: IngestionBoundsConfig
    label: NotRequired[str]
    notes: NotRequired[str]
    split_axis: NotRequired[str]
    ingest_tiles: NotRequired[bool]


class SourceLayoutIgnoreRegionConfig(TypedDict):
    id: str
    bounds: IngestionBoundsConfig
    label: NotRequired[str]
    reason: NotRequired[str]


class SheetCellConfig(TypedDict):
    col: int
    row: int


class SourceLayoutCollectionTileMemberConfig(TypedDict):
    tile_id: str


class SourceLayoutCollectionAliasMemberConfig(TypedDict):
    alias: str


class SourceLayoutCollectionSheetCellMemberConfig(TypedDict):
    sheet_cell: SheetCellConfig


SourceLayoutCollectionMemberConfig: TypeAlias = Union[
    SourceLayoutCollectionTileMemberConfig,
    SourceLayoutCollectionAliasMemberConfig,
    SourceLayoutCollectionSheetCellMemberConfig,
]


class SourceLayoutCollectionConfig(TypedDict):
    id: str
    kind: str
    label: NotRequired[str]
    source_region_id: NotRequired[str]
    source_cluster_id: NotRequired[str]
    bounds: NotRequired[IngestionBoundsConfig]
    members: NotRequired[list[SourceLayoutCollectionMemberConfig]]
    constructions: NotRequired[list[str]]
    notes: NotRequired[str]


class SourceLayoutManifest(TypedDict):
    sheet_bounds: IngestionBoundsConfig
    regions: list[SourceLayoutRegionConfig]
    clusters: list[SourceLayoutClusterConfig]
    ignore_regions: NotRequired[list[SourceLayoutIgnoreRegionConfig]]
    collections: NotRequired[list[SourceLayoutCollectionConfig]]
    notes: NotRequired[list[str]]


class ClusterBoundsConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ClusterConfig(TypedDict):
    id: str
    scope: NotRequired[str]
    members: NotRequired[list[str]]
    kind_guess: NotRequired[str]
    evidence: NotRequired[list[str]]
    source_label: NotRequired[str]
    source_notes: NotRequired[str]


class TileConfig(TypedDict):
    id: str
    layer: str
    category: str
    transparent: bool
    sheet_col: NotRequired[int]
    sheet_row: NotRequired[int]
    exact_duplicate_of: NotRequired[str]
    image_override: NotRequired[str]
    tags: NotRequired[list[str]]
    walkable: NotRequired[bool]
    blocking: NotRequired[bool]
    scenes: NotRequired[list[str]]
    semantics: NotRequired[list[str]]
    motifs: NotRequired[list[str]]
    cluster_ids: NotRequired[list[str]]
    source_group: NotRequired[str]
    noise: NotRequired[str]
    contrast: NotRequired[str]
    temperature: NotRequired[str]
    usage: NotRequired[str]
    style: NotRequired[str]
    overlay: NotRequired[str]
    footprint: NotRequired[str]
    orientation: NotRequired[str]
    facing: NotRequired[str]
    pose: NotRequired[str]
    compose_group: NotRequired[str]
    compose_role: NotRequired[str]
    state_group: NotRequired[str]
    state_role: NotRequired[str]
    animation_group: NotRequired[str]
    animation_frame: NotRequired[int]
    animation_frame_count: NotRequired[int]
    connects_on: NotRequired[list[str]]
    requires_exposed_on: NotRequired[list[str]]
    affordances: NotRequired[list[str]]
    alt_uses: NotRequired[list[str]]
    meaning: NotRequired[str]
    meaning_confidence: NotRequired[str]
    source_notes: NotRequired[str]


class TileRecordData(TypedDict):
    id: str
    family_id: str
    sheet_col: int | None
    sheet_row: int | None
    exact_duplicate_of: str | None
    image_override: str | None
    layer: str
    category: str
    transparent: bool
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    walkable: bool | None
    blocking: bool | None
    scenes: tuple[str, ...]
    semantics: tuple[str, ...]
    motifs: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    source_group: str | None
    noise: str | None
    contrast: str | None
    temperature: str | None
    usage: str | None
    style: str | None
    overlay: str | None
    footprint: str | None
    orientation: str | None
    facing: str | None
    pose: str | None
    compose_group: str | None
    compose_role: str | None
    state_group: str | None
    state_role: str | None
    animation_group: str | None
    animation_frame: int | None
    animation_frame_count: int | None
    connects_on: tuple[str, ...]
    requires_exposed_on: tuple[str, ...]
    affordances: tuple[str, ...]
    alt_uses: tuple[str, ...]
    meaning: str | None
    meaning_confidence: str | None
    source_notes: str | None


class TileFamilyIngestSourceRegionReport(TypedDict):
    total: int
    missing_source_group: int
    missing_cluster_ids: int
    missing_meaning: int
    missing_meaning_confidence: int
    uncertain_meaning: int
    by_meaning_confidence: dict[str, int]


class TileFamilyIngestReport(TypedDict):
    family_id: str
    tile_count: int
    cluster_count: int
    complete: bool
    missing_source_group: list[str]
    missing_cluster_ids: list[str]
    missing_meaning: list[str]
    missing_meaning_confidence: list[str]
    uncertain_meaning: list[str]
    by_meaning_confidence: dict[str, int]
    by_source_region: dict[str, TileFamilyIngestSourceRegionReport]
    by_cluster: dict[str, int]


class SourceLayoutCoverageReport(TypedDict):
    non_empty_total: int
    covered_non_empty: list[str]
    ignored_non_empty: list[str]
    outside_regions_non_empty: list[str]
    region_unclustered_non_empty: list[str]
    complete: bool


FamilyAliasesManifest = dict[str, str]


class ConstructionCellConfig(TypedDict):
    role: str


class MetatileConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["metatile"]
    cells: list[list[ConstructionCellConfig | str]]
    expose_as_entity: NotRequired[bool]


class ParametricRunConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["parametric_run"]
    axis: str
    length_param: str
    start_role: str
    repeat_role: str
    end_role: str
    expose_as_entity: NotRequired[bool]


class FrameSlotConfig(TypedDict):
    fill_mode: NotRequired[str]
    role: NotRequired[str]
    tile: NotRequired[str]
    flip_x: NotRequired[bool]
    flip_y: NotRequired[bool]


class FrameCornerSlotConfig(TypedDict):
    role: NotRequired[str]
    tile: NotRequired[str]
    cells: NotRequired[list[list[str]]]
    flip_x: NotRequired[bool]
    flip_y: NotRequired[bool]


class ParametricFrameConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["parametric_frame"]
    corners: list[str] | dict[str, FrameCornerSlotConfig]
    edges: NotRequired[dict[str, FrameSlotConfig]]
    fill: NotRequired[FrameSlotConfig]
    min_width: NotRequired[int]
    min_height: NotRequired[int]
    width_param: NotRequired[str]
    height_param: NotRequired[str]
    expose_as_entity: NotRequired[bool]


class AttachmentCanvasConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ConstructionAttachmentVariantConfig(TypedDict):
    id: str
    construction_id: str
    label: NotRequired[str]
    notes: NotRequired[str]


class ConstructionAttachmentSetConfig(TypedDict):
    id: str
    param: str
    target_construction_ids: list[str]
    canvas: AttachmentCanvasConfig
    variants: list[ConstructionAttachmentVariantConfig]
    required: NotRequired[bool]
    default_variant_id: NotRequired[str]
    label: NotRequired[str]
    notes: NotRequired[str]


ConstructionConfig = Union[
    MetatileConstructionConfig,
    ParametricRunConstructionConfig,
    ParametricFrameConstructionConfig,
]


class ConstructionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MetatileConstruction:
    id: str
    collection_id: str
    cells: tuple[tuple[TileRecord | None, ...], ...]
    expose_as_entity: bool = True
    kind: Literal["metatile"] = "metatile"


@dataclass(frozen=True)
class ParametricRunConstruction:
    id: str
    collection_id: str
    axis: Literal["x", "y"]
    length_param: str
    start_tile: TileRecord
    repeat_tile: TileRecord
    end_tile: TileRecord
    expose_as_entity: bool = True
    kind: Literal["parametric_run"] = "parametric_run"


FRAME_FILL_MODES: tuple[str, ...] = ("repeat", "round", "space", "stretch")


@dataclass(frozen=True)
class FrameSlot:
    """A resizable frame slot (edge or fill): the tile plus how it fills its span.

    ``flip_x``/``flip_y`` let one edge derive from the opposite edge's art (e.g.
    ``edge_right`` = ``edge_left`` mirrored on x), so a symmetric kit declares it once.
    """

    tile: TileRecord
    fill_mode: str = "repeat"
    flip_x: bool = False
    flip_y: bool = False


@dataclass(frozen=True)
class FrameCornerSlot:
    """A frame corner: a grid of tiles, optionally flipped.

    Thin frames use a 1x1 grid; fat ("thick") corners use an NxM grid. A flipped
    slot derives one corner from another (e.g. ``corner_tr`` = ``corner_tl``
    mirrored on x), so a symmetric kit declares its art once.
    """

    cells: tuple[tuple[TileRecord | None, ...], ...]
    flip_x: bool = False
    flip_y: bool = False

    @property
    def width(self) -> int:
        return len(self.cells[0]) if self.cells else 0

    @property
    def height(self) -> int:
        return len(self.cells)

    def tiles(self) -> tuple[TileRecord, ...]:
        return tuple(cell for row in self.cells for cell in row if cell is not None)


@dataclass(frozen=True)
class ParametricFrameConstruction:
    """A resizable border/UI frame — the 2-D analogue of a parametric run.

    Corners are placed once; present edges tile between them per ``fill_mode``;
    an optional ``fill`` tiles the interior. Absent slots render transparent,
    so a corner-only kit is simply a frame with empty ``edges`` and no ``fill``.
    """

    id: str
    collection_id: str
    corners: Mapping[str, FrameCornerSlot]
    edges: Mapping[str, FrameSlot]
    fill: FrameSlot | None = None
    min_width: int = 2
    min_height: int = 2
    width_param: str = "width"
    height_param: str = "height"
    expose_as_entity: bool = True
    kind: Literal["parametric_frame"] = "parametric_frame"


Construction: TypeAlias = Union[
    MetatileConstruction,
    ParametricRunConstruction,
    ParametricFrameConstruction,
]


@dataclass(frozen=True)
class ConstructionAttachmentVariant:
    id: str
    construction_id: str
    label: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ConstructionAttachmentSet:
    id: str
    param: str
    target_construction_ids: tuple[str, ...]
    canvas: GridBounds
    variants: Mapping[str, ConstructionAttachmentVariant] = field(repr=False)
    required: bool = False
    default_variant_id: str | None = None
    label: str | None = None
    notes: str | None = None

    def variant(self, variant_id: str) -> ConstructionAttachmentVariant | None:
        return self.variants.get(variant_id)

    def to_entity_record(self) -> EntityAttachmentSetRecord:
        return EntityAttachmentSetRecord(
            id=self.id,
            param=self.param,
            canvas=self.canvas,
            variant_ids=tuple(self.variants.keys()),
            required=self.required,
            default_variant_id=self.default_variant_id,
            label=self.label,
            notes=self.notes,
        )


@dataclass(frozen=True)
class EntityAttachmentSetRecord:
    id: str
    param: str
    canvas: GridBounds
    variant_ids: tuple[str, ...]
    required: bool = False
    default_variant_id: str | None = None
    label: str | None = None
    notes: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "param": self.param,
            "required": self.required,
            "default_variant_id": self.default_variant_id,
            "label": self.label,
            "notes": self.notes,
            "canvas": {
                "x": self.canvas.x,
                "y": self.canvas.y,
                "width": self.canvas.width,
                "height": self.canvas.height,
            },
            "variant_ids": list(self.variant_ids),
        }


@dataclass(frozen=True)
class EntityFootprintSpec:
    mode: Literal["fixed", "parametric_run", "parametric_frame"]
    width: int
    height: int
    axis: Literal["x", "y"] | None = None
    length_param: str | None = None
    minimum_length: int | None = None
    width_param: str | None = None
    height_param: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "width": self.width,
            "height": self.height,
            "axis": self.axis,
            "length_param": self.length_param,
            "minimum_length": self.minimum_length,
            "width_param": self.width_param,
            "height_param": self.height_param,
        }


@dataclass(frozen=True)
class EntityTemplateRecord:
    id: str
    construction_id: str
    collection_id: str
    kind: Literal["metatile", "parametric_run", "parametric_frame"]
    placement_anchor: Literal["top_left"]
    compose_roles: tuple[str, ...]
    affordances: tuple[str, ...]
    state_groups: tuple[str, ...]
    animation_groups: tuple[str, ...]
    footprint: EntityFootprintSpec
    attachment_sets: tuple[EntityAttachmentSetRecord, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "construction_id": self.construction_id,
            "collection_id": self.collection_id,
            "kind": self.kind,
            "placement_anchor": self.placement_anchor,
            "compose_roles": list(self.compose_roles),
            "affordances": list(self.affordances),
            "state_groups": list(self.state_groups),
            "animation_groups": list(self.animation_groups),
            "footprint": self.footprint.to_payload(),
            "attachment_sets": [attachment_set.to_payload() for attachment_set in self.attachment_sets],
        }


def load_family_manifest(path: Path) -> FamilyManifest:
    raw = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw, ("family_id", "grid", "variants"), context=str(path))
    grid_raw = require_mapping(raw["grid"], context=f"{path}: grid")
    check_required_keys(grid_raw, ("tile_width", "tile_height"), context=f"{path}: grid")
    variants_raw = require_list(raw["variants"], context=f"{path}: variants")
    for index, variant_value in enumerate(variants_raw):
        variant_mapping = require_mapping(variant_value, context=f"{path}: variants[{index}]")
        check_required_keys(
            variant_mapping,
            ("variant_id", "sheet"),
            context=f"{path}: variants[{index}]",
        )
    return cast(FamilyManifest, raw)


def load_family_variants_from_manifest(
    *,
    root: Path,
    variants_data: list[FamilyVariantConfig],
) -> dict[str, TileFamilyVariant]:
    variants: dict[str, TileFamilyVariant] = {}
    for spec in variants_data:
        variant_id = str(spec["variant_id"])
        if variant_id in variants:
            raise ValueError(f"Duplicate variant_id in {root}: {variant_id}")
        variants[variant_id] = TileFamilyVariant(
            id=variant_id,
            sheet_path=resolve_path(root, str(spec["sheet"])),
            transparent_mode=str(spec.get("transparent", DEFAULT_TRANSPARENT_MODE)),
            palette_family=spec.get("palette_family"),
            colorway=spec.get("colorway"),
            background_mode=spec.get("background_mode"),
            notes=spec.get("notes"),
        )
    return variants


def load_family_header_from_manifest(
    *,
    root: Path,
    family_data: FamilyManifest,
    variants: Mapping[str, TileFamilyVariant],
) -> TileFamilyHeader:
    grid = family_data.get("grid", {})
    render_defaults = family_data.get("render_defaults", {})
    declared_default_variant_id = family_data.get("default_variant_id")
    if declared_default_variant_id is None and not variants:
        raise ValueError(f"Tile family {root} must define at least one variant")
    default_variant_id = (
        str(declared_default_variant_id)
        if declared_default_variant_id is not None
        else next(iter(variants.keys()))
    )
    return TileFamilyHeader(
        root=root,
        family_id=str(family_data["family_id"]),
        title=family_data.get("title"),
        tile_width=int(grid["tile_width"]),
        tile_height=int(grid["tile_height"]),
        render_step_width=render_defaults.get("render_step_width"),
        render_step_height=render_defaults.get("render_step_height"),
        siblings_share_semantics=family_data.get("siblings_share_semantics"),
        notes=(
            _tuple(cast(Iterable[str], family_data["notes"]))
            if "notes" in family_data
            else None
        ),
        default_variant_id=default_variant_id,
    )


def load_family_header_and_variants(
    root: Path,
) -> tuple[TileFamilyHeader, dict[str, TileFamilyVariant], FamilyManifest]:
    family_data = load_family_manifest(root / "family.json")
    variants = load_family_variants_from_manifest(
        root=root,
        variants_data=family_data.get("variants", []),
    )
    header = load_family_header_from_manifest(
        root=root,
        family_data=family_data,
        variants=variants,
    )
    return header, variants, family_data


def load_cluster_manifest(path: Path) -> list[ClusterConfig]:
    raw = require_list(load_json(path), context=str(path))
    for index, value in enumerate(raw):
        mapping = require_mapping(value, context=f"{path}[{index}]")
        check_required_keys(mapping, ("id",), context=f"{path}[{index}]")
    return cast(list[ClusterConfig], raw)


def load_ingestion_manifest(path: Path) -> SourceLayoutManifest:
    raw = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw, ("sheet_bounds", "regions", "clusters"), context=str(path))
    sheet_bounds = require_mapping(raw["sheet_bounds"], context=f"{path}: sheet_bounds")
    check_required_keys(sheet_bounds, ("x", "y", "width", "height"), context=f"{path}: sheet_bounds")

    regions_raw = require_list(raw["regions"], context=f"{path}: regions")
    for index, value in enumerate(regions_raw):
        mapping = require_mapping(value, context=f"{path}: regions[{index}]")
        check_required_keys(mapping, ("id", "bounds"), context=f"{path}: regions[{index}]")
        bounds = require_mapping(mapping["bounds"], context=f"{path}: regions[{index}].bounds")
        check_required_keys(bounds, ("x", "y", "width", "height"), context=f"{path}: regions[{index}].bounds")
        areas_raw = mapping.get("areas")
        if areas_raw is not None:
            for area_index, area_value in enumerate(require_list(areas_raw, context=f"{path}: regions[{index}].areas")):
                area_mapping = require_mapping(area_value, context=f"{path}: regions[{index}].areas[{area_index}]")
                check_required_keys(
                    area_mapping,
                    ("x", "y", "width", "height"),
                    context=f"{path}: regions[{index}].areas[{area_index}]",
                )

    clusters_raw = require_list(raw["clusters"], context=f"{path}: clusters")
    for index, value in enumerate(clusters_raw):
        mapping = require_mapping(value, context=f"{path}: clusters[{index}]")
        check_required_keys(mapping, ("id", "source_region_id", "bounds"), context=f"{path}: clusters[{index}]")
        bounds = require_mapping(mapping["bounds"], context=f"{path}: clusters[{index}].bounds")
        check_required_keys(bounds, ("x", "y", "width", "height"), context=f"{path}: clusters[{index}].bounds")

    ignore_regions_raw = raw.get("ignore_regions")
    if ignore_regions_raw is not None:
        for index, value in enumerate(require_list(ignore_regions_raw, context=f"{path}: ignore_regions")):
            mapping = require_mapping(value, context=f"{path}: ignore_regions[{index}]")
            check_required_keys(mapping, ("id", "bounds"), context=f"{path}: ignore_regions[{index}]")
            bounds = require_mapping(mapping["bounds"], context=f"{path}: ignore_regions[{index}].bounds")
            check_required_keys(bounds, ("x", "y", "width", "height"), context=f"{path}: ignore_regions[{index}].bounds")

    collections_raw = raw.get("collections")
    if collections_raw is not None:
        for index, value in enumerate(require_list(collections_raw, context=f"{path}: collections")):
            mapping = require_mapping(value, context=f"{path}: collections[{index}]")
            check_required_keys(mapping, ("id", "kind"), context=f"{path}: collections[{index}]")
            bounds_value = mapping.get("bounds")
            if bounds_value is not None:
                bounds = require_mapping(bounds_value, context=f"{path}: collections[{index}].bounds")
                check_required_keys(bounds, ("x", "y", "width", "height"), context=f"{path}: collections[{index}].bounds")
            members_value = mapping.get("members")
            if members_value is not None:
                _load_ingestion_collection_members(members_value, context=f"{path}: collections[{index}].members")
    return cast(SourceLayoutManifest, raw)


def load_tile_manifest(path: Path) -> list[TileConfig]:
    raw = require_list(load_json(path), context=str(path))
    for index, value in enumerate(raw):
        mapping = require_mapping(value, context=f"{path}[{index}]")
        check_required_keys(
            mapping,
            ("id", "layer", "category", "transparent"),
            context=f"{path}[{index}]",
        )
    return cast(list[TileConfig], raw)


def load_alias_manifest(path: Path) -> FamilyAliasesManifest:
    return cast(FamilyAliasesManifest, require_mapping(load_json(path), context=str(path)))


def load_construction_manifest(path: Path) -> tuple[ConstructionConfig, ...]:
    raw_file = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw_file, ("constructions",), context=str(path))
    raw_list = require_list(raw_file["constructions"], context=f"{path}: constructions")
    loaded: list[ConstructionConfig] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_list):
        item_context = f"{path}: constructions[{index}]"
        item_mapping = require_mapping(raw_item, context=item_context)
        check_required_keys(item_mapping, ("id", "collection_id", "kind"), context=item_context)
        construction_kind = str(item_mapping["kind"])
        if construction_kind == "parametric_run":
            check_required_keys(
                item_mapping,
                ("axis", "length_param", "start_role", "repeat_role", "end_role"),
                context=item_context,
            )
        elif construction_kind == "parametric_frame":
            check_required_keys(item_mapping, ("corners",), context=item_context)
        else:
            check_required_keys(item_mapping, ("cells",), context=item_context)
        construction_id = str(item_mapping["id"])
        if construction_id in seen_ids:
            raise ValueError(f"Duplicate construction id in {path}: {construction_id!r}")
        seen_ids.add(construction_id)
        loaded.append(cast(ConstructionConfig, item_mapping))
    return tuple(loaded)


def load_attachment_manifest(path: Path) -> tuple[ConstructionAttachmentSetConfig, ...]:
    raw_file = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw_file, ("attachment_sets",), context=str(path))
    raw_list = require_list(raw_file["attachment_sets"], context=f"{path}: attachment_sets")
    loaded: list[ConstructionAttachmentSetConfig] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_list):
        item_context = f"{path}: attachment_sets[{index}]"
        item_mapping = require_mapping(raw_item, context=item_context)
        check_required_keys(
            item_mapping,
            ("id", "param", "target_construction_ids", "canvas", "variants"),
            context=item_context,
        )
        attachment_id = str(item_mapping["id"])
        if attachment_id in seen_ids:
            raise ValueError(f"Duplicate attachment set id in {path}: {attachment_id!r}")
        seen_ids.add(attachment_id)
        loaded.append(cast(ConstructionAttachmentSetConfig, item_mapping))
    return tuple(loaded)


def load_family_catalog_sources(
    paths: CompatibilityFamilyPaths,
) -> FamilyCatalogSources:
    constructions_data: tuple[ConstructionConfig, ...] = ()
    if paths.constructions_path is not None:
        constructions_data = load_construction_manifest(paths.constructions_path)
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...] = ()
    if paths.attachments_path is not None:
        attachments_data = load_attachment_manifest(paths.attachments_path)
    return FamilyCatalogSources(
        paths=paths,
        clusters_data=tuple(load_cluster_manifest(paths.clusters_path)),
        tiles_data=tuple(load_tile_manifest(paths.tiles_path)),
        aliases_data=MappingProxyType(dict(load_alias_manifest(paths.aliases_path))),
        constructions_data=constructions_data,
        attachments_data=attachments_data,
    )


def _tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(values or ())


def _group_aliases_by_tile(aliases: dict[str, str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for alias, tile_id in aliases.items():
        grouped[tile_id].append(alias)
    return {tile_id: tuple(sorted(items)) for tile_id, items in grouped.items()}


@dataclass(frozen=True)
class TileFamilyVariant:
    id: str
    sheet_path: Path
    transparent_mode: str
    palette_family: str | None = None
    colorway: str | None = None
    background_mode: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class TileFamilyHeader:
    root: Path
    family_id: str
    title: str | None
    tile_width: int
    tile_height: int
    render_step_width: int | None
    render_step_height: int | None
    siblings_share_semantics: bool | None
    notes: tuple[str, ...] | None
    default_variant_id: str


def _empty_tile_library_module_context() -> dict[str, ModuleContextValue]:
    return {}


@dataclass(frozen=True)
class TileLibraryPromotedMetadata:
    source_pack_id: str | None = None
    source_tileset_id: str | None = None
    source_tilesheet_id: str | None = None
    module_context: Mapping[str, ModuleContextValue] = field(
        default_factory=_empty_tile_library_module_context,
        repr=False,
    )
    render_traits: RenderTraits = field(default_factory=RenderTraits)
    documented_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_context", MappingProxyType(dict(self.module_context)))
        object.__setattr__(self, "documented_hints", tuple(self.documented_hints))


EMPTY_TILE_LIBRARY_PROMOTED_METADATA = TileLibraryPromotedMetadata()


@dataclass(frozen=True)
class FamilyCatalogSources:
    paths: CompatibilityFamilyPaths
    clusters_data: tuple[ClusterConfig, ...]
    tiles_data: tuple[TileConfig, ...]
    aliases_data: Mapping[str, str]
    constructions_data: tuple[ConstructionConfig, ...]
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...]


@dataclass(frozen=True)
class SourceLayoutRegion:
    id: str
    bounds: GridBounds
    areas: tuple[GridBounds, ...] = ()
    label: str | None = None
    notes: str | None = None
    ingest_tiles: bool = True


@dataclass(frozen=True)
class SourceLayoutCluster:
    id: str
    source_region_id: str
    bounds: GridBounds
    label: str | None = None
    notes: str | None = None
    split_axis: str | None = None
    ingest_tiles: bool = True


@dataclass(frozen=True)
class SourceLayoutIgnoreRegion:
    id: str
    bounds: GridBounds
    label: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SheetCell:
    col: int
    row: int

    @property
    def ref(self) -> str:
        return format_sheet_cell_ref(self.col, self.row)


@dataclass(frozen=True)
class SourceLayoutCollectionMember:
    kind: Literal["tile_id", "alias", "sheet_cell"]
    value: str | SheetCell


@dataclass(frozen=True)
class SourceLayoutCollection:
    id: str
    kind: str
    label: str | None = None
    source_region_id: str | None = None
    source_cluster_id: str | None = None
    bounds: GridBounds | None = None
    members: tuple[SourceLayoutCollectionMember, ...] = ()
    constructions: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class SourceLayoutIngestion:
    sheet_bounds: GridBounds
    source_regions: dict[str, SourceLayoutRegion]
    source_clusters: dict[str, SourceLayoutCluster]
    ignored_regions: dict[str, SourceLayoutIgnoreRegion]
    source_collections: dict[str, SourceLayoutCollection]
    notes: tuple[str, ...] = ()

    def contains_cell(self, col: int, row: int) -> bool:
        return self.sheet_bounds.x <= col < self.sheet_bounds.x + self.sheet_bounds.width and self.sheet_bounds.y <= row < self.sheet_bounds.y + self.sheet_bounds.height

    def ignored_cell(self, col: int, row: int) -> bool:
        return any(_bounds_contains(ignore.bounds, col, row) for ignore in self.ignored_regions.values())

    def source_region_for_cell(self, col: int, row: int) -> SourceLayoutRegion | None:
        for region in self.source_regions.values():
            if _source_layout_region_contains_cell(region, col, row):
                return region
        return None

    def source_clusters_for_cell(self, col: int, row: int) -> tuple[SourceLayoutCluster, ...]:
        return tuple(cluster for cluster in self.source_clusters.values() if _bounds_contains(cluster.bounds, col, row))


@dataclass(frozen=True)
class TileClusterRecord:
    id: str
    scope: str
    members: tuple[str, ...] = ()
    kind_guess: str | None = None
    evidence: tuple[str, ...] = ()
    source_label: str | None = None
    source_notes: str | None = None


@dataclass(frozen=True)
class TileRecord:
    id: str
    family_id: str
    layer: str
    category: str
    transparent: bool
    tags: tuple[str, ...]
    sheet_col: int | None = None
    sheet_row: int | None = None
    exact_duplicate_of: str | None = None
    image_override: str | None = None
    aliases: tuple[str, ...] = ()
    walkable: bool | None = None
    blocking: bool | None = None
    scenes: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    cluster_ids: tuple[str, ...] = ()
    source_group: str | None = None
    noise: str | None = None
    contrast: str | None = None
    temperature: str | None = None
    usage: str | None = None
    style: str | None = None
    overlay: str | None = None
    footprint: str | None = None
    orientation: str | None = None
    facing: str | None = None
    pose: str | None = None
    compose_group: str | None = None
    compose_role: str | None = None
    state_group: str | None = None
    state_role: str | None = None
    animation_group: str | None = None
    animation_frame: int | None = None
    animation_frame_count: int | None = None
    connects_on: tuple[str, ...] = ()
    requires_exposed_on: tuple[str, ...] = ()
    affordances: tuple[str, ...] = ()
    alt_uses: tuple[str, ...] = ()
    meaning: str | None = None
    meaning_confidence: str | None = None
    source_notes: str | None = None


TILE_SEQUENCE_FIELDS = frozenset(
    {
        "aliases",
        "tags",
        "scenes",
        "semantics",
        "motifs",
        "cluster_ids",
        "connects_on",
        "requires_exposed_on",
        "affordances",
        "alt_uses",
    }
)
TILE_EQUALITY_FIELDS = frozenset(field.name for field in fields(TileRecord) if field.name not in TILE_SEQUENCE_FIELDS)
TILE_QUERY_ALIASES = {
    "scene": "scenes",
    "semantic_cluster_id": "cluster_ids",
}
TILE_QUERY_FIELDS_FOR_SUGGESTION = TILE_EQUALITY_FIELDS | TILE_SEQUENCE_FIELDS | set(TILE_QUERY_ALIASES)
MEANING_CONFIDENCE_VALUES = frozenset({"confirmed", "tentative", "unknown"})
EXACT_DUPLICATE_INHERITED_SEQUENCE_FIELDS = frozenset(
    {
        "tags",
        "scenes",
        "semantics",
        "motifs",
        "connects_on",
        "requires_exposed_on",
        "affordances",
        "alt_uses",
    }
)
EXACT_DUPLICATE_INHERITED_SCALAR_FIELDS = frozenset(
    {
        "image_override",
        "layer",
        "category",
        "transparent",
        "walkable",
        "blocking",
        "noise",
        "contrast",
        "temperature",
        "usage",
        "style",
        "overlay",
        "footprint",
        "orientation",
        "compose_group",
        "compose_role",
        "meaning",
        "meaning_confidence",
        "source_notes",
    }
)


@dataclass(frozen=True)
class ResolvedFamilyTile:
    family_id: str
    variant_id: str
    tile_id: str
    sheet_col: int | None
    sheet_row: int | None
    image_override_path: Path | None = None

    @property
    def variant_ref(self) -> str:
        if self.image_override_path is not None or self.sheet_col is None or self.sheet_row is None:
            return self.tile_id
        return f"{self.family_id}@{self.variant_id}:{self.sheet_col},{self.sheet_row}"

    @property
    def physical_ref(self) -> str:
        if self.image_override_path is not None or self.sheet_col is None or self.sheet_row is None:
            return self.tile_id
        return f"{self.family_id}:{self.sheet_col},{self.sheet_row}"


class RuntimeConstructionCatalog(Protocol):
    def lookup_construction(self, construction_id: str) -> Construction | None:
        ...

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        ...

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        ...

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        ...


def attachment_sets_by_target(
    attachment_sets: Mapping[str, ConstructionAttachmentSet],
) -> Mapping[str, tuple[ConstructionAttachmentSet, ...]]:
    indexed: dict[str, list[ConstructionAttachmentSet]] = defaultdict(list)
    for attachment_set in attachment_sets.values():
        for target_id in attachment_set.target_construction_ids:
            indexed[target_id].append(attachment_set)
    return MappingProxyType({target_id: tuple(values) for target_id, values in indexed.items()})


def entity_template_for_construction(
    constructions: Mapping[str, Construction],
    construction_id: str,
    *,
    attachment_sets: Iterable[ConstructionAttachmentSet] = (),
) -> EntityTemplateRecord | None:
    construction = constructions.get(construction_id)
    if construction is None or not construction.expose_as_entity:
        return None
    return entity_template_from_construction(construction, attachment_sets=attachment_sets)


@dataclass(frozen=True, slots=True)
class TileLibraryUnit(RuntimeConstructionCatalog):
    family_id: str
    tile_width: int
    tile_height: int
    render_step_width: int | None
    render_step_height: int | None
    default_variant_id: str
    promoted_metadata: TileLibraryPromotedMetadata = field(repr=False)
    root: Path = field(repr=False)
    variants: Mapping[str, TileFamilyVariant] = field(repr=False)
    tiles: Mapping[str, TileRecord] = field(repr=False)
    aliases: Mapping[str, str] = field(repr=False)
    tiles_by_sheet_cell_index: Mapping[tuple[int, int], TileRecord] = field(repr=False)
    constructions: Mapping[str, Construction] = field(repr=False)
    attachment_sets: Mapping[str, ConstructionAttachmentSet] = field(repr=False)
    attachment_sets_by_target: Mapping[str, tuple[ConstructionAttachmentSet, ...]] = field(repr=False)

    @classmethod
    def from_family(cls, family: TileFamily) -> TileLibraryUnit:
        return cls(
            family_id=family.family_id,
            tile_width=family.tile_width,
            tile_height=family.tile_height,
            render_step_width=family.render_step_width,
            render_step_height=family.render_step_height,
            default_variant_id=family.default_variant_id,
            promoted_metadata=family.promoted_metadata,
            root=family.root,
            variants=family.variants,
            tiles=family.tiles,
            aliases=family.aliases,
            tiles_by_sheet_cell_index=family.tiles_by_sheet_cell,
            constructions=family.constructions,
            attachment_sets=family.attachment_sets,
            attachment_sets_by_target=attachment_sets_by_target(family.attachment_sets),
        )

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(self.variants.keys())

    def variant(self, variant_id: str | None = None) -> TileFamilyVariant:
        resolved_variant_id = variant_id or self.default_variant_id
        return self.variants[resolved_variant_id]

    def runtime_tileset_id(self, variant_id: str | None = None) -> str:
        resolved_variant_id = variant_id or self.default_variant_id
        return f"{self.family_id}@{resolved_variant_id}"

    def tile_record(self, tile_id: str) -> TileRecord | None:
        return self.tiles.get(tile_id)

    def tile_at_sheet_cell(self, *, sheet_col: int, sheet_row: int) -> TileRecord | None:
        return self.tiles_by_sheet_cell_index.get((sheet_col, sheet_row))

    def lookup_construction(self, construction_id: str) -> Construction | None:
        return self.constructions.get(construction_id)

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        return entity_template_for_construction(
            self.constructions,
            construction_id,
            attachment_sets=self.attachment_sets_for_construction(construction_id),
        )

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.attachment_sets_by_target.get(construction_id, ())

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        if construction_id not in self.constructions:
            return None
        self.variant(variant_id)
        return self.runtime_tileset_id(variant_id)

    def entity_templates(self) -> list[EntityTemplateRecord]:
        templates: list[EntityTemplateRecord] = []
        for construction in self.constructions.values():
            template = self.entity_template(construction.id)
            if template is not None:
                templates.append(template)
        return templates

    def resolve_ref(self, ref: str, *, variant_id: str | None = None) -> ResolvedFamilyTile | None:
        return _resolve_family_ref(
            family_id=self.family_id,
            root=self.root,
            default_variant_id=self.default_variant_id,
            variants=self.variants,
            tiles=self.tiles,
            aliases=self.aliases,
            tiles_by_sheet_cell=self.tiles_by_sheet_cell_index,
            ref=ref,
            variant_id=variant_id,
        )


@dataclass(frozen=True, slots=True)
class LoadedTileLibraryUnit:
    unit: TileLibraryUnit
    selected_variant_id: str

    @property
    def family_id(self) -> str:
        return self.unit.family_id

    @property
    def selected_tileset_id(self) -> str:
        return self.unit.runtime_tileset_id(self.selected_variant_id)

    @property
    def effective_render_step_width(self) -> int:
        return self.unit.render_step_width if self.unit.render_step_width is not None else self.unit.tile_width

    @property
    def effective_render_step_height(self) -> int:
        return self.unit.render_step_height if self.unit.render_step_height is not None else self.unit.tile_height

    def resolve_ref(self, ref: str) -> ResolvedFamilyTile | None:
        return self.unit.resolve_ref(ref, variant_id=self.selected_variant_id)


@dataclass(frozen=True, slots=True)
class TileLibraryRegistry(RuntimeConstructionCatalog):
    loaded_units_by_id: Mapping[str, LoadedTileLibraryUnit] = field(repr=False)
    construction_entries_by_id: Mapping[str, tuple[str, Construction]] = field(repr=False)
    alias_unit_ids: Mapping[str, str] = field(repr=False)
    tile_unit_ids: Mapping[str, str] = field(repr=False)
    tile_width: int
    tile_height: int
    render_step_width: int
    render_step_height: int

    @classmethod
    def from_units(cls, units: Iterable[TileLibraryUnit]) -> TileLibraryRegistry:
        return cls.from_loaded_units(
            LoadedTileLibraryUnit(unit=unit, selected_variant_id=unit.default_variant_id)
            for unit in units
        )

    @classmethod
    def from_loaded_units(cls, loaded_units: Iterable[LoadedTileLibraryUnit]) -> TileLibraryRegistry:
        loaded_units_by_id: dict[str, LoadedTileLibraryUnit] = {}
        construction_entries_by_id: dict[str, tuple[str, Construction]] = {}
        alias_unit_ids: dict[str, str] = {}
        tile_unit_ids: dict[str, str] = {}
        common_tile_width: int | None = None
        common_tile_height: int | None = None
        common_render_step_width: int | None = None
        common_render_step_height: int | None = None
        for loaded_unit in loaded_units:
            unit = loaded_unit.unit
            existing_unit = loaded_units_by_id.get(unit.family_id)
            if existing_unit is not None:
                raise ValueError(f"Duplicate tile library unit id {unit.family_id!r}")
            loaded_units_by_id[unit.family_id] = loaded_unit
            if common_tile_width is None:
                common_tile_width = unit.tile_width
                common_tile_height = unit.tile_height
                common_render_step_width = loaded_unit.effective_render_step_width
                common_render_step_height = loaded_unit.effective_render_step_height
            else:
                if unit.tile_width != common_tile_width:
                    raise ValueError("All loaded tile families must share the same tile_width")
                if unit.tile_height != common_tile_height:
                    raise ValueError("All loaded tile families must share the same tile_height")
                if loaded_unit.effective_render_step_width != common_render_step_width:
                    raise ValueError("All loaded tile families must share the same render_step_width")
                if loaded_unit.effective_render_step_height != common_render_step_height:
                    raise ValueError("All loaded tile families must share the same render_step_height")
            for tile_id in unit.tiles:
                existing_tile_owner = tile_unit_ids.get(tile_id)
                if existing_tile_owner is not None:
                    raise ValueError(
                        f"Duplicate tile id across tile library units: {tile_id!r} "
                        f"owned by {existing_tile_owner!r} and {unit.family_id!r}"
                    )
                existing_alias_owner = alias_unit_ids.get(tile_id)
                if existing_alias_owner is not None and existing_alias_owner != unit.family_id:
                    raise ValueError(
                        f"Cross-unit ref collision between tile id and alias: {tile_id!r} "
                        f"owned by tile family {unit.family_id!r} and alias family {existing_alias_owner!r}"
                    )
                tile_unit_ids[tile_id] = unit.family_id
            for construction_id, construction in unit.constructions.items():
                existing_construction = construction_entries_by_id.get(construction_id)
                if existing_construction is not None:
                    raise ValueError(
                        f"Duplicate construction id across tile library units: {construction_id!r} "
                        f"owned by {existing_construction[0]!r} and {unit.family_id!r}"
                    )
                construction_entries_by_id[construction_id] = (unit.family_id, construction)
            for alias in unit.aliases:
                existing_alias_owner = alias_unit_ids.get(alias)
                if existing_alias_owner is not None:
                    raise ValueError(
                        f"Duplicate alias across tile library units: {alias!r} "
                        f"owned by {existing_alias_owner!r} and {unit.family_id!r}"
                    )
                existing_tile_owner = tile_unit_ids.get(alias)
                if existing_tile_owner is not None and existing_tile_owner != unit.family_id:
                    raise ValueError(
                        f"Cross-unit ref collision between tile id and alias: {alias!r} "
                        f"owned by tile family {existing_tile_owner!r} and alias family {unit.family_id!r}"
                    )
                alias_unit_ids[alias] = unit.family_id
        if (
            common_tile_width is None
            or common_tile_height is None
            or common_render_step_width is None
            or common_render_step_height is None
        ):
            raise ValueError("Tile library registry requires at least one loaded unit")
        return cls(
            loaded_units_by_id=MappingProxyType(dict(loaded_units_by_id)),
            construction_entries_by_id=MappingProxyType(dict(construction_entries_by_id)),
            alias_unit_ids=MappingProxyType(dict(alias_unit_ids)),
            tile_unit_ids=MappingProxyType(dict(tile_unit_ids)),
            tile_width=common_tile_width,
            tile_height=common_tile_height,
            render_step_width=common_render_step_width,
            render_step_height=common_render_step_height,
        )

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(self.loaded_units_by_id.keys())

    def loaded_unit(self, unit_id: str) -> LoadedTileLibraryUnit | None:
        return self.loaded_units_by_id.get(unit_id)

    def unit(self, unit_id: str) -> TileLibraryUnit | None:
        loaded_unit = self.loaded_unit(unit_id)
        if loaded_unit is None:
            return None
        return loaded_unit.unit

    def unit_for_construction(self, construction_id: str) -> TileLibraryUnit | None:
        entry = self.construction_entries_by_id.get(construction_id)
        if entry is None:
            return None
        unit_id, _construction = entry
        return self.loaded_units_by_id[unit_id].unit

    def alias_owner(self, alias: str) -> TileLibraryUnit | None:
        unit_id = self.alias_unit_ids.get(alias)
        if unit_id is None:
            return None
        return self.loaded_units_by_id[unit_id].unit

    def tile_owner(self, tile_id: str) -> TileLibraryUnit | None:
        unit_id = self.tile_unit_ids.get(tile_id)
        if unit_id is None:
            return None
        return self.loaded_units_by_id[unit_id].unit

    def unit_for_ref(self, ref: str) -> TileLibraryUnit | None:
        loaded_unit = self.loaded_unit_for_ref(ref)
        if loaded_unit is None:
            return None
        return loaded_unit.unit

    def loaded_unit_for_ref(self, ref: str) -> LoadedTileLibraryUnit | None:
        variant_match = VARIANT_TILE_RE.match(ref)
        if variant_match is not None:
            return self.loaded_unit(variant_match.group("family"))
        physical_match = PHYSICAL_TILE_RE.match(ref)
        if physical_match is not None:
            return self.loaded_unit(physical_match.group("family"))
        tile_owner = self.tile_owner(ref)
        if tile_owner is not None:
            return self.loaded_unit(tile_owner.family_id)
        alias_owner = self.alias_owner(ref)
        if alias_owner is None:
            return None
        return self.loaded_unit(alias_owner.family_id)

    def resolve_ref(
        self,
        ref: str,
        *,
        default_unit_id: str | None = None,
    ) -> ResolvedFamilyTile | None:
        loaded_unit = self.loaded_unit_for_ref(ref)
        if loaded_unit is not None:
            return loaded_unit.resolve_ref(ref)
        if default_unit_id is None:
            return None
        default_loaded_unit = self.loaded_unit(default_unit_id)
        if default_loaded_unit is None:
            return None
        return default_loaded_unit.resolve_ref(ref)

    def lookup_construction(self, construction_id: str) -> Construction | None:
        entry = self.construction_entries_by_id.get(construction_id)
        if entry is None:
            return None
        return entry[1]

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return None
        return unit.entity_template(construction_id)

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return ()
        return unit.attachment_sets_for_construction(construction_id)

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return None
        unit.variant(variant_id)
        return unit.runtime_tileset_id(variant_id)


def tile_record_to_dict(tile: TileRecord) -> TileRecordData:
    return cast(TileRecordData, {field.name: getattr(tile, field.name) for field in fields(TileRecord)})


def _resolved_family_tile(
    *,
    family_id: str,
    root: Path,
    tile: TileRecord,
    variant_id: str,
) -> ResolvedFamilyTile:
    return ResolvedFamilyTile(
        family_id=family_id,
        variant_id=variant_id,
        tile_id=tile.id,
        sheet_col=tile.sheet_col,
        sheet_row=tile.sheet_row,
        image_override_path=(
            _resolve_tile_image_override_path(
                root=root,
                image_override=tile.image_override,
                variant_id=variant_id,
            )
            if tile.image_override is not None
            else None
        ),
    )


def _resolve_family_ref(
    *,
    family_id: str,
    root: Path,
    default_variant_id: str,
    variants: Mapping[str, TileFamilyVariant],
    tiles: Mapping[str, TileRecord],
    aliases: Mapping[str, str],
    tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord],
    ref: str,
    variant_id: str | None = None,
) -> ResolvedFamilyTile | None:
    resolved_variant_id = variant_id or default_variant_id

    variant_match = VARIANT_TILE_RE.match(ref)
    if variant_match:
        if variant_match.group("family") != family_id:
            return None
        explicit_variant_id = variant_match.group("variant")
        if explicit_variant_id not in variants:
            raise ValueError(f"Unknown variant ref: {ref}")
        tile = tiles_by_sheet_cell.get((int(variant_match.group("col")), int(variant_match.group("row"))))
        if tile is None:
            return None
        return _resolved_family_tile(
            family_id=family_id,
            root=root,
            tile=tile,
            variant_id=explicit_variant_id,
        )

    physical_match = PHYSICAL_TILE_RE.match(ref)
    if physical_match:
        if physical_match.group("family") != family_id:
            return None
        tile = tiles_by_sheet_cell.get((int(physical_match.group("col")), int(physical_match.group("row"))))
        if tile is None:
            return None
        return _resolved_family_tile(
            family_id=family_id,
            root=root,
            tile=tile,
            variant_id=resolved_variant_id,
        )

    tile = tiles.get(ref)
    if tile is None:
        alias_target = aliases.get(ref)
        if alias_target is None:
            return None
        tile = tiles.get(alias_target)
        if tile is None:
            return None
    return _resolved_family_tile(
        family_id=family_id,
        root=root,
        tile=tile,
        variant_id=resolved_variant_id,
    )


def _cluster_bounds_from_raw(raw_bounds: ClusterBoundsConfig | None) -> GridBounds | None:
    if raw_bounds is None:
        return None
    return GridBounds(
        x=int(raw_bounds["x"]),
        y=int(raw_bounds["y"]),
        width=int(raw_bounds["width"]),
        height=int(raw_bounds["height"]),
    )


def _require_cluster_bounds(raw_bounds: ClusterBoundsConfig | None, *, context: str) -> GridBounds:
    bounds = _cluster_bounds_from_raw(raw_bounds)
    if bounds is None:
        raise ValueError(f"{context} must define bounds")
    return bounds


def _bounds_contains(bounds: GridBounds, col: int, row: int) -> bool:
    return bounds.x <= col < bounds.x + bounds.width and bounds.y <= row < bounds.y + bounds.height


def format_sheet_cell_ref(col: int, row: int) -> str:
    return f"sheet:{col},{row}"


def _sheet_cell_from_ref(ref: str) -> SheetCell | None:
    match = SHEET_CELL_RE.match(ref)
    if match is None:
        return None
    return SheetCell(col=int(match.group("col")), row=int(match.group("row")))


def _sheet_cell_ref_within_bounds(ref: str, bounds: GridBounds) -> bool:
    cell = _sheet_cell_from_ref(ref)
    if cell is None:
        return False
    return _bounds_contains(bounds, cell.col, cell.row)


def _load_ingestion_collection_members(
    raw_members: object,
    *,
    context: str,
) -> tuple[SourceLayoutCollectionMember, ...]:
    members: list[SourceLayoutCollectionMember] = []
    for index, raw_member in enumerate(require_list(raw_members, context=context)):
        member_context = f"{context}[{index}]"
        mapping = require_mapping(raw_member, context=member_context)
        if set(mapping) == {"tile_id"}:
            members.append(SourceLayoutCollectionMember(kind="tile_id", value=str(mapping["tile_id"])))
            continue
        if set(mapping) == {"alias"}:
            members.append(SourceLayoutCollectionMember(kind="alias", value=str(mapping["alias"])))
            continue
        if set(mapping) == {"sheet_cell"}:
            cell_mapping = require_mapping(mapping["sheet_cell"], context=f"{member_context}.sheet_cell")
            check_required_keys(cell_mapping, ("col", "row"), context=f"{member_context}.sheet_cell")
            col = int(cast(Union[int, str], cell_mapping["col"]))
            row = int(cast(Union[int, str], cell_mapping["row"]))
            members.append(
                SourceLayoutCollectionMember(
                    kind="sheet_cell",
                    value=SheetCell(col=col, row=row),
                )
            )
            continue
        raise ValueError(
            f"{member_context} must be exactly one of {{tile_id}}, {{alias}}, or {{sheet_cell}}"
        )
    return tuple(members)


def collection_member_ref(member: SourceLayoutCollectionMember) -> str:
    if member.kind == "sheet_cell":
        cell = cast(SheetCell, member.value)
        return cell.ref
    return cast(str, member.value)


def collection_member_to_config(member: SourceLayoutCollectionMember) -> SourceLayoutCollectionMemberConfig:
    if member.kind == "tile_id":
        return {"tile_id": cast(str, member.value)}
    if member.kind == "alias":
        return {"alias": cast(str, member.value)}
    cell = cast(SheetCell, member.value)
    return {"sheet_cell": {"col": cell.col, "row": cell.row}}


def _source_layout_region_areas(region: SourceLayoutRegion) -> tuple[GridBounds, ...]:
    return region.areas or (region.bounds,)


def _source_layout_region_contains_cell(region: SourceLayoutRegion, col: int, row: int) -> bool:
    return any(_bounds_contains(area, col, row) for area in _source_layout_region_areas(region))


def _source_layout_region_contains_bounds(region: SourceLayoutRegion, bounds: GridBounds) -> bool:
    return any(
        area.x <= bounds.x
        and area.y <= bounds.y
        and bounds.x + bounds.width <= area.x + area.width
        and bounds.y + bounds.height <= area.y + area.height
        for area in _source_layout_region_areas(region)
    )


def _normalise_query_values(raw: object) -> set[str]:
    if isinstance(raw, str):
        return {raw}
    if not isinstance(raw, Iterable):
        raise TypeError(
            f"query value must be str or iterable of str, got {type(raw).__name__}"
        )
    return {str(value) for value in cast(Iterable[object], raw)}


def _non_empty_tiles_from_mask(mask: list[list[bool]]) -> list[dict[str, int]]:
    rows = len(mask)
    columns = len(mask[0]) if mask else 0
    return [
        {"col": col, "row": row}
        for row in range(rows)
        for col in range(columns)
        if mask[row][col]
    ]


def _unknown_query_field_error(raw_key: str) -> TypeError:
    suggestion = get_close_matches(
        raw_key.removesuffix("_all").removesuffix("_any"),
        list(TILE_QUERY_FIELDS_FOR_SUGGESTION),
        n=1,
    )
    if suggestion:
        return TypeError(f"Unknown tile query field {raw_key!r}; did you mean {suggestion[0]!r}?")
    return TypeError(f"Unknown tile query field {raw_key!r}")


def _meaning_is_uncertain(meaning: str | None) -> bool:
    if meaning is None:
        return False
    lower = meaning.lower()
    return any(marker in lower for marker in ("uncertain", "first-pass", "likely", "provisional"))


def _normalise_meaning_confidence(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context} meaning_confidence must be a string when present")
    if value not in MEANING_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(MEANING_CONFIDENCE_VALUES))
        raise ValueError(f"{context} meaning_confidence must be one of: {allowed}")
    return value


def _tile_image_bytes(
    *,
    variant: TileFamilyVariant,
    sheet_col: int | None,
    sheet_row: int | None,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
    image_override_path: Path | None = None,
) -> bytes:
    if image_override_path is not None:
        image = image_cache.get(image_override_path)
        if image is None:
            image = Image.open(image_override_path).convert("RGBA")
            image_cache[image_override_path] = image
        if image.size != (tile_width, tile_height):
            raise ValueError(
                f"Derived tile image {image_override_path} is {image.size}, expected {(tile_width, tile_height)}"
            )
        return image.tobytes()

    image = image_cache.get(variant.sheet_path)
    if image is None:
        image = Image.open(variant.sheet_path).convert("RGBA")
        image_cache[variant.sheet_path] = image
    if sheet_col is None or sheet_row is None:
        raise ValueError("Sheet-backed tile image lookup requires sheet_col and sheet_row")
    left = sheet_col * tile_width
    top = sheet_row * tile_height
    right = left + tile_width
    bottom = top + tile_height
    return image.crop((left, top, right, bottom)).tobytes()


def _resolve_tile_image_override_path(*, root: Path, image_override: str, variant_id: str) -> Path:
    return resolve_path(root, image_override.format(variant_id=variant_id))


def _sheet_bounds_for_variant(
    *,
    variant: TileFamilyVariant,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
) -> GridBounds:
    image = image_cache.get(variant.sheet_path)
    if image is None:
        image = Image.open(variant.sheet_path).convert("RGBA")
        image_cache[variant.sheet_path] = image
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError(
            f"Variant sheet {variant.sheet_path} size {image.width}x{image.height} is not aligned to"
            f" tile size {tile_width}x{tile_height}"
        )
    return GridBounds(
        x=0,
        y=0,
        width=image.width // tile_width,
        height=image.height // tile_height,
    )


_OPPOSITE: dict[str, str] = {
    "east": "west",
    "west": "east",
    "north": "south",
    "south": "north",
}


def _validate_metatile_construction(construction: MetatileConstruction) -> None:
    rows = construction.cells
    n_rows = len(rows)
    for row_idx, row in enumerate(rows):
        for col_idx, cell in enumerate(row):
            if cell is None:
                continue
            for direction, d_row, d_col in (("east", 0, 1), ("south", 1, 0)):
                n_row = row_idx + d_row
                n_col = col_idx + d_col
                if not (0 <= n_row < n_rows and 0 <= n_col < len(rows[n_row])):
                    continue
                neighbour = rows[n_row][n_col]
                if neighbour is None:
                    continue
                if direction not in cell.connects_on:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} cell (col={col_idx}, row={row_idx})"
                        f" must include {direction!r} in connects_on to connect with"
                        f" neighbour at (col={n_col}, row={n_row})"
                    )
                opposite = _OPPOSITE[direction]
                if opposite not in neighbour.connects_on:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} cell (col={n_col}, row={n_row})"
                        f" must include {opposite!r} in connects_on to connect with"
                        f" neighbour at (col={col_idx}, row={row_idx})"
                    )
            for direction, d_row, d_col in (
                ("north", -1, 0),
                ("south", 1, 0),
                ("east", 0, 1),
                ("west", 0, -1),
            ):
                if direction not in cell.requires_exposed_on:
                    continue
                n_row = row_idx + d_row
                n_col = col_idx + d_col
                if not (0 <= n_row < n_rows and 0 <= n_col < len(rows[n_row])):
                    continue
                neighbour = rows[n_row][n_col]
                if neighbour is not None:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} cell (col={col_idx}, row={row_idx})"
                        f" requires_exposed_on={list(cell.requires_exposed_on)!r}"
                        f" but internal neighbour at (col={n_col}, row={n_row}) is filled"
                    )


def _validate_parametric_run_construction(construction: ParametricRunConstruction) -> None:
    cid = construction.id
    start = construction.start_tile
    repeat = construction.repeat_tile
    end = construction.end_tile
    axis = construction.axis
    if axis == "x":
        forward, backward = "east", "west"
    else:
        forward, backward = "south", "north"
    # start must connect forward into repeat
    if forward not in start.connects_on:
        raise ConstructionValidationError(
            f"construction {cid!r} start_role tile {start.id!r}"
            f" must include {forward!r} in connects_on to connect with repeat tile"
        )
    if backward not in repeat.connects_on:
        raise ConstructionValidationError(
            f"construction {cid!r} repeat_role tile {repeat.id!r}"
            f" must include {backward!r} in connects_on to connect with start tile"
        )
    # repeat must connect forward into repeat (repeat–repeat boundary)
    if forward not in repeat.connects_on:
        raise ConstructionValidationError(
            f"construction {cid!r} repeat_role tile {repeat.id!r}"
            f" must include {forward!r} in connects_on for repeat–repeat adjacency"
        )
    # repeat must connect forward into end
    if backward not in end.connects_on:
        raise ConstructionValidationError(
            f"construction {cid!r} end_role tile {end.id!r}"
            f" must include {backward!r} in connects_on to connect with repeat tile"
        )


def _validate_parametric_frame_construction(construction: ParametricFrameConstruction) -> None:
    if not construction.corners:
        raise ConstructionValidationError(
            f"construction {construction.id!r} parametric_frame must declare at least one corner"
        )
    if construction.min_width < 2 or construction.min_height < 2:
        raise ConstructionValidationError(
            f"construction {construction.id!r} parametric_frame min_width/min_height must be >= 2"
        )


def validate_construction(construction: Construction) -> None:
    if isinstance(construction, ParametricRunConstruction):
        _validate_parametric_run_construction(construction)
    elif isinstance(construction, ParametricFrameConstruction):
        _validate_parametric_frame_construction(construction)
    else:
        _validate_metatile_construction(construction)


def _resolve_role(
    role: str,
    *,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
) -> TileRecord:
    matches = [
        t for t in tiles.values()
        if t.compose_group == collection_id and t.compose_role == role
    ]
    if len(matches) > 1:
        ids = [t.id for t in matches]
        raise ValueError(
            f"construction {construction_id!r} role {role!r}: "
            f"multiple tiles match compose_group={collection_id!r} + compose_role={role!r}: {ids}"
        )
    if not matches:
        raise ValueError(
            f"construction {construction_id!r} role {role!r}: "
            f"no tile found with compose_group={collection_id!r} + compose_role={role!r}"
        )
    return matches[0]


def _parse_expose_as_entity(
    raw: Mapping[str, object], construction_id: str, *, default: bool = True
) -> bool:
    expose_as_entity = raw.get("expose_as_entity", default)
    if not isinstance(expose_as_entity, bool):
        raise ValueError(f"construction {construction_id!r} expose_as_entity must be a boolean")
    return expose_as_entity


def _build_metatile_construction(
    raw: MetatileConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> MetatileConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]
    raw_rows = raw["cells"]

    if not raw_rows:
        raise ValueError(f"construction {construction_id!r} has no rows in cells")

    row_width = len(raw_rows[0])
    for row_idx, raw_row in enumerate(raw_rows):
        if len(raw_row) != row_width:
            raise ValueError(
                f"construction {construction_id!r} has ragged cells: "
                f"row 0 has {row_width} columns, row {row_idx} has {len(raw_row)}"
            )

    resolved_rows: list[tuple[TileRecord | None, ...]] = []
    for raw_row in raw_rows:
        resolved_cells: list[TileRecord | None] = []
        for raw_cell in raw_row:
            if raw_cell == ".":
                resolved_cells.append(None)
                continue
            if not isinstance(raw_cell, dict):
                raise ValueError(
                    f"construction {construction_id!r} cell must be a dict with 'role' or the string '.'"
                )
            role = str(raw_cell["role"])
            resolved_cells.append(_resolve_role(role, construction_id=construction_id, collection_id=collection_id, tiles=tiles))
        resolved_rows.append(tuple(resolved_cells))

    construction = MetatileConstruction(
        id=construction_id,
        collection_id=collection_id,
        cells=tuple(resolved_rows),
        expose_as_entity=_parse_expose_as_entity(raw, construction_id),
    )
    validate_construction(construction)
    return construction


def _build_parametric_run_construction(
    raw: ParametricRunConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> ParametricRunConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]
    axis = raw["axis"]
    if axis not in ("x", "y"):
        raise ValueError(
            f"construction {construction_id!r} parametric_run axis must be 'x' or 'y', got {axis!r}"
        )
    length_param = raw["length_param"]

    start_tile = _resolve_role(raw["start_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    repeat_tile = _resolve_role(raw["repeat_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    end_tile = _resolve_role(raw["end_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)

    construction = ParametricRunConstruction(
        id=construction_id,
        collection_id=collection_id,
        axis=axis,
        length_param=length_param,
        start_tile=start_tile,
        repeat_tile=repeat_tile,
        end_tile=end_tile,
        expose_as_entity=_parse_expose_as_entity(raw, construction_id),
    )
    validate_construction(construction)
    return construction


def _frame_slot(
    raw_slot: object,
    *,
    role: str,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
) -> FrameSlot:
    if not isinstance(raw_slot, Mapping):
        raise ValueError(
            f"construction {construction_id!r} slot {role!r} must be a mapping with optional "
            f"'fill_mode'; got {type(raw_slot).__name__}"
        )
    slot_mapping: Mapping[str, object] = cast(Mapping[str, object], raw_slot)
    fill_mode = str(slot_mapping.get("fill_mode", "repeat"))
    if fill_mode not in FRAME_FILL_MODES:
        raise ValueError(
            f"construction {construction_id!r} slot {role!r} has invalid fill_mode {fill_mode!r}; "
            f"expected one of {FRAME_FILL_MODES}"
        )
    flip_x = bool(slot_mapping.get("flip_x", False))
    flip_y = bool(slot_mapping.get("flip_y", False))
    raw_tile = slot_mapping.get("tile")
    if raw_tile is not None:
        tile_id = str(raw_tile)
        if tile_id not in tiles:
            raise ValueError(f"construction {construction_id!r} slot {role!r} references unknown tile {tile_id!r}")
        tile = tiles[tile_id]
    else:
        # An explicit 'role' lets one edge borrow the opposite edge's art
        # (e.g. edge_right resolves edge_left's tile, then flips it).
        resolve_role = str(slot_mapping.get("role", role))
        tile = _resolve_role(resolve_role, construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    return FrameSlot(tile=tile, fill_mode=fill_mode, flip_x=flip_x, flip_y=flip_y)


def _frame_corner_slot(
    key: str,
    raw_corner: object,
    *,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
) -> FrameCornerSlot:
    """Resolve one corner slot.

    List-form sugar (``raw_corner is None``) resolves a single tile by the
    canonical ``corner_<key>`` role. The dict form takes an optional ``role``
    (single 1x1 tile) or a ``cells`` grid (fat corner), plus ``flip_x``/
    ``flip_y`` to derive a corner from another's art.
    """
    default_role = f"corner_{key}"

    def _tile(role: str) -> TileRecord:
        return _resolve_role(role, construction_id=construction_id, collection_id=collection_id, tiles=tiles)

    def _cell(token: str) -> TileRecord:
        # A fat-corner cell may name a tile by id (to borrow art already owned by
        # another kit) or by a compose role within this kit's collection.
        return tiles[token] if token in tiles else _tile(token)

    if raw_corner is None:
        return FrameCornerSlot(cells=((_tile(default_role),),))
    if not isinstance(raw_corner, Mapping):
        raise ValueError(
            f"construction {construction_id!r} corner {key!r} must be a mapping with "
            f"'role'/'cells' and optional flip_x/flip_y; got {type(raw_corner).__name__}"
        )
    corner_cfg = cast(Mapping[str, object], raw_corner)
    flip_x = bool(corner_cfg.get("flip_x", False))
    flip_y = bool(corner_cfg.get("flip_y", False))
    raw_tile = corner_cfg.get("tile")
    if raw_tile is not None:
        # Direct tile reference — lets a kit borrow another kit's corner art
        # (interchangeability) without re-binding compose roles.
        tile_id = str(raw_tile)
        if tile_id not in tiles:
            raise ValueError(
                f"construction {construction_id!r} corner {key!r} references unknown tile {tile_id!r}"
            )
        return FrameCornerSlot(cells=((tiles[tile_id],),), flip_x=flip_x, flip_y=flip_y)
    raw_cells = corner_cfg.get("cells")
    if raw_cells is not None:
        if not isinstance(raw_cells, list) or not raw_cells:
            raise ValueError(f"construction {construction_id!r} corner {key!r} 'cells' must be a non-empty grid")
        grid: list[tuple[TileRecord | None, ...]] = []
        width: int | None = None
        for raw_row in cast(list[object], raw_cells):
            if not isinstance(raw_row, list):
                raise ValueError(f"construction {construction_id!r} corner {key!r} 'cells' rows must be lists")
            row: list[object] = cast(list[object], raw_row)
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ValueError(f"construction {construction_id!r} corner {key!r} has a ragged 'cells' grid")
            grid.append(tuple(None if r == "." else _cell(str(r)) for r in row))
        return FrameCornerSlot(cells=tuple(grid), flip_x=flip_x, flip_y=flip_y)
    role = str(corner_cfg.get("role", default_role))
    return FrameCornerSlot(cells=((_tile(role),),), flip_x=flip_x, flip_y=flip_y)


def _build_parametric_frame_construction(
    raw: ParametricFrameConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> ParametricFrameConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]

    corners: dict[str, FrameCornerSlot] = {}
    raw_corners = raw.get("corners", [])
    if isinstance(raw_corners, Mapping):
        corner_items: list[tuple[str, object]] = [(key, raw_corners[key]) for key in raw_corners]
    else:
        corner_items = [(key, None) for key in raw_corners]
    for key, raw_corner in corner_items:
        corners[f"corner_{key}"] = _frame_corner_slot(
            key, raw_corner, construction_id=construction_id, collection_id=collection_id, tiles=tiles
        )

    edges: dict[str, FrameSlot] = {}
    for key, raw_slot in (raw.get("edges") or {}).items():
        role = f"edge_{key}"
        edges[role] = _frame_slot(
            raw_slot, role=role, construction_id=construction_id, collection_id=collection_id, tiles=tiles
        )

    fill: FrameSlot | None = None
    raw_fill = raw.get("fill")
    if raw_fill is not None:
        fill = _frame_slot(
            raw_fill, role="fill", construction_id=construction_id, collection_id=collection_id, tiles=tiles
        )

    construction = ParametricFrameConstruction(
        id=construction_id,
        collection_id=collection_id,
        corners=MappingProxyType(corners),
        edges=MappingProxyType(edges),
        fill=fill,
        min_width=int(raw.get("min_width", 2)),
        min_height=int(raw.get("min_height", 2)),
        width_param=str(raw.get("width_param", "width")),
        height_param=str(raw.get("height_param", "height")),
        expose_as_entity=_parse_expose_as_entity(cast(Mapping[str, object], raw), construction_id),
    )
    validate_construction(construction)
    return construction


def build_construction(
    raw: ConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> Construction:
    kind = raw["kind"]
    if kind == "parametric_run":
        return _build_parametric_run_construction(cast(ParametricRunConstructionConfig, raw), tiles=tiles)
    if kind == "parametric_frame":
        return _build_parametric_frame_construction(cast(ParametricFrameConstructionConfig, raw), tiles=tiles)
    return _build_metatile_construction(cast(MetatileConstructionConfig, raw), tiles=tiles)


def _construction_tiles(construction: Construction) -> tuple[TileRecord, ...]:
    if isinstance(construction, ParametricRunConstruction):
        return (
            construction.start_tile,
            construction.repeat_tile,
            construction.end_tile,
        )
    if isinstance(construction, ParametricFrameConstruction):
        tiles: list[TileRecord] = []
        for corner in construction.corners.values():
            tiles.extend(corner.tiles())
        tiles.extend(slot.tile for slot in construction.edges.values())
        if construction.fill is not None:
            tiles.append(construction.fill.tile)
        return tuple(tiles)
    return tuple(
        cell
        for row in construction.cells
        for cell in row
        if cell is not None
    )


def _construction_footprint_spec(construction: Construction) -> EntityFootprintSpec:
    if isinstance(construction, ParametricRunConstruction):
        if construction.axis == "x":
            width, height = 2, 1
        else:
            width, height = 1, 2
        return EntityFootprintSpec(
            mode="parametric_run",
            width=width,
            height=height,
            axis=construction.axis,
            length_param=construction.length_param,
            minimum_length=2,
        )
    if isinstance(construction, ParametricFrameConstruction):
        # Both axes are variable; width/height carry the minimum bounding box
        # (the 2-D analogue of parametric_run's minimum-length box).
        return EntityFootprintSpec(
            mode="parametric_frame",
            width=construction.min_width,
            height=construction.min_height,
            width_param=construction.width_param,
            height_param=construction.height_param,
        )
    width = len(construction.cells[0]) if construction.cells else 0
    height = len(construction.cells)
    return EntityFootprintSpec(
        mode="fixed",
        width=width,
        height=height,
    )


def entity_template_from_construction(
    construction: Construction,
    *,
    attachment_sets: Iterable[ConstructionAttachmentSet] = (),
) -> EntityTemplateRecord:
    tiles = _construction_tiles(construction)

    def _sorted_unique(values: Iterable[str | None]) -> tuple[str, ...]:
        return tuple(sorted({value for value in values if value}))

    return EntityTemplateRecord(
        id=construction.id,
        construction_id=construction.id,
        collection_id=construction.collection_id,
        kind=construction.kind,
        placement_anchor="top_left",
        compose_roles=_sorted_unique(tile.compose_role for tile in tiles),
        affordances=_sorted_unique(affordance for tile in tiles for affordance in tile.affordances),
        state_groups=_sorted_unique(tile.state_group for tile in tiles),
        animation_groups=_sorted_unique(tile.animation_group for tile in tiles),
        footprint=_construction_footprint_spec(construction),
        attachment_sets=tuple(attachment_set.to_entity_record() for attachment_set in attachment_sets),
    )


def _load_clusters(
    *,
    root: Path,
    clusters_data: Iterable[ClusterConfig],
) -> dict[str, TileClusterRecord]:
    clusters: dict[str, TileClusterRecord] = {}
    for spec in clusters_data:
        cluster_id = str(spec["id"])
        if cluster_id in clusters:
            raise ValueError(f"Duplicate cluster id in {root}: {cluster_id}")
        clusters[cluster_id] = TileClusterRecord(
            id=cluster_id,
            scope=str(spec.get("scope", "family")),
            members=_tuple(spec.get("members")),
            kind_guess=spec.get("kind_guess"),
            evidence=_tuple(spec.get("evidence")),
            source_label=spec.get("source_label"),
            source_notes=spec.get("source_notes"),
        )
    return clusters


def load_source_layout_from_path(ingestion_path: Path) -> SourceLayoutIngestion:
    ingestion_data = load_ingestion_manifest(ingestion_path)
    sheet_bounds = _require_cluster_bounds(ingestion_data.get("sheet_bounds"), context=f"{ingestion_path}: sheet_bounds")
    source_regions: dict[str, SourceLayoutRegion] = {}
    for spec in ingestion_data["regions"]:
        region_id = str(spec["id"])
        if region_id in source_regions:
            raise ValueError(f"Duplicate ingestion region id in {ingestion_path}: {region_id}")
        bounds = _require_cluster_bounds(spec.get("bounds"), context=f"{ingestion_path}: region {region_id} bounds")
        if not _bounds_inside(sheet_bounds, bounds):
            raise ValueError(f"Ingestion region {region_id} falls outside sheet bounds in {ingestion_path}")
        area_specs = spec.get("areas", [])
        typed_areas = tuple(
            _require_cluster_bounds(
                area,
                context=f"{ingestion_path}: region {region_id} area {area_index}",
            )
            for area_index, area in enumerate(area_specs, start=1)
        )
        for area in typed_areas:
            if not _bounds_inside(sheet_bounds, area):
                raise ValueError(f"Ingestion region {region_id} area falls outside sheet bounds in {ingestion_path}")
            if not _bounds_inside(bounds, area):
                raise ValueError(f"Ingestion region {region_id} area falls outside region bounds in {ingestion_path}")
        source_regions[region_id] = SourceLayoutRegion(
            id=region_id,
            bounds=bounds,
            areas=typed_areas,
            label=spec.get("label"),
            notes=spec.get("notes"),
            ingest_tiles=bool(spec.get("ingest_tiles", True)),
        )

    source_clusters: dict[str, SourceLayoutCluster] = {}
    for spec in ingestion_data["clusters"]:
        cluster_id = str(spec["id"])
        if cluster_id in source_clusters:
            raise ValueError(f"Duplicate ingestion cluster id in {ingestion_path}: {cluster_id}")
        region_id = str(spec["source_region_id"])
        if region_id not in source_regions:
            raise ValueError(f"Ingestion cluster {cluster_id} references unknown ingestion region {region_id!r}")
        bounds = _require_cluster_bounds(spec.get("bounds"), context=f"{ingestion_path}: cluster {cluster_id} bounds")
        if not _bounds_inside(sheet_bounds, bounds):
            raise ValueError(f"Ingestion cluster {cluster_id} falls outside sheet bounds in {ingestion_path}")
        source_clusters[cluster_id] = SourceLayoutCluster(
            id=cluster_id,
            source_region_id=region_id,
            bounds=bounds,
            label=spec.get("label"),
            notes=spec.get("notes"),
            split_axis=spec.get("split_axis"),
            ingest_tiles=bool(spec.get("ingest_tiles", True)),
        )

    ignored_regions: dict[str, SourceLayoutIgnoreRegion] = {}
    for spec in ingestion_data.get("ignore_regions", []):
        ignore_id = str(spec["id"])
        if ignore_id in ignored_regions:
            raise ValueError(f"Duplicate ingestion ignore region id in {ingestion_path}: {ignore_id}")
        bounds = _require_cluster_bounds(spec.get("bounds"), context=f"{ingestion_path}: ignore region {ignore_id} bounds")
        if not _bounds_inside(sheet_bounds, bounds):
            raise ValueError(f"Ingestion ignore region {ignore_id} falls outside sheet bounds in {ingestion_path}")
        ignored_regions[ignore_id] = SourceLayoutIgnoreRegion(
            id=ignore_id,
            bounds=bounds,
            label=spec.get("label"),
            reason=spec.get("reason"),
        )

    source_collections: dict[str, SourceLayoutCollection] = {}
    for spec in ingestion_data.get("collections", []):
        collection_id = str(spec["id"])
        if collection_id in source_collections:
            raise ValueError(f"Duplicate ingestion collection id in {ingestion_path}: {collection_id}")
        raw_region_id = spec.get("source_region_id")
        raw_cluster_id = spec.get("source_cluster_id")
        region_id = str(raw_region_id) if raw_region_id is not None else None
        cluster_id = str(raw_cluster_id) if raw_cluster_id is not None else None
        if region_id is not None and region_id not in source_regions:
            raise ValueError(f"Ingestion collection {collection_id} references unknown ingestion region {region_id!r}")
        if cluster_id is not None and cluster_id not in source_clusters:
            raise ValueError(f"Ingestion collection {collection_id} references unknown ingestion cluster {cluster_id!r}")
        bounds = _cluster_bounds_from_raw(spec.get("bounds"))
        if bounds is not None and not _bounds_inside(sheet_bounds, bounds):
            raise ValueError(f"Ingestion collection {collection_id} bounds fall outside sheet bounds in {ingestion_path}")
        source_collections[collection_id] = SourceLayoutCollection(
            id=collection_id,
            kind=str(spec["kind"]),
            label=spec.get("label"),
            source_region_id=region_id,
            source_cluster_id=cluster_id,
            bounds=bounds,
            members=(
                _load_ingestion_collection_members(
                    spec.get("members"),
                    context=f"{ingestion_path}: collection {collection_id} members",
                )
                if spec.get("members") is not None
                else ()
            ),
            constructions=_tuple(cast(Iterable[str], spec.get("constructions")) if spec.get("constructions") is not None else None),
            notes=spec.get("notes"),
        )

    return SourceLayoutIngestion(
        sheet_bounds=sheet_bounds,
        source_regions=source_regions,
        source_clusters=source_clusters,
        ignored_regions=ignored_regions,
        source_collections=source_collections,
        notes=_tuple(ingestion_data.get("notes")),
    )


def _load_source_layout(
    *,
    root: Path,
    family_data: FamilyManifest,
) -> SourceLayoutIngestion | None:
    ingestion_spec_raw = family_data.get("ingestion_spec")
    ingestion_path = root / str(ingestion_spec_raw) if ingestion_spec_raw is not None else root / "ingestion.json"
    if ingestion_spec_raw is not None and not ingestion_path.exists():
        raise ValueError(f"Declared ingestion spec {ingestion_path} does not exist")
    if not ingestion_path.exists():
        return None
    return load_source_layout_from_path(ingestion_path)


def _validate_tile_override_images(
    *,
    root: Path,
    tiles: Mapping[str, TileRecord],
    variants: Mapping[str, TileFamilyVariant],
    tile_width: int,
    tile_height: int,
) -> None:
    override_image_cache: dict[Path, Image.Image] = {}
    for tile in tiles.values():
        if tile.image_override is None:
            continue
        for variant in variants.values():
            image_path = _resolve_tile_image_override_path(
                root=root,
                image_override=tile.image_override,
                variant_id=variant.id,
            )
            if not image_path.exists():
                raise ValueError(
                    f"Tile {tile.id} references missing image_override {tile.image_override!r} for variant {variant.id!r}"
                )
            image = override_image_cache.get(image_path)
            if image is None:
                image = Image.open(image_path).convert("RGBA")
                override_image_cache[image_path] = image
            if image.width <= 0 or image.height <= 0:
                raise ValueError(
                    f"Tile {tile.id} image_override {tile.image_override!r} is {image.size}, "
                    "expected a non-empty image"
                )


def _index_tiles_by_sheet_cell(tiles: Mapping[str, TileRecord]) -> dict[tuple[int, int], TileRecord]:
    tiles_by_sheet_cell: dict[tuple[int, int], TileRecord] = {}
    for tile in tiles.values():
        if tile.sheet_col is None or tile.sheet_row is None:
            continue
        key = (tile.sheet_col, tile.sheet_row)
        if key in tiles_by_sheet_cell:
            raise ValueError(
                f"Tiles {tiles_by_sheet_cell[key].id!r} and {tile.id!r} both claim sheet cell {key}"
            )
        tiles_by_sheet_cell[key] = tile
    return tiles_by_sheet_cell


def _validate_exact_duplicate_pixels(
    *,
    root: Path,
    tiles: Mapping[str, TileRecord],
    variants: Mapping[str, TileFamilyVariant],
    tile_width: int,
    tile_height: int,
) -> None:
    variant_image_cache: dict[Path, Image.Image] = {}
    for tile in tiles.values():
        if tile.exact_duplicate_of is None:
            continue
        canonical_tile = tiles[tile.exact_duplicate_of]
        for variant in variants.values():
            tile_bytes = _tile_image_bytes(
                variant=variant,
                sheet_col=tile.sheet_col,
                sheet_row=tile.sheet_row,
                tile_width=tile_width,
                tile_height=tile_height,
                image_cache=variant_image_cache,
                image_override_path=(
                    _resolve_tile_image_override_path(
                        root=root,
                        image_override=tile.image_override,
                        variant_id=variant.id,
                    )
                    if tile.image_override is not None
                    else None
                ),
            )
            canonical_bytes = _tile_image_bytes(
                variant=variant,
                sheet_col=canonical_tile.sheet_col,
                sheet_row=canonical_tile.sheet_row,
                tile_width=tile_width,
                tile_height=tile_height,
                image_cache=variant_image_cache,
                image_override_path=(
                    _resolve_tile_image_override_path(
                        root=root,
                        image_override=canonical_tile.image_override,
                        variant_id=variant.id,
                    )
                    if canonical_tile.image_override is not None
                    else None
                ),
            )
            if tile_bytes != canonical_bytes:
                raise ValueError(
                    f"Tile {tile.id} declares exact_duplicate_of {canonical_tile.id!r}, "
                    f"but their pixels differ in variant {variant.id!r}"
                )


def _validate_variant_sheet_bounds(
    *,
    variant_sheet_bounds: Mapping[str, GridBounds],
    family_sheet_bounds: GridBounds,
) -> None:
    for variant_id, bounds in variant_sheet_bounds.items():
        if not _bounds_inside(bounds, family_sheet_bounds):
            raise ValueError(
                f"Variant {variant_id!r} sheet bounds {bounds} do not cover family sheet bounds {family_sheet_bounds}"
            )


def _resolve_tiles_from_catalog(
    *,
    header: TileFamilyHeader,
    family_sheet_bounds: GridBounds,
    catalog: FamilyCatalogSources,
    aliases_by_tile: Mapping[str, tuple[str, ...]],
) -> dict[str, TileRecord]:
    raw_tile_specs: dict[str, TileConfig] = {}
    for spec in catalog.tiles_data:
        tile_id = str(spec["id"])
        if tile_id in raw_tile_specs:
            raise ValueError(f"Duplicate tile id in {header.root}: {tile_id}")
        raw_tile_specs[tile_id] = spec

    tiles: dict[str, TileRecord] = {}
    resolving_tile_ids: set[str] = set()

    def resolve_tile(tile_id: str) -> TileRecord:
        if tile_id in tiles:
            return tiles[tile_id]
        if tile_id in resolving_tile_ids:
            raise ValueError(f"Exact-duplicate cycle detected while resolving tile {tile_id!r}")
        if tile_id not in raw_tile_specs:
            raise ValueError(f"Unknown tile id {tile_id!r}")

        resolving_tile_ids.add(tile_id)
        try:
            spec = raw_tile_specs[tile_id]
            duplicate_of_raw = spec.get("exact_duplicate_of")
            inherited_tile: TileRecord | None = None
            resolved_duplicate_of: str | None = None
            if duplicate_of_raw is not None:
                resolved_duplicate_of = str(duplicate_of_raw)
                if resolved_duplicate_of == tile_id:
                    raise ValueError(f"Tile {tile_id} cannot exact_duplicate_of itself")
                if resolved_duplicate_of not in raw_tile_specs:
                    raise ValueError(
                        f"Tile {tile_id} references unknown exact_duplicate_of tile {resolved_duplicate_of!r}"
                    )
                inherited_tile = resolve_tile(resolved_duplicate_of)

            def inherited_scalar(field_name: str, default: object) -> object:
                if field_name in spec:
                    return spec.get(field_name)
                if inherited_tile is not None and field_name in EXACT_DUPLICATE_INHERITED_SCALAR_FIELDS:
                    return getattr(inherited_tile, field_name)
                return default

            def inherited_sequence(field_name: str) -> tuple[str, ...]:
                if field_name in spec:
                    raw_value = spec.get(field_name)
                    return _tuple(cast(Iterable[str], raw_value) if raw_value is not None else None)
                if inherited_tile is not None and field_name in EXACT_DUPLICATE_INHERITED_SEQUENCE_FIELDS:
                    return cast(tuple[str, ...], getattr(inherited_tile, field_name))
                return ()

            meaning_confidence_raw = (
                inherited_scalar("meaning_confidence", None)
                if inherited_tile is not None or "meaning_confidence" in spec
                else None
            )
            meaning_confidence = _normalise_meaning_confidence(meaning_confidence_raw, context=tile_id)
            walkable_raw = inherited_scalar("walkable", None)
            blocking_raw = inherited_scalar("blocking", None)
            cluster_ids_raw = spec.get("cluster_ids")
            noise_raw = inherited_scalar("noise", None)
            contrast_raw = inherited_scalar("contrast", None)
            temperature_raw = inherited_scalar("temperature", None)
            usage_raw = inherited_scalar("usage", None)
            style_raw = inherited_scalar("style", None)
            overlay_raw = inherited_scalar("overlay", None)
            footprint_raw = inherited_scalar("footprint", None)
            orientation_raw = inherited_scalar("orientation", None)
            facing_raw = inherited_scalar("facing", None)
            pose_raw = inherited_scalar("pose", None)
            compose_group_raw = inherited_scalar("compose_group", None)
            compose_role_raw = inherited_scalar("compose_role", None)
            state_group_raw = inherited_scalar("state_group", None)
            state_role_raw = inherited_scalar("state_role", None)
            animation_group_raw = inherited_scalar("animation_group", None)
            animation_frame_raw = inherited_scalar("animation_frame", None)
            animation_frame_count_raw = inherited_scalar("animation_frame_count", None)
            image_override_raw = inherited_scalar("image_override", None)
            meaning_raw = inherited_scalar("meaning", None)
            source_notes_raw = inherited_scalar("source_notes", None)
            raw_sheet_col = spec.get("sheet_col")
            raw_sheet_row = spec.get("sheet_row")
            image_override = cast(str, image_override_raw) if image_override_raw is not None else None
            if image_override is None:
                if raw_sheet_col is None or raw_sheet_row is None:
                    raise ValueError(f"Tile {tile_id} must define sheet_col and sheet_row")
                sheet_col = int(cast(Union[int, str], raw_sheet_col))
                sheet_row = int(cast(Union[int, str], raw_sheet_row))
                if not _bounds_contains(family_sheet_bounds, sheet_col, sheet_row):
                    raise ValueError(
                        f"Tile {tile_id} has sheet coordinate ({sheet_col}, {sheet_row}) outside family sheet bounds"
                    )
            else:
                if raw_sheet_col is not None or raw_sheet_row is not None:
                    raise ValueError(f"Synthetic tile {tile_id} must not define sheet_col or sheet_row")
                sheet_col = None
                sheet_row = None

            tile = TileRecord(
                id=tile_id,
                family_id=header.family_id,
                sheet_col=sheet_col,
                sheet_row=sheet_row,
                exact_duplicate_of=resolved_duplicate_of,
                image_override=image_override,
                layer=str(spec["layer"]),
                category=str(spec["category"]),
                transparent=bool(spec["transparent"]),
                tags=inherited_sequence("tags"),
                aliases=aliases_by_tile.get(tile_id, ()),
                walkable=cast(bool, walkable_raw) if walkable_raw is not None else None,
                blocking=cast(bool, blocking_raw) if blocking_raw is not None else None,
                scenes=inherited_sequence("scenes"),
                semantics=inherited_sequence("semantics"),
                motifs=inherited_sequence("motifs"),
                cluster_ids=_tuple(cast(Iterable[str], cluster_ids_raw) if cluster_ids_raw is not None else None),
                source_group=spec.get("source_group"),
                noise=cast(str, noise_raw) if noise_raw is not None else None,
                contrast=cast(str, contrast_raw) if contrast_raw is not None else None,
                temperature=cast(str, temperature_raw) if temperature_raw is not None else None,
                usage=cast(str, usage_raw) if usage_raw is not None else None,
                style=cast(str, style_raw) if style_raw is not None else None,
                overlay=cast(str, overlay_raw) if overlay_raw is not None else None,
                footprint=cast(str, footprint_raw) if footprint_raw is not None else None,
                orientation=cast(str, orientation_raw) if orientation_raw is not None else None,
                facing=cast(str, facing_raw) if facing_raw is not None else None,
                pose=cast(str, pose_raw) if pose_raw is not None else None,
                compose_group=cast(str, compose_group_raw) if compose_group_raw is not None else None,
                compose_role=cast(str, compose_role_raw) if compose_role_raw is not None else None,
                state_group=cast(str, state_group_raw) if state_group_raw is not None else None,
                state_role=cast(str, state_role_raw) if state_role_raw is not None else None,
                animation_group=cast(str, animation_group_raw) if animation_group_raw is not None else None,
                animation_frame=int(cast(Union[int, str], animation_frame_raw)) if animation_frame_raw is not None else None,
                animation_frame_count=int(cast(Union[int, str], animation_frame_count_raw))
                if animation_frame_count_raw is not None
                else None,
                connects_on=inherited_sequence("connects_on"),
                requires_exposed_on=inherited_sequence("requires_exposed_on"),
                affordances=inherited_sequence("affordances"),
                alt_uses=inherited_sequence("alt_uses"),
                meaning=cast(str, meaning_raw) if meaning_raw is not None else None,
                meaning_confidence=meaning_confidence,
                source_notes=cast(str, source_notes_raw) if source_notes_raw is not None else None,
            )
            tiles[tile_id] = tile
            return tile
        finally:
            resolving_tile_ids.remove(tile_id)

    for tile_id in raw_tile_specs:
        resolve_tile(tile_id)
    return tiles


def _validate_alias_targets(
    *,
    alias_map: Mapping[str, str],
    tiles: Mapping[str, TileRecord],
) -> None:
    for alias, tile_id in alias_map.items():
        if alias in tiles:
            raise ValueError(
                f"Alias {alias!r} collides with tile id of the same name in the loaded family"
            )
        if tile_id not in tiles:
            raise ValueError(f"Alias {alias!r} points at unknown tile id {tile_id!r}")


def _validate_clusters_against_tiles(
    *,
    clusters: Mapping[str, TileClusterRecord],
    tiles: Mapping[str, TileRecord],
) -> None:
    for cluster in clusters.values():
        for tile_id in cluster.members:
            if tile_id not in tiles:
                raise ValueError(f"Cluster {cluster.id} references unknown tile {tile_id!r}")
    for tile in tiles.values():
        for cluster_id in tile.cluster_ids:
            if cluster_id not in clusters:
                raise ValueError(f"Tile {tile.id} references unknown cluster {cluster_id!r}")


def _validate_source_layout_catalog_references(
    *,
    source_layout: SourceLayoutIngestion,
    tiles: Mapping[str, TileRecord],
    alias_map: Mapping[str, str],
) -> None:
    for source_cluster in source_layout.source_clusters.values():
        parent_region = source_layout.source_regions[source_cluster.source_region_id]
        if not _source_layout_region_contains_bounds(parent_region, source_cluster.bounds):
            raise ValueError(
                f"Ingestion cluster {source_cluster.id} falls outside ingestion region {source_cluster.source_region_id}"
            )
    for collection in source_layout.source_collections.values():
        for member in collection.members:
            member_ref = collection_member_ref(member)
            if member.kind == "tile_id":
                if member_ref not in tiles:
                    raise ValueError(
                        f"Ingestion collection {collection.id} references unknown member tile {member_ref!r}"
                    )
                continue
            if member.kind == "alias":
                if member_ref not in alias_map:
                    raise ValueError(
                        f"Ingestion collection {collection.id} references unknown member alias {member_ref!r}"
                    )
                continue
            if not _sheet_cell_ref_within_bounds(member_ref, source_layout.sheet_bounds):
                raise ValueError(
                    f"Ingestion collection {collection.id} references unknown member sheet cell {member_ref!r}"
                )


def load_constructions_from_data(
    constructions_data: tuple[ConstructionConfig, ...],
    *,
    constructions_path: Path | None,
    tiles: dict[str, TileRecord],
    source_layout: SourceLayoutIngestion | None,
) -> dict[str, Construction]:
    constructions: dict[str, Construction] = {}
    for raw_config in constructions_data:
        construction_id = str(raw_config["id"])
        constructions[construction_id] = build_construction(raw_config, tiles=tiles)

    if source_layout is not None:
        for collection in source_layout.source_collections.values():
            for construction_id in collection.constructions:
                if construction_id not in constructions:
                    if constructions_path is None:
                        raise ValueError(
                            f"Ingestion collection {collection.id!r} references unknown construction "
                            f"{construction_id!r}, but no constructions manifest was loaded"
                        )
                    raise ValueError(
                        f"Ingestion collection {collection.id!r} references unknown construction "
                        f"{construction_id!r} in {constructions_path}"
                    )
    return constructions


def _fixed_construction_bounds(construction: Construction, *, context: str) -> GridBounds:
    if isinstance(construction, ParametricRunConstruction):
        raise ValueError(f"{context} must reference a fixed metatile construction, not parametric_run {construction.id!r}")
    if isinstance(construction, ParametricFrameConstruction):
        raise ValueError(f"{context} must reference a fixed metatile construction, not parametric_frame {construction.id!r}")
    width = len(construction.cells[0]) if construction.cells else 0
    height = len(construction.cells)
    return GridBounds(x=0, y=0, width=width, height=height)


def _parse_attachment_param(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
) -> str:
    param_raw = raw["param"]
    if not isinstance(param_raw, str) or param_raw == "":
        raise ValueError(f"attachment set {attachment_id!r} param must be a non-empty string")
    return param_raw


def _parse_attachment_target_ids(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
) -> tuple[str, ...]:
    target_ids_raw = require_list(
        raw["target_construction_ids"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} target_construction_ids",
    )
    if not target_ids_raw:
        raise ValueError(f"attachment set {attachment_id!r} target_construction_ids must be a non-empty list")
    return tuple(str(value) for value in target_ids_raw)


def _parse_attachment_canvas(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
) -> GridBounds:
    canvas_raw = require_mapping(
        raw["canvas"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} canvas",
    )
    check_required_keys(canvas_raw, ("x", "y", "width", "height"), context=f"attachment set {attachment_id!r} canvas")
    canvas = GridBounds(
        x=int(cast(Union[int, str], canvas_raw["x"])),
        y=int(cast(Union[int, str], canvas_raw["y"])),
        width=int(cast(Union[int, str], canvas_raw["width"])),
        height=int(cast(Union[int, str], canvas_raw["height"])),
    )
    if canvas.x < 0 or canvas.y < 0 or canvas.width <= 0 or canvas.height <= 0:
        raise ValueError(f"attachment set {attachment_id!r} canvas must have non-negative origin and positive size")
    return canvas


def _validate_attachment_targets(
    *,
    attachment_id: str,
    target_ids: tuple[str, ...],
    canvas: GridBounds,
    constructions: Mapping[str, Construction],
) -> None:
    for target_id in target_ids:
        target_construction = constructions.get(target_id)
        if target_construction is None:
            raise ValueError(f"attachment set {attachment_id!r} references unknown target construction {target_id!r}")
        target_bounds = _fixed_construction_bounds(
            target_construction,
            context=f"attachment set {attachment_id!r} target {target_id!r}",
        )
        if not _bounds_inside(target_bounds, canvas):
            raise ValueError(
                f"attachment set {attachment_id!r} canvas {canvas} must stay inside target construction "
                f"{target_id!r} bounds {target_bounds}"
            )


def _parse_attachment_variants(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
    constructions: Mapping[str, Construction],
    canvas: GridBounds,
) -> Mapping[str, ConstructionAttachmentVariant]:
    raw_variants = require_list(
        raw["variants"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} variants",
    )
    if not raw_variants:
        raise ValueError(f"attachment set {attachment_id!r} must define at least one variant")
    variants: dict[str, ConstructionAttachmentVariant] = {}
    for index, raw_variant in enumerate(raw_variants):
        variant_context = f"attachment set {attachment_id!r} variants[{index}]"
        mapping = require_mapping(raw_variant, context=variant_context)
        check_required_keys(mapping, ("id", "construction_id"), context=variant_context)
        variant_id = str(mapping["id"])
        if variant_id in variants:
            raise ValueError(f"attachment set {attachment_id!r} declares duplicate variant id {variant_id!r}")
        construction_id = str(mapping["construction_id"])
        variant_construction = constructions.get(construction_id)
        if variant_construction is None:
            raise ValueError(
                f"attachment set {attachment_id!r} variant {variant_id!r} references unknown construction {construction_id!r}"
            )
        attachment_bounds = _fixed_construction_bounds(
            variant_construction,
            context=f"attachment set {attachment_id!r} variant {variant_id!r}",
        )
        if attachment_bounds.width > canvas.width or attachment_bounds.height > canvas.height:
            raise ValueError(
                f"attachment set {attachment_id!r} variant {variant_id!r} construction {construction_id!r} "
                f"size {attachment_bounds.width}x{attachment_bounds.height} exceeds canvas "
                f"{canvas.width}x{canvas.height}"
            )
        variants[variant_id] = ConstructionAttachmentVariant(
            id=variant_id,
            construction_id=construction_id,
            label=cast(str | None, mapping.get("label")),
            notes=cast(str | None, mapping.get("notes")),
        )
    return MappingProxyType(variants)


def _parse_attachment_default_variant_id(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    variants: Mapping[str, ConstructionAttachmentVariant],
) -> str | None:
    default_variant_id_raw = raw.get("default_variant_id")
    if default_variant_id_raw is None:
        return None
    default_variant_id = str(default_variant_id_raw)
    if default_variant_id == "":
        raise ValueError(f"attachment set {attachment_id!r} default_variant_id must be a non-empty string")
    if default_variant_id not in variants:
        raise ValueError(
            f"attachment set {attachment_id!r} default_variant_id {default_variant_id!r} "
            "must match a declared variant id"
        )
    return default_variant_id


def _parse_attachment_required(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
) -> bool:
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise ValueError(f"attachment set {attachment_id!r} required must be a boolean")
    return required


def load_attachment_sets_from_data(
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...],
    *,
    attachments_path: Path | None,
    constructions: Mapping[str, Construction],
) -> dict[str, ConstructionAttachmentSet]:
    attachment_sets: dict[str, ConstructionAttachmentSet] = {}
    for raw in attachments_data:
        attachment_id = str(raw["id"])
        param = _parse_attachment_param(raw, attachment_id=attachment_id)
        target_ids = _parse_attachment_target_ids(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
        )
        canvas = _parse_attachment_canvas(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
        )
        _validate_attachment_targets(
            attachment_id=attachment_id,
            target_ids=target_ids,
            canvas=canvas,
            constructions=constructions,
        )
        variants = _parse_attachment_variants(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
            constructions=constructions,
            canvas=canvas,
        )
        default_variant_id = _parse_attachment_default_variant_id(
            raw,
            attachment_id=attachment_id,
            variants=variants,
        )

        attachment_sets[attachment_id] = ConstructionAttachmentSet(
            id=attachment_id,
            param=param,
            target_construction_ids=target_ids,
            canvas=canvas,
            variants=variants,
            required=_parse_attachment_required(raw, attachment_id=attachment_id),
            default_variant_id=default_variant_id,
            label=raw.get("label"),
            notes=raw.get("notes"),
        )
    return attachment_sets


class TileFamily:
    def __init__(
        self,
        *,
        header: TileFamilyHeader,
        promoted_metadata: TileLibraryPromotedMetadata = EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
        source_layout: SourceLayoutIngestion | None,
        variants: dict[str, TileFamilyVariant],
        clusters: dict[str, TileClusterRecord],
        tiles: dict[str, TileRecord],
        aliases: dict[str, str],
        tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord] | None = None,
        constructions: Mapping[str, Construction] | None = None,
        attachment_sets: Mapping[str, ConstructionAttachmentSet] | None = None,
    ) -> None:
        self.header = header
        self.promoted_metadata = promoted_metadata
        self.source_layout = source_layout
        self.variants = MappingProxyType(dict(variants))
        self.clusters = MappingProxyType(dict(clusters))
        self.tiles = MappingProxyType(dict(tiles))
        self.aliases = MappingProxyType(dict(aliases))
        self.aliases_by_tile = _group_aliases_by_tile(aliases)
        self.tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord] = (
            MappingProxyType(dict(tiles_by_sheet_cell))
            if tiles_by_sheet_cell is not None
            else MappingProxyType({})
        )
        self.constructions: Mapping[str, Construction] = (
            MappingProxyType(dict(constructions)) if constructions is not None else MappingProxyType({})
        )
        self.attachment_sets: Mapping[str, ConstructionAttachmentSet] = (
            MappingProxyType(dict(attachment_sets)) if attachment_sets is not None else MappingProxyType({})
        )
        self.attachment_sets_by_target: Mapping[str, tuple[ConstructionAttachmentSet, ...]] = (
            attachment_sets_by_target(self.attachment_sets)
        )

    @property
    def root(self) -> Path:
        return self.header.root

    @property
    def family_id(self) -> str:
        return self.header.family_id

    @property
    def title(self) -> str | None:
        return self.header.title

    @property
    def tile_width(self) -> int:
        return self.header.tile_width

    @property
    def tile_height(self) -> int:
        return self.header.tile_height

    @property
    def render_step_width(self) -> int | None:
        return self.header.render_step_width

    @property
    def render_step_height(self) -> int | None:
        return self.header.render_step_height

    @property
    def siblings_share_semantics(self) -> bool:
        return bool(self.header.siblings_share_semantics)

    @property
    def notes(self) -> tuple[str, ...]:
        return self.header.notes or ()

    @property
    def default_variant_id(self) -> str:
        return self.header.default_variant_id

    @cached_property
    def runtime_unit(self) -> TileLibraryUnit:
        return TileLibraryUnit.from_family(self)

    def lookup_construction(self, construction_id: str) -> Construction | None:
        return self.constructions.get(construction_id)

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        return self.runtime_unit.entity_template(construction_id)

    def entity_templates(self) -> list[EntityTemplateRecord]:
        return self.runtime_unit.entity_templates()

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.runtime_unit.attachment_sets_for_construction(construction_id)

    @classmethod
    def from_catalog_sources(
        cls,
        *,
        header: TileFamilyHeader,
        variants: Mapping[str, TileFamilyVariant],
        catalog: FamilyCatalogSources,
        source_layout: SourceLayoutIngestion | None,
        promoted_metadata: TileLibraryPromotedMetadata = EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
    ) -> TileFamily:
        root = header.root
        if not variants:
            raise ValueError(f"Tile family {root} must define at least one variant")

        variant_sheet_image_cache: dict[Path, Image.Image] = {}
        variant_sheet_bounds = {
            variant_id: _sheet_bounds_for_variant(
                variant=variant,
                tile_width=header.tile_width,
                tile_height=header.tile_height,
                image_cache=variant_sheet_image_cache,
            )
            for variant_id, variant in variants.items()
        }
        family_sheet_bounds = source_layout.sheet_bounds if source_layout is not None else next(iter(variant_sheet_bounds.values()))

        clusters = _load_clusters(root=root, clusters_data=catalog.clusters_data)
        _validate_variant_sheet_bounds(
            variant_sheet_bounds=variant_sheet_bounds,
            family_sheet_bounds=family_sheet_bounds,
        )

        alias_map: dict[str, str] = {str(alias): str(target) for alias, target in catalog.aliases_data.items()}
        aliases_by_tile = _group_aliases_by_tile(alias_map)
        tiles = _resolve_tiles_from_catalog(
            header=header,
            family_sheet_bounds=family_sheet_bounds,
            catalog=catalog,
            aliases_by_tile=aliases_by_tile,
        )
        _validate_alias_targets(alias_map=alias_map, tiles=tiles)

        _validate_tile_override_images(
            root=root,
            tiles=tiles,
            variants=variants,
            tile_width=header.tile_width,
            tile_height=header.tile_height,
        )
        _validate_clusters_against_tiles(clusters=clusters, tiles=tiles)

        tiles_by_sheet_cell = _index_tiles_by_sheet_cell(tiles)
        _validate_exact_duplicate_pixels(
            root=root,
            tiles=tiles,
            variants=variants,
            tile_width=header.tile_width,
            tile_height=header.tile_height,
        )

        if source_layout is not None:
            _validate_source_layout_catalog_references(
                source_layout=source_layout,
                tiles=tiles,
                alias_map=alias_map,
            )

        if header.default_variant_id not in variants:
            raise ValueError(
                f"Unknown default_variant_id {header.default_variant_id!r} in family {header.family_id!r}"
            )

        constructions = load_constructions_from_data(
            catalog.constructions_data,
            constructions_path=catalog.paths.constructions_path,
            tiles=tiles,
            source_layout=source_layout,
        )
        attachment_sets = load_attachment_sets_from_data(
            catalog.attachments_data,
            attachments_path=catalog.paths.attachments_path,
            constructions=constructions,
        )

        return cls(
            header=header,
            promoted_metadata=promoted_metadata,
            source_layout=source_layout,
            variants=dict(variants),
            clusters=clusters,
            tiles=tiles,
            aliases=alias_map,
            tiles_by_sheet_cell=tiles_by_sheet_cell,
            constructions=constructions,
            attachment_sets=attachment_sets,
        )

    @classmethod
    def load(cls, family_dir: Path) -> TileFamily:
        root = family_dir.resolve()
        header, variants, family_data = load_family_header_and_variants(root)
        return cls.from_catalog_sources(
            header=header,
            variants=variants,
            catalog=load_family_catalog_sources(CompatibilityFamilyPaths.for_legacy_root(root)),
            source_layout=_load_source_layout(root=root, family_data=family_data),
        )

    def variant(self, variant_id: str | None = None) -> TileFamilyVariant:
        resolved_variant_id = variant_id or self.default_variant_id
        return self.variants[resolved_variant_id]

    def runtime_tileset_id(self, variant_id: str | None = None) -> str:
        resolved_variant_id = variant_id or self.default_variant_id
        return f"{self.family_id}@{resolved_variant_id}"

    def physical_tile_id(self, *, sheet_col: int, sheet_row: int) -> str:
        return f"{self.family_id}:{sheet_col},{sheet_row}"

    def variant_ref_for_tile(self, tile: TileRecord, *, variant_id: str | None = None) -> str:
        """Return the concrete variant ref, defaulting to the family's default variant when omitted."""
        resolved = self.resolve_ref(tile.id, variant_id=variant_id)
        if resolved is None:
            raise ValueError(f"Unable to resolve tile {tile.id!r} in family {self.family_id!r}")
        return resolved.variant_ref

    def by_id(self, tile_id: str) -> TileRecord:
        return self.tiles[tile_id]

    def by_alias(self, alias: str) -> TileRecord:
        return self.tiles[self.aliases[alias]]

    def canonical_tile_id(self, tile_id: str) -> str:
        seen: set[str] = set()
        current = tile_id
        while True:
            if current in seen:
                raise ValueError(f"Exact-duplicate cycle detected while resolving canonical tile for {tile_id!r}")
            seen.add(current)
            tile = self.tiles[current]
            if tile.exact_duplicate_of is None:
                return current
            current = tile.exact_duplicate_of

    def canonical_tile(self, tile_or_id: TileRecord | str) -> TileRecord:
        tile_id = tile_or_id.id if isinstance(tile_or_id, TileRecord) else tile_or_id
        return self.tiles[self.canonical_tile_id(tile_id)]

    def aliases_for_tile(self, tile_id: str) -> tuple[str, ...]:
        return self.aliases_by_tile.get(tile_id, ())

    def tile_at_sheet_cell(self, *, sheet_col: int, sheet_row: int) -> TileRecord | None:
        return self.tiles_by_sheet_cell.get((sheet_col, sheet_row))

    def _source_region_id_for_tile(self, tile: TileRecord) -> str | None:
        if self.source_layout is None or tile.sheet_col is None or tile.sheet_row is None:
            return None
        source_region = self.source_layout.source_region_for_cell(tile.sheet_col, tile.sheet_row)
        return None if source_region is None else source_region.id

    def source_region_id_for_tile(self, tile: TileRecord) -> str | None:
        return self._source_region_id_for_tile(tile)

    @staticmethod
    def _sheet_sort_key(tile: TileRecord) -> tuple[int, int, int, str]:
        sheet_row = tile.sheet_row if tile.sheet_row is not None else 10**9
        sheet_col = tile.sheet_col if tile.sheet_col is not None else 10**9
        return (1 if tile.sheet_row is None or tile.sheet_col is None else 0, sheet_row, sheet_col, tile.id)

    def summary(self) -> dict[str, object]:
        by_source_region: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_usage: dict[str, int] = {}
        by_noise: dict[str, int] = {}
        by_contrast: dict[str, int] = {}
        by_temperature: dict[str, int] = {}
        by_scene: dict[str, int] = {}
        tagged = 0
        for tile in self.tiles.values():
            bucket = self._source_region_id_for_tile(tile) or ("synthetic" if tile.sheet_col is None else "unmapped")
            by_source_region[bucket] = by_source_region.get(bucket, 0) + 1
            by_category[tile.category] = by_category.get(tile.category, 0) + 1
            if tile.usage is not None:
                by_usage[tile.usage] = by_usage.get(tile.usage, 0) + 1
            if tile.noise is not None:
                by_noise[tile.noise] = by_noise.get(tile.noise, 0) + 1
            if tile.contrast is not None:
                by_contrast[tile.contrast] = by_contrast.get(tile.contrast, 0) + 1
            if tile.temperature is not None:
                by_temperature[tile.temperature] = by_temperature.get(tile.temperature, 0) + 1
            for scene in tile.scenes:
                by_scene[scene] = by_scene.get(scene, 0) + 1
            if len(tile.tags) > 3:
                tagged += 1
        return {
            "family_id": self.family_id,
            "tile_count": len(self.tiles),
            "alias_count": len(self.aliases),
            "variant_count": len(self.variants),
            "cluster_count": len(self.clusters),
            "source_layout_region_count": 0 if self.source_layout is None else len(self.source_layout.source_regions),
            "source_layout_cluster_count": 0 if self.source_layout is None else len(self.source_layout.source_clusters),
            "source_layout_collection_count": 0 if self.source_layout is None else len(self.source_layout.source_collections),
            "by_source_region": dict(sorted(by_source_region.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_usage": dict(sorted(by_usage.items())),
            "by_noise": dict(sorted(by_noise.items())),
            "by_contrast": dict(sorted(by_contrast.items())),
            "by_temperature": dict(sorted(by_temperature.items())),
            "by_scene": dict(sorted(by_scene.items())),
            "semantically_tagged": tagged,
        }

    def ingest_report(self) -> TileFamilyIngestReport:
        by_source_region: dict[str, TileFamilyIngestSourceRegionReport] = {
            region_id: {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            }
            for region_id in (() if self.source_layout is None else self.source_layout.source_regions.keys())
        }
        by_source_region.setdefault(
            "synthetic",
            {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            },
        )
        by_source_region.setdefault(
            "unmapped",
            {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            },
        )
        by_cluster: dict[str, int] = {}
        by_meaning_confidence: dict[str, int] = {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)}
        missing_source_group: list[str] = []
        missing_cluster_ids: list[str] = []
        missing_meaning: list[str] = []
        missing_meaning_confidence: list[str] = []
        uncertain_meaning: list[str] = []

        for tile in self.tiles.values():
            bucket = self._source_region_id_for_tile(tile) or ("synthetic" if tile.sheet_col is None else "unmapped")
            region_report = by_source_region[bucket]
            region_report["total"] += 1
            if tile.source_group is None or not tile.source_group.strip():
                missing_source_group.append(tile.id)
                region_report["missing_source_group"] += 1
            if not tile.cluster_ids:
                missing_cluster_ids.append(tile.id)
                region_report["missing_cluster_ids"] += 1
            else:
                for cluster_id in tile.cluster_ids:
                    by_cluster[cluster_id] = by_cluster.get(cluster_id, 0) + 1
            if tile.meaning is None or not tile.meaning.strip():
                missing_meaning.append(tile.id)
                region_report["missing_meaning"] += 1
            confidence = tile.meaning_confidence
            if confidence is None or not confidence.strip():
                missing_meaning_confidence.append(tile.id)
                region_report["missing_meaning_confidence"] += 1
            else:
                by_meaning_confidence[confidence] = by_meaning_confidence.get(confidence, 0) + 1
                region_report["by_meaning_confidence"][confidence] = (
                    region_report["by_meaning_confidence"].get(confidence, 0) + 1
                )
            is_uncertain = (
                confidence in {"tentative", "unknown"}
                if confidence is not None
                else _meaning_is_uncertain(tile.meaning)
            )
            if tile.meaning is not None and tile.meaning.strip() and is_uncertain:
                uncertain_meaning.append(tile.id)
                region_report["uncertain_meaning"] += 1

        return {
            "family_id": self.family_id,
            "tile_count": len(self.tiles),
            "cluster_count": len(self.clusters),
            "complete": not (
                missing_source_group
                or missing_cluster_ids
                or missing_meaning
                or missing_meaning_confidence
            ),
            "missing_source_group": sorted(missing_source_group),
            "missing_cluster_ids": sorted(missing_cluster_ids),
            "missing_meaning": sorted(missing_meaning),
            "missing_meaning_confidence": sorted(missing_meaning_confidence),
            "uncertain_meaning": sorted(uncertain_meaning),
            "by_meaning_confidence": dict(sorted(by_meaning_confidence.items())),
            "by_source_region": dict(sorted(by_source_region.items())),
            "by_cluster": dict(sorted(by_cluster.items())),
        }

    def query(
        self,
        **query_kwargs: object,
    ) -> list[TileRecord]:
        """Return tiles matching the provided filters.

        Passing `None` omits a filter; it does not mean "match records whose field is None".
        Sequence fields use `*_all` / `*_any`, while singular convenience aliases like
        `scene=` and `semantic_cluster_id=` map onto their underlying tuple fields.
        """
        equality_filters: dict[str, object] = {}
        contains_all: dict[str, set[str]] = {}
        contains_any: dict[str, set[str]] = {}

        for raw_key, raw_value in query_kwargs.items():
            if raw_value is None:
                continue
            if raw_key == "cluster_id":
                raise TypeError("Ambiguous tile query field 'cluster_id'; use 'semantic_cluster_id' for semantic cluster membership")
            if raw_key in TILE_QUERY_ALIASES:
                contains_any[TILE_QUERY_ALIASES[raw_key]] = _normalise_query_values(raw_value)
                continue
            if raw_key.endswith("_all"):
                field_name = raw_key[:-4]
                if field_name not in TILE_SEQUENCE_FIELDS:
                    raise _unknown_query_field_error(raw_key)
                values = _normalise_query_values(raw_value)
                if values:
                    contains_all[field_name] = values
                continue
            if raw_key.endswith("_any"):
                field_name = raw_key[:-4]
                if field_name not in TILE_SEQUENCE_FIELDS:
                    raise _unknown_query_field_error(raw_key)
                values = _normalise_query_values(raw_value)
                if values:
                    contains_any[field_name] = values
                continue
            if raw_key not in TILE_EQUALITY_FIELDS:
                raise _unknown_query_field_error(raw_key)
            equality_filters[raw_key] = raw_value

        results: list[TileRecord] = []
        for tile in self.tiles.values():
            if any(getattr(tile, field_name) != expected for field_name, expected in equality_filters.items()):
                continue
            failed = False
            for field_name, required in contains_all.items():
                values = set(getattr(tile, field_name))
                if not required.issubset(values):
                    failed = True
                    break
            if failed:
                continue
            for field_name, allowed in contains_any.items():
                values = set(getattr(tile, field_name))
                if values.isdisjoint(allowed):
                    failed = True
                    break
            if failed:
                continue
            results.append(tile)
        return sorted(results, key=self._sheet_sort_key)

    def aliases_for(self, **query_kwargs: object) -> list[str]:
        aliases: list[str] = []
        for tile in self.query(**query_kwargs):
            aliases.extend(tile.aliases)
        return aliases

    def resolve_ref(self, ref: str, *, variant_id: str | None = None) -> ResolvedFamilyTile | None:
        return self.runtime_unit.resolve_ref(ref, variant_id=variant_id)


def compute_non_empty_tile_mask(
    *,
    image: Image.Image,
    tile_width: int,
    tile_height: int,
) -> list[list[bool]]:
    rgba = image.convert("RGBA")
    background = rgba.getpixel((0, 0))
    columns = rgba.width // tile_width
    rows = rgba.height // tile_height
    mask: list[list[bool]] = [[False for _ in range(columns)] for _ in range(rows)]
    for row in range(rows):
        for col in range(columns):
            occupied = False
            for pixel_y in range(row * tile_height, (row + 1) * tile_height):
                for pixel_x in range(col * tile_width, (col + 1) * tile_width):
                    if rgba.getpixel((pixel_x, pixel_y)) != background:
                        occupied = True
                        break
                if occupied:
                    break
            mask[row][col] = occupied
    return mask


def compute_source_layout_coverage(
    layout: SourceLayoutIngestion,
    mask: list[list[bool]],
) -> SourceLayoutCoverageReport:
    covered_non_empty: list[str] = []
    ignored_non_empty: list[str] = []
    outside_regions_non_empty: list[str] = []
    region_unclustered_non_empty: list[str] = []
    non_empty_tiles = _non_empty_tiles_from_mask(mask)
    for tile in non_empty_tiles:
        col = tile["col"]
        row = tile["row"]
        cell_ref = f"sheet:{col},{row}"
        region = layout.source_region_for_cell(col, row)
        if region is None:
            outside_regions_non_empty.append(cell_ref)
            continue
        if layout.ignored_cell(col, row):
            ignored_non_empty.append(cell_ref)
            continue
        if layout.source_clusters_for_cell(col, row):
            covered_non_empty.append(cell_ref)
            continue
        region_unclustered_non_empty.append(cell_ref)
    return {
        "non_empty_total": len(non_empty_tiles),
        "covered_non_empty": covered_non_empty,
        "ignored_non_empty": ignored_non_empty,
        "outside_regions_non_empty": outside_regions_non_empty,
        "region_unclustered_non_empty": region_unclustered_non_empty,
        "complete": not region_unclustered_non_empty,
    }


def _contiguous_true_runs(values: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - start))
            start = None
    return runs


def _occupied_bounds(mask: list[list[bool]], *, left: int, top: int, width: int, height: int) -> GridBounds | None:
    occupied_cols: list[int] = []
    occupied_rows: list[int] = []
    for row in range(top, top + height):
        for col in range(left, left + width):
            if mask[row][col]:
                occupied_cols.append(col)
                occupied_rows.append(row)
    if not occupied_cols or not occupied_rows:
        return None
    min_col = min(occupied_cols)
    max_col = max(occupied_cols)
    min_row = min(occupied_rows)
    max_row = max(occupied_rows)
    return GridBounds(x=min_col, y=min_row, width=max_col - min_col + 1, height=max_row - min_row + 1)


def _connected_components(mask: list[list[bool]], bounds: GridBounds) -> list[list[tuple[int, int]]]:
    visited: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []
    for row in range(bounds.y, bounds.y + bounds.height):
        for col in range(bounds.x, bounds.x + bounds.width):
            if not mask[row][col] or (col, row) in visited:
                continue
            stack = [(col, row)]
            visited.add((col, row))
            component: list[tuple[int, int]] = []
            while stack:
                current_col, current_row = stack.pop()
                component.append((current_col, current_row))
                for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    next_col = current_col + delta_col
                    next_row = current_row + delta_row
                    if not (
                        bounds.x <= next_col < bounds.x + bounds.width
                        and bounds.y <= next_row < bounds.y + bounds.height
                    ):
                        continue
                    if not mask[next_row][next_col] or (next_col, next_row) in visited:
                        continue
                    visited.add((next_col, next_row))
                    stack.append((next_col, next_row))
            components.append(sorted(component, key=lambda item: (item[1], item[0])))
    return components


def detect_source_layout(
    *,
    image: Image.Image,
    tile_width: int,
    tile_height: int,
) -> dict[str, object]:
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError("Source sheet is not aligned to the declared grid")
    mask = compute_non_empty_tile_mask(image=image, tile_width=tile_width, tile_height=tile_height)
    rows = len(mask)
    columns = len(mask[0]) if mask else 0

    column_has_content = [any(mask[row][col] for row in range(rows)) for col in range(columns)]
    region_runs = _contiguous_true_runs(column_has_content)
    regions: list[dict[str, object]] = []
    clusters: list[dict[str, object]] = []
    collections: list[dict[str, object]] = []

    for region_index, (start_col, width) in enumerate(region_runs, start=1):
        occupied_rows = [row for row in range(rows) if any(mask[row][col] for col in range(start_col, start_col + width))]
        if not occupied_rows:
            continue
        region_id = f"region_{region_index:02d}"
        region_bounds = GridBounds(
            x=start_col,
            y=min(occupied_rows),
            width=width,
            height=max(occupied_rows) - min(occupied_rows) + 1,
        )
        regions.append(
            {
                "id": region_id,
                "bounds": {
                    "x": region_bounds.x,
                    "y": region_bounds.y,
                    "width": region_bounds.width,
                    "height": region_bounds.height,
                },
                "label": f"Detected region {region_index}",
            }
        )

        row_has_content = [
            any(mask[row][col] for col in range(region_bounds.x, region_bounds.x + region_bounds.width))
            for row in range(region_bounds.y, region_bounds.y + region_bounds.height)
        ]
        row_runs = _contiguous_true_runs(row_has_content)
        cluster_index = 1
        for row_start_offset, row_height in row_runs:
            band_top = region_bounds.y + row_start_offset
            band_bounds = _occupied_bounds(
                mask,
                left=region_bounds.x,
                top=band_top,
                width=region_bounds.width,
                height=row_height,
            )
            if band_bounds is None:
                continue
            band_col_has_content = [
                any(mask[row][col] for row in range(band_bounds.y, band_bounds.y + band_bounds.height))
                for col in range(band_bounds.x, band_bounds.x + band_bounds.width)
            ]
            band_col_runs = _contiguous_true_runs(band_col_has_content)
            if len(band_col_runs) <= 1:
                cluster_id = f"{region_id}.cluster_{cluster_index:02d}"
                clusters.append(
                    {
                        "id": cluster_id,
                        "source_region_id": region_id,
                        "bounds": {
                            "x": band_bounds.x,
                            "y": band_bounds.y,
                            "width": band_bounds.width,
                            "height": band_bounds.height,
                        },
                        "label": f"Detected cluster {cluster_index}",
                        "split_axis": "row",
                    }
                )
                components = _connected_components(mask, band_bounds)
                for component_index, component in enumerate(components, start=1):
                    if len(component) <= 1:
                        continue
                    component_bounds = GridBounds(
                        x=min(col for col, _ in component),
                        y=min(row for _, row in component),
                        width=max(col for col, _ in component) - min(col for col, _ in component) + 1,
                        height=max(row for _, row in component) - min(row for _, row in component) + 1,
                    )
                    collections.append(
                        {
                            "id": f"{cluster_id}.component_{component_index:02d}",
                            "kind": "connected_component",
                            "source_cluster_id": cluster_id,
                            "bounds": {
                                "x": component_bounds.x,
                            "y": component_bounds.y,
                            "width": component_bounds.width,
                            "height": component_bounds.height,
                        },
                            "members": [{"sheet_cell": {"col": col, "row": row}} for col, row in component],
                        }
                    )
                cluster_index += 1
                continue

            for run_start_offset, run_width in band_col_runs:
                split_left = band_bounds.x + run_start_offset
                split_bounds = _occupied_bounds(
                    mask,
                    left=split_left,
                    top=band_bounds.y,
                    width=run_width,
                    height=band_bounds.height,
                )
                if split_bounds is None:
                    continue
                cluster_id = f"{region_id}.cluster_{cluster_index:02d}"
                clusters.append(
                    {
                        "id": cluster_id,
                        "source_region_id": region_id,
                        "bounds": {
                            "x": split_bounds.x,
                            "y": split_bounds.y,
                            "width": split_bounds.width,
                            "height": split_bounds.height,
                        },
                        "label": f"Detected cluster {cluster_index}",
                        "split_axis": "column",
                    }
                )
                components = _connected_components(mask, split_bounds)
                for component_index, component in enumerate(components, start=1):
                    if len(component) <= 1:
                        continue
                    component_bounds = GridBounds(
                        x=min(col for col, _ in component),
                        y=min(row for _, row in component),
                        width=max(col for col, _ in component) - min(col for col, _ in component) + 1,
                        height=max(row for _, row in component) - min(row for _, row in component) + 1,
                    )
                    collections.append(
                        {
                            "id": f"{cluster_id}.component_{component_index:02d}",
                            "kind": "connected_component",
                            "source_cluster_id": cluster_id,
                            "bounds": {
                                "x": component_bounds.x,
                            "y": component_bounds.y,
                            "width": component_bounds.width,
                            "height": component_bounds.height,
                        },
                            "members": [{"sheet_cell": {"col": col, "row": row}} for col, row in component],
                        }
                    )
                cluster_index += 1

    non_empty_tiles = _non_empty_tiles_from_mask(mask)
    return {
        "sheet_bounds": {"x": 0, "y": 0, "width": columns, "height": rows},
        "regions": regions,
        "clusters": clusters,
        "ignore_regions": [],
        "collections": collections,
        "non_empty_tiles": non_empty_tiles,
    }


def bootstrap_family(
    *,
    sheet_path: Path,
    output_dir: Path,
    tile_width: int,
    tile_height: int,
    transparent: str,
    family_id: str,
    variant_id: str,
) -> Path:
    image = Image.open(sheet_path).convert("RGBA")
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError(
            f"Sheet size {image.width}x{image.height} is not divisible by tile size {tile_width}x{tile_height}"
        )
    columns = image.width // tile_width
    rows = image.height // tile_height
    output_dir.mkdir(parents=True, exist_ok=True)
    relative_sheet = os.path.relpath(sheet_path.resolve(), output_dir.resolve())
    family = {
        "family_id": family_id,
        "grid": {"tile_width": tile_width, "tile_height": tile_height},
        "render_defaults": {"render_step_width": tile_width, "render_step_height": tile_height},
        "siblings_share_semantics": False,
        "default_variant_id": variant_id,
        "ingestion_spec": "ingestion.json",
        "notes": [],
        "variants": [
            {
                "variant_id": variant_id,
                "sheet": relative_sheet,
                "transparent": transparent,
                "background_mode": "unspecified",
            }
        ],
    }
    ingestion = {
        "sheet_bounds": {"x": 0, "y": 0, "width": columns, "height": rows},
        "regions": [
            {
                "id": "all",
                "bounds": {"x": 0, "y": 0, "width": columns, "height": rows},
                "label": "All sheet content",
            }
        ],
        "clusters": [],
        "ignore_regions": [],
        "collections": [],
        "notes": [],
    }
    (output_dir / "family.json").write_text(json.dumps(family, indent=2) + "\n", encoding="utf-8")
    (output_dir / "ingestion.json").write_text(json.dumps(ingestion, indent=2) + "\n", encoding="utf-8")
    (output_dir / "clusters.json").write_text("[]\n", encoding="utf-8")
    (output_dir / "tiles.json").write_text("[]\n", encoding="utf-8")
    (output_dir / "aliases.json").write_text("{}\n", encoding="utf-8")
    return output_dir
