from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, Mapping, TypeAlias, cast

from PIL import Image, ImageColor, ImageDraw, ImageFont


RGBA = tuple[int, int, int, int]
ContentBox: TypeAlias = tuple[int, int, int, int]
Rect: TypeAlias = tuple[int, int, int, int]
GuideLineMode: TypeAlias = Literal["separated", "overlay"]
NormalizeCellSizeSetting: TypeAlias = int | Literal["auto"] | None


@dataclass(frozen=True)
class GridTransform:
    origin_x: float
    origin_y: float
    cell_size: float
    tile_size: int = 8
    content_box: ContentBox | None = None

    @property
    def gutter_size(self) -> int:
        return max(1, round(self.cell_size / self.tile_size))


@dataclass(frozen=True)
class GridExtraction:
    transform: GridTransform
    columns: int
    rows: int
    crop_box: tuple[int, int, int, int]
    x_edges: tuple[int, ...]
    y_edges: tuple[int, ...]


@dataclass(frozen=True)
class GridRunSettings:
    image_path: Path
    output_dir: Path
    prefix: str
    transform: GridTransform
    span_box: Rect | None
    normalize_cell_size: NormalizeCellSizeSetting
    columns: int | None
    rows: int | None
    relevant_boxes: tuple[Rect, ...]
    excluded_boxes: tuple[Rect, ...]
    exclude_partial_edge_cells: bool
    guide_line_mode: GuideLineMode
    background: str | None
    zoom_cell: tuple[int, int] | None
    scale: int


@dataclass
class PreparedReferenceGrid:
    crop: Image.Image
    extraction: GridExtraction
    relevant_boxes: tuple[Rect, ...]
    excluded_boxes: tuple[Rect, ...]
    normalized_cell_size: int | None


GUIDE_OUTER_PAD = 8
GUIDE_LABEL_BAND = 20
GUIDE_MARGIN = GUIDE_OUTER_PAD + GUIDE_LABEL_BAND


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a rendered reference image onto a stable tile grid, then emit "
            "cropped, contact-sheet, and guide-overlay views."
        )
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional JSON config file describing a canonical reference solve.")
    parser.add_argument("--image", type=Path, default=None, help="Reference image to slice.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated outputs.")
    parser.add_argument("--prefix", default=None, help="Filename prefix for generated outputs.")
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
            "a tiled region that should count as real reference content. Repeat "
            "to keep multiple sections. The extracted grid trims itself to the "
            "cells touched by these regions before exclusions are applied."
        ),
    )
    parser.add_argument(
        "--exclude-box",
        action="append",
        default=None,
        help=(
            "Optional absolute image-space exclusion box as left,top,right,bottom. "
            "Use this to ignore non-tiled regions such as a heading while solving "
            "or matching a real tiled body."
        ),
    )
    parser.add_argument(
        "--exclude-partial-edge-cells",
        action="store_true",
        help=(
            "Drop any partially visible edge cells from the extracted grid instead "
            "of padding them out to full-cell size."
        ),
    )
    parser.add_argument(
        "--guide-line-mode",
        choices=("separated", "overlay"),
        default=None,
        help=(
            "How the human-facing guide should draw tile separators. "
            "'separated' inserts thin grid lines between tiles without drawing "
            "over source pixels; 'overlay' keeps a compact guide and draws thin "
            "lines over the tile-edge guide gutters."
        ),
    )
    parser.add_argument(
        "--content-box",
        default=None,
        help=(
            "Optional logical content box as left,top,right,bottom in base-tile "
            "coordinates. Use this for sheets with a stable art convention, such "
            "as Minimal 8's 7x7 content inside an 8x8 cell."
        ),
    )
    parser.add_argument(
        "--background",
        default=None,
        help="Optional background colour as #RRGGBB or #RRGGBBAA. Defaults to the image's top-left pixel.",
    )
    parser.add_argument(
        "--zoom-cell",
        default=None,
        help="Optional zoom target as col,row for a 2-cell padded crop around one tile.",
    )
    parser.add_argument("--scale", type=int, default=4, help="Scale factor for the tile contact sheet.")
    return parser.parse_args()


def require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return cast(Mapping[str, object], value)


def load_reference_config(config_path: Path | None) -> tuple[Mapping[str, object], Path | None]:
    if config_path is None:
        return {}, None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return require_mapping(payload, "config"), config_path.parent


def _resolve_relative_path(raw: str, config_dir: Path | None) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute() or config_dir is None:
        return path
    return config_dir / path


def path_setting(
    cli_value: Path | None,
    config: Mapping[str, object],
    key: str,
    *,
    config_dir: Path | None,
) -> Path | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} must be a string path")
    return _resolve_relative_path(raw, config_dir)


def string_setting(cli_value: str | None, config: Mapping[str, object], key: str) -> str | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} must be a string")
    return raw


def guide_line_mode_setting(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
) -> GuideLineMode:
    raw = cli_value if cli_value is not None else config.get(key, "separated")
    if raw not in {"separated", "overlay"}:
        raise ValueError(f"{key} must be 'separated' or 'overlay'")
    return cast(GuideLineMode, raw)


def int_setting(cli_value: int | None, config: Mapping[str, object], key: str) -> int | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    return raw


def float_setting(cli_value: float | None, config: Mapping[str, object], key: str) -> float | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(raw)


def rectangle_setting(cli_value: str | None, config: Mapping[str, object], key: str) -> Rect | None:
    if cli_value is not None:
        return parse_rect(cli_value)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a rectangle list")
    parts = cast(list[object], raw)
    return parse_rect(",".join(str(part) for part in parts))


def normalize_cell_size_setting(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
) -> NormalizeCellSizeSetting:
    raw: object | None = cli_value if cli_value is not None else config.get(key)
    if raw is None:
        return None
    if raw == "auto":
        return "auto"
    if isinstance(raw, int):
        if raw <= 0:
            raise ValueError(f"{key} must be positive")
        return raw
    if isinstance(raw, str):
        value = int(raw)
        if value <= 0:
            raise ValueError(f"{key} must be positive")
        return value
    raise ValueError(f"{key} must be a positive integer or 'auto'")


def rectangles_setting(cli_value: list[str] | None, config: Mapping[str, object], key: str) -> tuple[Rect, ...]:
    if cli_value is not None:
        return tuple(parse_rect(raw) for raw in cli_value)
    raw = config.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list of rectangles")
    rectangles: list[Rect] = []
    items = cast(list[object], raw)
    for index, item in enumerate(items):
        if not isinstance(item, list):
            raise ValueError(f"{key}[{index}] must be a list")
        parts = cast(list[object], item)
        rectangles.append(parse_rect(",".join(str(part) for part in parts)))
    return tuple(rectangles)


