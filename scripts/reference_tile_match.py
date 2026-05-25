from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal, Mapping, TypedDict, cast

from PIL import Image

from reference_grid import (
    build_cell_crops,
    cell_intersects_rectangles,
    content_box_setting,
    float_setting,
    int_setting,
    normalize_cell_size_setting,
    path_setting,
    prepare_reference_grid,
    rectangle_setting,
    rectangles_setting,
    require_mapping,
    GridExtraction,
    GridTransform,
    build_tile_grid,
    load_reference_config,
    normalize_prepared_reference_grid,
    Rect,
    resolve_normalized_cell_size,
    resize_nearest,
    string_setting,
)
from tile_families import TileFamily


RGBA = tuple[int, int, int, int]
GuideRef = str


class TileMatchMetadata(TypedDict):
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: list[str]


class TileMatchCandidate(TypedDict):
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: list[str]
    score: float
    pixel_match_ratio: float
    mask_match_ratio: float
    mask_iou: float
    effective_mask_iou: float
    trimmed_logical_iou: float
    mask_iou_rescue_applied: bool
    fill_similarity: float
    edge_match_ratio: float
    chamfer_similarity: float
    projection_similarity: float


class ReferenceCellMatch(TypedDict):
    col: int
    row: int
    status: str
    exact_matches: list[TileMatchMetadata]
    candidates: list[TileMatchCandidate]
    review: "ReferenceCellReview"


class ReferenceCellSelection(TypedDict, total=False):
    kind: str
    tile_id: str


class ReferenceCellReview(TypedDict, total=False):
    status: str
    selection: ReferenceCellSelection
    note: str
    selected_candidate_rank: int


class MatchSummary(TypedDict):
    columns: int
    rows: int
    blank_cells: int
    exact_match_cells: int
    high_confidence_cells: int
    best_guess_cells: int
    unresolved_cells: int


class MatchReport(TypedDict):
    reference_image: str
    family_path: str
    variant_id: str
    grid: dict[str, object]
    summary: MatchSummary
    cells: list[ReferenceCellMatch]


@dataclass(frozen=True)
class SourceTile:
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: tuple[str, ...]
    image: Image.Image


@dataclass(frozen=True)
class SimilarityScore:
    score: float
    pixel_match_ratio: float
    mask_match_ratio: float
    mask_iou: float
    effective_mask_iou: float
    trimmed_logical_iou: float
    mask_iou_rescue_applied: bool
    fill_similarity: float
    edge_match_ratio: float
    chamfer_similarity: float
    projection_similarity: float


@dataclass(frozen=True)
class CheapSimilarityScore:
    score: float
    fill_similarity: float
    edge_match_ratio: float
    projection_similarity: float


@dataclass(frozen=True)
class TileFeatures:
    width: int
    height: int
    pixels: tuple[RGBA, ...]
    foreground_mask: tuple[bool, ...]
    fill_count: int
    edge_signature: tuple[bool, bool, bool, bool]
    edge_points: tuple[tuple[int, int], ...]
    edge_distance_map: tuple[float, ...]
    row_projection: tuple[int, ...]
    col_projection: tuple[int, ...]


