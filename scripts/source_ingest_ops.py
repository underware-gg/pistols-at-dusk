#!/usr/bin/env python3
"""Source-ingest operators: the inspect / export / audit / validate / detect
functions (and their helpers) that turn a loaded tile family + project into
review packs, public tile packs, Tiled kits, catalogs and diagnostics. This is
the operator layer; it depends on layout_core (and the upstream ingest modules)
and is consumed by the harness CLI.
"""

from __future__ import annotations

import csv
from datetime import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Iterator, Sequence, TypedDict, Union, cast

from typing_extensions import NotRequired

from PIL import Image, ImageDraw

from scene_templates import (
    TileRefToken,
)
from tile_library import (
    CompositeTileRecord,
    Construction,
    EntityTemplateRecord,
    MetatileConstruction,
    ParametricFrameConstruction,
    ParametricRunConstruction,
    SheetCell,
    TileClusterRecord,
    TileRecord,
)
from tile_families import (
    SourceLayoutCollection,
    SourceLayoutCollectionMember,
    SourceLayoutIngestion,
    TileFamily,
    TileFamilyIngestReport,
    collection_member_ref,
    collection_member_to_config,
    compute_non_empty_tile_mask,
    compute_source_layout_coverage,
    detect_source_layout,
)
from _manifest_utils import GridBounds
from layout_core import (
    resize_nearest,
    GridRegionBounds,
    load_layout_config,
    escape_xml,
    slugify_identifier,
    humanize_identifier,
    ResolvedTile,
    Pattern,
    GridTileset,
    LayoutProject,
    trim_rows,
    AlphaBoundsInfo,
    analyse_alpha_bounds,
    pattern_tileset_ids,
    render_tile_preview_image,
    render_pattern_image,
)




class RawCatalogEntry(TypedDict):
    index: int
    col: int
    row: int
    region: str | None


class SemanticCatalogEntry(TypedDict):
    id: str
    family_id: str
    layer: str
    category: str
    transparent: bool
    tags: list[str]
    sheet_col: int | None
    sheet_row: int | None
    exact_duplicate_of: str | None
    image_override: str | None
    aliases: list[str]
    walkable: bool | None
    blocking: bool | None
    scenes: list[str]
    semantics: list[str]
    motifs: list[str]
    cluster_ids: list[str]
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
    connects_on: list[str]
    requires_exposed_on: list[str]
    affordances: list[str]
    alt_uses: list[str]
    meaning: str | None
    meaning_confidence: str | None
    source_notes: str | None
    index: int | None
    variant_id: str | None
    physical_ref: str
    variant_ref: str | None
    empty: bool


def build_catalog(project: LayoutProject, tileset_id: str) -> list[RawCatalogEntry]:
    tileset = project.get_tileset(tileset_id)
    family = project.source_family_for_tileset(tileset_id)

    def region_for_cell(col: int, row: int) -> str | None:
        if family is None or family.source_layout is None:
            return tileset.region_name_for_col_row(col, row)
        source_region = family.source_layout.source_region_for_cell(col, row)
        return None if source_region is None else source_region.id

    catalog: list[RawCatalogEntry] = []
    for index in tileset.catalog_indices():
        if tileset.is_empty(index):
            continue
        col, row = tileset.col_row_from_index(index)
        catalog.append(
            {
                "index": index,
                "col": col,
                "row": row,
                "region": region_for_cell(col, row),
            }
        )
    return catalog


def build_semantic_catalog_entries(
    project: LayoutProject,
    tileset_id: str,
    *,
    include_empty: bool = False,
    tile_records: Sequence[TileRecord] | None = None,
) -> list[SemanticCatalogEntry]:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        return []

    tileset = project.get_tileset(tileset_id)
    variant_id = project.variant_id_for_tileset(tileset_id)
    entries: list[SemanticCatalogEntry] = []
    records = family.tiles.values() if tile_records is None else tile_records
    for meta in records:
        resolved = family.resolve_ref(meta.id, variant_id=variant_id)
        if resolved is None:
            continue
        genesis = meta.genesis
        index: int | None = None
        empty = False
        if genesis.sheet_col is not None and genesis.sheet_row is not None:
            if not (0 <= genesis.sheet_col < tileset.columns and 0 <= genesis.sheet_row < tileset.rows):
                continue
            index = tileset.index_from_col_row(genesis.sheet_col, genesis.sheet_row)
            empty = tileset.is_empty(index)
            if empty and not include_empty:
                continue
        # Build the catalog entry directly so the JSON-friendly list fields are
        # the canonical shape — no after-the-fact tuple-to-list mutation needed.
        entry: SemanticCatalogEntry = {
            "id": meta.id,
            "family_id": meta.family_id,
            "layer": meta.layer,
            "category": meta.category,
            "transparent": meta.transparent,
            "tags": list(meta.tags),
            "sheet_col": genesis.sheet_col,
            "sheet_row": genesis.sheet_row,
            "exact_duplicate_of": meta.exact_duplicate_of,
            "image_override": meta.image_override,
            "aliases": list(meta.aliases),
            "walkable": meta.walkable,
            "blocking": meta.blocking,
            "scenes": list(meta.scenes),
            "semantics": list(meta.semantics),
            "motifs": list(meta.motifs),
            "cluster_ids": list(genesis.cluster_ids),
            "source_group": genesis.source_group,
            "noise": meta.noise,
            "contrast": meta.contrast,
            "temperature": meta.temperature,
            "usage": meta.usage,
            "style": meta.style,
            "overlay": meta.overlay,
            "footprint": meta.footprint,
            "orientation": meta.orientation,
            "facing": meta.facing,
            "pose": meta.pose,
            "compose_group": meta.compose_group,
            "compose_role": meta.compose_role,
            "state_group": meta.state_group,
            "state_role": meta.state_role,
            "animation_group": meta.animation_group,
            "animation_frame": meta.animation_frame,
            "animation_frame_count": meta.animation_frame_count,
            "connects_on": list(meta.connects_on),
            "requires_exposed_on": list(meta.requires_exposed_on),
            "affordances": list(meta.affordances),
            "alt_uses": list(meta.alt_uses),
            "meaning": meta.meaning,
            "meaning_confidence": meta.meaning_confidence,
            "source_notes": meta.source_notes,
            "index": index,
            "variant_id": variant_id,
            "physical_ref": resolved.physical_ref,
            "variant_ref": resolved.variant_ref if variant_id is not None else None,
            "empty": empty,
        }
        entries.append(entry)
    return sorted(
        entries,
        key=lambda entry: (
            1 if entry["sheet_row"] is None or entry["sheet_col"] is None else 0,
            10**9 if entry["sheet_row"] is None else entry["sheet_row"],
            10**9 if entry["sheet_col"] is None else entry["sheet_col"],
            entry["id"],
        ),
    )


def build_semantic_catalog(project: LayoutProject, tileset_id: str) -> list[SemanticCatalogEntry]:
    return build_semantic_catalog_entries(project, tileset_id, include_empty=False)


def merge_semantic_catalog(
    raw_catalog: list[RawCatalogEntry],
    semantic_catalog: list[SemanticCatalogEntry],
) -> list[dict[str, object]]:
    by_index = {entry["index"]: entry for entry in semantic_catalog if entry["index"] is not None}
    merged: list[dict[str, object]] = []
    for entry in raw_catalog:
        semantic = by_index.get(entry["index"])
        if semantic is None:
            merged.append(cast(dict[str, object], entry))
            continue
        merged.append(
            {
                **cast(dict[str, object], entry),
                **{
                    key: value
                    for key, value in cast(dict[str, object], semantic).items()
                    if key not in {"index", "col", "row", "region"}
                },
            }
        )
    return merged


class EdgeAlphaCounts(TypedDict):
    left: int
    top: int
    right: int
    bottom: int


class TileEdgeInfo(AlphaBoundsInfo):
    edge_alpha_pixels: EdgeAlphaCounts
    edge_contact_score: int


class TileEdgeCatalogEntry(TileEdgeInfo, RawCatalogEntry, total=False):
    tile_id: str
    layer: str
    category: str
    physical_ref: str


def _alpha_value(alpha: Image.Image, x: int, y: int) -> int:
    return cast(int, alpha.getpixel((x, y)))


def analyse_tile_edges(tile: Image.Image) -> TileEdgeInfo:
    alpha = tile.getchannel("A")
    edge_alpha: EdgeAlphaCounts = {
        "left": sum(1 for y in range(tile.height) if _alpha_value(alpha, 0, y) > 0),
        "top": sum(1 for x in range(tile.width) if _alpha_value(alpha, x, 0) > 0),
        "right": sum(1 for y in range(tile.height) if _alpha_value(alpha, tile.width - 1, y) > 0),
        "bottom": sum(1 for x in range(tile.width) if _alpha_value(alpha, x, tile.height - 1) > 0),
    }
    bounds = analyse_alpha_bounds(tile)
    return {
        "alpha_bbox_pixels": bounds["alpha_bbox_pixels"],
        "inset_left_pixels": bounds["inset_left_pixels"],
        "inset_top_pixels": bounds["inset_top_pixels"],
        "inset_right_pixels": bounds["inset_right_pixels"],
        "inset_bottom_pixels": bounds["inset_bottom_pixels"],
        "edge_alpha_pixels": edge_alpha,
        "edge_contact_score": (
            edge_alpha["left"]
            + edge_alpha["top"]
            + edge_alpha["right"]
            + edge_alpha["bottom"]
        ),
    }


def build_tile_edge_catalog(project: LayoutProject, tileset_id: str) -> list[TileEdgeCatalogEntry]:
    tileset = project.get_tileset(tileset_id)
    semantic_by_index = {
        entry["index"]: entry
        for entry in build_semantic_catalog_entries(project, tileset_id, include_empty=True)
        if entry["index"] is not None
    }
    catalog: list[TileEdgeCatalogEntry] = []
    for entry in build_catalog(project, tileset_id):
        tile = tileset.tile_image(entry["index"])
        edges = analyse_tile_edges(tile)
        semantic = semantic_by_index.get(entry["index"])
        catalog.append(
            cast(
                TileEdgeCatalogEntry,
                {
                    **entry,
                    **edges,
                    **(
                        {}
                        if semantic is None
                        else {
                            "tile_id": semantic["id"],
                            "layer": semantic["layer"],
                            "category": semantic["category"],
                            "physical_ref": semantic["physical_ref"],
                        }
                    ),
                },
            )
        )
    return catalog