def content_box_setting(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
    *,
    tile_size: int,
) -> ContentBox | None:
    if cli_value is not None:
        return parse_content_box(cli_value, tile_size)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    parts = cast(list[object], raw)
    return parse_content_box(",".join(str(part) for part in parts), tile_size)


def zoom_cell_setting(cli_value: str | None, config: Mapping[str, object], key: str) -> tuple[int, int] | None:
    if cli_value is not None:
        return parse_zoom_cell(cli_value)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    parts = cast(list[object], raw)
    return parse_zoom_cell(",".join(str(part) for part in parts))


def resolve_grid_run_settings(args: argparse.Namespace) -> GridRunSettings:
    config, config_dir = load_reference_config(args.config)
    grid_config = require_mapping(config.get("grid", {}), "grid")

    tile_size = int_setting(args.tile_size, grid_config, "tile_size")
    if tile_size is None:
        tile_size = 8
    image_path = path_setting(args.image, config, "image", config_dir=config_dir)
    output_dir = path_setting(args.output_dir, config, "output_dir", config_dir=config_dir)
    prefix = string_setting(args.prefix, config, "prefix")
    origin_x = float_setting(args.origin_x, grid_config, "origin_x")
    origin_y = float_setting(args.origin_y, grid_config, "origin_y")
    cell_size = float_setting(args.cell_size, grid_config, "cell_size")
    span_box = rectangle_setting(args.span_box, grid_config, "span_box")
    normalize_cell_size = normalize_cell_size_setting(args.normalize_cell_size, config, "normalize_cell_size")
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
    guide_line_mode = guide_line_mode_setting(args.guide_line_mode, config, "guide_line_mode")
    background = string_setting(args.background, config, "background")
    zoom_cell = zoom_cell_setting(args.zoom_cell, config, "zoom_cell")
    scale = int_setting(args.scale, config, "scale")
    if scale is None:
        scale = 4

    if image_path is None:
        raise ValueError("image is required")
    if output_dir is None:
        raise ValueError("output_dir is required")
    if prefix is None:
        raise ValueError("prefix is required")
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

    return GridRunSettings(
        image_path=image_path,
        output_dir=output_dir,
        prefix=prefix,
        transform=GridTransform(
            origin_x=origin_x,
            origin_y=origin_y,
            cell_size=cell_size,
            tile_size=tile_size,
            content_box=content_box,
        ),
        span_box=span_box,
        normalize_cell_size=normalize_cell_size,
        columns=cols,
        rows=rows,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        exclude_partial_edge_cells=exclude_partial_edge_cells,
        guide_line_mode=guide_line_mode,
        background=background,
        zoom_cell=zoom_cell,
        scale=scale,
    )


def compute_extraction(
    image_size: tuple[int, int],
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    *,
    include_partial_edges: bool = True,
    span_box: Rect | None = None,
) -> GridExtraction:
    width, height = image_size
    if transform.cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if transform.tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if span_box is not None:
        if cols is None or rows is None:
            raise ValueError("span_box extraction requires explicit cols and rows")
        span_left, span_top, span_right, span_bottom = span_box
        if span_right <= span_left or span_bottom <= span_top:
            raise ValueError("span_box bounds must satisfy left < right and top < bottom")
        if span_right <= 0 or span_bottom <= 0 or span_left >= width or span_top >= height:
            raise ValueError("span_box must intersect the reference image")
        abs_x_edges = _quantized_span_edges(span_left, span_right, cols)
        abs_y_edges = _quantized_span_edges(span_top, span_bottom, rows)
        return GridExtraction(
            transform=transform,
            columns=cols,
            rows=rows,
            crop_box=(span_left, span_top, span_right, span_bottom),
            x_edges=tuple(edge - span_left for edge in abs_x_edges),
            y_edges=tuple(edge - span_top for edge in abs_y_edges),
        )
    if transform.origin_x < 0 or transform.origin_y < 0:
        raise ValueError("grid origin must be non-negative")
    if transform.origin_x >= width or transform.origin_y >= height:
        raise ValueError("grid origin lies outside the reference image")

    max_full_cols = _max_cells_within_limit(width, transform.origin_x, transform.cell_size)
    max_full_rows = _max_cells_within_limit(height, transform.origin_y, transform.cell_size)
    max_partial_cols = _max_intersecting_cells_within_limit(width, transform.origin_x, transform.cell_size)
    max_partial_rows = _max_intersecting_cells_within_limit(height, transform.origin_y, transform.cell_size)
    max_cols = max_partial_cols if include_partial_edges else max_full_cols
    max_rows = max_partial_rows if include_partial_edges else max_full_rows
    if max_cols <= 0 or max_rows <= 0:
        kind = "intersecting" if include_partial_edges else "full"
        raise ValueError(f"grid transform does not leave any {kind} cells inside the image")

    resolved_cols = max_cols if cols is None else cols
    resolved_rows = max_rows if rows is None else rows
    if resolved_cols <= 0 or resolved_rows <= 0:
        raise ValueError("resolved grid dimensions must be positive")
    if resolved_cols > max_cols or resolved_rows > max_rows:
        raise ValueError("requested grid dimensions exceed the available full-cell crop")

    abs_x_edges = _quantized_edges(transform.origin_x, transform.cell_size, resolved_cols)
    abs_y_edges = _quantized_edges(transform.origin_y, transform.cell_size, resolved_rows)
    x0 = abs_x_edges[0]
    y0 = abs_y_edges[0]
    x1 = abs_x_edges[-1]
    y1 = abs_y_edges[-1]
    return GridExtraction(
        transform=transform,
        columns=resolved_cols,
        rows=resolved_rows,
        crop_box=(x0, y0, x1, y1),
        x_edges=tuple(edge - x0 for edge in abs_x_edges),
        y_edges=tuple(edge - y0 for edge in abs_y_edges),
    )


def _quantized_edges(origin: float, cell_size: float, cells: int) -> list[int]:
    if cells <= 0:
        raise ValueError("cells must be positive")
    return [round(origin + (index * cell_size)) for index in range(cells + 1)]


def _quantized_span_edges(start: int, end: int, cells: int) -> list[int]:
    if cells <= 0:
        raise ValueError("cells must be positive")
    span = end - start
    return [start + round((index * span) / cells) for index in range(cells + 1)]