@dataclass(frozen=True)
class MatchRunSettings:
    image_path: Path
    family_path: Path
    variant_id: str | None
    output_path: Path | None
    transform: GridTransform
    span_box: Rect | None
    normalize_cell_size: int | Literal["auto"] | None
    review_overrides: dict[GuideRef, ReferenceCellReview]
    columns: int | None
    rows: int | None
    relevant_boxes: tuple[Rect, ...]
    excluded_boxes: tuple[Rect, ...]
    exclude_partial_edge_cells: bool
    max_candidates: int
    candidate_threshold: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Match reference-sheet cells against a family variant source sheet once the "
            "render-grid transform is known."
        )
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional JSON config file describing a canonical reference solve.")
    parser.add_argument("--image", type=Path, default=None, help="Reference image to analyse.")
    parser.add_argument("--family-path", type=Path, default=None, help="Tile family package directory.")
    parser.add_argument("--variant-id", default=None, help="Family variant to match against.")
    parser.add_argument("--origin-x", type=float, default=None, help="Render-space x origin of the tile grid.")
    parser.add_argument("--origin-y", type=float, default=None, help="Render-space y origin of the tile grid.")
    parser.add_argument("--cell-size", type=float, default=None, help="Render-space tile size in pixels.")
    parser.add_argument(
        "--span-box",
        default=None,
        help=(
            "Optional exact tiled-body box as left,top,right,bottom. When set, the "
            "grid partitions this full span directly instead of solving edges from "
            "origin + cell_size rounding."
        ),
    )
    parser.add_argument("--tile-size", type=int, default=8, help="Base tile size to recover. Defaults to 8.")
    parser.add_argument("--cols", type=int, help="Optional column count override.")
    parser.add_argument("--rows", type=int, help="Optional row count override.")
    parser.add_argument(
        "--normalize-cell-size",
        default=None,
        help=(
            "Optional normalized per-cell size for the ingest surface. Use an "
            "integer multiple of tile_size, or 'auto' to choose the nearest valid "
            "multiple to the native average cell size."
        ),
    )
    parser.add_argument(
        "--relevant-box",
        action="append",
        default=None,
        help=(
            "Optional absolute image-space box as left,top,right,bottom describing "
            "reference regions that contain real tiled content. Repeat to keep "
            "multiple sections; cells outside those sections are ignored."
        ),
    )
    parser.add_argument(
        "--content-box",
        default=None,
        help=(
            "Optional logical content box as left,top,right,bottom in base-tile "
            "coordinates. Use this when the reference obeys a stable art convention "
            "such as Minimal 8's 7x7 content inside an 8x8 cell."
        ),
    )
    parser.add_argument(
        "--exclude-box",
        action="append",
        default=None,
        help=(
            "Optional absolute image-space exclusion box as left,top,right,bottom. "
            "Excluded cells are reported and ignored during matching."
        ),
    )
    parser.add_argument(
        "--exclude-partial-edge-cells",
        action="store_true",
        help=(
            "Drop any partially visible edge cells from the extracted grid instead "
            "of matching against a padded full-cell crop."
        ),
    )
    parser.add_argument("--max-candidates", type=int, default=5, help="How many fallback candidates to keep.")
    parser.add_argument(
        "--candidate-threshold",
        type=float,
        default=0.75,
        help="Minimum similarity score to treat a non-exact cell as a candidate match.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Defaults to stdout only.")
    return parser.parse_args()


def _parse_review_selection(raw: object, field_name: str) -> ReferenceCellSelection:
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} must be an object")
    selection = cast(dict[str, object], raw)
    kind = selection.get("kind")
    if kind not in {"tile", "blank"}:
        raise ValueError(f"{field_name}.kind must be 'tile' or 'blank'")
    parsed: ReferenceCellSelection = {"kind": cast(str, kind)}
    tile_id = selection.get("tile_id")
    if kind == "tile":
        if not isinstance(tile_id, str):
            raise ValueError(f"{field_name}.tile_id must be a string when kind='tile'")
        parsed["tile_id"] = tile_id
    return parsed


def review_overrides_setting(config: Mapping[str, object], key: str) -> dict[GuideRef, ReferenceCellReview]:
    raw = config.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{key} must be an object")
    overrides: dict[GuideRef, ReferenceCellReview] = {}
    for guide_ref, review_raw in cast(dict[str, object], raw).items():
        if not isinstance(review_raw, dict):
            raise ValueError(f"{key}.{guide_ref} must be an object")
        review_map = cast(dict[str, object], review_raw)
        status = review_map.get("status")
        if status not in {"unreviewed", "confirmed", "corrected", "rejected"}:
            raise ValueError(f"{key}.{guide_ref}.status must be one of unreviewed|confirmed|corrected|rejected")
        parsed: ReferenceCellReview = {"status": cast(str, status)}
        selection = review_map.get("selection")
        if selection is not None:
            parsed["selection"] = _parse_review_selection(selection, f"{key}.{guide_ref}.selection")
        note = review_map.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise ValueError(f"{key}.{guide_ref}.note must be a string")
            parsed["note"] = note
        overrides[guide_ref] = parsed
    return overrides


