#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Mapping, TypeVar, Union, cast

from PIL import Image

from _manifest_utils import (
    GridBounds,
    bounds_inside as _bounds_inside,
    check_required_keys,
    load_json,
    require_list,
    require_mapping,
)
from source_layout_model import (
    IngestionBoundsConfig,
    SourceLayoutCluster,
    SourceLayoutCollection,
    SourceLayoutCollectionMember,
    SourceLayoutCoverageReport,
    SourceLayoutIgnoreRegion,
    SourceLayoutIngestion,
    SourceLayoutManifest,
    SourceLayoutRegion,
)
from compatibility_family import CompatibilityFamilyPaths
from tile_library import SheetCell
from tile_family_runtime import (
    TileFamily,
    load_family_catalog_sources,
    load_family_header_and_variants,
)

TileFamilyT = TypeVar("TileFamilyT", bound=TileFamily)

def _tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(values or ())


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


def _cluster_bounds_from_raw(raw_bounds: IngestionBoundsConfig | None) -> GridBounds | None:
    if raw_bounds is None:
        return None
    return GridBounds(
        x=int(raw_bounds["x"]),
        y=int(raw_bounds["y"]),
        width=int(raw_bounds["width"]),
        height=int(raw_bounds["height"]),
    )


def _require_cluster_bounds(raw_bounds: IngestionBoundsConfig | None, *, context: str) -> GridBounds:
    bounds = _cluster_bounds_from_raw(raw_bounds)
    if bounds is None:
        raise ValueError(f"{context} must define bounds")
    return bounds


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


def load_legacy_source_layout(
    *,
    root: Path,
    family_data: Mapping[str, object],
) -> SourceLayoutIngestion | None:
    ingestion_spec_raw = family_data.get("ingestion_spec")
    ingestion_path = root / str(ingestion_spec_raw) if ingestion_spec_raw is not None else root / "ingestion.json"
    if ingestion_spec_raw is not None and not ingestion_path.exists():
        raise ValueError(f"Declared ingestion spec {ingestion_path} does not exist")
    if not ingestion_path.exists():
        return None
    return load_source_layout_from_path(ingestion_path)


def load_source_tile_family(
    family_path: Path,
    *,
    family_cls: type[TileFamilyT] = TileFamily,
) -> TileFamilyT:
    root = family_path.resolve()
    header, variants, family_data = load_family_header_and_variants(root)
    return cast(TileFamilyT, family_cls.from_catalog_sources(
        header=header,
        variants=variants,
        catalog=load_family_catalog_sources(CompatibilityFamilyPaths.for_legacy_root(root)),
        source_layout=load_legacy_source_layout(root=root, family_data=family_data),
    ))


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


def _non_empty_tiles_from_mask(mask: list[list[bool]]) -> list[dict[str, int]]:
    rows = len(mask)
    columns = len(mask[0]) if mask else 0
    return [
        {"col": col, "row": row}
        for row in range(rows)
        for col in range(columns)
        if mask[row][col]
    ]


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