def _max_cells_within_limit(limit: int, origin: float, cell_size: float) -> int:
    cells = 0
    while round(origin + ((cells + 1) * cell_size)) <= limit:
        cells += 1
    return cells


def _max_intersecting_cells_within_limit(limit: int, origin: float, cell_size: float) -> int:
    cells = 0
    while round(origin + (cells * cell_size)) < limit:
        cells += 1
    return cells


def parse_content_box(raw: str | None, tile_size: int) -> ContentBox | None:
    if raw is None:
        return None
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("content_box must be left,top,right,bottom")
    left, top, right, bottom = parts
    if not (0 <= left < right <= tile_size):
        raise ValueError("content_box horizontal bounds must satisfy 0 <= left < right <= tile_size")
    if not (0 <= top < bottom <= tile_size):
        raise ValueError("content_box vertical bounds must satisfy 0 <= top < bottom <= tile_size")
    return (left, top, right, bottom)


def parse_rect(raw: str) -> Rect:
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("rectangle must be left,top,right,bottom")
    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        raise ValueError("rectangle bounds must satisfy left < right and top < bottom")
    return (left, top, right, bottom)


def _resolve_rectangles(raw_boxes: list[str] | None) -> tuple[Rect, ...]:
    if not raw_boxes:
        return ()
    return tuple(parse_rect(raw) for raw in raw_boxes)


def resolve_relevant_boxes(raw_boxes: list[str] | None) -> tuple[Rect, ...]:
    return _resolve_rectangles(raw_boxes)


def resolve_excluded_boxes(raw_boxes: list[str] | None) -> tuple[Rect, ...]:
    return _resolve_rectangles(raw_boxes)


def resolve_background(image: Image.Image, background: str | None) -> RGBA:
    if background is None:
        return cast(RGBA, image.convert("RGBA").getpixel((0, 0)))
    return cast(RGBA, ImageColor.getcolor(background, "RGBA"))


def extract_crop(
    image: Image.Image,
    extraction: GridExtraction,
    *,
    background: RGBA | None = None,
) -> Image.Image:
    crop_left, crop_top, crop_right, crop_bottom = extraction.crop_box
    image_left = max(0, crop_left)
    image_top = max(0, crop_top)
    image_right = min(image.width, crop_right)
    image_bottom = min(image.height, crop_bottom)
    if (
        crop_left >= 0
        and crop_top >= 0
        and crop_right <= image.width
        and crop_bottom <= image.height
    ):
        return image.crop(extraction.crop_box)
    if background is None:
        background = cast(RGBA, image.convert("RGBA").getpixel((0, 0)))
    crop = Image.new("RGBA", (crop_right - crop_left, crop_bottom - crop_top), background)
    if image_left < image_right and image_top < image_bottom:
        cropped = image.crop((image_left, image_top, image_right, image_bottom))
        crop.alpha_composite(cropped, (image_left - crop_left, image_top - crop_top))
    return crop


def crop_relative_rectangles(extraction: GridExtraction, rectangles: tuple[Rect, ...]) -> tuple[Rect, ...]:
    crop_left, crop_top, crop_right, crop_bottom = extraction.crop_box
    relative: list[Rect] = []
    for left, top, right, bottom in rectangles:
        clipped_left = max(left, crop_left)
        clipped_top = max(top, crop_top)
        clipped_right = min(right, crop_right)
        clipped_bottom = min(bottom, crop_bottom)
        if clipped_left >= clipped_right or clipped_top >= clipped_bottom:
            continue
        relative.append(
            (
                clipped_left - crop_left,
                clipped_top - crop_top,
                clipped_right - crop_left,
                clipped_bottom - crop_top,
            )
        )
    return tuple(relative)


def _rectangles_intersect(left: Rect, right: Rect) -> bool:
    left_x0, left_y0, left_x1, left_y1 = left
    right_x0, right_y0, right_x1, right_y1 = right
    return left_x0 < right_x1 and right_x0 < left_x1 and left_y0 < right_y1 and right_y0 < left_y1


def cell_bounds(extraction: GridExtraction, col_index: int, row_index: int, *, absolute: bool = False) -> Rect:
    x0 = extraction.x_edges[col_index]
    y0 = extraction.y_edges[row_index]
    x1 = extraction.x_edges[col_index + 1]
    y1 = extraction.y_edges[row_index + 1]
    if not absolute:
        return (x0, y0, x1, y1)
    crop_left, crop_top, _, _ = extraction.crop_box
    return (crop_left + x0, crop_top + y0, crop_left + x1, crop_top + y1)


def cell_intersects_rectangles(
    col_index: int,
    row_index: int,
    extraction: GridExtraction,
    rectangles: tuple[Rect, ...],
) -> bool:
    if not rectangles:
        return False
    cell = cell_bounds(extraction, col_index, row_index)
    return any(_rectangles_intersect(cell, rectangle) for rectangle in rectangles)