def resolve_match_run_settings(args: argparse.Namespace) -> MatchRunSettings:
    config, config_dir = load_reference_config(args.config)
    grid_config = require_mapping(config.get("grid", {}), "grid")

    tile_size = int_setting(args.tile_size, grid_config, "tile_size")
    if tile_size is None:
        tile_size = 8
    image_path = path_setting(args.image, config, "image", config_dir=config_dir)
    family_path = path_setting(args.family_path, config, "family_path", config_dir=config_dir)
    output_path = path_setting(args.output, config, "output", config_dir=config_dir)
    variant_id = string_setting(args.variant_id, config, "variant_id")
    origin_x = float_setting(args.origin_x, grid_config, "origin_x")
    origin_y = float_setting(args.origin_y, grid_config, "origin_y")
    cell_size = float_setting(args.cell_size, grid_config, "cell_size")
    span_box = rectangle_setting(args.span_box, grid_config, "span_box")
    normalize_cell_size = normalize_cell_size_setting(args.normalize_cell_size, config, "normalize_cell_size")
    review_overrides = review_overrides_setting(config, "reviews")
    cols = int_setting(args.cols, grid_config, "cols")
    rows = int_setting(args.rows, grid_config, "rows")
    content_box = content_box_setting(args.content_box, grid_config, "content_box", tile_size=tile_size)
    relevant_boxes = rectangles_setting(args.relevant_box, config, "relevant_boxes")
    excluded_boxes = rectangles_setting(args.exclude_box, config, "excluded_boxes")
    raw_exclude_partial_edge_cells = config.get("exclude_partial_edge_cells", False)
    if not isinstance(raw_exclude_partial_edge_cells, bool):
        raise ValueError("exclude_partial_edge_cells must be a boolean")
    exclude_partial_edge_cells = raw_exclude_partial_edge_cells
    if args.exclude_partial_edge_cells:
        exclude_partial_edge_cells = True
    max_candidates = int_setting(args.max_candidates, config, "max_candidates")
    if max_candidates is None:
        max_candidates = 5
    candidate_threshold = float_setting(args.candidate_threshold, config, "candidate_threshold")
    if candidate_threshold is None:
        candidate_threshold = 0.75

    if image_path is None:
        raise ValueError("image is required")
    if family_path is None:
        raise ValueError("family_path is required")
    if span_box is not None:
        if cols is None or rows is None:
            raise ValueError("grid.span_box requires grid.cols and grid.rows")
        span_width = span_box[2] - span_box[0]
        span_height = span_box[3] - span_box[1]
        origin_x = float(span_box[0])
        origin_y = float(span_box[1])
        cell_size = ((span_width / cols) + (span_height / rows)) / 2
    else:
        if origin_x is None:
            raise ValueError("grid.origin_x is required")
        if origin_y is None:
            raise ValueError("grid.origin_y is required")
        if cell_size is None:
            raise ValueError("grid.cell_size is required")

    return MatchRunSettings(
        image_path=image_path,
        family_path=family_path,
        variant_id=variant_id,
        output_path=output_path,
        transform=GridTransform(
            origin_x=origin_x,
            origin_y=origin_y,
            cell_size=cell_size,
            tile_size=tile_size,
            content_box=content_box,
        ),
        span_box=span_box,
        normalize_cell_size=normalize_cell_size,
        review_overrides=review_overrides,
        columns=cols,
        rows=rows,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        exclude_partial_edge_cells=exclude_partial_edge_cells,
        max_candidates=max_candidates,
        candidate_threshold=candidate_threshold,
    )


