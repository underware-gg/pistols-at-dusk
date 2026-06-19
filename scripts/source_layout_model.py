#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Union, cast

from typing_extensions import NotRequired, TypeAlias, TypedDict

from _manifest_utils import GridBounds, bounds_inside
from tile_library import SheetCell

SHEET_CELL_REF_RE = re.compile(r"^sheet:(?P<col>\d+),(?P<row>\d+)$")


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


class SourceLayoutCoverageReport(TypedDict):
    non_empty_total: int
    covered_non_empty: list[str]
    ignored_non_empty: list[str]
    outside_regions_non_empty: list[str]
    region_unclustered_non_empty: list[str]
    complete: bool


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
        return bounds_contains(self.sheet_bounds, col, row)

    def ignored_cell(self, col: int, row: int) -> bool:
        return any(bounds_contains(ignore.bounds, col, row) for ignore in self.ignored_regions.values())

    def source_region_for_cell(self, col: int, row: int) -> SourceLayoutRegion | None:
        for region in self.source_regions.values():
            if source_layout_region_contains_cell(region, col, row):
                return region
        return None

    def source_clusters_for_cell(self, col: int, row: int) -> tuple[SourceLayoutCluster, ...]:
        return tuple(cluster for cluster in self.source_clusters.values() if bounds_contains(cluster.bounds, col, row))


def bounds_contains(bounds: GridBounds, col: int, row: int) -> bool:
    return bounds.x <= col < bounds.x + bounds.width and bounds.y <= row < bounds.y + bounds.height


def source_layout_region_areas(region: SourceLayoutRegion) -> tuple[GridBounds, ...]:
    return region.areas or (region.bounds,)


def source_layout_region_contains_cell(region: SourceLayoutRegion, col: int, row: int) -> bool:
    return any(bounds_contains(area, col, row) for area in source_layout_region_areas(region))


def source_layout_region_contains_bounds(region: SourceLayoutRegion, bounds: GridBounds) -> bool:
    return any(bounds_inside(area, bounds) for area in source_layout_region_areas(region))


def sheet_cell_from_ref(ref: str) -> SheetCell | None:
    match = SHEET_CELL_REF_RE.match(ref)
    if match is None:
        return None
    return SheetCell(col=int(match.group("col")), row=int(match.group("row")))


def sheet_cell_ref_within_bounds(ref: str, bounds: GridBounds) -> bool:
    cell = sheet_cell_from_ref(ref)
    if cell is None:
        return False
    return bounds_contains(bounds, cell.col, cell.row)


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