def partial_edge_cells(
    extraction: GridExtraction,
    image_size: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    image_width, image_height = image_size
    cells: list[tuple[int, int]] = []
    for row_index in range(extraction.rows):
        for col_index in range(extraction.columns):
            left, top, right, bottom = cell_bounds(extraction, col_index, row_index, absolute=True)
            if left < 0 or top < 0 or right > image_width or bottom > image_height:
                cells.append((col_index, row_index))
    return tuple(cells)


def trim_extraction_to_full_cells(
    extraction: GridExtraction,
    image_size: tuple[int, int],
) -> GridExtraction:
    partial_cells = set(partial_edge_cells(extraction, image_size))
    full_cells = [
        (col_index, row_index)
        for row_index in range(extraction.rows)
        for col_index in range(extraction.columns)
        if (col_index, row_index) not in partial_cells
    ]
    if not full_cells:
        raise ValueError("extraction does not contain any fully visible cells")

    min_col = min(col_index for col_index, _ in full_cells)
    max_col = max(col_index for col_index, _ in full_cells)
    min_row = min(row_index for _, row_index in full_cells)
    max_row = max(row_index for _, row_index in full_cells)

    crop_left, crop_top, _, _ = extraction.crop_box
    x0 = extraction.x_edges[min_col]
    x1 = extraction.x_edges[max_col + 1]
    y0 = extraction.y_edges[min_row]
    y1 = extraction.y_edges[max_row + 1]
    return GridExtraction(
        transform=extraction.transform,
        columns=(max_col - min_col) + 1,
        rows=(max_row - min_row) + 1,
        crop_box=(crop_left + x0, crop_top + y0, crop_left + x1, crop_top + y1),
        x_edges=tuple(edge - x0 for edge in extraction.x_edges[min_col : max_col + 2]),
        y_edges=tuple(edge - y0 for edge in extraction.y_edges[min_row : max_row + 2]),
    )


def trim_extraction_to_relevant_boxes(
    extraction: GridExtraction,
    relevant_boxes: tuple[Rect, ...],
) -> GridExtraction:
    if not relevant_boxes:
        return extraction

    intersecting_cells = [
        (col_index, row_index)
        for row_index in range(extraction.rows)
        for col_index in range(extraction.columns)
        if any(
            _rectangles_intersect(cell_bounds(extraction, col_index, row_index, absolute=True), rectangle)
            for rectangle in relevant_boxes
        )
    ]
    if not intersecting_cells:
        raise ValueError("relevant_box does not intersect any extracted grid cells")

    min_col = min(col_index for col_index, _ in intersecting_cells)
    max_col = max(col_index for col_index, _ in intersecting_cells)
    min_row = min(row_index for _, row_index in intersecting_cells)
    max_row = max(row_index for _, row_index in intersecting_cells)

    crop_left, crop_top, _, _ = extraction.crop_box
    x0 = extraction.x_edges[min_col]
    x1 = extraction.x_edges[max_col + 1]
    y0 = extraction.y_edges[min_row]
    y1 = extraction.y_edges[max_row + 1]
    return GridExtraction(
        transform=extraction.transform,
        columns=(max_col - min_col) + 1,
        rows=(max_row - min_row) + 1,
        crop_box=(crop_left + x0, crop_top + y0, crop_left + x1, crop_top + y1),
        x_edges=tuple(edge - x0 for edge in extraction.x_edges[min_col : max_col + 2]),
        y_edges=tuple(edge - y0 for edge in extraction.y_edges[min_row : max_row + 2]),
    )


def resolve_normalized_cell_size(
    requested: NormalizeCellSizeSetting,
    extraction: GridExtraction,
) -> int | None:
    if requested is None:
        return None
    tile_size = extraction.transform.tile_size
    if requested == "auto":
        native_width = extraction.crop_box[2] - extraction.crop_box[0]
        native_height = extraction.crop_box[3] - extraction.crop_box[1]
        native_average = ((native_width / extraction.columns) + (native_height / extraction.rows)) / 2
        multiplier = max(1, round(native_average / tile_size))
        return multiplier * tile_size
    if requested % tile_size != 0:
        raise ValueError("normalize_cell_size must be an integer multiple of tile_size")
    return requested


def _normalization_resample(source_size: tuple[int, int], target_size: tuple[int, int]) -> Image.Resampling:
    source_width, source_height = source_size
    target_width, target_height = target_size
    if target_width == source_width and target_height == source_height:
        return Image.Resampling.NEAREST  # pyright: ignore[reportUnknownMemberType]
    if target_width < source_width or target_height < source_height:
        return Image.Resampling.BOX  # pyright: ignore[reportUnknownMemberType]
    return Image.Resampling.BICUBIC  # pyright: ignore[reportUnknownMemberType]


def _scale_rectangles(
    rectangles: tuple[Rect, ...],
    *,
    from_size: tuple[int, int],
    to_size: tuple[int, int],
) -> tuple[Rect, ...]:
    if not rectangles:
        return ()
    from_width, from_height = from_size
    to_width, to_height = to_size
    scale_x = to_width / from_width
    scale_y = to_height / from_height
    scaled: list[Rect] = []
    for left, top, right, bottom in rectangles:
        scaled_left = round(left * scale_x)
        scaled_top = round(top * scale_y)
        scaled_right = round(right * scale_x)
        scaled_bottom = round(bottom * scale_y)
        if scaled_left >= scaled_right or scaled_top >= scaled_bottom:
            continue
        scaled.append((scaled_left, scaled_top, scaled_right, scaled_bottom))
    return tuple(scaled)


def normalize_prepared_reference_grid(
    prepared: PreparedReferenceGrid,
    *,
    target_cell_size: int,
) -> PreparedReferenceGrid:
    target_size = (
        prepared.extraction.columns * target_cell_size,
        prepared.extraction.rows * target_cell_size,
    )
    resample = _normalization_resample(prepared.crop.size, target_size)
    normalized_crop = prepared.crop.resize(target_size, resample)  # pyright: ignore[reportUnknownMemberType]
    normalized_transform = GridTransform(
        origin_x=0,
        origin_y=0,
        cell_size=target_cell_size,
        tile_size=prepared.extraction.transform.tile_size,
        content_box=prepared.extraction.transform.content_box,
    )
    normalized_extraction = GridExtraction(
        transform=normalized_transform,
        columns=prepared.extraction.columns,
        rows=prepared.extraction.rows,
        crop_box=(0, 0, target_size[0], target_size[1]),
        x_edges=tuple(index * target_cell_size for index in range(prepared.extraction.columns + 1)),
        y_edges=tuple(index * target_cell_size for index in range(prepared.extraction.rows + 1)),
    )
    return PreparedReferenceGrid(
        crop=normalized_crop,
        extraction=normalized_extraction,
        relevant_boxes=_scale_rectangles(
            prepared.relevant_boxes,
            from_size=prepared.crop.size,
            to_size=target_size,
        ),
        excluded_boxes=_scale_rectangles(
            prepared.excluded_boxes,
            from_size=prepared.crop.size,
            to_size=target_size,
        ),
        normalized_cell_size=target_cell_size,
    )


def prepare_reference_grid(
    image: Image.Image,
    *,
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    span_box: Rect | None = None,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    exclude_partial_edge_cells: bool = False,
    background: RGBA,
) -> PreparedReferenceGrid:
    extraction = compute_extraction(
        image.size,
        transform,
        cols=cols,
        rows=rows,
        include_partial_edges=True,
        span_box=span_box,
    )
    if exclude_partial_edge_cells:
        extraction = trim_extraction_to_full_cells(extraction, image.size)
    extraction = trim_extraction_to_relevant_boxes(extraction, relevant_boxes)
    crop = extract_crop(image, extraction, background=background)
    return PreparedReferenceGrid(
        crop=crop,
        extraction=extraction,
        relevant_boxes=crop_relative_rectangles(extraction, relevant_boxes),
        excluded_boxes=crop_relative_rectangles(extraction, excluded_boxes),
        normalized_cell_size=None,
    )


def resize_nearest(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.NEAREST)  # pyright: ignore[reportUnknownMemberType]


def scaled_partition_bounds(cell_size: int, tile_size: int) -> list[int]:
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    return [round((index * cell_size) / tile_size) for index in range(tile_size)] + [cell_size]


def _dominant_colour(cell_image: Image.Image, bounds: tuple[int, int, int, int]) -> RGBA:
    x0, y0, x1, y1 = bounds
    colours = [
        cast(RGBA, cell_image.getpixel((x, y)))
        for y in range(y0, y1)
        for x in range(x0, x1)
    ]
    if not colours:
        raise ValueError("partition bounds must describe at least one pixel")
    return Counter(colours).most_common(1)[0][0]


def _recover_partitioned_content_box(
    cell_image: Image.Image,
    *,
    tile_size: int,
    content_box: ContentBox,
    output: Image.Image,
) -> None:
    x_bounds = scaled_partition_bounds(cell_image.width, tile_size)
    y_bounds = scaled_partition_bounds(cell_image.height, tile_size)
    left, top, right, bottom = content_box
    for y in range(top, bottom):
        y0 = y_bounds[y]
        y1 = y_bounds[y + 1]
        if y1 <= y0:
            y1 = y0 + 1
        for x in range(left, right):
            x0 = x_bounds[x]
            x1 = x_bounds[x + 1]
            if x1 <= x0:
                x1 = x0 + 1
            output.putpixel((x, y), _dominant_colour(cell_image, (x0, y0, x1, y1)))


def recover_base_tile(
    cell_image: Image.Image,
    tile_size: int,
    *,
    content_box: ContentBox | None = None,
    background: RGBA | None = None,
) -> Image.Image:
    rgba = cell_image.convert("RGBA")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    out = Image.new("RGBA", (tile_size, tile_size))
    x_bounds = scaled_partition_bounds(rgba.width, tile_size)
    y_bounds = scaled_partition_bounds(rgba.height, tile_size)
    for y in range(tile_size):
        y0 = y_bounds[y]
        y1 = y_bounds[y + 1]
        if y1 <= y0:
            y1 = y0 + 1
        for x in range(tile_size):
            x0 = x_bounds[x]
            x1 = x_bounds[x + 1]
            if x1 <= x0:
                x1 = x0 + 1
            out.putpixel((x, y), _dominant_colour(rgba, (x0, y0, x1, y1)))
    if content_box is not None:
        if background is not None:
            left, top, right, bottom = content_box
            for y in range(tile_size):
                for x in range(tile_size):
                    if not (left <= x < right and top <= y < bottom):
                        out.putpixel((x, y), background)
        _recover_partitioned_content_box(rgba, tile_size=tile_size, content_box=content_box, output=out)
    return out


def build_cell_crops(crop: Image.Image, extraction: GridExtraction) -> list[list[Image.Image]]:
    grid: list[list[Image.Image]] = []
    for row in range(extraction.rows):
        row_cells: list[Image.Image] = []
        for col in range(extraction.columns):
            x0 = extraction.x_edges[col]
            x1 = extraction.x_edges[col + 1]
            y0 = extraction.y_edges[row]
            y1 = extraction.y_edges[row + 1]
            row_cells.append(crop.crop((x0, y0, x1, y1)))
        grid.append(row_cells)
    return grid


def build_tile_grid(crop: Image.Image, extraction: GridExtraction, *, background: RGBA | None = None) -> list[list[Image.Image]]:
    tile_size = extraction.transform.tile_size
    grid: list[list[Image.Image]] = []
    for row_cells in build_cell_crops(crop, extraction):
        row_tiles: list[Image.Image] = []
        for cell in row_cells:
            row_tiles.append(
                recover_base_tile(
                    cell,
                    tile_size,
                    content_box=extraction.transform.content_box,
                    background=background,
                )
            )
        grid.append(row_tiles)
    return grid


def _point_is_excluded(x: int, y: int, excluded_boxes: tuple[Rect, ...]) -> bool:
    return any(left <= x < right and top <= y < bottom for left, top, right, bottom in excluded_boxes)


def _point_is_relevant(x: int, y: int, relevant_boxes: tuple[Rect, ...]) -> bool:
    if not relevant_boxes:
        return True
    return any(left <= x < right and top <= y < bottom for left, top, right, bottom in relevant_boxes)


def count_solid_guide_pixels(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    *,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
) -> tuple[int, int]:
    content_box = extraction.transform.content_box
    verticals: list[int] = []
    horizontals: list[int] = []
    if content_box is None:
        gutter = extraction.transform.gutter_size
        for col in range(extraction.columns):
            cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
            verticals.append(extraction.x_edges[col] + (cell_width - gutter))
        for row in range(extraction.rows):
            horizontals.append(extraction.y_edges[row] + gutter - 1)
    else:
        for col in range(extraction.columns):
            cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
            bounds_x = scaled_partition_bounds(cell_width, extraction.transform.tile_size)
            left, _, right, _ = content_box
            left_px = bounds_x[left]
            right_px = bounds_x[right]
            if left_px > 0:
                verticals.append(extraction.x_edges[col] + left_px - 1)
            if right_px < cell_width:
                verticals.append(extraction.x_edges[col] + right_px)
        for row in range(extraction.rows):
            cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
            bounds_y = scaled_partition_bounds(cell_height, extraction.transform.tile_size)
            _, top, _, bottom = content_box
            top_px = bounds_y[top]
            bottom_px = bounds_y[bottom]
            if top_px > 0:
                horizontals.append(extraction.y_edges[row] + top_px - 1)
            if bottom_px < cell_height:
                horizontals.append(extraction.y_edges[row] + bottom_px)
    solid = 0
    total = 0
    rgba = crop.convert("RGBA")
    for offset in verticals:
        for y in range(rgba.height):
            if not _point_is_relevant(offset, y, relevant_boxes):
                continue
            if _point_is_excluded(offset, y, excluded_boxes):
                continue
            total += 1
            solid += cast(RGBA, rgba.getpixel((offset, y))) != background
    for offset in horizontals:
        for x in range(rgba.width):
            if not _point_is_relevant(x, offset, relevant_boxes):
                continue
            if _point_is_excluded(x, offset, excluded_boxes):
                continue
            total += 1
            solid += cast(RGBA, rgba.getpixel((x, offset))) != background
    return solid, total


def render_contact_sheet(
    tile_grid: list[list[Image.Image]],
    background: RGBA,
    scale: int,
    label_colour: RGBA = (218, 206, 185, 255),
) -> Image.Image:
    if not tile_grid or not tile_grid[0]:
        raise ValueError("tile grid must not be empty")
    rows = len(tile_grid)
    cols = len(tile_grid[0])
    tile_size = tile_grid[0][0].width
    pad = max(4, scale + 2)
    left_margin = 42
    top_margin = 30
    canvas = Image.new(
        "RGBA",
        (
            left_margin + cols * (tile_size * scale + pad) + pad,
            top_margin + rows * (tile_size * scale + pad) + pad,
        ),
        background,
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for col in range(cols):
        label = str(col + 1)
        center_x = left_margin + pad + col * (tile_size * scale + pad) + (tile_size * scale / 2)
        _draw_centered_text(draw, label, center_x=center_x, center_y=11, fill=label_colour, font=font)
    for row in range(rows):
        label = str(row + 1)
        center_y = top_margin + pad + row * (tile_size * scale + pad) + (tile_size * scale / 2)
        _draw_centered_text(draw, label, center_x=11, center_y=center_y, fill=label_colour, font=font)
    for row_index, row_tiles in enumerate(tile_grid):
        for col_index, tile in enumerate(row_tiles):
            x = left_margin + pad + col_index * (tile_size * scale + pad)
            y = top_margin + pad + row_index * (tile_size * scale + pad)
            scaled_tile = resize_nearest(tile, (tile_size * scale, tile_size * scale))
            canvas.alpha_composite(scaled_tile, (x, y))
    return canvas


def _new_guide_canvas(
    *,
    content_width: int,
    content_height: int,
    background: RGBA,
) -> tuple[Image.Image, int, int]:
    left_margin = GUIDE_MARGIN
    top_margin = GUIDE_MARGIN
    right_margin = GUIDE_MARGIN
    bottom_margin = GUIDE_MARGIN
    canvas = Image.new(
        "RGBA",
        (
            left_margin + content_width + right_margin + 1,
            top_margin + content_height + bottom_margin + 1,
        ),
        background,
    )
    return canvas, left_margin, top_margin


def _draw_guide_labels(
    draw: ImageDraw.ImageDraw,
    extraction: GridExtraction,
    *,
    guide_line_mode: GuideLineMode,
    left_margin: int,
    top_margin: int,
    crop_width: int,
    crop_height: int,
    label_colour: RGBA,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    top_y = GUIDE_OUTER_PAD // 2
    bottom_y = top_margin + crop_height + GUIDE_OUTER_PAD // 2
    left_x = GUIDE_OUTER_PAD // 2
    right_x = left_margin + crop_width + GUIDE_OUTER_PAD // 2
    x_edges = _guide_display_edges(
        extraction,
        axis="x",
        guide_line_mode=guide_line_mode,
        margin=left_margin,
    )
    y_edges = _guide_display_edges(
        extraction,
        axis="y",
        guide_line_mode=guide_line_mode,
        margin=top_margin,
    )
    for col in range(extraction.columns):
        label = str(col + 1)
        center_x = (x_edges[col] + x_edges[col + 1]) / 2
        _draw_centered_text(draw, label, center_x=center_x, center_y=top_y + 5, fill=label_colour, font=font)
        _draw_centered_text(draw, label, center_x=center_x, center_y=bottom_y + 5, fill=label_colour, font=font)
    for row in range(extraction.rows):
        label = str(row + 1)
        center_y = (y_edges[row] + y_edges[row + 1]) / 2
        _draw_centered_text(draw, label, center_x=left_x + 5, center_y=center_y, fill=label_colour, font=font)
        _draw_centered_text(draw, label, center_x=right_x + 5, center_y=center_y, fill=label_colour, font=font)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    center_x: float,
    center_y: float,
    fill: RGBA,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width = right - left
    height = bottom - top
    draw.text(
        (round(center_x - (width / 2)), round(center_y - (height / 2))),
        text,
        fill=fill,
        font=font,
    )


def _draw_guide_border(
    draw: ImageDraw.ImageDraw,
    *,
    left_margin: int,
    top_margin: int,
    crop_width: int,
    crop_height: int,
    line_colour: RGBA,
) -> None:
    draw.rectangle(
        (
            left_margin,
            top_margin,
            left_margin + crop_width,
            top_margin + crop_height,
        ),
        outline=line_colour,
        width=1,
    )


def _fill_region(
    canvas: Image.Image,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    fill: RGBA,
) -> None:
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(Image.new("RGBA", (right - left, bottom - top), fill), (left, top))


def _outline_region(
    draw: ImageDraw.ImageDraw,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    outline: RGBA,
) -> None:
    if right <= left or bottom <= top:
        return
    draw.rectangle((left, top, right - 1, bottom - 1), outline=outline, width=1)


def _guide_display_edges(
    extraction: GridExtraction,
    *,
    axis: Literal["x", "y"],
    guide_line_mode: GuideLineMode,
    margin: int,
) -> tuple[int, ...]:
    edges = extraction.x_edges if axis == "x" else extraction.y_edges
    if guide_line_mode == "overlay":
        return tuple(margin + edge for edge in edges)
    return tuple(margin + 1 + edge + index for index, edge in enumerate(edges))


def _mapped_crop_coordinate_for_separated(
    extraction: GridExtraction,
    coordinate: int,
    *,
    axis: Literal["x", "y"],
    margin: int,
) -> int:
    edges = extraction.x_edges if axis == "x" else extraction.y_edges
    separators_before = sum(1 for edge in edges[1:-1] if edge < coordinate)
    return margin + 1 + coordinate + separators_before


def _mapped_cell_origin_for_separated(
    extraction: GridExtraction,
    col: int,
    row: int,
    *,
    left_margin: int,
    top_margin: int,
) -> tuple[int, int]:
    return (
        left_margin + 1 + extraction.x_edges[col] + col,
        top_margin + 1 + extraction.y_edges[row] + row,
    )


def _grid_span_for_separated(extraction: GridExtraction) -> tuple[int, int]:
    return (
        extraction.x_edges[-1] + extraction.columns + 1,
        extraction.y_edges[-1] + extraction.rows + 1,
    )


def render_exact_boundary_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    line_colour: RGBA = (218, 206, 185, 180),
    label_colour: RGBA = (218, 206, 185, 255),
) -> Image.Image:
    canvas, left_margin, top_margin = _new_guide_canvas(
        content_width=crop.width,
        content_height=crop.height,
        background=background,
    )
    canvas.alpha_composite(crop, (left_margin, top_margin))
    for left, top, right, bottom in relevant_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=(80, 160, 120, 48),
        )
    for left, top, right, bottom in excluded_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=(218, 80, 80, 64),
        )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for edge in extraction.x_edges:
        x = left_margin + edge
        draw.line((x, top_margin, x, top_margin + crop.height), fill=line_colour, width=1)
    for edge in extraction.y_edges:
        y = top_margin + edge
        draw.line((left_margin, y, left_margin + crop.width, y), fill=line_colour, width=1)
    _draw_guide_border(
        draw,
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=crop.width,
        crop_height=crop.height,
        line_colour=line_colour,
    )
    _draw_guide_labels(
        draw,
        extraction,
        guide_line_mode="overlay",
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=crop.width,
        crop_height=crop.height,
        label_colour=label_colour,
        font=font,
    )
    for left, top, right, bottom in excluded_boxes:
        _outline_region(
            draw,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            outline=(218, 80, 80, 255),
        )
    return canvas