def inspect_tile_edges(project: LayoutProject, tileset_id: str, output_dir: Path) -> None:
    catalog = build_tile_edge_catalog(project, tileset_id)
    catalog.sort(
        key=lambda entry: (
            0 if entry.get("layer") == "architecture" else 1,
            -entry["edge_contact_score"],
            entry["row"],
            entry["col"],
        )
    )
    (output_dir / "tile_edges.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    def _edge_alpha_max(entry: TileEdgeCatalogEntry) -> int:
        edges = entry["edge_alpha_pixels"]
        return max(edges["left"], edges["top"], edges["right"], edges["bottom"])

    candidates = [
        entry
        for entry in catalog
        if entry.get("layer") == "architecture"
        and entry["edge_contact_score"] >= 10
        and _edge_alpha_max(entry) >= 4
    ]
    if not candidates:
        candidates = catalog[:48]

    scale = 6
    card_width = 80
    card_height = 92
    columns = 6
    rows = (len(candidates) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)
    tileset = project.get_tileset(tileset_id)

    for idx, entry in enumerate(candidates):
        row = idx // columns
        col = idx % columns
        card_left = col * card_width
        card_top = row * card_height
        draw.rectangle(
            (card_left + 4, card_top + 4, card_left + card_width - 5, card_top + card_height - 5),
            outline=(246, 195, 124, 255),
        )
        tile = resize_nearest(tileset.tile_image(entry["index"]), (tileset.tile_width * scale, tileset.tile_height * scale))
        tile_left = card_left + (card_width - tile.width) // 2
        tile_top = card_top + 10
        contact.alpha_composite(tile, (tile_left, tile_top))
        draw.text(
            (card_left + 8, card_top + 66),
            f'{entry["col"]},{entry["row"]}  s{entry["edge_contact_score"]}',
            fill=(255, 255, 255, 255),
        )
        edge_alpha = entry["edge_alpha_pixels"]
        draw.text(
            (card_left + 8, card_top + 78),
            f'L{edge_alpha["left"]} T{edge_alpha["top"]} R{edge_alpha["right"]} B{edge_alpha["bottom"]}',
            fill=(180, 220, 255, 255),
        )
    contact.save(output_dir / "seam_candidate_tiles.png")


class PatternCatalogEntry(TypedDict):
    name: str
    width_tiles: int
    height_tiles: int
    width_pixels: int
    height_pixels: int
    tileset_ids: list[str]


def build_pattern_catalog(
    project: LayoutProject, *, tileset_id: str | None = None
) -> list[PatternCatalogEntry]:
    catalog: list[PatternCatalogEntry] = []
    for name in project.pattern_names():
        pattern = project.pattern_from_name(name)
        tileset_ids = sorted(pattern_tileset_ids(pattern))
        if tileset_id is not None and tileset_ids and any(item != tileset_id for item in tileset_ids):
            continue
        rendered = render_pattern_image(project, pattern, snap_to_grid=True)
        catalog.append(
            {
                "name": name,
                "width_tiles": pattern.width,
                "height_tiles": pattern.height,
                "width_pixels": rendered.width,
                "height_pixels": rendered.height,
                "tileset_ids": tileset_ids,
            }
        )
    return catalog


def scaffold_pattern(
    project_path: Path,
    *,
    tileset_id: str,
    name: str,
    x: int,
    y: int,
    width: int,
    height: int,
    trim: bool,
) -> str:
    project = LayoutProject(project_path)
    tileset = project.get_tileset(tileset_id)
    rows: list[list[str]] = []
    for row in range(y, y + height):
        current: list[str] = []
        for col in range(x, x + width):
            index = tileset.index_from_col_row(col, row)
            current.append("." if tileset.is_empty(index) else f"{col},{row}")
        rows.append(current)

    if trim:
        tuple_rows: list[tuple[str | None, ...]] = [
            tuple(None if cell == "." else cell for cell in row) for row in rows
        ]
        trimmed = trim_rows(tuple_rows)
        rows = [[cell if cell is not None else "." for cell in row] for row in trimmed]

    return json.dumps({"tileset": tileset_id, "rows": rows}, indent=2)


def inspect_patterns(project: LayoutProject, tileset_id: str, output_dir: Path) -> None:
    catalog = build_pattern_catalog(project, tileset_id=tileset_id)
    (output_dir / "patterns.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    if not catalog:
        return

    scale = 4
    max_width_px = max(item["width_pixels"] for item in catalog)
    max_height_px = max(item["height_pixels"] for item in catalog)
    card_width = max(128, max_width_px * scale + 16)
    card_height = max(96, max_height_px * scale + 32)
    columns = 4
    rows = (len(catalog) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, entry in enumerate(catalog):
        row = idx // columns
        col = idx % columns
        left = col * card_width
        top = row * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(246, 195, 124, 255))
        pattern = project.pattern_from_name(entry["name"])
        sprite = resize_nearest(
            render_pattern_image(project, pattern, snap_to_grid=True),
            (entry["width_pixels"] * scale, entry["height_pixels"] * scale),
        )
        sx = left + (card_width - sprite.width) // 2
        sy = top + 10
        contact.alpha_composite(sprite, (sx, sy))
        draw.text((left + 8, top + card_height - 28), entry["name"], fill=(255, 255, 255, 255))
        draw.text(
            (left + 8, top + card_height - 14),
            f'{entry["width_tiles"]}x{entry["height_tiles"]} tiles',
            fill=(180, 220, 255, 255),
        )
    contact.save(output_dir / "patterns.png")


class ClusterBoundsPayload(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ClusterPayload(TypedDict):
    id: str
    scope: str
    bounds: ClusterBoundsPayload | None
    members: list[str]
    kind_guess: str | None
    evidence: list[str]
    source_label: str | None
    source_notes: str | None


class SourceLayoutRegionPayload(TypedDict):
    id: str
    label: str | None
    bounds: ClusterBoundsPayload
    areas: list[ClusterBoundsPayload]
    notes: str | None
    ingest_tiles: bool


class SourceLayoutClusterPayload(TypedDict):
    id: str
    source_region_id: str
    label: str | None
    bounds: ClusterBoundsPayload
    notes: str | None
    split_axis: str | None
    ingest_tiles: bool


class SourceLayoutIgnoreRegionPayload(TypedDict):
    id: str
    label: str | None
    bounds: ClusterBoundsPayload
    reason: str | None


class SourceLayoutCollectionTileMemberPayload(TypedDict):
    tile_id: str


class SourceLayoutCollectionAliasMemberPayload(TypedDict):
    alias: str


class SourceLayoutCollectionSheetCellPayload(TypedDict):
    col: int
    row: int


class SourceLayoutCollectionSheetCellMemberPayload(TypedDict):
    sheet_cell: SourceLayoutCollectionSheetCellPayload


class SourceLayoutCollectionPayload(TypedDict):
    id: str
    kind: str
    label: str | None
    source_region_id: str | None
    source_cluster_id: str | None
    bounds: ClusterBoundsPayload | None
    members: list[
        SourceLayoutCollectionTileMemberPayload
        | SourceLayoutCollectionAliasMemberPayload
        | SourceLayoutCollectionSheetCellMemberPayload
    ]
    notes: str | None


def _draw_bounds(
    *,
    draw: ImageDraw.ImageDraw,
    bounds: ClusterBoundsPayload,
    scale: int,
    tile_width: int,
    tile_height: int,
    colour: tuple[int, int, int, int],
    label: str,
    origin: tuple[int, int] = (0, 0),
) -> None:
    origin_x, origin_y = origin
    left = origin_x + (bounds["x"] * scale * tile_width)
    top = origin_y + (bounds["y"] * scale * tile_height)
    right = left + bounds["width"] * scale * tile_width
    bottom = top + bounds["height"] * scale * tile_height
    draw.rectangle((left, top, right - 1, bottom - 1), outline=colour, width=2)
    _draw_text_with_backplate(draw, (left + 4, top + 4), label[:32], fill=colour)


SOURCE_LAYOUT_REGION_COLOURS: tuple[tuple[int, int, int, int], ...] = (
    (255, 220, 120, 255),
    (120, 220, 255, 255),
    (180, 255, 160, 255),
    (255, 160, 210, 255),
)
SOURCE_LAYOUT_CLUSTER_COLOUR = (246, 195, 124, 255)
SOURCE_LAYOUT_IGNORE_COLOUR = (255, 100, 100, 255)
SOURCE_LAYOUT_COLLECTION_COLOUR = (160, 240, 255, 255)
SOURCE_GUIDE_OUTER_PAD = 8
SOURCE_GUIDE_LABEL_BAND = 22


def _draw_source_layout_features(
    *,
    draw: ImageDraw.ImageDraw,
    layout: SourceLayoutIngestion,
    scale: int,
    tile_width: int,
    tile_height: int,
    origin: tuple[int, int] = (0, 0),
    bounds_offset: tuple[int, int] = (0, 0),
) -> None:
    offset_x, offset_y = bounds_offset

    def shifted_bounds(bounds: ClusterBoundsPayload) -> ClusterBoundsPayload:
        return {
            "x": bounds["x"] + offset_x,
            "y": bounds["y"] + offset_y,
            "width": bounds["width"],
            "height": bounds["height"],
        }

    def draw_feature(
        *,
        raw_bounds: GridRegionBounds | GridBounds,
        colour: tuple[int, int, int, int],
        label: str,
    ) -> None:
        _draw_bounds(
            draw=draw,
            bounds=shifted_bounds(
                {
                    "x": raw_bounds.x,
                    "y": raw_bounds.y,
                    "width": raw_bounds.width,
                    "height": raw_bounds.height,
                }
            ),
            scale=scale,
            tile_width=tile_width,
            tile_height=tile_height,
            colour=colour,
            label=label,
            origin=origin,
        )

    for index, region in enumerate(layout.source_regions.values()):
        region_areas = region.areas or (region.bounds,)
        for area_index, area in enumerate(region_areas):
            draw_feature(
                raw_bounds=area,
                colour=SOURCE_LAYOUT_REGION_COLOURS[index % len(SOURCE_LAYOUT_REGION_COLOURS)],
                label=(region.label or region.id) if area_index == 0 else f"{region.id}:area_{area_index + 1}",
            )
    for cluster in layout.source_clusters.values():
        draw_feature(
            raw_bounds=cluster.bounds,
            colour=SOURCE_LAYOUT_CLUSTER_COLOUR,
            label=cluster.label or cluster.id,
        )
    for ignore in layout.ignored_regions.values():
        draw_feature(
            raw_bounds=ignore.bounds,
            colour=SOURCE_LAYOUT_IGNORE_COLOUR,
            label=ignore.label or ignore.id,
        )
    for collection in layout.source_collections.values():
        if collection.bounds is None:
            continue
        draw_feature(
            raw_bounds=collection.bounds,
            colour=SOURCE_LAYOUT_COLLECTION_COLOUR,
            label=collection.label or collection.id,
        )


def _draw_text_with_backplate(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    *,
    fill: tuple[int, int, int, int],
    background: tuple[int, int, int, int] = (0, 0, 0, 160),
    padding_x: int = 2,
    padding_y: int = 1,
) -> None:
    if not text:
        return
    left, top, right, bottom = draw.textbbox(position, text)
    draw.rectangle(
        (left - padding_x, top - padding_y, right + padding_x, bottom + padding_y),
        fill=background,
    )
    draw.text(position, text, fill=fill)


def _render_source_layout_guide(
    *,
    image: Image.Image,
    layout: SourceLayoutIngestion,
    tile_width: int,
    tile_height: int,
    scale: int,
) -> Image.Image:
    sheet_bounds: ClusterBoundsPayload = {
        "x": layout.sheet_bounds.x,
        "y": layout.sheet_bounds.y,
        "width": layout.sheet_bounds.width,
        "height": layout.sheet_bounds.height,
    }
    grid_width = sheet_bounds["width"] * scale * tile_width
    grid_height = sheet_bounds["height"] * scale * tile_height
    outer_pad = SOURCE_GUIDE_OUTER_PAD
    label_band = SOURCE_GUIDE_LABEL_BAND
    margin = outer_pad + label_band
    canvas = Image.new(
        "RGBA",
        (grid_width + margin * 2, grid_height + margin * 2),
        (28, 28, 36, 255),
    )

    preview = resize_nearest(image, (image.width * scale, image.height * scale))
    canvas.alpha_composite(preview, (margin, margin))

    draw = ImageDraw.Draw(canvas)
    grid_colour = (230, 220, 200, 132)
    border_colour = (246, 195, 124, 255)
    label_colour = (246, 195, 124, 255)
    for offset in range(sheet_bounds["width"] + 1):
        x = margin + offset * scale * tile_width
        draw.line((x, margin, x, margin + grid_height), fill=grid_colour, width=1)
    for offset in range(sheet_bounds["height"] + 1):
        y = margin + offset * scale * tile_height
        draw.line((margin, y, margin + grid_width, y), fill=grid_colour, width=1)
    draw.rectangle(
        (margin, margin, margin + grid_width - 1, margin + grid_height - 1),
        outline=border_colour,
        width=2,
    )

    for col in range(sheet_bounds["x"], sheet_bounds["x"] + sheet_bounds["width"]):
        x = margin + (col - sheet_bounds["x"]) * scale * tile_width + (scale * tile_width) // 2
        label = str(col)
        left, top, right, bottom = draw.textbbox((0, 0), label)
        label_width = right - left
        draw.text((x - label_width // 2, outer_pad), label, fill=label_colour)
    for row in range(sheet_bounds["y"], sheet_bounds["y"] + sheet_bounds["height"]):
        y = margin + (row - sheet_bounds["y"]) * scale * tile_height + (scale * tile_height) // 2
        label = str(row)
        left, top, right, bottom = draw.textbbox((0, 0), label)
        label_height = bottom - top
        draw.text((outer_pad, y - label_height // 2), label, fill=label_colour)

    _draw_source_layout_features(
        draw=draw,
        layout=layout,
        scale=scale,
        tile_width=tile_width,
        tile_height=tile_height,
        origin=(margin, margin),
        bounds_offset=(-sheet_bounds["x"], -sheet_bounds["y"]),
    )
    return canvas


def _source_layout_payload(layout: object) -> dict[str, object]:
    source_layout = cast(SourceLayoutIngestion, layout)
    return {
        "sheet_bounds": {
            "x": source_layout.sheet_bounds.x,
            "y": source_layout.sheet_bounds.y,
            "width": source_layout.sheet_bounds.width,
            "height": source_layout.sheet_bounds.height,
        },
        "regions": [
            {
                "id": region.id,
                "label": region.label,
                "bounds": {
                    "x": region.bounds.x,
                    "y": region.bounds.y,
                    "width": region.bounds.width,
                    "height": region.bounds.height,
                },
                "areas": [
                    {
                        "x": area.x,
                        "y": area.y,
                        "width": area.width,
                        "height": area.height,
                    }
                    for area in region.areas
                ],
                "notes": region.notes,
                "ingest_tiles": region.ingest_tiles,
            }
            for region in source_layout.source_regions.values()
        ],
        "clusters": [
            {
                "id": cluster.id,
                "source_region_id": cluster.source_region_id,
                "label": cluster.label,
                "bounds": {
                    "x": cluster.bounds.x,
                    "y": cluster.bounds.y,
                    "width": cluster.bounds.width,
                    "height": cluster.bounds.height,
                },
                "notes": cluster.notes,
                "split_axis": cluster.split_axis,
                "ingest_tiles": cluster.ingest_tiles,
            }
            for cluster in source_layout.source_clusters.values()
        ],
        "ignore_regions": [
            {
                "id": ignore.id,
                "label": ignore.label,
                "bounds": {
                    "x": ignore.bounds.x,
                    "y": ignore.bounds.y,
                    "width": ignore.bounds.width,
                    "height": ignore.bounds.height,
                },
                "reason": ignore.reason,
            }
            for ignore in source_layout.ignored_regions.values()
        ],
        "collections": [
            {
                "id": collection.id,
                "kind": collection.kind,
                "label": collection.label,
                "source_region_id": collection.source_region_id,
                "source_cluster_id": collection.source_cluster_id,
                "bounds": (
                    {
                        "x": collection.bounds.x,
                        "y": collection.bounds.y,
                        "width": collection.bounds.width,
                        "height": collection.bounds.height,
                    }
                    if collection.bounds is not None
                    else None
                ),
                "members": [collection_member_to_config(member) for member in collection.members],
                "constructions": list(collection.constructions),
                "notes": collection.notes,
            }
            for collection in source_layout.source_collections.values()
        ],
        "notes": list(source_layout.notes),
    }


def _tile_cluster_payloads(family: TileFamily) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for cluster in family.clusters.values():
        payloads.append(
            {
                "id": cluster.id,
                "scope": cluster.scope,
                "bounds": _semantic_cluster_bounds_from_members(family, cluster),
                "members": list(cluster.members),
                "kind_guess": cluster.kind_guess,
                "evidence": list(cluster.evidence),
                "source_label": cluster.source_label,
                "source_notes": cluster.source_notes,
            }
        )
    return payloads


def inspect_source_layout(project: LayoutProject, tileset_id: str, output_dir: Path) -> None:
    family = project.source_family_for_tileset(tileset_id)
    if family is None or family.source_layout is None:
        return

    layout = family.source_layout
    payload = _source_layout_payload(layout)
    (output_dir / "source_layout.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    tileset = project.get_tileset(tileset_id)
    scale = 4
    preview = resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
    draw = ImageDraw.Draw(preview)
    _draw_source_layout_features(
        draw=draw,
        layout=layout,
        scale=scale,
        tile_width=tileset.tile_width,
        tile_height=tileset.tile_height,
    )
    preview.save(output_dir / "source_layout.png")
    source_layout_guide = _render_source_layout_guide(
        image=tileset.image,
        layout=layout,
        tile_width=tileset.tile_width,
        tile_height=tileset.tile_height,
        scale=scale,
    )
    source_layout_guide.save(output_dir / "source_layout.guide.png")

    detected = detect_source_layout(image=tileset.image, tile_width=project.grid_width, tile_height=project.grid_height)
    (output_dir / "source_layout.detected.json").write_text(json.dumps(detected, indent=2) + "\n", encoding="utf-8")

    mask = compute_non_empty_tile_mask(
        image=tileset.image,
        tile_width=project.grid_width,
        tile_height=project.grid_height,
    )
    coverage_report = compute_source_layout_coverage(layout, mask)
    (output_dir / "source_layout.coverage.json").write_text(json.dumps(coverage_report, indent=2) + "\n", encoding="utf-8")


def inspect_clusters(project: LayoutProject, tileset_id: str, output_dir: Path) -> None:
    family = project.source_family_for_tileset(tileset_id)
    if family is None or not family.clusters:
        return

    payload: list[ClusterPayload] = []
    for cluster in family.clusters.values():
        if cluster.kind_guess == "utility_gap_cluster":
            continue
        payload.append(
            {
                "id": cluster.id,
                "scope": cluster.scope,
                "bounds": _semantic_cluster_bounds_from_members(family, cluster),
                "members": list(cluster.members),
                "kind_guess": cluster.kind_guess,
                "evidence": list(cluster.evidence),
                "source_label": cluster.source_label,
                "source_notes": cluster.source_notes,
            }
        )
    payload.sort(key=lambda item: item["id"])
    (output_dir / "clusters.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    tileset = project.get_tileset(tileset_id)
    scale = 4
    preview = resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
    draw = ImageDraw.Draw(preview)
    colours = [
        (246, 195, 124, 255),
        (180, 220, 255, 255),
        (156, 228, 160, 255),
        (255, 165, 195, 255),
        (255, 230, 120, 255),
    ]

    for index, cluster in enumerate(payload):
        bounds = cluster["bounds"]
        if bounds is None:
            continue
        colour = colours[index % len(colours)]
        left = bounds["x"] * project.grid_width * scale
        top = bounds["y"] * project.grid_height * scale
        right = left + bounds["width"] * project.grid_width * scale
        bottom = top + bounds["height"] * project.grid_height * scale
        draw.rectangle((left, top, right - 1, bottom - 1), outline=colour, width=2)
        label = (cluster["source_label"] or cluster["id"]).split(":")[-1]
        draw.text((left + 4, top + 4), label[:28], fill=colour)
    preview.save(output_dir / "clusters.png")


def inspect_semantic_catalog(project: LayoutProject, tileset_id: str, output_dir: Path) -> None:
    catalog = build_semantic_catalog(project, tileset_id)
    if not catalog:
        return

    (output_dir / "semantic_catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    scale = 6
    previews: list[Image.Image] = []
    for entry in catalog:
        preview = _image_for_semantic_entry(project, tileset_id, entry)
        previews.append(resize_nearest(preview, (preview.width * scale, preview.height * scale)))
    max_preview_width = max((preview.width for preview in previews), default=project.grid_width * scale)
    max_preview_height = max((preview.height for preview in previews), default=project.grid_height * scale)
    card_width = max(128, max_preview_width + 16)
    card_height = max(92, max_preview_height + 54)
    columns = 6
    rows = (len(catalog) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)
    for idx, entry in enumerate(catalog):
        row = idx // columns
        col = idx % columns
        card_left = col * card_width
        card_top = row * card_height
        draw.rectangle(
            (card_left + 4, card_top + 4, card_left + card_width - 5, card_top + card_height - 5),
            outline=(246, 195, 124, 255),
        )
        tile = previews[idx]
        tile_left = card_left + (card_width - tile.width) // 2
        tile_top = card_top + 10
        contact.alpha_composite(tile, (tile_left, tile_top))
        label = entry["aliases"][0] if entry["aliases"] else entry["id"]
        text_top = card_top + card_height - 34
        draw.text((card_left + 8, text_top), label[:18], fill=(255, 255, 255, 255))
        draw.text(
            (card_left + 8, text_top + 12),
            f'{entry["category"]} • {entry["usage"] or "untyped"}',
            fill=(180, 220, 255, 255),
        )
        if entry["scenes"]:
            draw.text((card_left + 8, text_top + 24), ",".join(entry["scenes"])[:18], fill=(190, 200, 190, 255))
    contact.save(output_dir / "semantic_catalog.png")


class ReviewEntry(SemanticCatalogEntry):
    review_id: int
    primary_alias: str
    label: str
    file: NotRequired[str]


def write_review_contact_sheet(
    entries: Sequence[ReviewEntry],
    *,
    project: LayoutProject,
    tileset_id: str,
    output_path: Path,
    scale: int,
) -> None:
    if not entries:
        return

    previews: list[Image.Image] = []
    for entry in entries:
        preview = _image_for_semantic_entry(project, tileset_id, entry)
        previews.append(resize_nearest(preview, (preview.width * scale, preview.height * scale)))
    max_preview_width = max((preview.width for preview in previews), default=project.grid_width * scale)
    max_preview_height = max((preview.height for preview in previews), default=project.grid_height * scale)
    card_width = max(180, max_preview_width + 16)
    card_height = max(120, max_preview_height + 54)
    columns = 4
    rows = (len(entries) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, entry in enumerate(entries):
        row = idx // columns
        col = idx % columns
        left = col * card_width
        top = row * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(246, 195, 124, 255))
        tile = previews[idx]
        tile_left = left + (card_width - tile.width) // 2
        tile_top = top + 10
        contact.alpha_composite(tile, (tile_left, tile_top))
        draw.text((left + 8, top + card_height - 38), f'{entry["review_id"]:03d} {entry["primary_alias"][:20]}', fill=(255, 255, 255, 255))
        compose_bits: list[str] = []
        compose_group = entry["compose_group"]
        if compose_group:
            compose_bits.append(compose_group.split(".")[-1])
        compose_role = entry["compose_role"]
        if compose_role:
            compose_bits.append(compose_role)
        draw.text(
            (left + 8, top + card_height - 26),
            " • ".join(compose_bits)[:28] if compose_bits else entry["category"],
            fill=(180, 220, 255, 255),
        )
        connects = ",".join(entry["connects_on"]) or "-"
        draw.text((left + 8, top + card_height - 14), f"joins {connects}", fill=(190, 200, 190, 255))

    contact.save(output_path)


def _collection_member_sheet_cell(
    family: TileFamily,
    member: SourceLayoutCollectionMember,
) -> tuple[int, int] | None:
    if member.kind == "sheet_cell":
        cell = cast(SheetCell, member.value)
        return (cell.col, cell.row)
    if member.kind == "tile_id":
        tile = family.tiles.get(cast(str, member.value))
    else:
        alias = cast(str, member.value)
        tile = family.by_alias(alias) if alias in family.aliases else None
    if tile is None:
        return None
    if tile.genesis.sheet_col is None or tile.genesis.sheet_row is None:
        return None
    return (tile.genesis.sheet_col, tile.genesis.sheet_row)


def _collection_bounds_from_members(
    family: TileFamily,
    collection: SourceLayoutCollection,
) -> ClusterBoundsPayload | None:
    member_cells = [
        sheet_cell
        for member in collection.members
        for sheet_cell in [_collection_member_sheet_cell(family, member)]
        if sheet_cell is not None
    ]
    if not member_cells:
        return None
    min_col = min(col for col, _ in member_cells)
    max_col = max(col for col, _ in member_cells)
    min_row = min(row for _, row in member_cells)
    max_row = max(row for _, row in member_cells)
    return {
        "x": min_col,
        "y": min_row,
        "width": max_col - min_col + 1,
        "height": max_row - min_row + 1,
    }


def _semantic_cluster_bounds_from_members(
    family: TileFamily,
    cluster: TileClusterRecord,
) -> ClusterBoundsPayload | None:
    member_cells = [
        (tile.genesis.sheet_col, tile.genesis.sheet_row)
        for tile_id in cluster.members
        for tile in [family.tiles.get(tile_id)]
        if tile is not None and tile.genesis.sheet_col is not None and tile.genesis.sheet_row is not None
    ]
    if not member_cells:
        return None
    min_col = min(col for col, _ in member_cells)
    max_col = max(col for col, _ in member_cells)
    min_row = min(row for _, row in member_cells)
    max_row = max(row for _, row in member_cells)
    return {
        "x": min_col,
        "y": min_row,
        "width": max_col - min_col + 1,
        "height": max_row - min_row + 1,
    }


def _next_collection_review_round_id(root_dir: Path) -> str:
    rounds_dir = root_dir / "rounds"
    existing_numbers: list[int] = []
    if rounds_dir.exists():
        for child in rounds_dir.iterdir():
            match = re.fullmatch(r"round_(\d{3})", child.name)
            if match is not None and child.is_dir():
                existing_numbers.append(int(match.group(1)))
    next_number = 1 if not existing_numbers else max(existing_numbers) + 1
    return f"round_{next_number:03d}"


def _migrate_legacy_collection_review_root(root_dir: Path) -> None:
    rounds_dir = root_dir / "rounds"
    if rounds_dir.exists():
        return
    legacy_manifest = root_dir / "manifest.json"
    legacy_readme = root_dir / "README.md"
    legacy_images = root_dir / "images"
    legacy_collections = root_dir / "collections"
    if not (legacy_manifest.exists() and legacy_readme.exists() and legacy_images.exists() and legacy_collections.exists()):
        return
    round_dir = rounds_dir / "round_001"
    round_dir.mkdir(parents=True, exist_ok=False)
    legacy_manifest.rename(round_dir / "manifest.json")
    legacy_readme.rename(round_dir / "README.md")
    legacy_images.rename(round_dir / "images")
    legacy_collections.rename(round_dir / "collections")


def _write_collection_review_series_readme(
    *,
    root_dir: Path,
    project_path: Path,
    tileset_id: str,
    rounds: Sequence[str],
) -> None:
    lines = [
        "# Collection Review Series",
        "",
        "This directory tracks multiple committed rounds of collection feedback.",
        "Each round is additive: export a new round, review the Markdown files, and commit the edits.",
        "",
        f"- project: `{project_path}`",
        f"- tileset: `{tileset_id}`",
        "",
        "Rounds:",
        "",
    ]
    for round_id in rounds:
        lines.append(f"- [{round_id}](rounds/{round_id}/README.md)")
    (root_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root_dir / "series.json").write_text(
        json.dumps(
            {
                "project": str(project_path),
                "tileset": tileset_id,
                "round_count": len(rounds),
                "rounds": [
                    {"id": round_id, "path": f"rounds/{round_id}"}
                    for round_id in rounds
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_collection_review_scratch_assets(
    *,
    tileset: GridTileset,
    project: LayoutProject,
    round_dir: Path,
    scratch_round_dir: Path,
    manifest_collections: Sequence[dict[str, object]],
    scale: int,
) -> None:
    scratch_round_dir.mkdir(parents=True, exist_ok=True)

    overview_columns = 2
    preview_images: list[tuple[dict[str, object], Image.Image]] = []
    max_preview_width = 0
    max_preview_height = 0
    for collection in manifest_collections:
        preview_rel = cast(Union[str, None], collection.get("preview"))
        if preview_rel is None:
            continue
        preview_path = round_dir / preview_rel
        preview = Image.open(preview_path).convert("RGBA")
        preview_images.append((collection, preview))
        max_preview_width = max(max_preview_width, preview.width)
        max_preview_height = max(max_preview_height, preview.height)

    if preview_images:
        card_width = max(220, max_preview_width + 20)
        card_height = max(150, max_preview_height + 58)
        overview_rows = (len(preview_images) + overview_columns - 1) // overview_columns
        overview = Image.new(
            "RGBA",
            (overview_columns * card_width, overview_rows * card_height),
            (24, 25, 32, 255),
        )
        draw = ImageDraw.Draw(overview)

        for index, (collection, preview) in enumerate(preview_images):
            row = index // overview_columns
            col = index % overview_columns
            left = col * card_width
            top = row * card_height
            draw.rectangle(
                (left + 4, top + 4, left + card_width - 5, top + card_height - 5),
                outline=(246, 195, 124, 255),
            )
            preview_left = left + (card_width - preview.width) // 2
            preview_top = top + 10
            overview.alpha_composite(preview, (preview_left, preview_top))

            label = cast(str, collection["label"] or collection["id"])
            source_region_id = cast(Union[str, None], collection.get("source_region_id"))
            source_cluster_id = cast(Union[str, None], collection.get("source_cluster_id"))
            draw.text((left + 8, top + card_height - 38), label[:28], fill=(255, 255, 255, 255))
            draw.text((left + 8, top + card_height - 26), cast(str, collection["kind"])[:28], fill=(180, 220, 255, 255))
            source_bits: list[str] = []
            if source_region_id:
                source_bits.append(source_region_id.split(".")[-1])
            if source_cluster_id:
                source_bits.append(source_cluster_id.split(".")[-1])
            draw.text((left + 8, top + card_height - 14), " • ".join(source_bits)[:28], fill=(190, 200, 190, 255))

        overview.save(scratch_round_dir / "overview.png")

    overlay_scale = max(2, scale // 2)
    overlay = resize_nearest(tileset.image, (tileset.image.width * overlay_scale, tileset.image.height * overlay_scale))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_colours = [
        (246, 195, 124, 255),
        (180, 220, 255, 255),
        (156, 228, 160, 255),
        (255, 165, 195, 255),
        (255, 230, 120, 255),
    ]
    for index, collection in enumerate(manifest_collections):
        bounds = cast(Union[ClusterBoundsPayload, None], collection.get("bounds"))
        if bounds is None:
            continue
        _draw_bounds(
            draw=overlay_draw,
            bounds=bounds,
            scale=overlay_scale,
            tile_width=project.grid_width,
            tile_height=project.grid_height,
            colour=overlay_colours[index % len(overlay_colours)],
            label=cast(str, collection["label"] or collection["id"]),
        )
    overlay.save(scratch_round_dir / "sheet_overlay.png")

    scratch_readme_lines = [
        "# Collection Review Scratch Assets",
        "",
        "Scratch-only visuals for the committed collection review round.",
        "",
        f"- committed round: `{round_dir}`",
        "- overview: `overview.png`",
        "- overlay: `sheet_overlay.png`",
        "",
        "These files are disposable visual aids and can be regenerated from the committed round manifest and images.",
        "",
    ]
    (scratch_round_dir / "README.md").write_text("\n".join(scratch_readme_lines), encoding="utf-8")


def export_collection_review_pack(
    project: LayoutProject,
    tileset_id: str,
    output_dir: Path,
    *,
    scale: int = 8,
    scratch_output_root: Path | None = None,
) -> Path:
    family = project.source_family_for_tileset(tileset_id)
    if family is None or family.source_layout is None:
        raise ValueError(f"Tileset {tileset_id!r} does not expose a source-layout ingestion model")

    tileset = project.get_tileset(tileset_id)
    root_dir = output_dir
    root_dir.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_collection_review_root(root_dir)
    rounds_dir = root_dir / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)
    round_id = _next_collection_review_round_id(root_dir)
    round_dir = rounds_dir / round_id
    round_dir.mkdir(parents=True, exist_ok=False)
    images_dir = round_dir / "images"
    notes_dir = round_dir / "collections"
    images_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    manifest_collections: list[dict[str, object]] = []
    index_lines = [
        "# Collection Review Pack",
        "",
        "This pack is intended to be edited and committed.",
        "Do not regenerate it in place if you want to keep prior feedback; create a new slugged pack instead.",
        "",
        f"- project: `{project.project_path}`",
        f"- tileset: `{tileset_id}`",
        f"- round: `{round_id}`",
        "",
        "Collections in this pack:",
        "",
    ]

    for collection in family.source_layout.source_collections.values():
        slug = slugify_identifier(collection.id.replace(".", "-"))
        bounds = (
            {
                "x": collection.bounds.x,
                "y": collection.bounds.y,
                "width": collection.bounds.width,
                "height": collection.bounds.height,
            }
            if collection.bounds is not None
            else _collection_bounds_from_members(family, collection)
        )
        preview_rel: str | None = None
        if bounds is not None:
            preview = resize_nearest(
                tileset.image.crop(
                    (
                        bounds["x"] * project.grid_width,
                        bounds["y"] * project.grid_height,
                        (bounds["x"] + bounds["width"]) * project.grid_width,
                        (bounds["y"] + bounds["height"]) * project.grid_height,
                    )
                ),
                (bounds["width"] * project.grid_width * scale, bounds["height"] * project.grid_height * scale),
            )
            preview_name = f"{slug}.png"
            preview.save(images_dir / preview_name)
            preview_rel = f"images/{preview_name}"

        member_payloads = [collection_member_to_config(member) for member in collection.members]
        resolved_members = [
            {
                "ref": collection_member_ref(member),
                "kind": member.kind,
                "sheet_cell": (
                    {"col": sheet_cell[0], "row": sheet_cell[1]}
                    if (sheet_cell := _collection_member_sheet_cell(family, member)) is not None
                    else None
                ),
            }
            for member in collection.members
        ]
        manifest_collections.append(
            {
                "id": collection.id,
                "kind": collection.kind,
                "label": collection.label,
                "source_region_id": collection.source_region_id,
                "source_cluster_id": collection.source_cluster_id,
                "bounds": bounds,
                "members": member_payloads,
                "resolved_members": resolved_members,
                "notes": collection.notes,
                "preview": preview_rel,
                "feedback_file": f"collections/{slug}.md",
            }
        )

        feedback_lines = [
            f"# Collection Review: {collection.label or collection.id}",
            "",
            f"- collection_id: `{collection.id}`",
            f"- kind: `{collection.kind}`",
            f"- source_region_id: `{collection.source_region_id or ''}`",
            f"- source_cluster_id: `{collection.source_cluster_id or ''}`",
            f"- preview: `{preview_rel or 'none'}`",
            "",
            "## Current Members",
            "",
        ]
        for member in resolved_members:
            location = member["sheet_cell"]
            if location is not None:
                location_mapping = cast(dict[str, int], location)
                location_bits = f" -> sheet:{location_mapping['col']},{location_mapping['row']}"
            else:
                location_bits = ""
            feedback_lines.append(f"- `{member['kind']}` `{member['ref']}`{location_bits}")
        feedback_lines.extend(
            [
                "",
                "## Current Interpretation",
                "",
                collection.notes or "_No authored notes yet._",
                "",
                "## Feedback",
                "",
                "- Keep / rename / split / merge:",
                "- Membership corrections:",
                "- Better label:",
                "- Better kind:",
                "- Semantic notes:",
                "",
                "## Decision",
                "",
                "- Status:",
                "- Follow-up:",
                "",
            ]
        )
        (notes_dir / f"{slug}.md").write_text("\n".join(feedback_lines), encoding="utf-8")
        index_lines.append(f"- [{collection.label or collection.id}](collections/{slug}.md)")

    manifest = {
        "project": str(project.project_path),
        "tileset": tileset_id,
        "round_id": round_id,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "collection_count": len(manifest_collections),
        "collections": manifest_collections,
    }
    (round_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (round_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    if scratch_output_root is not None:
        _write_collection_review_scratch_assets(
            tileset=tileset,
            project=project,
            round_dir=round_dir,
            scratch_round_dir=scratch_output_root / round_id,
            manifest_collections=manifest_collections,
            scale=scale,
        )

    round_ids = sorted(child.name for child in rounds_dir.iterdir() if child.is_dir())
    _write_collection_review_series_readme(
        root_dir=root_dir,
        project_path=project.project_path,
        tileset_id=tileset_id,
        rounds=round_ids,
    )
    return round_dir


def _resolved_tile_for_semantic_entry(
    project: LayoutProject,
    tileset_id: str,
    entry: SemanticCatalogEntry,
) -> ResolvedTile:
    resolved = project.family_tile_for_ref(entry["id"], tileset_id=tileset_id)
    if resolved is not None:
        return resolved
    if entry["index"] is None:
        raise ValueError(f"Semantic entry {entry['id']!r} does not have a sheet index")
    return ResolvedTile(tileset_id=tileset_id, index=entry["index"])


def _image_for_semantic_entry(
    project: LayoutProject,
    tileset_id: str,
    entry: SemanticCatalogEntry,
) -> Image.Image:
    return render_tile_preview_image(project, _resolved_tile_for_semantic_entry(project, tileset_id, entry))


def _infer_art_convention(
    project: LayoutProject,
    tileset_id: str,
    entries: Sequence[SemanticCatalogEntry],
) -> dict[str, object]:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")

    bbox_counts: dict[tuple[int, int, int, int], int] = {}
    left_gutter = 0
    top_gutter = 0
    right_gutter = 0
    bottom_gutter = 0
    samples = 0

    for entry in entries:
        if entry["image_override"] is not None:
            continue
        image = _image_for_semantic_entry(project, tileset_id, entry)
        bbox = image.getbbox()
        if bbox is None:
            continue
        samples += 1
        bbox_counts[bbox] = bbox_counts.get(bbox, 0) + 1
        if bbox[0] > 0:
            left_gutter += 1
        if bbox[1] > 0:
            top_gutter += 1
        if bbox[2] < family.tile_width:
            right_gutter += 1
        if bbox[3] < family.tile_height:
            bottom_gutter += 1

    gutter_counts = {
        "left": left_gutter,
        "top": top_gutter,
        "right": right_gutter,
        "bottom": bottom_gutter,
    }
    dominant_gutter_edges = [
        edge
        for edge, _count in sorted(gutter_counts.items(), key=lambda item: (-item[1], item[0]))
        if gutter_counts[edge] > 0
    ][:2]
    anchor_x = "left" if right_gutter >= left_gutter else "right"
    anchor_y = "bottom" if top_gutter >= bottom_gutter else "top"
    dominant_bbox: dict[str, int] | None = None
    if bbox_counts:
        bbox, count = max(bbox_counts.items(), key=lambda item: (item[1], item[0]))
        dominant_bbox = {
            "left": bbox[0],
            "top": bbox[1],
            "right": bbox[2],
            "bottom": bbox[3],
            "count": count,
        }

    return {
        "tile_size": {"width": family.tile_width, "height": family.tile_height},
        "render_step": {
            "width": family.render_step_width or family.tile_width,
            "height": family.render_step_height or family.tile_height,
        },
        "sample_count": samples,
        "dominant_anchor": f"{anchor_y}_{anchor_x}",
        "dominant_gutter_edges": dominant_gutter_edges,
        "gutter_counts": gutter_counts,
        "dominant_bbox": dominant_bbox,
    }


def _public_label_for_semantic_entry(entry: SemanticCatalogEntry) -> str:
    meaning = (entry["meaning"] or "").strip()
    if meaning:
        return meaning.rstrip(".")
    if entry["aliases"]:
        return humanize_identifier(entry["aliases"][0])
    if entry["compose_group"] and entry["compose_role"]:
        return humanize_identifier(f'{entry["compose_group"].split(".")[-1]}_{entry["compose_role"]}')
    return humanize_identifier(entry["id"].split(":")[-1])


def _semantic_entry_sheet_label(entry: SemanticCatalogEntry) -> str:
    if entry["sheet_col"] is None or entry["sheet_row"] is None:
        return "synthetic"
    return f'{entry["sheet_col"]},{entry["sheet_row"]}'


def _public_tile_entry(
    family: TileFamily,
    entry: SemanticCatalogEntry,
) -> dict[str, object]:
    is_synthetic = entry["image_override"] is not None
    source_region_id: str | None = None
    source_cluster_ids: list[str] = []
    if (
        family.source_layout is not None
        and not is_synthetic
        and entry["sheet_col"] is not None
        and entry["sheet_row"] is not None
    ):
        source_region = family.source_layout.source_region_for_cell(entry["sheet_col"], entry["sheet_row"])
        source_region_id = source_region.id if source_region is not None else None
        source_cluster_ids = [
            cluster.id
            for cluster in family.source_layout.source_clusters_for_cell(entry["sheet_col"], entry["sheet_row"])
        ]

    compose: dict[str, object] | None = None
    if entry["compose_group"] or entry["compose_role"] or entry["connects_on"] or entry["requires_exposed_on"]:
        compose = {
            "group": entry["compose_group"],
            "role": entry["compose_role"],
            "connects_on": list(entry["connects_on"]),
            "requires_exposed_on": list(entry["requires_exposed_on"]),
        }

    state: dict[str, object] | None = None
    if entry["state_group"] or entry["state_role"] or entry["facing"] or entry["pose"]:
        state = {
            "group": entry["state_group"],
            "role": entry["state_role"],
            "facing": entry["facing"],
            "pose": entry["pose"],
        }

    animation: dict[str, object] | None = None
    if entry["animation_group"] or entry["animation_frame"] is not None:
        animation = {
            "group": entry["animation_group"],
            "frame": entry["animation_frame"],
            "frame_count": entry["animation_frame_count"],
        }

    return {
        "id": entry["id"],
        "label": _public_label_for_semantic_entry(entry),
        "description": entry["meaning"],
        "family_id": entry["family_id"],
        "sheet": None
        if is_synthetic
        else {
            "col": entry["sheet_col"],
            "row": entry["sheet_row"],
        },
        "source_layout": None
        if is_synthetic
        else {
            "source_region_id": source_region_id,
            "source_cluster_ids": source_cluster_ids,
            "source_group": entry["source_group"],
        },
        "layer": entry["layer"],
        "category": entry["category"],
        "tags": list(entry["tags"]),
        "aliases": list(entry["aliases"]),
        "scenes": list(entry["scenes"]),
        "semantics": list(entry["semantics"]),
        "motifs": list(entry["motifs"]),
        "cluster_ids": list(entry["cluster_ids"]),
        "walkable": entry["walkable"],
        "blocking": entry["blocking"],
        "noise": entry["noise"],
        "contrast": entry["contrast"],
        "temperature": entry["temperature"],
        "usage": entry["usage"],
        "style": entry["style"],
        "overlay": entry["overlay"],
        "footprint": entry["footprint"],
        "orientation": entry["orientation"],
        "compose": compose,
        "state": state,
        "animation": animation,
        "affordances": list(entry["affordances"]),
        "alt_uses": list(entry["alt_uses"]),
        "confidence": entry["meaning_confidence"],
        "empty_source_cell": entry["empty"],
        "exact_duplicate_of": entry["exact_duplicate_of"],
        "provenance": {
            "kind": "synthetic" if entry["image_override"] is not None else "sheet",
            "image_override": entry["image_override"],
            "physical_ref": entry["physical_ref"],
            "variant_ref": entry["variant_ref"],
        },
        "source_notes": entry["source_notes"],
    }


def _public_construction_entry(construction: object) -> dict[str, object]:
    if isinstance(construction, ParametricRunConstruction):
        return {
            "id": construction.id,
            "collection_id": construction.collection_id,
            "kind": construction.kind,
            "expose_as_entity": construction.expose_as_entity,
            "axis": construction.axis,
            "length_param": construction.length_param,
            "start": {
                "tile_id": construction.start_tile.id,
                "role": construction.start_tile.compose_role,
            },
            "repeat": {
                "tile_id": construction.repeat_tile.id,
                "role": construction.repeat_tile.compose_role,
            },
            "end": {
                "tile_id": construction.end_tile.id,
                "role": construction.end_tile.compose_role,
            },
        }

    if isinstance(construction, ParametricFrameConstruction):
        return {
            "id": construction.id,
            "collection_id": construction.collection_id,
            "kind": construction.kind,
            "expose_as_entity": construction.expose_as_entity,
            "min_width": construction.min_width,
            "min_height": construction.min_height,
            "width_param": construction.width_param,
            "height_param": construction.height_param,
            "corners": {
                role: {
                    "flip_x": corner.flip_x,
                    "flip_y": corner.flip_y,
                    "cells": [
                        [
                            None if tile is None else {"tile_id": tile.id, "role": tile.compose_role}
                            for tile in row
                        ]
                        for row in corner.cells
                    ],
                }
                for role, corner in construction.corners.items()
            },
            "edges": {
                role: {
                    "tile_id": slot.tile.id,
                    "role": slot.tile.compose_role,
                    "fill_mode": slot.fill_mode,
                    "flip_x": slot.flip_x,
                    "flip_y": slot.flip_y,
                }
                for role, slot in construction.edges.items()
            },
            "fill": (
                None
                if construction.fill is None
                else {
                    "tile_id": construction.fill.tile.id,
                    "role": construction.fill.tile.compose_role,
                    "fill_mode": construction.fill.fill_mode,
                }
            ),
        }
    metatile = cast(MetatileConstruction, construction)
    return {
        "id": metatile.id,
        "collection_id": metatile.collection_id,
        "kind": metatile.kind,
        "expose_as_entity": metatile.expose_as_entity,
        "shape": {
            "width": len(metatile.cells[0]) if metatile.cells else 0,
            "height": len(metatile.cells),
        },
        "cells": [
            [
                None
                if cell is None
                else {
                    "tile_id": cell.id,
                    "role": cell.compose_role,
                }
                for cell in row
            ]
            for row in metatile.cells
        ],
    }


def _public_composite_tile_entry(composite: CompositeTileRecord) -> dict[str, object]:
    return {
        "id": composite.id,
        "collection_id": composite.collection_id,
        "kind": composite.kind,
        "expose_as_entity": composite.expose_as_entity,
        "placement_anchor": composite.placement_anchor,
        "tags": list(composite.tags),
        "shape": {
            "width": composite.width,
            "height": composite.height,
        },
        "cells": [
            [
                None
                if cell is None
                else {
                    "tile_id": cell.tile.id,
                    "role": cell.role or cell.tile.compose_role,
                }
                for cell in row
            ]
            for row in composite.cells
        ],
    }


def _public_entity_template_entry(template: EntityTemplateRecord) -> dict[str, object]:
    return template.to_payload()


def _write_public_tiles_csv(entries: Sequence[dict[str, object]], output_path: Path) -> None:
    fieldnames = [
        "id",
        "label",
        "description",
        "family_id",
        "col",
        "row",
        "category",
        "layer",
        "confidence",
        "aliases",
        "tags",
        "semantics",
        "motifs",
        "cluster_ids",
        "source_region_id",
        "source_cluster_ids",
        "source_group",
        "compose_group",
        "compose_role",
        "connects_on",
        "requires_exposed_on",
        "state_group",
        "state_role",
        "facing",
        "pose",
        "animation_group",
        "animation_frame",
        "animation_frame_count",
        "exact_duplicate_of",
        "provenance_kind",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            sheet_obj = entry["sheet"]
            source_layout_obj = entry["source_layout"]
            sheet = cast(dict[str, object], sheet_obj) if isinstance(sheet_obj, dict) else None
            source_layout = cast(dict[str, object], source_layout_obj) if isinstance(source_layout_obj, dict) else None
            compose_obj = entry["compose"]
            state_obj = entry["state"]
            animation_obj = entry["animation"]
            compose = cast(dict[str, object], compose_obj) if isinstance(compose_obj, dict) else None
            state = cast(dict[str, object], state_obj) if isinstance(state_obj, dict) else None
            animation = cast(dict[str, object], animation_obj) if isinstance(animation_obj, dict) else None
            provenance = cast(dict[str, object], entry["provenance"])
            description = entry["description"] if isinstance(entry["description"], str) else ""
            confidence = entry["confidence"] if isinstance(entry["confidence"], str) else ""
            source_region_id = (
                source_layout["source_region_id"]
                if source_layout is not None and isinstance(source_layout["source_region_id"], str)
                else ""
            )
            source_group = (
                source_layout["source_group"]
                if source_layout is not None and isinstance(source_layout["source_group"], str)
                else ""
            )
            compose_group = compose["group"] if compose is not None and isinstance(compose["group"], str) else ""
            compose_role = compose["role"] if compose is not None and isinstance(compose["role"], str) else ""
            state_group = state["group"] if state is not None and isinstance(state["group"], str) else ""
            state_role = state["role"] if state is not None and isinstance(state["role"], str) else ""
            facing = state["facing"] if state is not None and isinstance(state["facing"], str) else ""
            pose = state["pose"] if state is not None and isinstance(state["pose"], str) else ""
            animation_group = animation["group"] if animation is not None and isinstance(animation["group"], str) else ""
            exact_duplicate_of = entry["exact_duplicate_of"] if isinstance(entry["exact_duplicate_of"], str) else ""
            writer.writerow(
                {
                    "id": cast(str, entry["id"]),
                    "label": cast(str, entry["label"]),
                    "description": description,
                    "family_id": cast(str, entry["family_id"]),
                    "col": "" if sheet is None else cast(int, sheet["col"]),
                    "row": "" if sheet is None else cast(int, sheet["row"]),
                    "category": cast(str, entry["category"]),
                    "layer": cast(str, entry["layer"]),
                    "confidence": confidence,
                    "aliases": "|".join(cast(list[str], entry["aliases"])),
                    "tags": "|".join(cast(list[str], entry["tags"])),
                    "semantics": "|".join(cast(list[str], entry["semantics"])),
                    "motifs": "|".join(cast(list[str], entry["motifs"])),
                    "cluster_ids": "|".join(cast(list[str], entry["cluster_ids"])),
                    "source_region_id": source_region_id,
                    "source_cluster_ids": "" if source_layout is None else "|".join(cast(list[str], source_layout["source_cluster_ids"])),
                    "source_group": source_group,
                    "compose_group": compose_group,
                    "compose_role": compose_role,
                    "connects_on": "" if compose is None else "|".join(cast(list[str], compose["connects_on"])),
                    "requires_exposed_on": "" if compose is None else "|".join(cast(list[str], compose["requires_exposed_on"])),
                    "state_group": state_group,
                    "state_role": state_role,
                    "facing": facing,
                    "pose": pose,
                    "animation_group": animation_group,
                    "animation_frame": "" if animation is None or animation["frame"] is None else cast(int, animation["frame"]),
                    "animation_frame_count": "" if animation is None or animation["frame_count"] is None else cast(int, animation["frame_count"]),
                    "exact_duplicate_of": exact_duplicate_of,
                    "provenance_kind": cast(str, provenance["kind"]),
                }
            )


def _write_public_tiles_contact_sheet(
    project: LayoutProject,
    tileset_id: str,
    entries: Sequence[SemanticCatalogEntry],
    output_path: Path,
    *,
    scale: int,
) -> None:
    if not entries:
        return

    previews: list[Image.Image] = []
    for entry in entries:
        preview = _image_for_semantic_entry(project, tileset_id, entry)
        previews.append(resize_nearest(preview, (preview.width * scale, preview.height * scale)))
    max_preview_width = max((preview.width for preview in previews), default=project.grid_width * scale)
    max_preview_height = max((preview.height for preview in previews), default=project.grid_height * scale)
    card_width = max(220, max_preview_width + 16)
    card_height = max(120, max_preview_height + 56)
    columns = 6
    rows = (len(entries) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, entry in enumerate(entries):
        row_index = idx // columns
        col_index = idx % columns
        left = col_index * card_width
        top = row_index * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(246, 195, 124, 255))
        tile = previews[idx]
        tile_left = left + (card_width - tile.width) // 2
        tile_top = top + 10
        contact.alpha_composite(tile, (tile_left, tile_top))
        label = _public_label_for_semantic_entry(entry)
        draw.text((left + 8, top + card_height - 38), label[:30], fill=(255, 255, 255, 255))
        draw.text(
            (left + 8, top + card_height - 26),
            f'{_semantic_entry_sheet_label(entry)} • {entry["category"]}',
            fill=(180, 220, 255, 255),
        )
        draw.text((left + 8, top + card_height - 14), entry["id"][:34], fill=(190, 200, 190, 255))

    contact.save(output_path)


def _collection_preview_image(
    tileset: GridTileset,
    project: LayoutProject,
    bounds: ClusterBoundsPayload,
    *,
    scale: int,
) -> Image.Image:
    return resize_nearest(
        tileset.image.crop(
            (
                bounds["x"] * project.grid_width,
                bounds["y"] * project.grid_height,
                (bounds["x"] + bounds["width"]) * project.grid_width,
                (bounds["y"] + bounds["height"]) * project.grid_height,
            )
        ),
        (bounds["width"] * project.grid_width * scale, bounds["height"] * project.grid_height * scale),
    )

def _construction_preview_image(
    project: LayoutProject,
    tileset_id: str,
    construction: Construction,
    *,
    scale: int,
    preview_length: int = 4,
) -> Image.Image:
    if isinstance(construction, ParametricFrameConstruction):
        preview_width = max(construction.min_width, 4)
        preview_height = max(construction.min_height, 3)

        def _preview_slot_tile(col: int, row: int) -> TileRecord | None:
            on_left = col == 0
            on_right = col == preview_width - 1
            on_top = row == 0
            on_bottom = row == preview_height - 1
            if (on_left or on_right) and (on_top or on_bottom):
                role = f"corner_{'t' if on_top else 'b'}{'l' if on_left else 'r'}"
                corner = construction.corners.get(role)
                if corner is None:
                    return None
                corner_tiles = corner.tiles()
                # Thumbnail: a representative corner tile (fat corners + flips are
                # rendered faithfully by the placement renderer, not this preview).
                return corner_tiles[0] if corner_tiles else None
            if on_top:
                slot = construction.edges.get("edge_top")
            elif on_bottom:
                slot = construction.edges.get("edge_bottom")
            elif on_left:
                slot = construction.edges.get("edge_left")
            elif on_right:
                slot = construction.edges.get("edge_right")
            else:
                slot = construction.fill
            return slot.tile if slot is not None else None

        frame_rows: list[list[ResolvedTile | None]] = []
        for row in range(preview_height):
            frame_row: list[ResolvedTile | None] = []
            for col in range(preview_width):
                tile = _preview_slot_tile(col, row)
                if tile is None:
                    frame_row.append(None)
                    continue
                resolved = project.family_tile_for_ref(tile.id, tileset_id=tileset_id)
                if resolved is None:
                    raise ValueError(f"Unable to resolve construction tile preview for {tile.id!r} in {tileset_id!r}")
                frame_row.append(resolved)
            frame_rows.append(frame_row)
        pattern = Pattern(
            width=preview_width,
            height=preview_height,
            cells=tuple(tuple(row) for row in frame_rows),
        )
        rendered = render_pattern_image(project, pattern, snap_to_grid=True)
        return resize_nearest(rendered, (rendered.width * scale, rendered.height * scale))
    if isinstance(construction, ParametricRunConstruction):
        length = max(3, preview_length)
        run_tiles = [construction.start_tile] + [construction.repeat_tile] * (length - 2) + [construction.end_tile]
        pattern_cells: list[list[ResolvedTile | None]] = []
        for tile in run_tiles:
            resolved = project.family_tile_for_ref(tile.id, tileset_id=tileset_id)
            if resolved is None:
                raise ValueError(f"Unable to resolve construction tile preview for {tile.id!r} in {tileset_id!r}")
            if construction.axis == "x":
                if not pattern_cells:
                    pattern_cells.append([])
                pattern_cells[0].append(resolved)
            else:
                pattern_cells.append([resolved])
        pattern = Pattern(
            width=length if construction.axis == "x" else 1,
            height=1 if construction.axis == "x" else length,
            cells=tuple(tuple(row) for row in pattern_cells),
        )
    else:
        resolved_rows: list[list[ResolvedTile | None]] = []
        for row in construction.cells:
            resolved_row: list[ResolvedTile | None] = []
            for cell in row:
                if cell is None:
                    resolved_row.append(None)
                    continue
                resolved = project.family_tile_for_ref(cell.id, tileset_id=tileset_id)
                if resolved is None:
                    raise ValueError(f"Unable to resolve construction tile preview for {cell.id!r} in {tileset_id!r}")
                resolved_row.append(resolved)
            resolved_rows.append(resolved_row)
        pattern = Pattern(
            width=len(construction.cells[0]) if construction.cells else 0,
            height=len(construction.cells),
            cells=tuple(tuple(row) for row in resolved_rows),
        )

    rendered = render_pattern_image(project, pattern, snap_to_grid=True)
    return resize_nearest(rendered, (rendered.width * scale, rendered.height * scale))


def _write_public_collections_contact_sheet(
    tileset: GridTileset,
    project: LayoutProject,
    collections: Sequence[dict[str, object]],
    output_path: Path,
    *,
    scale: int,
) -> None:
    if not collections:
        return

    previews: list[tuple[dict[str, object], Image.Image]] = []
    max_preview_width = 0
    max_preview_height = 0
    for collection in collections:
        bounds_value = collection.get("bounds")
        bounds = cast(ClusterBoundsPayload, bounds_value) if isinstance(bounds_value, dict) else None
        if bounds is None:
            continue
        preview = _collection_preview_image(tileset, project, bounds, scale=scale)
        previews.append((collection, preview))
        max_preview_width = max(max_preview_width, preview.width)
        max_preview_height = max(max_preview_height, preview.height)

    if not previews:
        return

    card_width = max(240, max_preview_width + 20)
    card_height = max(140, max_preview_height + 56)
    columns = 3
    rows = (len(previews) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, (collection, preview) in enumerate(previews):
        row_index = idx // columns
        col_index = idx % columns
        left = col_index * card_width
        top = row_index * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(120, 220, 255, 255))
        preview_left = left + (card_width - preview.width) // 2
        preview_top = top + 10
        contact.alpha_composite(preview, (preview_left, preview_top))
        label_value = collection.get("label")
        label = label_value if isinstance(label_value, str) else cast(str, collection["id"])
        draw.text((left + 8, top + card_height - 38), label[:30], fill=(255, 255, 255, 255))
        draw.text((left + 8, top + card_height - 26), cast(str, collection["kind"])[:30], fill=(180, 220, 255, 255))
        region_bits: list[str] = []
        source_region_value = collection.get("source_region_id")
        source_cluster_value = collection.get("source_cluster_id")
        source_region_id = source_region_value if isinstance(source_region_value, str) else None
        source_cluster_id = source_cluster_value if isinstance(source_cluster_value, str) else None
        if source_region_id:
            region_bits.append(source_region_id.split(".")[-1])
        if source_cluster_id:
            region_bits.append(source_cluster_id.split(".")[-1])
        draw.text((left + 8, top + card_height - 14), " • ".join(region_bits)[:30], fill=(190, 200, 190, 255))

    contact.save(output_path)


def _write_public_constructions_contact_sheet(
    constructions: Sequence[dict[str, object]],
    round_dir: Path,
    output_path: Path,
) -> None:
    preview_images: list[tuple[dict[str, object], Image.Image]] = []
    max_preview_width = 0
    max_preview_height = 0
    for construction in constructions:
        preview_rel_value = construction.get("preview")
        preview_rel = preview_rel_value if isinstance(preview_rel_value, str) else None
        if preview_rel is None:
            continue
        preview_path = round_dir / preview_rel
        preview = Image.open(preview_path).convert("RGBA")
        preview_images.append((construction, preview))
        max_preview_width = max(max_preview_width, preview.width)
        max_preview_height = max(max_preview_height, preview.height)

    if not preview_images:
        return

    card_width = max(240, max_preview_width + 20)
    card_height = max(140, max_preview_height + 56)
    columns = 3
    rows = (len(preview_images) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, (construction, preview) in enumerate(preview_images):
        row_index = idx // columns
        col_index = idx % columns
        left = col_index * card_width
        top = row_index * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(255, 200, 120, 255))
        preview_left = left + (card_width - preview.width) // 2
        preview_top = top + 10
        contact.alpha_composite(preview, (preview_left, preview_top))
        label_value = construction.get("id")
        label = label_value if isinstance(label_value, str) else "construction"
        kind_value = construction.get("kind")
        kind = kind_value if isinstance(kind_value, str) else "unknown"
        collection_value = construction.get("collection_id")
        collection_id = collection_value if isinstance(collection_value, str) else ""
        draw.text((left + 8, top + card_height - 38), humanize_identifier(label.split(".")[-1])[:30], fill=(255, 255, 255, 255))
        draw.text((left + 8, top + card_height - 26), kind[:30], fill=(180, 220, 255, 255))
        draw.text((left + 8, top + card_height - 14), collection_id[:30], fill=(190, 200, 190, 255))

    contact.save(output_path)


def _write_public_sheet_annotated(
    project: LayoutProject,
    tileset_id: str,
    output_path: Path,
    *,
    scale: int,
) -> None:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")

    tileset = project.get_tileset(tileset_id)
    preview = resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
    draw = ImageDraw.Draw(preview)

    for col in range(tileset.columns + 1):
        x = (tileset.margin + col * (tileset.tile_width + tileset.spacing)) * scale
        draw.line((x, 0, x, preview.height), fill=(255, 255, 255, 40))
    for row in range(tileset.rows + 1):
        y = (tileset.margin + row * (tileset.tile_height + tileset.spacing)) * scale
        draw.line((0, y, preview.width, y), fill=(255, 255, 255, 40))
    for col in range(0, tileset.columns, 4):
        _draw_text_with_backplate(draw, (col * tileset.tile_width * scale + 2, 2), str(col), fill=(255, 255, 255, 255))
    for row in range(0, tileset.rows, 4):
        _draw_text_with_backplate(draw, (2, row * tileset.tile_height * scale + 2), str(row), fill=(255, 255, 255, 255))

    if family.source_layout is not None:
        region_colours = [
            (255, 220, 120, 255),
            (120, 220, 255, 255),
            (180, 255, 160, 255),
            (255, 160, 210, 255),
        ]
        cluster_colour = (246, 195, 124, 255)
        collection_colour = (160, 240, 255, 255)
        for region_index, region in enumerate(family.source_layout.source_regions.values()):
            colour = region_colours[region_index % len(region_colours)]
            areas = region.areas or (region.bounds,)
            for area_index, area in enumerate(areas):
                _draw_bounds(
                    draw=draw,
                    bounds={"x": area.x, "y": area.y, "width": area.width, "height": area.height},
                    scale=scale,
                    tile_width=project.grid_width,
                    tile_height=project.grid_height,
                    colour=colour,
                    label=(region.label or region.id) if area_index == 0 else f"{region.id} area {area_index + 1}",
                )
        for cluster in family.source_layout.source_clusters.values():
            _draw_bounds(
                draw=draw,
                bounds={"x": cluster.bounds.x, "y": cluster.bounds.y, "width": cluster.bounds.width, "height": cluster.bounds.height},
                scale=scale,
                tile_width=project.grid_width,
                tile_height=project.grid_height,
                colour=cluster_colour,
                label=cluster.label or cluster.id,
            )
        for collection in family.source_layout.source_collections.values():
            bounds: ClusterBoundsPayload | None = (
                cast(
                    ClusterBoundsPayload,
                    {
                        "x": collection.bounds.x,
                        "y": collection.bounds.y,
                        "width": collection.bounds.width,
                        "height": collection.bounds.height,
                    },
                )
                if collection.bounds is not None
                else _collection_bounds_from_members(family, collection)
            )
            if bounds is None:
                continue
            _draw_bounds(
                draw=draw,
                bounds=bounds,
                scale=scale,
                tile_width=project.grid_width,
                tile_height=project.grid_height,
                colour=collection_colour,
                label=collection.label or collection.id,
            )

    preview.save(output_path)


def _prepare_public_tile_pack_output_dirs(output_dir: Path) -> tuple[Path, Path, Path]:
    if output_dir.exists():
        if output_dir.is_dir():
            shutil.rmtree(output_dir)
        else:
            output_dir.unlink()
    images_dir = output_dir / "images"
    collections_images_dir = images_dir / "collections"
    constructions_images_dir = images_dir / "constructions"
    collections_images_dir.mkdir(parents=True, exist_ok=True)
    constructions_images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir, collections_images_dir, constructions_images_dir


def _build_public_construction_entries(
    project: LayoutProject,
    tileset_id: str,
    family: TileFamily,
    constructions_images_dir: Path,
    *,
    scale: int,
) -> list[dict[str, object]]:
    construction_records = list(family.constructions.values())
    public_constructions = [_public_construction_entry(construction) for construction in construction_records]
    if len(public_constructions) != len(construction_records):
        raise ValueError("Construction preview export lost sync with the family construction registry")
    for index, construction in enumerate(construction_records):
        construction_entry = public_constructions[index]
        preview_name = f"{slugify_identifier(cast(str, construction_entry['id']))}.png"
        preview_path = constructions_images_dir / preview_name
        preview_length = 4 if isinstance(construction, ParametricRunConstruction) else None
        _construction_preview_image(
            project,
            tileset_id,
            construction,
            scale=scale,
            preview_length=preview_length or 4,
        ).save(preview_path)
        construction_entry["preview"] = f"images/constructions/{preview_name}"
        if preview_length is not None:
            construction_entry["preview_length"] = preview_length
    return public_constructions


def _build_public_composite_tile_entries(family: TileFamily) -> list[dict[str, object]]:
    return [_public_composite_tile_entry(composite) for composite in family.composite_tiles.values()]


def _build_public_collection_entries(
    family: TileFamily,
    tileset: GridTileset,
    project: LayoutProject,
    collections_images_dir: Path,
    *,
    scale: int,
) -> list[dict[str, object]]:
    public_collections: list[dict[str, object]] = []
    if family.source_layout is None:
        return public_collections
    for collection in family.source_layout.source_collections.values():
        bounds: ClusterBoundsPayload | None = (
            cast(
                ClusterBoundsPayload,
                {
                    "x": collection.bounds.x,
                    "y": collection.bounds.y,
                    "width": collection.bounds.width,
                    "height": collection.bounds.height,
                },
            )
            if collection.bounds is not None
            else _collection_bounds_from_members(family, collection)
        )
        preview_rel: str | None = None
        if bounds is not None:
            preview_name = f"{slugify_identifier(collection.id)}.png"
            preview_path = collections_images_dir / preview_name
            _collection_preview_image(tileset, project, bounds, scale=scale).save(preview_path)
            preview_rel = f"images/collections/{preview_name}"
        public_collections.append(
            {
                "id": collection.id,
                "kind": collection.kind,
                "label": collection.label or humanize_identifier(collection.id),
                "source_region_id": collection.source_region_id,
                "source_cluster_id": collection.source_cluster_id,
                "bounds": bounds,
                "members": [collection_member_to_config(member) for member in collection.members],
                "constructions": list(collection.constructions),
                "resolved_members": [
                    {
                        "ref": collection_member_ref(member),
                        "kind": member.kind,
                        "sheet_cell": (
                            {"col": sheet_cell[0], "row": sheet_cell[1]}
                            if (sheet_cell := _collection_member_sheet_cell(family, member)) is not None
                            else None
                        ),
                    }
                    for member in collection.members
                ],
                "notes": collection.notes,
                "preview": preview_rel,
            }
        )
    return public_collections


def _build_public_tile_pack_manifest(
    *,
    project_path: Path,
    tileset_id: str,
    family: TileFamily,
    variant_id: str | None,
    public_tiles: Sequence[dict[str, object]],
    preview_entries: Sequence[SemanticCatalogEntry],
    tile_clusters: Sequence[dict[str, object]],
    entity_templates: Sequence[dict[str, object]],
    source_layout_payload: dict[str, object] | None,
    public_collections: Sequence[dict[str, object]],
    public_composite_tiles: Sequence[dict[str, object]],
    public_constructions: Sequence[dict[str, object]],
    art_convention: dict[str, object],
) -> dict[str, object]:
    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "project": str(project_path),
        "tileset": tileset_id,
        "family_id": family.family_id,
        "family_title": family.title,
        "variant_id": variant_id,
        "tile_size": {"width": family.tile_width, "height": family.tile_height},
        "render_step": {
            "width": family.render_step_width or family.tile_width,
            "height": family.render_step_height or family.tile_height,
        },
        "art_convention": art_convention,
        "counts": {
            "tiles": len(public_tiles),
            "preview_tiles": len(preview_entries),
            "tile_clusters": len(tile_clusters),
            "entity_templates": len(entity_templates),
            "source_regions": 0 if source_layout_payload is None else len(cast(list[object], source_layout_payload["regions"])),
            "source_clusters": 0 if source_layout_payload is None else len(cast(list[object], source_layout_payload["clusters"])),
            "source_collections": len(public_collections),
            "composite_tiles": len(public_composite_tiles),
            "constructions": len(public_constructions),
        },
        "files": {
            "tiles": "tiles.json",
            "tiles_csv": "tiles.csv",
            "tile_clusters": "tile_clusters.json",
            "entity_templates": None if not entity_templates else "entity_templates.json",
            "source_regions": None if source_layout_payload is None else "source_regions.json",
            "source_clusters": None if source_layout_payload is None else "source_clusters.json",
            "source_collections": None if source_layout_payload is None else "source_collections.json",
            "sheet_annotated": "images/sheet_annotated.png",
            "tiles_contact_sheet": "images/tiles_contact_sheet.png",
            "collections_contact_sheet": None if not public_collections else "images/collections_contact_sheet.png",
            "composite_tiles": None if not public_composite_tiles else "composite_tiles.json",
            "constructions_contact_sheet": None if not public_constructions else "images/constructions_contact_sheet.png",
            "constructions": None if not public_constructions else "constructions.json",
        },
    }


def _write_public_tile_pack_payloads(
    *,
    output_dir: Path,
    manifest: dict[str, object],
    public_tiles: Sequence[dict[str, object]],
    tile_clusters: Sequence[dict[str, object]],
    entity_templates: Sequence[dict[str, object]],
    source_layout_payload: dict[str, object] | None,
    public_collections: Sequence[dict[str, object]],
    public_composite_tiles: Sequence[dict[str, object]],
    public_constructions: Sequence[dict[str, object]],
) -> None:
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_dir / "tiles.json").write_text(json.dumps(list(public_tiles), indent=2) + "\n", encoding="utf-8")
    _write_public_tiles_csv(list(public_tiles), output_dir / "tiles.csv")
    (output_dir / "tile_clusters.json").write_text(json.dumps(list(tile_clusters), indent=2) + "\n", encoding="utf-8")
    if entity_templates:
        (output_dir / "entity_templates.json").write_text(
            json.dumps(list(entity_templates), indent=2) + "\n",
            encoding="utf-8",
        )
    if source_layout_payload is not None:
        (output_dir / "source_regions.json").write_text(
            json.dumps(cast(list[object], source_layout_payload["regions"]), indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "source_clusters.json").write_text(
            json.dumps(cast(list[object], source_layout_payload["clusters"]), indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "source_collections.json").write_text(
            json.dumps(list(public_collections), indent=2) + "\n",
            encoding="utf-8",
        )
    if public_composite_tiles:
        (output_dir / "composite_tiles.json").write_text(
            json.dumps(list(public_composite_tiles), indent=2) + "\n",
            encoding="utf-8",
        )
    if public_constructions:
        (output_dir / "constructions.json").write_text(
            json.dumps(list(public_constructions), indent=2) + "\n",
            encoding="utf-8",
        )


def export_public_tile_pack(
    project_path: Path,
    tileset_id: str,
    output_dir: Path,
    *,
    scale: int = 8,
) -> Path:
    project = LayoutProject(project_path)
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")

    tileset = project.get_tileset(tileset_id)
    variant_id = project.variant_id_for_tileset(tileset_id)
    images_dir, collections_images_dir, constructions_images_dir = _prepare_public_tile_pack_output_dirs(output_dir)

    semantic_entries = build_semantic_catalog_entries(project, tileset_id, include_empty=True)
    preview_entries = [entry for entry in semantic_entries if _image_for_semantic_entry(project, tileset_id, entry).getbbox() is not None]
    public_tiles = [_public_tile_entry(family, entry) for entry in semantic_entries]
    tile_clusters = _tile_cluster_payloads(family)
    entity_templates = [_public_entity_template_entry(template) for template in family.entity_templates()]
    source_layout_payload = _source_layout_payload(family.source_layout) if family.source_layout is not None else None
    public_constructions = _build_public_construction_entries(
        project,
        tileset_id,
        family,
        constructions_images_dir,
        scale=scale,
    )
    public_composite_tiles = _build_public_composite_tile_entries(family)
    public_collections = _build_public_collection_entries(
        family,
        tileset,
        project,
        collections_images_dir,
        scale=scale,
    )
    art_convention = _infer_art_convention(project, tileset_id, semantic_entries)
    manifest = _build_public_tile_pack_manifest(
        project_path=project_path,
        tileset_id=tileset_id,
        family=family,
        variant_id=variant_id,
        public_tiles=public_tiles,
        preview_entries=preview_entries,
        tile_clusters=tile_clusters,
        entity_templates=entity_templates,
        source_layout_payload=source_layout_payload,
        public_collections=public_collections,
        public_composite_tiles=public_composite_tiles,
        public_constructions=public_constructions,
        art_convention=art_convention,
    )
    _write_public_tile_pack_payloads(
        output_dir=output_dir,
        manifest=manifest,
        public_tiles=public_tiles,
        tile_clusters=tile_clusters,
        entity_templates=entity_templates,
        source_layout_payload=source_layout_payload,
        public_collections=public_collections,
        public_composite_tiles=public_composite_tiles,
        public_constructions=public_constructions,
    )

    _write_public_sheet_annotated(project, tileset_id, images_dir / "sheet_annotated.png", scale=max(2, scale // 2))
    _write_public_tiles_contact_sheet(project, tileset_id, preview_entries, images_dir / "tiles_contact_sheet.png", scale=scale)
    _write_public_collections_contact_sheet(
        tileset=tileset,
        project=project,
        collections=public_collections,
        output_path=images_dir / "collections_contact_sheet.png",
        scale=scale,
    )
    _write_public_constructions_contact_sheet(
        public_constructions,
        output_dir,
        images_dir / "constructions_contact_sheet.png",
    )

    readme_lines = [
        f"# Public Tile Pack: {family.title or humanize_identifier(family.family_id)}",
        "",
        "Engine-light annotated export for external browsing, tooling, and procedural generation.",
        "",
        f"- tileset: `{tileset_id}`",
        f"- family_id: `{family.family_id}`",
        f"- variant_id: `{variant_id or ''}`",
        f"- tiles: `{len(public_tiles)}`",
        f"- tile_clusters: `{len(tile_clusters)}`",
        f"- entity_templates: `{len(entity_templates)}`",
        f"- source_collections: `{len(public_collections)}`",
        f"- composite_tiles: `{len(public_composite_tiles)}`",
        f"- constructions: `{len(public_constructions)}`",
        "",
        "Files:",
        "",
        "- `manifest.json`: pack summary and art convention metadata",
        "- `tiles.json`: one public semantic record per tile",
        "- `tiles.csv`: flat spreadsheet-friendly view of the tiles",
        "- `tile_clusters.json`: semantic/taxonomic cluster metadata",
        "- `entity_templates.json`: derived runtime entity templates backed by placeables",
        "- `composite_tiles.json`: resolved public composite tile records",
        "- `source_regions.json` / `source_clusters.json` / `source_collections.json`: source-sheet layout model",
        "- `images/sheet_annotated.png`: grid + region/cluster/collection overlay",
        "- `images/tiles_contact_sheet.png`: all exported tiles with labels",
        "- `images/collections_contact_sheet.png`: authored multi-tile collection previews",
        "",
    ]
    if public_constructions:
        readme_lines.append("- `images/constructions_contact_sheet.png`: resolved construction previews")
        readme_lines.append("- `constructions.json`: resolved public construction records with preview links")
        readme_lines.append("")
    (output_dir / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")
    return output_dir


def export_semantic_review_pack(
    project: LayoutProject,
    tileset_id: str,
    output_dir: Path,
    *,
    scene: str | None = None,
    categories: list[str] | None = None,
    alias_prefix: str | None = None,
    scale: int = 8,
) -> Path:
    tileset = project.get_tileset(tileset_id)
    entries = build_semantic_catalog_entries(project, tileset_id, include_empty=True)

    filtered: list[SemanticCatalogEntry] = []
    category_set = set(categories or [])
    for entry in entries:
        if scene is not None and scene not in entry["scenes"]:
            continue
        if category_set and entry["category"] not in category_set:
            continue
        if alias_prefix is not None and not any(alias.startswith(alias_prefix) for alias in entry["aliases"]):
            continue
        filtered.append(entry)

    filtered.sort(
        key=lambda entry: (
            entry["empty"],
            10**9 if entry["sheet_row"] is None else entry["sheet_row"],
            10**9 if entry["sheet_col"] is None else entry["sheet_col"],
            entry["id"],
        )
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    tiles_dir = output_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    exported: list[ReviewEntry] = []
    unresolved: list[ReviewEntry] = []
    for review_id, entry in enumerate(filtered, start=1):
        primary_alias = entry["aliases"][0] if entry["aliases"] else entry["id"]
        label = humanize_identifier(primary_alias)
        slug = slugify_identifier(primary_alias.replace(".", " "))
        enriched: ReviewEntry = {
            **entry,
            "review_id": review_id,
            "primary_alias": primary_alias,
            "label": label,
        }
        if entry["empty"]:
            unresolved.append(enriched)
            continue
        filename = f"{review_id:03d}_{slug}.png"
        tile = resize_nearest(
            _image_for_semantic_entry(project, tileset_id, entry),
            (tileset.tile_width * scale, tileset.tile_height * scale),
        )
        tile.save(tiles_dir / filename)
        enriched["file"] = f"tiles/{filename}"
        exported.append(enriched)

    payload = {
        "project": str(project.project_path),
        "tileset": tileset_id,
        "scene": scene,
        "categories": list(categories or []),
        "alias_prefix": alias_prefix,
        "scale": scale,
        "exported_count": len(exported),
        "unresolved_count": len(unresolved),
        "entries": exported,
        "unresolved_entries": unresolved,
    }
    (output_dir / "index.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Semantic Review Pack",
        "",
        f"- Project: `{project.project_path}`",
        f"- Tileset: `{tileset_id}`",
        f"- Scene filter: `{scene or 'none'}`",
        f"- Categories: `{', '.join(categories or []) or 'all'}`",
        f"- Alias prefix: `{alias_prefix or 'none'}`",
        f"- Tile export scale: `{scale}x`",
        "",
        "## Exported Tiles",
        "",
        "| Review ID | Physical ID | Alias | Category | Compose Group | Compose Role | Connects | File |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in exported:
        lines.append(
            f'| {entry["review_id"]:03d} | `{entry["id"]}` | `{entry["primary_alias"]}` | `{entry["category"]}` | '
            f'`{entry["compose_group"] or "-"}` | `{entry["compose_role"] or "-"}` | '
            f'`{",".join(entry["connects_on"]) or "-"}` | `{entry.get("file", "-")}` |'
        )
    if unresolved:
        lines.extend(
            [
                "",
                "## Semantic Entries With Empty Source Tiles",
                "",
                "| Alias | Category | Sheet Cell | Notes |",
                "| --- | --- | --- | --- |",
            ]
        )
        for entry in unresolved:
            lines.append(
                f'| `{entry["primary_alias"]}` | `{entry["category"]}` | '
                f'`{_semantic_entry_sheet_label(entry)}` | {entry["meaning"] or entry["source_notes"] or "-"} |'
            )
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    notes_lines = [
        "# Review Notes",
        "",
        "Write plain-language notes under each tile heading.",
        "",
        "You do not need to fill out metadata fields or use a rigid format.",
        "Just make it clear which tile you are talking about by writing under that tile's section.",
        "",
        "Good note examples:",
        "",
        "- Actually a bench, not a table.",
        "- This is the left end of a 3-wide counter. The flat side connects to the right.",
        "- Use against a north wall; do not place freestanding.",
        "- Not tavern furniture at all. Probably exterior trim.",
        "",
        "I will turn your notes into metadata after review.",
        "",
    ]
    for entry in exported:
        notes_lines.extend(
            [
                f'## Tile {entry["review_id"]:03d} - {entry["label"]}',
                "",
                f'![Tile {entry["review_id"]:03d}]({entry.get("file", "")})',
                "",
                f'- file: `{entry.get("file", "-")}`',
                f'- stable tile id: `{entry["id"]}`',
                f'- variant address: `{entry["variant_ref"] or "-"}`',
                f'- source sheet cell: `{_semantic_entry_sheet_label(entry)}`',
                f'- source group: `{entry["source_group"] or "-"}`',
                f'- current guess: `{entry["primary_alias"]}`',
                f'- category: `{entry["category"]}`',
                f'- current meaning: {entry["meaning"] or "-"}',
                f'- meaning confidence: `{entry["meaning_confidence"] or "-"}`',
                f'- source context: {entry["source_notes"] or "-"}',
                f'- current semantics: `{", ".join(entry["semantics"]) or "-"}`',
                f'- alternate uses: `{", ".join(entry["alt_uses"]) or "-"}`',
                "",
                "Your notes:",
                "- ",
                "",
            ]
        )
    if unresolved:
        notes_lines.extend(
            [
                "## Unresolved Semantic Entries",
                "",
            ]
        )
        for entry in unresolved:
            notes_lines.extend(
                [
                    f'### {entry["primary_alias"]}',
                    "",
                    f'- mapped sheet cell: `{_semantic_entry_sheet_label(entry)}`',
                    f'- current issue: {entry["source_notes"] or entry["meaning"] or "-"}',
                    "",
                    "Your notes:",
                    "- ",
                    "",
                ]
            )
    (output_dir / "review_notes.md").write_text("\n".join(notes_lines), encoding="utf-8")

    write_review_contact_sheet(
        exported,
        project=project,
        tileset_id=tileset_id,
        output_path=output_dir / "contact_sheet.png",
        scale=scale,
    )
    return output_dir


def query_semantic_catalog(
    project_path: Path,
    tileset_id: str,
    *,
    region: str | None = None,
    category: str | None = None,
    scene: str | None = None,
    usage: str | None = None,
    contrast: str | None = None,
    temperature: str | None = None,
    style: str | None = None,
    orientation: str | None = None,
    compose_group: str | None = None,
    compose_role: str | None = None,
    semantics_all: list[str] | None = None,
    tags_all: list[str] | None = None,
    walkable: bool | None = None,
    blocking: bool | None = None,
    alias_prefix: str | None = None,
    limit: int | None = None,
) -> list[SemanticCatalogEntry]:
    project = LayoutProject(project_path)
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        return []
    records = family.query(
        category=category,
        scene=scene,
        usage=usage,
        contrast=contrast,
        temperature=temperature,
        style=style,
        orientation=orientation,
        compose_group=compose_group,
        compose_role=compose_role,
        semantics_all=semantics_all or (),
        tags_all=tags_all or (),
        walkable=walkable,
        blocking=blocking,
    )
    if region is not None:
        records = [tile for tile in records if family.source_region_id_for_tile(tile) == region]
    results = build_semantic_catalog_entries(project, tileset_id, tile_records=records)
    if alias_prefix is not None:
        results = [entry for entry in results if any(alias.startswith(alias_prefix) for alias in entry["aliases"])]
    if limit is not None:
        return results[:limit]
    return results


def inspect_source_cell(
    project: LayoutProject,
    tileset_id: str,
    *,
    sheet_col: int,
    sheet_row: int,
) -> dict[str, object]:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")
    if family.source_layout is None:
        raise ValueError(f"Tileset {tileset_id!r} has no source-layout ingest metadata")

    source_region = family.source_layout.source_region_for_cell(sheet_col, sheet_row)
    source_clusters = family.source_layout.source_clusters_for_cell(sheet_col, sheet_row)
    tile = family.tile_at_sheet_cell(sheet_col=sheet_col, sheet_row=sheet_row)

    tile_payload: dict[str, object] | None = None
    if tile is not None:
        tile_payload = {
            "id": tile.id,
            "canonical_tile_id": family.canonical_tile_id(tile.id),
            "family_id": tile.family_id,
            "layer": tile.layer,
            "category": tile.category,
            "sheet": {
                "col": tile.genesis.sheet_col,
                "row": tile.genesis.sheet_row,
                "label_col": None if tile.genesis.sheet_col is None else tile.genesis.sheet_col + 1,
                "label_row": None if tile.genesis.sheet_row is None else tile.genesis.sheet_row + 1,
            },
            "source_group": tile.genesis.source_group,
            "semantic_cluster_ids": list(tile.genesis.cluster_ids),
            "aliases": list(family.aliases_for_tile(tile.id)),
            "semantics": list(tile.semantics),
            "meaning": tile.meaning,
            "meaning_confidence": tile.meaning_confidence,
        }

    return {
        "project": str(project.project_path),
        "tileset": tileset_id,
        "sheet_cell": {
            "col": sheet_col,
            "row": sheet_row,
            "label_col": sheet_col + 1,
            "label_row": sheet_row + 1,
        },
        "source_layout": {
            "in_sheet_bounds": family.source_layout.contains_cell(sheet_col, sheet_row),
            "ignored": family.source_layout.ignored_cell(sheet_col, sheet_row),
            "region": None
            if source_region is None
            else {
                "id": source_region.id,
                "label": source_region.label,
                "bounds": {
                    "x": source_region.bounds.x,
                    "y": source_region.bounds.y,
                    "width": source_region.bounds.width,
                    "height": source_region.bounds.height,
                },
            },
            "clusters": [
                {
                    "id": cluster.id,
                    "label": cluster.label,
                    "source_region_id": cluster.source_region_id,
                    "bounds": {
                        "x": cluster.bounds.x,
                        "y": cluster.bounds.y,
                        "width": cluster.bounds.width,
                        "height": cluster.bounds.height,
                    },
                }
                for cluster in source_clusters
            ],
        },
        "tile": tile_payload,
    }


def inspect_family(
    project: LayoutProject,
    tileset_id: str,
    output_dir: Path,
) -> Path:
    tileset = project.get_tileset(tileset_id)
    family = project.source_family_for_tileset(tileset_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_catalog = build_catalog(project, tileset_id)
    semantic_catalog = build_semantic_catalog(project, tileset_id)
    catalog = merge_semantic_catalog(raw_catalog, semantic_catalog)
    (output_dir / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    scale = 4
    preview = resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
    draw = ImageDraw.Draw(preview)
    for col in range(tileset.columns + 1):
        x = (tileset.margin + col * (tileset.tile_width + tileset.spacing)) * scale
        draw.line((x, 0, x, preview.height), fill=(255, 255, 255, 40))
    for row in range(tileset.rows + 1):
        y = (tileset.margin + row * (tileset.tile_height + tileset.spacing)) * scale
        draw.line((0, y, preview.width, y), fill=(255, 255, 255, 40))
    if family is not None and family.source_layout is not None:
        for region in family.source_layout.source_regions.values():
            areas = region.areas or (region.bounds,)
            for area_index, area in enumerate(areas):
                left = area.x * tileset.tile_width * scale
                top = area.y * tileset.tile_height * scale
                right = left + area.width * tileset.tile_width * scale
                bottom = top + area.height * tileset.tile_height * scale
                draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 220, 120, 255), width=2)
                label = region.label or region.id
                if area_index > 0:
                    label = f"{region.id}:area_{area_index + 1}"
                draw.text((left + 4, top + 4), label, fill=(255, 220, 120, 255))
    else:
        for region_name, region in tileset.regions.items():
            left = region.x * tileset.tile_width * scale
            top = region.y * tileset.tile_height * scale
            right = left + region.width * tileset.tile_width * scale
            bottom = top + region.height * tileset.tile_height * scale
            draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 220, 120, 255), width=2)
            draw.text((left + 4, top + 4), region_name, fill=(255, 220, 120, 255))
    for col in range(0, tileset.columns, 4):
        draw.text((col * tileset.tile_width * scale + 2, 2), str(col), fill=(255, 255, 255, 255))
    for row in range(0, tileset.rows, 4):
        draw.text((2, row * tileset.tile_height * scale + 2), str(row), fill=(255, 255, 255, 255))
    preview.save(output_dir / "sheet_grid.png")

    card_width = 112
    card_height = 80
    columns = 6
    rows = (len(catalog) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)
    for idx, entry in enumerate(catalog):
        row = idx // columns
        col = idx % columns
        card_left = col * card_width
        card_top = row * card_height
        index = cast(int, entry["index"])
        entry_col = cast(int, entry["col"])
        entry_row = cast(int, entry["row"])
        draw.rectangle((card_left + 4, card_top + 4, card_left + card_width - 5, card_top + card_height - 5), outline=(246, 195, 124, 255))
        tile = resize_nearest(tileset.tile_image(index), (tileset.tile_width * 6, tileset.tile_height * 6))
        tile_left = card_left + (card_width - tile.width) // 2
        tile_top = card_top + 12
        contact.alpha_composite(tile, (tile_left, tile_top))
        draw.text((card_left + 8, card_top + 56), f'id {index}', fill=(255, 255, 255, 255))
        draw.text((card_left + 8, card_top + 68), f'{entry_col},{entry_row}', fill=(180, 220, 255, 255))
    contact.save(output_dir / "non_empty_tiles.png")
    inspect_tile_edges(project, tileset_id, output_dir)
    inspect_patterns(project, tileset_id, output_dir)
    inspect_source_layout(project, tileset_id, output_dir)
    inspect_clusters(project, tileset_id, output_dir)
    inspect_semantic_catalog(project, tileset_id, output_dir)
    return output_dir


def detect_family_source_layout(
    project: LayoutProject,
    tileset_id: str,
    output_dir: Path,
) -> Path:
    tileset = project.get_tileset(tileset_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    detected = detect_source_layout(image=tileset.image, tile_width=project.grid_width, tile_height=project.grid_height)
    (output_dir / "source_layout.detected.json").write_text(json.dumps(detected, indent=2) + "\n", encoding="utf-8")
    return output_dir


def validate_family_ingest(
    project: LayoutProject,
    tileset_id: str,
) -> TileFamilyIngestReport:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")
    return family.ingest_report()


class SemanticUsageAuditIssue(TypedDict):
    source: str
    ref: str
    resolved_tile_id: str
    tileset_id: str
    meaning_confidence: str | None
    meaning: str | None


class SemanticUsageAuditReport(TypedDict):
    project: str
    tileset: str
    total_references: int
    total_resolved_family_tiles: int
    flagged_references: int
    by_meaning_confidence: dict[str, int]
    issues: list[SemanticUsageAuditIssue]


def _token_label(token: TileRefToken) -> str:
    if isinstance(token, str):
        return token
    return json.dumps(token, sort_keys=True)


def _collect_project_semantic_reference_tokens(
    project: LayoutProject,
    *,
    layouts_dir: Path,
) -> Iterator[tuple[str, TileRefToken]]:
    for alias, token in sorted(project.aliases.items()):
        yield (f"project alias {alias}", token)

    for name, spec in sorted(project.pattern_specs.items()):
        rows = spec.get("rows")
        if rows is None:
            continue
        for row_index, row in enumerate(rows):
            for col_index, cell in enumerate(row):
                yield (f"pattern {name} rows[{row_index}][{col_index}]", cell)

    for layout_path in sorted(layouts_dir.glob("*.json")):
        layout = load_layout_config(layout_path)
        for layer_index, layer in enumerate(layout.get("layers", [])):
            for op_index, op in enumerate(layer.get("ops", [])):
                kind = op.get("kind")
                base = f"{layout_path.name} layer[{layer_index}] op[{op_index}]"
                ref = op.get("ref")
                if kind in {"stamp", "fill", "mask_fill", "repeat"} and ref is not None:
                    yield (f"{base} {kind}.ref", ref)
                elif kind == "scatter":
                    for ref_index, ref in enumerate(cast(list[TileRefToken], op.get("refs", []))):
                        yield (f"{base} scatter.refs[{ref_index}]", ref)
                elif kind == "ascii":
                    legend = cast(dict[str, TileRefToken], op.get("legend", {}))
                    for key, ref in sorted(legend.items()):
                        yield (f"{base} ascii.legend[{key!r}]", ref)


def audit_family_semantic_usage(
    project: LayoutProject,
    tileset_id: str,
    *,
    layouts_dir: Path | None = None,
) -> SemanticUsageAuditReport:
    family = project.source_family_for_tileset(tileset_id)
    if family is None:
        raise ValueError(f"Tileset {tileset_id!r} is not backed by a tile family")

    resolved_by_tileset: dict[str, tuple[dict[str, SemanticCatalogEntry], dict[int, SemanticCatalogEntry]]] = {}

    def entry_for_resolved_tile(tile: ResolvedTile) -> SemanticCatalogEntry | None:
        if tile.tileset_id not in resolved_by_tileset:
            tile_family = project.source_family_for_tileset(tile.tileset_id)
            if tile_family is None:
                resolved_by_tileset[tile.tileset_id] = ({}, {})
            else:
                entries = build_semantic_catalog_entries(project, tile.tileset_id, include_empty=True)
                by_id = {entry["id"]: entry for entry in entries}
                by_index = {
                    entry["index"]: entry
                    for entry in entries
                    if entry["index"] is not None
                }
                resolved_by_tileset[tile.tileset_id] = (by_id, by_index)
        by_id, by_index = resolved_by_tileset[tile.tileset_id]
        if tile.family_tile_id is not None:
            return by_id.get(tile.family_tile_id)
        if tile.index is None:
            return None
        return by_index.get(tile.index)

    issues: list[SemanticUsageAuditIssue] = []
    by_meaning_confidence: dict[str, int] = {}
    total_references = 0
    total_resolved_family_tiles = 0

    for alias, tile_id in sorted(family.aliases.items()):
        total_references += 1
        tile = family.tiles[tile_id]
        confidence = tile.meaning_confidence
        by_meaning_confidence[confidence or "missing"] = by_meaning_confidence.get(confidence or "missing", 0) + 1
        total_resolved_family_tiles += 1
        if confidence != "confirmed":
            issues.append(
                {
                    "source": f"family alias {alias}",
                    "ref": alias,
                    "resolved_tile_id": tile.id,
                    "tileset_id": tileset_id,
                    "meaning_confidence": confidence,
                    "meaning": tile.meaning,
                }
            )

    scan_layouts_dir = layouts_dir or (project.base_dir / "layouts")
    for source, token in _collect_project_semantic_reference_tokens(project, layouts_dir=scan_layouts_dir):
        total_references += 1
        pattern = project.pattern_from_ref(token, default_tileset=tileset_id)
        seen_entries: set[tuple[str, str]] = set()
        for row in pattern.cells:
            for cell in row:
                if cell is None:
                    continue
                entry = entry_for_resolved_tile(cell)
                if entry is None:
                    continue
                total_resolved_family_tiles += 1
                confidence = entry["meaning_confidence"]
                by_meaning_confidence[confidence or "missing"] = by_meaning_confidence.get(confidence or "missing", 0) + 1
                key = (source, entry["id"])
                if confidence == "confirmed" or key in seen_entries:
                    continue
                seen_entries.add(key)
                issues.append(
                    {
                        "source": source,
                        "ref": _token_label(token),
                        "resolved_tile_id": entry["id"],
                        "tileset_id": cell.tileset_id,
                        "meaning_confidence": confidence,
                        "meaning": entry["meaning"],
                    }
                )

    return {
        "project": str(project.project_path),
        "tileset": tileset_id,
        "total_references": total_references,
        "total_resolved_family_tiles": total_resolved_family_tiles,
        "flagged_references": len(issues),
        "by_meaning_confidence": dict(sorted(by_meaning_confidence.items())),
        "issues": sorted(issues, key=lambda issue: (issue["source"], issue["resolved_tile_id"])),
    }


class CollectionTilesetEntry(TypedDict):
    id: int
    name: str
    source: str
    width: int
    height: int


def write_collection_tileset(
    tsx_path: Path,
    *,
    name: str,
    tiles: Sequence[CollectionTilesetEntry],
    object_alignment: str = "topleft",
) -> None:
    tilewidth = max((tile["width"] for tile in tiles), default=8)
    tileheight = max((tile["height"] for tile in tiles), default=8)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<tileset version="1.10" tiledversion="1.12.1" name="{escape_xml(name)}" '
            f'tilewidth="{tilewidth}" tileheight="{tileheight}" tilecount="{len(tiles)}" '
            f'columns="0" objectalignment="{escape_xml(object_alignment)}">'
        ),
    ]
    for tile in tiles:
        lines.append(f'  <tile id="{tile["id"]}" type="{escape_xml(tile["name"])}">')
        lines.append(
            f'    <image source="{escape_xml(tile["source"])}" width="{tile["width"]}" height="{tile["height"]}"/>'
        )
        lines.append("  </tile>")
    lines.append("</tileset>")
    tsx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_starter_map(
    map_path: Path,
    *,
    cells_tileset_name: str,
    cell_count: int,
    source_tile_width: int,
    source_tile_height: int,
    render_step_width: int,
    render_step_height: int,
    viewport_width_pixels: int,
    viewport_height_pixels: int,
    patterns_tileset_name: str | None = None,
    pattern_count: int = 0,
) -> None:
    width_tiles = 40
    height_tiles = 25
    layers: list[dict[str, object]] = [
        {
            "id": 1,
            "name": "terrain",
            "type": "tilelayer",
            "width": width_tiles,
            "height": height_tiles,
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "data": [0] * (width_tiles * height_tiles),
        },
        {
            "id": 2,
            "name": "detail",
            "type": "tilelayer",
            "width": width_tiles,
            "height": height_tiles,
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "data": [0] * (width_tiles * height_tiles),
        },
        {
            "id": 3,
            "name": "prefabs_back",
            "type": "objectgroup",
            "draworder": "topdown",
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "objects": [],
        },
        {
            "id": 4,
            "name": "actors",
            "type": "objectgroup",
            "draworder": "topdown",
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "objects": [],
        },
        {
            "id": 5,
            "name": "prefabs_front",
            "type": "objectgroup",
            "draworder": "topdown",
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "objects": [],
        },
        {
            "id": 6,
            "name": "hud",
            "type": "objectgroup",
            "draworder": "topdown",
            "x": 0,
            "y": 0,
            "visible": True,
            "opacity": 1,
            "objects": [],
        },
    ]
    tilesets: list[dict[str, object]] = [{"firstgid": 1, "source": "cells.tsx"}]
    if patterns_tileset_name is not None and pattern_count:
        tilesets.append({"firstgid": 1 + cell_count, "source": "patterns.tsx"})
    data: dict[str, object] = {
        "compressionlevel": -1,
        "height": height_tiles,
        "infinite": False,
        "layers": layers,
        "nextlayerid": 7,
        "nextobjectid": 1,
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "tileheight": source_tile_height,
        "tilewidth": source_tile_width,
        "tiledversion": "1.12.1",
        "type": "map",
        "version": "1.10",
        "width": width_tiles,
        "properties": [
            {"name": "viewport_width", "type": "int", "value": viewport_width_pixels},
            {"name": "viewport_height", "type": "int", "value": viewport_height_pixels},
            {"name": "render_step_width", "type": "int", "value": render_step_width},
            {"name": "render_step_height", "type": "int", "value": render_step_height},
            {"name": "cells_tileset_name", "type": "string", "value": cells_tileset_name},
            {"name": "cell_count", "type": "int", "value": cell_count},
            {"name": "patterns_tileset_name", "type": "string", "value": patterns_tileset_name or ""},
            {"name": "pattern_count", "type": "int", "value": pattern_count},
        ],
        "tilesets": tilesets,
    }
    map_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def export_tiled_kit(project_path: Path, tileset_id: str, output_dir: Path) -> Path:
    project = LayoutProject(project_path)
    tileset = project.get_tileset(tileset_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_dir in (output_dir / "cells", output_dir / "patterns", output_dir / "tiles"):
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    for stale_file in (
        output_dir / "tiles.tsx",
        output_dir / "cells.tsx",
        output_dir / "patterns.tsx",
        output_dir / "catalog.json",
        output_dir / "cells_catalog.json",
        output_dir / "patterns_catalog.json",
        output_dir / "semantic_catalog.json",
        output_dir / "starter_c64_room.tmj",
        output_dir / "README.md",
    ):
        if stale_file.exists():
            stale_file.unlink()
    cells_dir = output_dir / "cells"
    patterns_dir = output_dir / "patterns"
    cells_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)

    raw_catalog = build_catalog(project, tileset_id)
    semantic_catalog = build_semantic_catalog(project, tileset_id)
    catalog = merge_semantic_catalog(raw_catalog, semantic_catalog)
    exported_tiles: list[CollectionTilesetEntry] = []
    for exported_id, entry in enumerate(catalog):
        index = cast(int, entry["index"])
        col = cast(int, entry["col"])
        row = cast(int, entry["row"])
        filename = f'{index:04d}_{col:02d}_{row:02d}.png'
        path = cells_dir / filename
        tileset.tile_image(index).save(path)
        exported_tiles.append(
            {
                "id": exported_id,
                "name": f'{tileset_id}_{col}_{row}',
                "source": path.relative_to(output_dir).as_posix(),
                "width": project.grid_width,
                "height": project.grid_height,
            }
        )

    pattern_catalog = build_pattern_catalog(project, tileset_id=tileset_id)
    exported_patterns: list[CollectionTilesetEntry] = []
    for exported_id, entry in enumerate(pattern_catalog):
        filename = f'{entry["name"]}.png'
        path = patterns_dir / filename
        pattern = project.pattern_from_name(entry["name"])
        render_pattern_image(project, pattern, snap_to_grid=True).save(path)
        exported_patterns.append(
            {
                "id": exported_id,
                "name": entry["name"],
                "source": path.relative_to(output_dir).as_posix(),
                "width": entry["width_pixels"],
                "height": entry["height_pixels"],
            }
        )

    write_collection_tileset(output_dir / "cells.tsx", name=f"{tileset_id} cells", tiles=exported_tiles)
    write_collection_tileset(output_dir / "patterns.tsx", name=f"{tileset_id} patterns", tiles=exported_patterns)
    write_starter_map(
        output_dir / "starter_c64_room.tmj",
        cells_tileset_name=tileset_id,
        cell_count=len(exported_tiles),
        source_tile_width=project.grid_width,
        source_tile_height=project.grid_height,
        render_step_width=project.render_step_width,
        render_step_height=project.render_step_height,
        viewport_width_pixels=project.pixel_width_for_tiles(40),
        viewport_height_pixels=project.pixel_height_for_tiles(25),
        patterns_tileset_name=tileset_id,
        pattern_count=len(exported_patterns),
    )
    (output_dir / "cells_catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    (output_dir / "patterns_catalog.json").write_text(json.dumps(pattern_catalog, indent=2) + "\n", encoding="utf-8")
    if semantic_catalog:
        (output_dir / "semantic_catalog.json").write_text(json.dumps(semantic_catalog, indent=2) + "\n", encoding="utf-8")
    readme = "\n".join(
        [
            "# Tiled Kit",
            "",
            "This exports every non-empty 8x8 cell from the selected spritesheet plus project-defined patterns.",
            "",
            f"- `cells.tsx`: collection-of-images tileset for all {len(exported_tiles)} non-empty source cells",
            "- `patterns.tsx`: collection-of-images tileset for larger reusable modules and snippets",
            (
                "- `starter_c64_room.tmj`: 40x25 logical starter room, rendered here as "
                f"{project.pixel_width_for_tiles(40)}x{project.pixel_height_for_tiles(25)} "
                f"with a {project.render_step_width}x{project.render_step_height} stride"
            ),
            "- `cells_catalog.json`: source-sheet index/coordinate lookup, merged with semantic metadata where available",
            "- `patterns_catalog.json`: pattern size and name lookup",
            "- `semantic_catalog.json`: canonical semantic tile metadata for agent-assisted layout work",
            "",
            "Suggested split:",
            "- paint terrain and detail on tile layers using `cells.tsx`",
            "- place larger structures on object layers using `patterns.tsx`",
            "- keep actors and HUD separate so the viewport logic stays clean",
        ]
    )
    (output_dir / "README.md").write_text(readme + "\n", encoding="utf-8")
    return output_dir