def load_source_tiles(family_path: Path, variant_id: str | None) -> tuple[TileFamily, str, list[SourceTile]]:
    family = TileFamily.load(family_path)
    resolved_variant_id = variant_id or family.default_variant_id
    variant = family.variant(resolved_variant_id)
    sheet = Image.open(variant.sheet_path).convert("RGBA")
    tiles: list[SourceTile] = []
    for sheet_row in range(sheet.height // family.tile_height):
        for sheet_col in range(sheet.width // family.tile_width):
            left = sheet_col * family.tile_width
            top = sheet_row * family.tile_height
            tile_image = sheet.crop((left, top, left + family.tile_width, top + family.tile_height))
            tile_record = family.tile_at_sheet_cell(sheet_col=sheet_col, sheet_row=sheet_row)
            tile_id = tile_record.id if tile_record is not None else None
            aliases = tuple(sorted(family.aliases_by_tile.get(tile_id, ()))) if tile_id is not None else ()
            tiles.append(
                SourceTile(
                    sheet_col=sheet_col,
                    sheet_row=sheet_row,
                    tile_id=tile_id,
                    aliases=aliases,
                    image=tile_image,
                )
            )
    return family, resolved_variant_id, tiles


def render_source_tiles(source_tiles: list[SourceTile], *, cell_size: int) -> list[SourceTile]:
    return [
        SourceTile(
            sheet_col=tile.sheet_col,
            sheet_row=tile.sheet_row,
            tile_id=tile.tile_id,
            aliases=tile.aliases,
            image=resize_nearest(tile.image, (cell_size, cell_size)),
        )
        for tile in source_tiles
    ]


def _pixel_distance(left: RGBA, right: RGBA) -> int:
    return sum(abs(left[index] - right[index]) for index in range(4))


def _otsu_threshold(values: list[int]) -> int:
    if not values:
        return 0
    max_value = max(values)
    if max_value <= 0:
        return 0

    histogram = [0] * (max_value + 1)
    for value in values:
        histogram[value] += 1

    total = len(values)
    weighted_total = sum(index * count for index, count in enumerate(histogram))
    sum_background = 0.0
    weight_background = 0
    best_threshold = 0
    best_variance = -1.0

    for threshold, count in enumerate(histogram):
        weight_background += count
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += threshold * count
        mean_background = sum_background / weight_background
        mean_foreground = (weighted_total - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * ((mean_background - mean_foreground) ** 2)
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def _foreground_mask(
    image: Image.Image,
    background: RGBA,
    *,
    adaptive: bool,
) -> list[bool]:
    rgba = image.convert("RGBA")
    pixels = [
        cast(RGBA, rgba.getpixel((x, y)))
        for y in range(rgba.height)
        for x in range(rgba.width)
    ]
    if not adaptive:
        return [pixel != background for pixel in pixels]

    distances = [_pixel_distance(pixel, background) for pixel in pixels]
    if not any(distance > 0 for distance in distances):
        return [False] * len(distances)
    threshold = _otsu_threshold(distances)
    return [distance > threshold for distance in distances]


def _tile_features(image: Image.Image, background: RGBA, *, adaptive: bool) -> TileFeatures:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = tuple(
        cast(RGBA, rgba.getpixel((x, y)))
        for y in range(height)
        for x in range(width)
    )
    foreground_mask = tuple(_foreground_mask(rgba, background, adaptive=adaptive))
    edge_signature = _edge_signature_from_mask(list(foreground_mask), width, height)
    edge_points = tuple(_edge_points(list(foreground_mask), width=width, height=height))
    edge_distance_map = _edge_distance_map(edge_points, width=width, height=height)
    row_projection = tuple(
        sum(1 for x in range(width) if foreground_mask[(y * width) + x])
        for y in range(height)
    )
    col_projection = tuple(
        sum(1 for y in range(height) if foreground_mask[(y * width) + x])
        for x in range(width)
    )
    return TileFeatures(
        width=width,
        height=height,
        pixels=pixels,
        foreground_mask=foreground_mask,
        fill_count=sum(1 for value in foreground_mask if value),
        edge_signature=edge_signature,
        edge_points=edge_points,
        edge_distance_map=edge_distance_map,
        row_projection=row_projection,
        col_projection=col_projection,
    )


def is_background_tile(image: Image.Image, background: RGBA, *, adaptive: bool = False) -> bool:
    return not any(_foreground_mask(image, background, adaptive=adaptive))


def _edge_signature_from_mask(mask: list[bool], width: int, height: int) -> tuple[bool, bool, bool, bool]:
    left = any(mask[(y * width)] for y in range(height))
    right = any(mask[(y * width) + (width - 1)] for y in range(height))
    top = any(mask[x] for x in range(width))
    bottom = any(mask[((height - 1) * width) + x] for x in range(width))
    return (left, top, right, bottom)


def _mask_iou(left: list[bool], right: list[bool]) -> float:
    union = sum(1 for left_value, right_value in zip(left, right) if left_value or right_value)
    if union == 0:
        return 1.0
    intersection = sum(1 for left_value, right_value in zip(left, right) if left_value and right_value)
    return intersection / union


def _logical_axis_bounds(size: int, logical_tile_size: int) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    previous = 0
    for index in range(logical_tile_size):
        start = previous
        end = round(((index + 1) * size) / logical_tile_size)
        if end <= start:
            end = start + 1
        bounds.append((start, min(size, end)))
        previous = end
    if bounds:
        start, _end = bounds[-1]
        bounds[-1] = (start, size)
    return bounds


def _collapse_mask_to_logical_grid(mask: tuple[bool, ...], *, width: int, height: int, logical_tile_size: int) -> tuple[bool, ...]:
    x_bounds = _logical_axis_bounds(width, logical_tile_size)
    y_bounds = _logical_axis_bounds(height, logical_tile_size)
    collapsed: list[bool] = []
    for top, bottom in y_bounds:
        for left, right in x_bounds:
            filled = 0
            total = 0
            for y in range(top, bottom):
                for x in range(left, right):
                    total += 1
                    if mask[(y * width) + x]:
                        filled += 1
            threshold = max(1, (total + 1) // 2)
            collapsed.append(filled >= threshold)
    return tuple(collapsed)


def _trim_logical_mask(mask: tuple[bool, ...], logical_tile_size: int) -> tuple[tuple[bool, ...], int, int]:
    points = [
        (index % logical_tile_size, index // logical_tile_size)
        for index, filled in enumerate(mask)
        if filled
    ]
    if not points:
        return (), 0, 0

    min_x = min(x for x, _y in points)
    max_x = max(x for x, _y in points)
    min_y = min(y for _x, y in points)
    max_y = max(y for _x, y in points)
    width = (max_x - min_x) + 1
    height = (max_y - min_y) + 1
    trimmed = tuple(
        mask[((min_y + row) * logical_tile_size) + (min_x + col)]
        for row in range(height)
        for col in range(width)
    )
    return trimmed, width, height


def _trimmed_logical_iou(left: TileFeatures, right: TileFeatures, *, logical_tile_size: int) -> float:
    left_logical = _collapse_mask_to_logical_grid(
        left.foreground_mask,
        width=left.width,
        height=left.height,
        logical_tile_size=logical_tile_size,
    )
    right_logical = _collapse_mask_to_logical_grid(
        right.foreground_mask,
        width=right.width,
        height=right.height,
        logical_tile_size=logical_tile_size,
    )
    left_trimmed, left_width, left_height = _trim_logical_mask(left_logical, logical_tile_size)
    right_trimmed, right_width, right_height = _trim_logical_mask(right_logical, logical_tile_size)
    if not left_trimmed and not right_trimmed:
        return 1.0
    if not left_trimmed or not right_trimmed:
        return 0.0
    if left_width != right_width or left_height != right_height:
        return 0.0
    return _mask_iou(list(left_trimmed), list(right_trimmed))


def _projection_similarity(left: TileFeatures, right: TileFeatures) -> float:
    width = left.width
    height = left.height
    row_diff = 0
    col_diff = 0
    for y in range(height):
        left_row = left.row_projection[y]
        right_row = right.row_projection[y]
        row_diff += abs(left_row - right_row)
    for x in range(width):
        left_col = left.col_projection[x]
        right_col = right.col_projection[x]
        col_diff += abs(left_col - right_col)
    total = width * height
    return 1.0 - ((row_diff + col_diff) / (2 * total))


def _edge_points(mask: list[bool], *, width: int, height: int) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            index = (y * width) + x
            if not mask[index]:
                continue
            neighbours = (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            )
            if any(
                neighbour_x < 0
                or neighbour_y < 0
                or neighbour_x >= width
                or neighbour_y >= height
                or not mask[(neighbour_y * width) + neighbour_x]
                for neighbour_x, neighbour_y in neighbours
            ):
                points.append((x, y))
    return points


def _edge_distance_map(
    edge_points: tuple[tuple[int, int], ...],
    *,
    width: int,
    height: int,
) -> tuple[float, ...]:
    if not edge_points:
        return tuple(math.inf for _ in range(width * height))
    distances: list[float] = []
    for y in range(height):
        for x in range(width):
            distances.append(
                min(math.hypot(x - edge_x, y - edge_y) for edge_x, edge_y in edge_points)
            )
    return tuple(distances)


def _average_distance_from_map(
    points: tuple[tuple[int, int], ...],
    distance_map: tuple[float, ...],
    *,
    width: int,
) -> float:
    if not points:
        return math.inf
    total = sum(distance_map[(point_y * width) + point_x] for point_x, point_y in points)
    return total / len(points)


def _chamfer_similarity(left: TileFeatures, right: TileFeatures) -> float:
    left_points = left.edge_points
    right_points = right.edge_points
    if not left_points and not right_points:
        return 1.0
    if not left_points or not right_points:
        return 0.0
    forward = _average_distance_from_map(
        left_points,
        right.edge_distance_map,
        width=right.width,
    )
    backward = _average_distance_from_map(
        right_points,
        left.edge_distance_map,
        width=left.width,
    )
    average_distance = (forward + backward) / 2
    max_distance = math.hypot(left.width - 1, left.height - 1)
    if max_distance <= 0:
        return 1.0
    return max(0.0, 1.0 - min(1.0, average_distance / max_distance))


def score_tile_similarity(
    reference_tile: Image.Image,
    source_tile: Image.Image,
    background: RGBA,
    *,
    logical_tile_size: int | None = None,
) -> SimilarityScore:
    reference_features = _tile_features(reference_tile, background, adaptive=True)
    source_features = _tile_features(source_tile, background, adaptive=False)
    return _score_tile_similarity(reference_features, source_features, logical_tile_size=logical_tile_size)


def _score_tile_similarity(
    reference: TileFeatures,
    source: TileFeatures,
    *,
    logical_tile_size: int | None = None,
) -> SimilarityScore:
    if (reference.width, reference.height) != (source.width, source.height):
        raise ValueError("reference and source tiles must share a size")

    total = reference.width * reference.height
    pixel_matches = sum(1 for left, right in zip(reference.pixels, source.pixels) if left == right)
    mask_matches = sum(
        1
        for left, right in zip(reference.foreground_mask, source.foreground_mask)
        if left == right
    )
    fill_similarity = 1.0 - (abs(reference.fill_count - source.fill_count) / total)
    mask_iou = _mask_iou(list(reference.foreground_mask), list(source.foreground_mask))
    projection_similarity = _projection_similarity(reference, source)
    chamfer_similarity = _chamfer_similarity(reference, source)
    edge_matches = sum(
        1
        for left, right in zip(reference.edge_signature, source.edge_signature)
        if left == right
    )

    pixel_ratio = pixel_matches / total
    mask_ratio = mask_matches / total
    edge_ratio = edge_matches / 4
    trimmed_logical_iou = (
        _trimmed_logical_iou(reference, source, logical_tile_size=logical_tile_size)
        if logical_tile_size is not None
        else mask_iou
    )
    mask_iou_rescue_applied = mask_iou < 0.1 and projection_similarity >= 0.9 and chamfer_similarity >= 0.94
    effective_mask_iou = max(mask_iou, trimmed_logical_iou * 0.75) if mask_iou_rescue_applied else mask_iou
    score = (
        (0.32 * effective_mask_iou)
        + (0.26 * chamfer_similarity)
        + (0.16 * projection_similarity)
        + (0.11 * edge_ratio)
        + (0.10 * fill_similarity)
        + (0.05 * pixel_ratio)
    )
    return SimilarityScore(
        score=score,
        pixel_match_ratio=pixel_ratio,
        mask_match_ratio=mask_ratio,
        mask_iou=mask_iou,
        effective_mask_iou=effective_mask_iou,
        trimmed_logical_iou=trimmed_logical_iou,
        mask_iou_rescue_applied=mask_iou_rescue_applied,
        fill_similarity=fill_similarity,
        edge_match_ratio=edge_ratio,
        chamfer_similarity=chamfer_similarity,
        projection_similarity=projection_similarity,
    )


def _cheap_similarity(reference: TileFeatures, source: TileFeatures) -> CheapSimilarityScore:
    total = reference.width * reference.height
    fill_similarity = 1.0 - (abs(reference.fill_count - source.fill_count) / total)
    projection_similarity = _projection_similarity(reference, source)
    edge_matches = sum(
        1
        for left, right in zip(reference.edge_signature, source.edge_signature)
        if left == right
    )
    edge_ratio = edge_matches / 4
    score = (0.5 * projection_similarity) + (0.3 * fill_similarity) + (0.2 * edge_ratio)
    return CheapSimilarityScore(
        score=score,
        fill_similarity=fill_similarity,
        edge_match_ratio=edge_ratio,
        projection_similarity=projection_similarity,
    )


def exact_matches_for_tile(reference_tile: Image.Image, source_tiles: list[SourceTile]) -> list[SourceTile]:
    reference_bytes = reference_tile.convert("RGBA").tobytes()
    return [tile for tile in source_tiles if tile.image.convert("RGBA").tobytes() == reference_bytes]


def candidate_matches_for_tile(
    reference_tile: Image.Image,
    source_tiles: list[SourceTile],
    background: RGBA,
    *,
    max_candidates: int,
    logical_tile_size: int,
    source_features: dict[int, TileFeatures] | None = None,
) -> list[tuple[SourceTile, SimilarityScore]]:
    reference_features = _tile_features(reference_tile, background, adaptive=True)
    resolved_source_features = source_features or {
        id(tile): _tile_features(tile.image, background, adaptive=False) for tile in source_tiles
    }
    non_background_tiles = [
        tile
        for tile in source_tiles
        if id(tile) in resolved_source_features
    ]
    shortlist = non_background_tiles
    shortlist_size = max(max_candidates * 16, 64)
    if len(non_background_tiles) > shortlist_size:
        cheap_ranked = [
            (tile, _cheap_similarity(reference_features, resolved_source_features[id(tile)]))
            for tile in non_background_tiles
        ]
        cheap_ranked.sort(
            key=lambda item: (
                item[1].score,
                item[1].projection_similarity,
                item[1].fill_similarity,
                item[1].edge_match_ratio,
            ),
            reverse=True,
        )
        shortlist = [tile for tile, _score in cheap_ranked[:shortlist_size]]
    ranked = [
        (
            tile,
            _score_tile_similarity(
                reference_features,
                resolved_source_features[id(tile)],
                logical_tile_size=logical_tile_size,
            ),
        )
        for tile in shortlist
    ]
    ranked.sort(
        key=lambda item: (
            item[1].score,
            item[1].mask_iou,
            item[1].chamfer_similarity,
            item[1].projection_similarity,
            item[1].pixel_match_ratio,
            item[1].mask_match_ratio,
            item[1].edge_match_ratio,
        ),
        reverse=True,
    )
    return ranked[:max_candidates]


def _match_metadata(tile: SourceTile) -> TileMatchMetadata:
    return {
        "sheet_col": tile.sheet_col,
        "sheet_row": tile.sheet_row,
        "tile_id": tile.tile_id,
        "aliases": list(tile.aliases),
    }


def _candidate_payload(tile: SourceTile, score: SimilarityScore) -> TileMatchCandidate:
    return {
        "sheet_col": tile.sheet_col,
        "sheet_row": tile.sheet_row,
        "tile_id": tile.tile_id,
        "aliases": list(tile.aliases),
        "score": round(score.score, 4),
        "pixel_match_ratio": round(score.pixel_match_ratio, 4),
        "mask_match_ratio": round(score.mask_match_ratio, 4),
        "mask_iou": round(score.mask_iou, 4),
        "effective_mask_iou": round(score.effective_mask_iou, 4),
        "trimmed_logical_iou": round(score.trimmed_logical_iou, 4),
        "mask_iou_rescue_applied": score.mask_iou_rescue_applied,
        "fill_similarity": round(score.fill_similarity, 4),
        "edge_match_ratio": round(score.edge_match_ratio, 4),
        "chamfer_similarity": round(score.chamfer_similarity, 4),
        "projection_similarity": round(score.projection_similarity, 4),
    }


def _cell_intersects_region(
    col_index: int,
    row_index: int,
    extraction: GridExtraction,
    rectangles: tuple[Rect, ...],
) -> bool:
    return cell_intersects_rectangles(col_index, row_index, extraction, rectangles)


def guide_ref(col_index: int, row_index: int) -> GuideRef:
    return f"C{col_index + 1}R{row_index + 1}"


def _selected_candidate_rank(
    review: ReferenceCellReview,
    cell: ReferenceCellMatch,
) -> int | None:
    selection = review.get("selection")
    if selection is None:
        return None
    if selection.get("kind") == "blank":
        return None
    selected_tile_id = selection.get("tile_id")
    if selected_tile_id is None:
        return None
    for index, exact in enumerate(cell["exact_matches"], start=1):
        if exact["tile_id"] == selected_tile_id:
            return index
    for index, candidate in enumerate(cell["candidates"], start=1):
        if candidate["tile_id"] == selected_tile_id:
            return index
    return None


def apply_review_overrides(
    cells: list[ReferenceCellMatch],
    overrides: dict[GuideRef, ReferenceCellReview],
) -> list[ReferenceCellMatch]:
    applied: list[ReferenceCellMatch] = []
    for cell in cells:
        review: ReferenceCellReview = {"status": "unreviewed"}
        override = overrides.get(guide_ref(cell["col"], cell["row"]))
        if override is not None:
            review.update(override)
            selected_rank = _selected_candidate_rank(review, cell)
            if selected_rank is not None:
                review["selected_candidate_rank"] = selected_rank
        applied.append(
            {
                "col": cell["col"],
                "row": cell["row"],
                "status": cell["status"],
                "exact_matches": cell["exact_matches"],
                "candidates": cell["candidates"],
                "review": review,
            }
        )
    return applied


def match_reference_tiles(
    *,
    reference_image: Image.Image,
    source_tiles: list[SourceTile],
    background: RGBA,
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    max_candidates: int = 5,
    candidate_threshold: float = 0.75,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    exclude_partial_edge_cells: bool = False,
    span_box: Rect | None = None,
    normalize_cell_size: int | Literal["auto"] | None = None,
) -> tuple[list[ReferenceCellMatch], MatchSummary]:
    prepared = prepare_reference_grid(
        reference_image,
        transform=transform,
        cols=cols,
        rows=rows,
        span_box=span_box,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        exclude_partial_edge_cells=exclude_partial_edge_cells,
        background=background,
    )
    resolved_normalized_cell_size = resolve_normalized_cell_size(normalize_cell_size, prepared.extraction)
    active_source_tiles = source_tiles
    if resolved_normalized_cell_size is not None:
        prepared = normalize_prepared_reference_grid(
            prepared,
            target_cell_size=resolved_normalized_cell_size,
        )
        tile_grid = build_cell_crops(prepared.crop, prepared.extraction)
        active_source_tiles = render_source_tiles(source_tiles, cell_size=resolved_normalized_cell_size)
    else:
        tile_grid = build_tile_grid(prepared.crop, prepared.extraction, background=background)
    source_features = {
        id(tile): _tile_features(tile.image, background, adaptive=False)
        for tile in active_source_tiles
        if not is_background_tile(tile.image, background)
    }

    cells: list[ReferenceCellMatch] = []
    blank_cells = 0
    exact_cells = 0
    high_confidence_cells = 0
    best_guess_cells = 0
    unresolved_cells = 0

    for row_index, row_tiles in enumerate(tile_grid):
        for col_index, reference_tile in enumerate(row_tiles):
            if prepared.relevant_boxes and not _cell_intersects_region(
                col_index,
                row_index,
                prepared.extraction,
                prepared.relevant_boxes,
            ):
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "excluded",
                        "exact_matches": [],
                        "candidates": [],
                        "review": {"status": "unreviewed"},
                    }
                )
                continue
            if _cell_intersects_region(
                col_index,
                row_index,
                prepared.extraction,
                prepared.excluded_boxes,
            ):
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "excluded",
                        "exact_matches": [],
                        "candidates": [],
                        "review": {"status": "unreviewed"},
                    }
                )
                continue
            if is_background_tile(reference_tile, background, adaptive=True):
                blank_cells += 1
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "blank",
                        "exact_matches": [],
                        "candidates": [],
                        "review": {"status": "unreviewed"},
                    }
                )
                continue

            exact = exact_matches_for_tile(reference_tile, active_source_tiles)
            if exact:
                exact_cells += 1
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "exact",
                        "exact_matches": [_match_metadata(tile) for tile in exact],
                        "candidates": [],
                        "review": {"status": "unreviewed"},
                    }
                )
                continue

            candidates = candidate_matches_for_tile(
                reference_tile,
                active_source_tiles,
                background,
                max_candidates=max_candidates,
                logical_tile_size=transform.tile_size,
                source_features=source_features,
            )
            if candidates:
                if candidates[0][1].score >= candidate_threshold:
                    high_confidence_cells += 1
                    status = "high_confidence"
                else:
                    best_guess_cells += 1
                    status = "best_guess"
            else:
                unresolved_cells += 1
                status = "unresolved"

            cells.append(
                {
                    "col": col_index,
                    "row": row_index,
                    "status": status,
                    "exact_matches": [],
                    "candidates": [_candidate_payload(tile, score) for tile, score in candidates],
                    "review": {"status": "unreviewed"},
                }
            )

    summary: MatchSummary = {
        "columns": prepared.extraction.columns,
        "rows": prepared.extraction.rows,
        "blank_cells": blank_cells,
        "exact_match_cells": exact_cells,
        "high_confidence_cells": high_confidence_cells,
        "best_guess_cells": best_guess_cells,
        "unresolved_cells": unresolved_cells,
    }
    return cells, summary