def render_gutter_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    band_colour: RGBA = (218, 206, 185, 40),
    guide_colour: RGBA = (218, 206, 185, 70),
    label_colour: RGBA = (218, 206, 185, 255),
    guide_line_mode: GuideLineMode = "separated",
) -> Image.Image:
    content_box = extraction.transform.content_box
    if guide_line_mode == "separated":
        grid_width, grid_height = _grid_span_for_separated(extraction)
        canvas, left_margin, top_margin = _new_guide_canvas(
            content_width=grid_width,
            content_height=grid_height,
            background=background,
        )
        for row in range(extraction.rows):
            for col in range(extraction.columns):
                x0 = extraction.x_edges[col]
                x1 = extraction.x_edges[col + 1]
                y0 = extraction.y_edges[row]
                y1 = extraction.y_edges[row + 1]
                cell = crop.crop((x0, y0, x1, y1))
                cell_left, cell_top = _mapped_cell_origin_for_separated(
                    extraction,
                    col,
                    row,
                    left_margin=left_margin,
                    top_margin=top_margin,
                )
                canvas.alpha_composite(cell, (cell_left, cell_top))

        for left, top, right, bottom in relevant_boxes:
            mapped_left = _mapped_crop_coordinate_for_separated(extraction, left, axis="x", margin=left_margin)
            mapped_top = _mapped_crop_coordinate_for_separated(extraction, top, axis="y", margin=top_margin)
            mapped_right = _mapped_crop_coordinate_for_separated(extraction, right, axis="x", margin=left_margin)
            mapped_bottom = _mapped_crop_coordinate_for_separated(extraction, bottom, axis="y", margin=top_margin)
            _fill_region(
                canvas,
                left=mapped_left,
                top=mapped_top,
                right=mapped_right,
                bottom=mapped_bottom,
                fill=(80, 160, 120, 48),
            )
        for left, top, right, bottom in excluded_boxes:
            mapped_left = _mapped_crop_coordinate_for_separated(extraction, left, axis="x", margin=left_margin)
            mapped_top = _mapped_crop_coordinate_for_separated(extraction, top, axis="y", margin=top_margin)
            mapped_right = _mapped_crop_coordinate_for_separated(extraction, right, axis="x", margin=left_margin)
            mapped_bottom = _mapped_crop_coordinate_for_separated(extraction, bottom, axis="y", margin=top_margin)
            _fill_region(
                canvas,
                left=mapped_left,
                top=mapped_top,
                right=mapped_right,
                bottom=mapped_bottom,
                fill=(218, 80, 80, 64),
            )

        draw = ImageDraw.Draw(canvas)
        for col in range(1, extraction.columns):
            edge = extraction.x_edges[col]
            x = left_margin + edge + col
            draw.line((x, top_margin, x, top_margin + grid_height - 1), fill=guide_colour, width=1)
        for row in range(1, extraction.rows):
            edge = extraction.y_edges[row]
            y = top_margin + edge + row
            draw.line((left_margin, y, left_margin + grid_width - 1, y), fill=guide_colour, width=1)

        _draw_guide_border(
            draw,
            left_margin=left_margin,
            top_margin=top_margin,
            crop_width=grid_width - 1,
            crop_height=grid_height - 1,
            line_colour=label_colour,
        )

        font = ImageFont.load_default()
        _draw_guide_labels(
            draw,
            extraction,
            guide_line_mode="separated",
            left_margin=left_margin,
            top_margin=top_margin,
            crop_width=grid_width - 1,
            crop_height=grid_height - 1,
            label_colour=label_colour,
            font=font,
        )
        for left, top, right, bottom in excluded_boxes:
            mapped_left = _mapped_crop_coordinate_for_separated(extraction, left, axis="x", margin=left_margin)
            mapped_top = _mapped_crop_coordinate_for_separated(extraction, top, axis="y", margin=top_margin)
            mapped_right = _mapped_crop_coordinate_for_separated(extraction, right, axis="x", margin=left_margin)
            mapped_bottom = _mapped_crop_coordinate_for_separated(extraction, bottom, axis="y", margin=top_margin)
            _outline_region(
                draw,
                left=mapped_left,
                top=mapped_top,
                right=mapped_right,
                bottom=mapped_bottom,
                outline=(218, 80, 80, 255),
            )
        return canvas

    canvas, left_margin, top_margin = _new_guide_canvas(
        content_width=crop.width,
        content_height=crop.height,
        background=background,
    )
    canvas.alpha_composite(crop, (left_margin, top_margin))
    for left, top, right, bottom in relevant_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=(80, 160, 120, 48),
        )
    for left, top, right, bottom in excluded_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=(218, 80, 80, 64),
        )
    line_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(line_layer)
    if content_box is None:
        gutter = extraction.transform.gutter_size
        for col in range(extraction.columns):
            cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
            x = left_margin + extraction.x_edges[col] + max(0, cell_width - gutter)
            draw.line((x, top_margin, x, top_margin + crop.height), fill=guide_colour, width=1)
        for row in range(extraction.rows):
            y = top_margin + extraction.y_edges[row] + max(0, gutter - 1)
            draw.line((left_margin, y, left_margin + crop.width, y), fill=guide_colour, width=1)
    else:
        for col in range(extraction.columns):
            cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
            bounds_x = scaled_partition_bounds(cell_width, extraction.transform.tile_size)
            left, _, right, _ = content_box
            left_px = bounds_x[left]
            right_px = bounds_x[right]
            if left_px > 0:
                x = left_margin + extraction.x_edges[col] + left_px - 1
                draw.line((x, top_margin, x, top_margin + crop.height), fill=guide_colour, width=1)
            if right_px < cell_width:
                x = left_margin + extraction.x_edges[col] + right_px
                draw.line((x, top_margin, x, top_margin + crop.height), fill=guide_colour, width=1)
        for row in range(extraction.rows):
            cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
            bounds_y = scaled_partition_bounds(cell_height, extraction.transform.tile_size)
            _, top, _, bottom = content_box
            top_px = bounds_y[top]
            bottom_px = bounds_y[bottom]
            if top_px > 0:
                y = top_margin + extraction.y_edges[row] + top_px - 1
                draw.line((left_margin, y, left_margin + crop.width, y), fill=guide_colour, width=1)
            if bottom_px < cell_height:
                y = top_margin + extraction.y_edges[row] + bottom_px
                draw.line((left_margin, y, left_margin + crop.width, y), fill=guide_colour, width=1)
    canvas.alpha_composite(line_layer)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    _draw_guide_border(
        draw,
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=crop.width,
        crop_height=crop.height,
        line_colour=label_colour,
    )
    _draw_guide_labels(
        draw,
        extraction,
        guide_line_mode="overlay",
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=crop.width,
        crop_height=crop.height,
        label_colour=label_colour,
        font=font,
    )
    for left, top, right, bottom in excluded_boxes:
        _outline_region(
            draw,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            outline=(218, 80, 80, 255),
        )
    return canvas


def parse_zoom_cell(raw: str | None) -> tuple[int, int] | None:
    if raw is None:
        return None
    col_raw, row_raw = raw.split(",", 1)
    return int(col_raw), int(row_raw)


def render_zoom(
    canvas: Image.Image,
    extraction: GridExtraction,
    cell: tuple[int, int],
    *,
    guide_line_mode: GuideLineMode,
) -> Image.Image:
    col, row = cell
    if not (0 <= col < extraction.columns and 0 <= row < extraction.rows):
        raise ValueError("zoom cell lies outside the extracted grid")
    left_margin = GUIDE_MARGIN
    top_margin = GUIDE_MARGIN
    if guide_line_mode == "separated":
        cell_left, cell_top = _mapped_cell_origin_for_separated(
            extraction,
            col,
            row,
            left_margin=left_margin,
            top_margin=top_margin,
        )
        cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
        cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
        x0 = cell_left
        y0 = cell_top
        x1 = cell_left + cell_width
        y1 = cell_top + cell_height
    else:
        cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
        cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
        x0 = left_margin + extraction.x_edges[col]
        y0 = top_margin + extraction.y_edges[row]
        x1 = left_margin + extraction.x_edges[col + 1]
        y1 = top_margin + extraction.y_edges[row + 1]
    pad_x = cell_width // 2
    pad_y = cell_height // 2
    x0 -= pad_x
    y0 -= pad_y
    x1 += pad_x
    y1 += pad_y
    return resize_nearest(canvas.crop((x0, y0, x1, y1)), (256, 256))