def build_match_report(
    *,
    image_path: Path,
    family_path: Path,
    variant_id: str | None,
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    max_candidates: int = 5,
    candidate_threshold: float = 0.75,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    exclude_partial_edge_cells: bool = False,
    span_box: Rect | None = None,
    normalize_cell_size: int | Literal["auto"] | None = None,
    review_overrides: dict[GuideRef, ReferenceCellReview] | None = None,
) -> MatchReport:
    reference_image = Image.open(image_path).convert("RGBA")
    background = cast(RGBA, reference_image.getpixel((0, 0)))
    prepared = prepare_reference_grid(
        reference_image,
        transform=transform,
        cols=cols,
        rows=rows,
        span_box=span_box,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        exclude_partial_edge_cells=exclude_partial_edge_cells,
        background=background,
    )
    resolved_normalized_cell_size = resolve_normalized_cell_size(normalize_cell_size, prepared.extraction)
    _, resolved_variant_id, source_tiles = load_source_tiles(family_path, variant_id)
    cells, summary = match_reference_tiles(
        reference_image=reference_image,
        source_tiles=source_tiles,
        background=background,
        transform=transform,
        cols=cols,
        rows=rows,
        max_candidates=max_candidates,
        candidate_threshold=candidate_threshold,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        exclude_partial_edge_cells=exclude_partial_edge_cells,
        span_box=span_box,
        normalize_cell_size=normalize_cell_size,
    )
    reviewed_cells = apply_review_overrides(cells, review_overrides or {})
    return {
        "reference_image": str(image_path),
        "family_path": str(family_path),
        "variant_id": resolved_variant_id,
        "grid": {
            "origin_x": transform.origin_x,
            "origin_y": transform.origin_y,
            "cell_size": transform.cell_size,
            "tile_size": transform.tile_size,
            "span_box": list(span_box) if span_box is not None else None,
            "normalize_cell_size": resolved_normalized_cell_size,
            "content_box": list(transform.content_box) if transform.content_box is not None else None,
            "relevant_boxes": [list(box) for box in relevant_boxes],
            "excluded_boxes": [list(box) for box in excluded_boxes],
            "exclude_partial_edge_cells": exclude_partial_edge_cells,
        },
        "summary": summary,
        "cells": reviewed_cells,
    }


def main() -> int:
    args = parse_args()
    settings = resolve_match_run_settings(args)
    report = build_match_report(
        image_path=settings.image_path,
        family_path=settings.family_path,
        variant_id=settings.variant_id,
        transform=settings.transform,
        cols=settings.columns,
        rows=settings.rows,
        max_candidates=settings.max_candidates,
        candidate_threshold=settings.candidate_threshold,
        relevant_boxes=settings.relevant_boxes,
        excluded_boxes=settings.excluded_boxes,
        exclude_partial_edge_cells=settings.exclude_partial_edge_cells,
        span_box=settings.span_box,
        normalize_cell_size=settings.normalize_cell_size,
        review_overrides=settings.review_overrides,
    )
    payload = json.dumps(report, indent=2)
    if settings.output_path is not None:
        settings.output_path.parent.mkdir(parents=True, exist_ok=True)
        settings.output_path.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