def save_outputs(args: argparse.Namespace) -> list[Path]:
    settings = resolve_grid_run_settings(args)
    image = Image.open(settings.image_path).convert("RGBA")
    background = resolve_background(image, settings.background)
    prepared = prepare_reference_grid(
        image,
        transform=settings.transform,
        cols=settings.columns,
        rows=settings.rows,
        span_box=settings.span_box,
        relevant_boxes=settings.relevant_boxes,
        excluded_boxes=settings.excluded_boxes,
        exclude_partial_edge_cells=settings.exclude_partial_edge_cells,
        background=background,
    )
    normalized_target = resolve_normalized_cell_size(settings.normalize_cell_size, prepared.extraction)
    prepared_for_outputs = prepared
    if normalized_target is not None:
        prepared_for_outputs = normalize_prepared_reference_grid(
            prepared,
            target_cell_size=normalized_target,
        )
    tile_grid = build_tile_grid(
        prepared_for_outputs.crop,
        prepared_for_outputs.extraction,
        background=background,
    )

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    cropped_path = settings.output_dir / f"{settings.prefix}_cropped.png"
    prepared.crop.save(cropped_path)
    outputs.append(cropped_path)

    if prepared_for_outputs.normalized_cell_size is not None:
        normalized_path = settings.output_dir / f"{settings.prefix}_normalized_body.png"
        prepared_for_outputs.crop.save(normalized_path)
        outputs.append(normalized_path)

    contact_sheet = render_contact_sheet(tile_grid, background, scale=settings.scale)
    contact_path = settings.output_dir / f"{settings.prefix}_contact_sheet.png"
    contact_sheet.save(contact_path)
    outputs.append(contact_path)

    exact_overlay = render_exact_boundary_overlay(
        prepared_for_outputs.crop,
        prepared_for_outputs.extraction,
        background,
        relevant_boxes=prepared_for_outputs.relevant_boxes,
        excluded_boxes=prepared_for_outputs.excluded_boxes,
    )
    exact_path = settings.output_dir / f"{settings.prefix}_exact_boundary.png"
    exact_overlay.save(exact_path)
    outputs.append(exact_path)

    gutter_overlay = render_gutter_overlay(
        prepared_for_outputs.crop,
        prepared_for_outputs.extraction,
        background,
        relevant_boxes=prepared_for_outputs.relevant_boxes,
        excluded_boxes=prepared_for_outputs.excluded_boxes,
        guide_line_mode=settings.guide_line_mode,
    )
    gutter_path = settings.output_dir / f"{settings.prefix}_gutter_guides.png"
    gutter_overlay.save(gutter_path)
    outputs.append(gutter_path)

    sibling_guide_path = settings.image_path.with_name(f"{settings.image_path.stem}--guide{settings.image_path.suffix}")
    gutter_overlay.save(sibling_guide_path)
    outputs.append(sibling_guide_path)

    if settings.zoom_cell is not None:
        zoom = render_zoom(
            gutter_overlay,
            prepared_for_outputs.extraction,
            settings.zoom_cell,
            guide_line_mode=settings.guide_line_mode,
        )
        zoom_path = settings.output_dir / f"{settings.prefix}_zoom_c{settings.zoom_cell[0]}_r{settings.zoom_cell[1]}.png"
        zoom.save(zoom_path)
        outputs.append(zoom_path)

    return outputs


def main() -> int:
    args = parse_args()
    outputs = save_outputs(args)
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
