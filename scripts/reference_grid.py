from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from PIL import Image, ImageColor, ImageDraw, ImageFont

from reference_config import (
    load_reference_config,
    read_bool,
    read_content_box,
    read_float,
    read_guide_line_mode,
    read_int,
    read_normalize_cell_size,
    read_path,
    read_rect,
    read_rectangles,
    read_string,
    read_zoom_cell,
)
from reference_grid_types import ContentBox, GuideLineMode, NormalizeCellSizeSetting, Rect
from _manifest_utils import require_mapping

RGBA = tuple[int, int, int, int]


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
    guide_render_scale: int
    transparent_grid_surface: bool
    emit_recovered_tile_sheet: bool
    background: str | None
    zoom_cell: tuple[int, int] | None
    recovered_tile_scale: int


@dataclass
class PreparedReferenceGrid:
    crop: Image.Image
    extraction: GridExtraction
    relevant_boxes: tuple[Rect, ...]
    excluded_boxes: tuple[Rect, ...]
    normalized_cell_size: int | None


GUIDE_MIN_OUTER_PAD = 4
GUIDE_LABEL_HEIGHT_RATIO = 0.30
GUIDE_LABEL_WIDTH_RATIO = 0.75
GUIDE_LABEL_MIN_HEIGHT = 4
GUIDE_LABEL_MAX_HEIGHT = 72
GUIDE_LABEL_INNER_PAD_RATIO = 0.20
GUIDE_OUTER_PAD_CELL_RATIO = 0.125
GUIDE_OUTER_PAD_LABEL_RATIO = 0.25
GUIDE_LINE_ALPHA_MIN = 30
GUIDE_LINE_ALPHA_MAX = 70
GUIDE_LINE_FULL_STRENGTH_CELL = 24
DEFAULT_GUIDE_BACKGROUND: RGBA = (36, 25, 42, 255)
RELEVANT_FILL_COLOUR: RGBA = (80, 160, 120, 48)
EXCLUDED_FILL_COLOUR: RGBA = (218, 80, 80, 64)
EXCLUDED_OUTLINE_COLOUR: RGBA = (218, 80, 80, 255)
DEFAULT_GUIDE_LINE_RGB = (218, 206, 185)


@dataclass(frozen=True)
class GuideChrome:
    outer_pad: int
    label_band: int
    label_inner_pad: int
    margin: int
    target_label_height: int
    actual_label_height: int
    actual_label_width: int
    font_size: int | None


@dataclass(frozen=True)
class GuideLabelFit:
    sample_text: str
    max_label_height: int
    max_label_width: int
    actual_label_height: int
    actual_label_width: int
    font_size: int | None


@dataclass(frozen=True)
class GuideCanvasLayout:
    left_margin: int
    top_margin: int
    right_margin: int
    bottom_margin: int
    content_width: int
    content_height: int
    canvas_width: int
    canvas_height: int
    top_label_center_y: float
    bottom_label_center_y: float
    left_label_center_x: float
    right_label_center_x: float


GUIDE_FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/Courier.ttc",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSansMono-Bold.ttf",
    "DejaVuSansMono.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
)


@lru_cache(maxsize=1)
def _resolve_guide_font_resource() -> str | None:
    for resource in GUIDE_FONT_CANDIDATES:
        try:
            ImageFont.truetype(resource, 12)
            return resource
        except OSError:
            continue
    return None


def _measure_text(font: ImageFont.ImageFont | ImageFont.FreeTypeFont, text: str = "88") -> tuple[int, int]:
    left, top, right, bottom = font.getbbox(text)
    return (int(right - left), int(bottom - top))


def _font_metrics_for_size(
    size: int,
    *,
    sample_text: str,
) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, int, int]:
    resource = _resolve_guide_font_resource()
    if resource is None:
        font = ImageFont.load_default()
        width, height = _measure_text(font, sample_text)
        return (font, width, height)
    font = ImageFont.truetype(resource, size)
    width, height = _measure_text(font, sample_text)
    return (font, width, height)


def _load_guide_font(
    *,
    target_label_height: int,
    max_label_width: int,
    sample_text: str,
) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, int | None, int, int]:
    resource = _resolve_guide_font_resource()
    if resource is None:
        font = ImageFont.load_default()
        width, height = _measure_text(font, sample_text)
        return (font, None, width, height)

    low = 4
    high = max(target_label_height * 3, 12)
    best_size = low
    best_font: ImageFont.ImageFont | ImageFont.FreeTypeFont | None = None
    best_width = 0
    best_height = 0
    while low <= high:
        mid = (low + high) // 2
        font, width, height = _font_metrics_for_size(mid, sample_text=sample_text)
        if height <= target_label_height and width <= max_label_width:
            best_size = mid
            best_font = font
            best_width = width
            best_height = height
            low = mid + 1
        else:
            high = mid - 1
    if best_font is None:
        best_font, best_width, best_height = _font_metrics_for_size(best_size, sample_text=sample_text)
    return (best_font, best_size, best_width, best_height)


def _average_cell_extent(extraction: GridExtraction) -> float:
    widths = [extraction.x_edges[index + 1] - extraction.x_edges[index] for index in range(extraction.columns)]
    heights = [extraction.y_edges[index + 1] - extraction.y_edges[index] for index in range(extraction.rows)]
    extents = widths + heights
    return sum(extents) / len(extents)


def _average_cell_width(extraction: GridExtraction) -> float:
    widths = [extraction.x_edges[index + 1] - extraction.x_edges[index] for index in range(extraction.columns)]
    return sum(widths) / len(widths)


def _guide_font_for_extraction(
    extraction: GridExtraction,
    *,
    target_label_height: int,
    render_scale: int,
) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, int | None, int, int]:
    sample_text = str(max(extraction.columns, extraction.rows))
    return _load_guide_font(
        target_label_height=target_label_height,
        max_label_width=max(5, round((_average_cell_width(extraction) * render_scale) * GUIDE_LABEL_WIDTH_RATIO)),
        sample_text=sample_text,
    )


def _build_guide_label_fit(extraction: GridExtraction, *, render_scale: int) -> GuideLabelFit:
    sample_text = str(max(extraction.columns, extraction.rows))
    average_extent = _average_cell_extent(extraction) * render_scale
    max_label_height = round(average_extent * GUIDE_LABEL_HEIGHT_RATIO)
    max_label_height = max(GUIDE_LABEL_MIN_HEIGHT, min(GUIDE_LABEL_MAX_HEIGHT, max_label_height))
    max_label_width = max(5, round((_average_cell_width(extraction) * render_scale) * GUIDE_LABEL_WIDTH_RATIO))
    _, font_size, actual_label_width, actual_label_height = _load_guide_font(
        target_label_height=max_label_height,
        max_label_width=max_label_width,
        sample_text=sample_text,
    )
    return GuideLabelFit(
        sample_text=sample_text,
        max_label_height=max_label_height,
        max_label_width=max_label_width,
        actual_label_height=actual_label_height,
        actual_label_width=actual_label_width,
        font_size=font_size,
    )


@lru_cache(maxsize=None)
def _build_guide_chrome(extraction: GridExtraction, render_scale: int = 1) -> GuideChrome:
    average_extent = _average_cell_extent(extraction) * render_scale
    fit = _build_guide_label_fit(extraction, render_scale=render_scale)
    label_extent = max(fit.actual_label_width, fit.actual_label_height)
    label_inner_pad = max(2, round(label_extent * GUIDE_LABEL_INNER_PAD_RATIO))
    outer_pad = max(
        GUIDE_MIN_OUTER_PAD,
        round(average_extent * GUIDE_OUTER_PAD_CELL_RATIO),
        round(label_extent * GUIDE_OUTER_PAD_LABEL_RATIO),
    )
    label_band = label_extent + (label_inner_pad * 2)
    return GuideChrome(
        outer_pad=outer_pad,
        label_band=label_band,
        label_inner_pad=label_inner_pad,
        margin=outer_pad + label_band,
        target_label_height=fit.max_label_height,
        actual_label_height=fit.actual_label_height,
        actual_label_width=fit.actual_label_width,
        font_size=fit.font_size,
    )


def guide_margin_for_extraction(extraction: GridExtraction, *, render_scale: int = 1) -> int:
    return _build_guide_chrome(extraction, render_scale=render_scale).margin


def _resolve_default_guide_line_colour(extraction: GridExtraction, *, render_scale: int = 1) -> RGBA:
    average_extent = _average_cell_extent(extraction) * render_scale
    if average_extent >= GUIDE_LINE_FULL_STRENGTH_CELL:
        alpha = GUIDE_LINE_ALPHA_MAX
    else:
        ratio = max(0.0, (average_extent - 8.0) / (GUIDE_LINE_FULL_STRENGTH_CELL - 8.0))
        alpha = round(GUIDE_LINE_ALPHA_MIN + ((GUIDE_LINE_ALPHA_MAX - GUIDE_LINE_ALPHA_MIN) * ratio))
    r, g, b = DEFAULT_GUIDE_LINE_RGB
    return (r, g, b, alpha)


def _build_guide_canvas_layout(
    *,
    content_width: int,
    content_height: int,
    chrome: GuideChrome,
) -> GuideCanvasLayout:
    left_margin = chrome.margin
    top_margin = chrome.margin
    right_margin = chrome.margin
    bottom_margin = chrome.margin
    canvas_width = left_margin + content_width + right_margin + 1
    canvas_height = top_margin + content_height + bottom_margin + 1
    label_center_offset = chrome.label_band / 2
    return GuideCanvasLayout(
        left_margin=left_margin,
        top_margin=top_margin,
        right_margin=right_margin,
        bottom_margin=bottom_margin,
        content_width=content_width,
        content_height=content_height,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        top_label_center_y=chrome.outer_pad + label_center_offset,
        bottom_label_center_y=top_margin + content_height + label_center_offset,
        left_label_center_x=chrome.outer_pad + label_center_offset,
        right_label_center_x=left_margin + content_width + label_center_offset,
    )


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
        "--guide-render-scale",
        type=int,
        default=None,
        help=(
            "Optional integer guide-only render scale. The guide overlays are "
            "rendered on a nearest-neighbour magnified view of the native grid, "
            "without changing extraction or matching."
        ),
    )
    parser.add_argument(
        "--transparent-grid-surface",
        action="store_true",
        help=(
            "Render the grid content area with a transparent background while "
            "keeping the outer guide chrome filled. This only affects guide-style "
            "overlay outputs."
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
    parser.add_argument(
        "--emit-recovered-tile-sheet",
        action="store_true",
        help=(
            "Also emit a recovered-tile matcher-debug sheet. This is not part of the "
            "default human review workflow; it shows the per-cell canonical tile "
            "recovery surface that the matcher would compare against source tiles."
        ),
    )
    parser.add_argument(
        "--recovered-tile-scale",
        "--scale",
        dest="recovered_tile_scale",
        type=int,
        default=4,
        help="Scale factor for the optional recovered-tile matcher-debug sheet.",
    )
    return parser.parse_args()

def resolve_grid_run_settings(args: argparse.Namespace) -> GridRunSettings:
    config, config_dir = load_reference_config(args.config)
    grid_config = require_mapping(config.get("grid", {}), context="grid")

    tile_size = read_int(args.tile_size, grid_config, "tile_size")
    if tile_size is None:
        tile_size = 8
    image_path = read_path(args.image, config, "image", config_dir=config_dir)
    output_dir = read_path(args.output_dir, config, "output_dir", config_dir=config_dir)
    prefix = read_string(args.prefix, config, "prefix")
    origin_x = read_float(args.origin_x, grid_config, "origin_x")
    origin_y = read_float(args.origin_y, grid_config, "origin_y")
    cell_size = read_float(args.cell_size, grid_config, "cell_size")
    span_box = read_rect(args.span_box, grid_config, "span_box")
    normalize_cell_size = read_normalize_cell_size(args.normalize_cell_size, config, "normalize_cell_size")
    cols = read_int(args.cols, grid_config, "cols")
    rows = read_int(args.rows, grid_config, "rows")
    content_box = read_content_box(args.content_box, grid_config, "content_box", tile_size=tile_size)
    relevant_boxes = read_rectangles(args.relevant_box, config, "relevant_boxes")
    excluded_boxes = read_rectangles(args.exclude_box, config, "excluded_boxes")
    exclude_partial_edge_cells = read_bool(
        args.exclude_partial_edge_cells,
        config,
        "exclude_partial_edge_cells",
        default=False,
    )
    guide_line_mode = read_guide_line_mode(args.guide_line_mode, config, "guide_line_mode")
    guide_render_scale = read_int(args.guide_render_scale, config, "guide_render_scale")
    transparent_grid_surface = read_bool(
        args.transparent_grid_surface,
        config,
        "transparent_grid_surface",
        default=False,
    )
    emit_recovered_tile_sheet = read_bool(
        args.emit_recovered_tile_sheet,
        config,
        "emit_recovered_tile_sheet",
        default=False,
    )
    background = read_string(args.background, config, "background")
    zoom_cell = read_zoom_cell(args.zoom_cell, config, "zoom_cell")
    recovered_tile_scale = read_int(args.recovered_tile_scale, config, "recovered_tile_scale")
    if recovered_tile_scale is None:
        recovered_tile_scale = read_int(args.recovered_tile_scale, config, "scale")
    if recovered_tile_scale is None:
        recovered_tile_scale = 4

    if image_path is None:
        raise ValueError("image is required")
    if output_dir is None:
        raise ValueError("output_dir is required")
    if prefix is None:
        raise ValueError("prefix is required")
    if guide_render_scale is None:
        guide_render_scale = 1
    if guide_render_scale <= 0:
        raise ValueError("guide_render_scale must be positive")
    return GridRunSettings(
        image_path=image_path,
        output_dir=output_dir,
        prefix=prefix,
        transform=resolve_grid_transform(
            origin_x=origin_x,
            origin_y=origin_y,
            cell_size=cell_size,
            span_box=span_box,
            cols=cols,
            rows=rows,
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
        guide_render_scale=guide_render_scale,
        transparent_grid_surface=transparent_grid_surface,
        emit_recovered_tile_sheet=emit_recovered_tile_sheet,
        background=background,
        zoom_cell=zoom_cell,
        recovered_tile_scale=recovered_tile_scale,
    )


def resolve_grid_transform(
    *,
    origin_x: float | None,
    origin_y: float | None,
    cell_size: float | None,
    span_box: Rect | None,
    cols: int | None,
    rows: int | None,
    tile_size: int,
    content_box: ContentBox | None,
) -> GridTransform:
    """Resolve the display transform for a reference solve.

    When ``span_box`` is provided, the returned origin/cell_size are synthetic
    display values derived from the exact span so the rest of the pipeline and
    reports can still describe the solved grid in one consistent shape.
    """
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
    return GridTransform(
        origin_x=origin_x,
        origin_y=origin_y,
        cell_size=cell_size,
        tile_size=tile_size,
        content_box=content_box,
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


def resolve_background(image: Image.Image, background: str | None) -> RGBA:
    if background is None:
        sampled = cast(RGBA, image.convert("RGBA").getpixel((0, 0)))
        if sampled[3] == 255:
            return sampled
        background_base = Image.new("RGBA", (1, 1), DEFAULT_GUIDE_BACKGROUND)
        background_base.alpha_composite(Image.new("RGBA", (1, 1), sampled))
        return cast(RGBA, background_base.getpixel((0, 0)))
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
        background = resolve_background(image, None)
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

    return _rebuild_extraction_from_cells(
        extraction,
        min_col=min_col,
        max_col=max_col,
        min_row=min_row,
        max_row=max_row,
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

    return _rebuild_extraction_from_cells(
        extraction,
        min_col=min_col,
        max_col=max_col,
        min_row=min_row,
        max_row=max_row,
    )


def _rebuild_extraction_from_cells(
    extraction: GridExtraction,
    *,
    min_col: int,
    max_col: int,
    min_row: int,
    max_row: int,
) -> GridExtraction:
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
            vertical_offsets, _ = _content_box_edge_offsets(
                cell_extent=cell_width,
                tile_size=extraction.transform.tile_size,
                content_box=content_box,
                axis="x",
            )
            for offset in vertical_offsets:
                verticals.append(extraction.x_edges[col] + offset)
        for row in range(extraction.rows):
            cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
            _, horizontal_offsets = _content_box_edge_offsets(
                cell_extent=cell_height,
                tile_size=extraction.transform.tile_size,
                content_box=content_box,
                axis="y",
            )
            for offset in horizontal_offsets:
                horizontals.append(extraction.y_edges[row] + offset)
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


def _content_box_edge_offsets(
    *,
    cell_extent: int,
    tile_size: int,
    content_box: ContentBox,
    axis: Literal["x", "y"],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    bounds = scaled_partition_bounds(cell_extent, tile_size)
    if axis == "x":
        left, _, right, _ = content_box
        offsets: list[int] = []
        left_px = bounds[left]
        right_px = bounds[right]
        if left_px > 0:
            offsets.append(left_px - 1)
        if right_px < cell_extent:
            offsets.append(right_px)
        return (tuple(offsets), ())
    _, top, _, bottom = content_box
    offsets = []
    top_px = bounds[top]
    bottom_px = bounds[bottom]
    if top_px > 0:
        offsets.append(top_px - 1)
    if bottom_px < cell_extent:
        offsets.append(bottom_px)
    return ((), tuple(offsets))


def _crop_and_extraction_for_recovered_tile_grid(
    tile_grid: list[list[Image.Image]],
    *,
    background: RGBA,
) -> tuple[Image.Image, GridExtraction]:
    if not tile_grid or not tile_grid[0]:
        raise ValueError("tile grid must not be empty")
    rows = len(tile_grid)
    cols = len(tile_grid[0])
    tile_width = tile_grid[0][0].width
    tile_height = tile_grid[0][0].height
    if tile_width != tile_height:
        raise ValueError("tile grid cells must be square")
    for row_tiles in tile_grid:
        if len(row_tiles) != cols:
            raise ValueError("tile grid rows must have a consistent width")
        for tile in row_tiles:
            if tile.width != tile_width or tile.height != tile_height:
                raise ValueError("tile grid cells must all share the same size")

    crop = Image.new("RGBA", (cols * tile_width, rows * tile_height), background)
    for row_index, row_tiles in enumerate(tile_grid):
        for col_index, tile in enumerate(row_tiles):
            crop.alpha_composite(tile.convert("RGBA"), (col_index * tile_width, row_index * tile_height))

    extraction = GridExtraction(
        transform=GridTransform(
            origin_x=0,
            origin_y=0,
            cell_size=tile_width,
            tile_size=tile_width,
        ),
        columns=cols,
        rows=rows,
        crop_box=(0, 0, crop.width, crop.height),
        x_edges=tuple(index * tile_width for index in range(cols + 1)),
        y_edges=tuple(index * tile_height for index in range(rows + 1)),
    )
    return crop, extraction


def _new_guide_canvas(
    *,
    layout: GuideCanvasLayout,
    background: RGBA,
) -> tuple[Image.Image, int, int]:
    canvas = Image.new(
        "RGBA",
        (layout.canvas_width, layout.canvas_height),
        background,
    )
    return canvas, layout.left_margin, layout.top_margin


def _clear_region(
    canvas: Image.Image,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    if right <= left or bottom <= top:
        return
    canvas.paste((0, 0, 0, 0), (left, top, right, bottom))


def _draw_guide_labels(
    draw: ImageDraw.ImageDraw,
    extraction: GridExtraction,
    *,
    layout: GuideCanvasLayout,
    render_scale: int,
    guide_line_mode: GuideLineMode,
    left_margin: int,
    top_margin: int,
    label_colour: RGBA,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    x_edges = _guide_display_edges(
        extraction,
        axis="x",
        guide_line_mode=guide_line_mode,
        margin=left_margin,
        render_scale=render_scale,
    )
    y_edges = _guide_display_edges(
        extraction,
        axis="y",
        guide_line_mode=guide_line_mode,
        margin=top_margin,
        render_scale=render_scale,
    )
    for col in range(extraction.columns):
        label = str(col + 1)
        center_x = (x_edges[col] + x_edges[col + 1]) / 2
        _draw_centered_text(
            draw, label, center_x=center_x, center_y=layout.top_label_center_y, fill=label_colour, font=font
        )
        _draw_centered_text(
            draw, label, center_x=center_x, center_y=layout.bottom_label_center_y, fill=label_colour, font=font
        )
    for row in range(extraction.rows):
        label = str(row + 1)
        center_y = (y_edges[row] + y_edges[row + 1]) / 2
        _draw_centered_text(
            draw, label, center_x=layout.left_label_center_x, center_y=center_y, fill=label_colour, font=font
        )
        _draw_centered_text(
            draw, label, center_x=layout.right_label_center_x, center_y=center_y, fill=label_colour, font=font
        )


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
    draw.text(
        _text_origin_for_centered_bbox(
            left=int(left),
            top=int(top),
            right=int(right),
            bottom=int(bottom),
            center_x=center_x,
            center_y=center_y,
        ),
        text,
        fill=fill,
        font=font,
    )


def _text_origin_for_centered_bbox(
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    center_x: float,
    center_y: float,
) -> tuple[int, int]:
    return (
        round(center_x - ((left + right) / 2)),
        round(center_y - ((top + bottom) / 2)),
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
    right = left_margin + crop_width
    bottom = top_margin + crop_height
    draw.line((left_margin, top_margin, right, top_margin), fill=line_colour, width=1)
    draw.line((left_margin, bottom, right, bottom), fill=line_colour, width=1)
    draw.line((left_margin, top_margin, left_margin, bottom), fill=line_colour, width=1)
    draw.line((right, top_margin, right, bottom), fill=line_colour, width=1)


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
    draw.line((left, top, right, top), fill=outline, width=1)
    draw.line((left, bottom, right, bottom), fill=outline, width=1)
    draw.line((left, top, left, bottom), fill=outline, width=1)
    draw.line((right, top, right, bottom), fill=outline, width=1)


def _guide_display_edges(
    extraction: GridExtraction,
    *,
    axis: Literal["x", "y"],
    guide_line_mode: GuideLineMode,
    margin: int,
    render_scale: int,
) -> tuple[int, ...]:
    edges = extraction.x_edges if axis == "x" else extraction.y_edges
    if guide_line_mode == "overlay":
        return tuple(margin + (edge * render_scale) for edge in edges)
    return tuple(margin + 1 + (edge * render_scale) + index for index, edge in enumerate(edges))


def _mapped_crop_coordinate_for_separated(
    extraction: GridExtraction,
    coordinate: int,
    *,
    axis: Literal["x", "y"],
    margin: int,
    render_scale: int,
) -> int:
    edges = extraction.x_edges if axis == "x" else extraction.y_edges
    separators_before = sum(1 for edge in edges[1:-1] if edge < coordinate)
    return margin + 1 + (coordinate * render_scale) + separators_before


def _mapped_cell_origin_for_separated(
    extraction: GridExtraction,
    col: int,
    row: int,
    *,
    left_margin: int,
    top_margin: int,
    render_scale: int,
) -> tuple[int, int]:
    return (
        left_margin + 1 + (extraction.x_edges[col] * render_scale) + col,
        top_margin + 1 + (extraction.y_edges[row] * render_scale) + row,
    )


def _grid_span_for_separated(extraction: GridExtraction, *, render_scale: int) -> tuple[int, int]:
    return (
        (extraction.x_edges[-1] * render_scale) + extraction.columns + 1,
        (extraction.y_edges[-1] * render_scale) + extraction.rows + 1,
    )


def render_exact_boundary_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    transparent_grid_surface: bool = False,
    guide_render_scale: int = 1,
    line_colour: RGBA = (218, 206, 185, 180),
    label_colour: RGBA = (218, 206, 185, 255),
) -> Image.Image:
    scaled_size = (crop.width * guide_render_scale, crop.height * guide_render_scale)
    scaled_crop = resize_nearest(crop, scaled_size) if guide_render_scale != 1 else crop
    scaled_relevant_boxes = _scale_rectangles(relevant_boxes, from_size=crop.size, to_size=scaled_size)
    scaled_excluded_boxes = _scale_rectangles(excluded_boxes, from_size=crop.size, to_size=scaled_size)
    chrome = _build_guide_chrome(extraction, render_scale=guide_render_scale)
    layout = _build_guide_canvas_layout(
        content_width=scaled_crop.width,
        content_height=scaled_crop.height,
        chrome=chrome,
    )
    canvas, left_margin, top_margin = _new_guide_canvas(
        layout=layout,
        background=background,
    )
    if transparent_grid_surface:
        _clear_region(
            canvas,
            left=left_margin,
            top=top_margin,
            right=left_margin + scaled_crop.width,
            bottom=top_margin + scaled_crop.height,
        )
    canvas.alpha_composite(scaled_crop, (left_margin, top_margin))
    for left, top, right, bottom in scaled_relevant_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=RELEVANT_FILL_COLOUR,
        )
    for left, top, right, bottom in scaled_excluded_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=EXCLUDED_FILL_COLOUR,
        )
    draw = ImageDraw.Draw(canvas)
    font, _, _, _ = _guide_font_for_extraction(
        extraction,
        target_label_height=chrome.target_label_height,
        render_scale=guide_render_scale,
    )
    for edge in extraction.x_edges:
        x = left_margin + (edge * guide_render_scale)
        draw.line((x, top_margin, x, top_margin + scaled_crop.height), fill=line_colour, width=1)
    for edge in extraction.y_edges:
        y = top_margin + (edge * guide_render_scale)
        draw.line((left_margin, y, left_margin + scaled_crop.width, y), fill=line_colour, width=1)
    _draw_guide_border(
        draw,
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=scaled_crop.width,
        crop_height=scaled_crop.height,
        line_colour=line_colour,
    )
    _draw_guide_labels(
        draw,
        extraction,
        layout=layout,
        render_scale=guide_render_scale,
        guide_line_mode="overlay",
        left_margin=left_margin,
        top_margin=top_margin,
        label_colour=label_colour,
        font=font,
    )
    for left, top, right, bottom in scaled_excluded_boxes:
        _outline_region(
            draw,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            outline=EXCLUDED_OUTLINE_COLOUR,
        )
    return canvas


def render_gutter_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...] = (),
    excluded_boxes: tuple[Rect, ...] = (),
    transparent_grid_surface: bool = False,
    guide_render_scale: int = 1,
    guide_colour: RGBA | None = None,
    label_colour: RGBA = (218, 206, 185, 255),
    guide_line_mode: GuideLineMode = "separated",
) -> Image.Image:
    resolved_guide_colour = guide_colour or _resolve_default_guide_line_colour(
        extraction,
        render_scale=guide_render_scale,
    )
    if guide_line_mode == "separated":
        return _render_gutter_overlay_separated(
            crop=crop,
            extraction=extraction,
            background=background,
            relevant_boxes=relevant_boxes,
            excluded_boxes=excluded_boxes,
            transparent_grid_surface=transparent_grid_surface,
            guide_render_scale=guide_render_scale,
            guide_colour=resolved_guide_colour,
            label_colour=label_colour,
        )
    return _render_gutter_overlay_overlay(
        crop=crop,
        extraction=extraction,
        background=background,
        relevant_boxes=relevant_boxes,
        excluded_boxes=excluded_boxes,
        transparent_grid_surface=transparent_grid_surface,
        guide_render_scale=guide_render_scale,
        guide_colour=resolved_guide_colour,
        label_colour=label_colour,
    )


def _render_gutter_overlay_separated(
    *,
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...],
    excluded_boxes: tuple[Rect, ...],
    transparent_grid_surface: bool,
    guide_render_scale: int,
    guide_colour: RGBA,
    label_colour: RGBA,
) -> Image.Image:
    grid_width, grid_height = _grid_span_for_separated(extraction, render_scale=guide_render_scale)
    chrome = _build_guide_chrome(extraction, render_scale=guide_render_scale)
    layout = _build_guide_canvas_layout(
        content_width=grid_width,
        content_height=grid_height,
        chrome=chrome,
    )
    canvas, left_margin, top_margin = _new_guide_canvas(
        layout=layout,
        background=background,
    )
    if transparent_grid_surface:
        _clear_region(
            canvas,
            left=left_margin,
            top=top_margin,
            right=left_margin + grid_width,
            bottom=top_margin + grid_height,
        )
    for row in range(extraction.rows):
        for col in range(extraction.columns):
            x0 = extraction.x_edges[col]
            x1 = extraction.x_edges[col + 1]
            y0 = extraction.y_edges[row]
            y1 = extraction.y_edges[row + 1]
            cell = crop.crop((x0, y0, x1, y1))
            if guide_render_scale != 1:
                cell = resize_nearest(cell, ((x1 - x0) * guide_render_scale, (y1 - y0) * guide_render_scale))
            cell_left, cell_top = _mapped_cell_origin_for_separated(
                extraction,
                col,
                row,
                left_margin=left_margin,
                top_margin=top_margin,
                render_scale=guide_render_scale,
            )
            canvas.alpha_composite(cell, (cell_left, cell_top))

    for left, top, right, bottom in relevant_boxes:
        mapped_left = _mapped_crop_coordinate_for_separated(
            extraction,
            left,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_top = _mapped_crop_coordinate_for_separated(
            extraction,
            top,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        mapped_right = _mapped_crop_coordinate_for_separated(
            extraction,
            right,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_bottom = _mapped_crop_coordinate_for_separated(
            extraction,
            bottom,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        _fill_region(
            canvas,
            left=mapped_left,
            top=mapped_top,
            right=mapped_right,
            bottom=mapped_bottom,
            fill=RELEVANT_FILL_COLOUR,
        )
    for left, top, right, bottom in excluded_boxes:
        mapped_left = _mapped_crop_coordinate_for_separated(
            extraction,
            left,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_top = _mapped_crop_coordinate_for_separated(
            extraction,
            top,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        mapped_right = _mapped_crop_coordinate_for_separated(
            extraction,
            right,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_bottom = _mapped_crop_coordinate_for_separated(
            extraction,
            bottom,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        _fill_region(
            canvas,
            left=mapped_left,
            top=mapped_top,
            right=mapped_right,
            bottom=mapped_bottom,
            fill=EXCLUDED_FILL_COLOUR,
        )

    draw = ImageDraw.Draw(canvas)
    for col in range(1, extraction.columns):
        edge = extraction.x_edges[col]
        x = left_margin + (edge * guide_render_scale) + col
        draw.line((x, top_margin, x, top_margin + grid_height - 1), fill=guide_colour, width=1)
    for row in range(1, extraction.rows):
        edge = extraction.y_edges[row]
        y = top_margin + (edge * guide_render_scale) + row
        draw.line((left_margin, y, left_margin + grid_width - 1, y), fill=guide_colour, width=1)

    _draw_guide_border(
        draw,
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=grid_width - 1,
        crop_height=grid_height - 1,
        line_colour=guide_colour,
    )
    font, _, _, _ = _guide_font_for_extraction(
        extraction,
        target_label_height=chrome.target_label_height,
        render_scale=guide_render_scale,
    )
    _draw_guide_labels(
        draw,
        extraction,
        layout=layout,
        render_scale=guide_render_scale,
        guide_line_mode="separated",
        left_margin=left_margin,
        top_margin=top_margin,
        label_colour=label_colour,
        font=font,
    )
    for left, top, right, bottom in excluded_boxes:
        mapped_left = _mapped_crop_coordinate_for_separated(
            extraction,
            left,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_top = _mapped_crop_coordinate_for_separated(
            extraction,
            top,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        mapped_right = _mapped_crop_coordinate_for_separated(
            extraction,
            right,
            axis="x",
            margin=left_margin,
            render_scale=guide_render_scale,
        )
        mapped_bottom = _mapped_crop_coordinate_for_separated(
            extraction,
            bottom,
            axis="y",
            margin=top_margin,
            render_scale=guide_render_scale,
        )
        _outline_region(
            draw,
            left=mapped_left,
            top=mapped_top,
            right=mapped_right,
            bottom=mapped_bottom,
            outline=EXCLUDED_OUTLINE_COLOUR,
        )
    return canvas


def _render_gutter_overlay_overlay(
    *,
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    relevant_boxes: tuple[Rect, ...],
    excluded_boxes: tuple[Rect, ...],
    transparent_grid_surface: bool,
    guide_render_scale: int,
    guide_colour: RGBA,
    label_colour: RGBA,
) -> Image.Image:
    content_box = extraction.transform.content_box
    scaled_size = (crop.width * guide_render_scale, crop.height * guide_render_scale)
    scaled_crop = resize_nearest(crop, scaled_size) if guide_render_scale != 1 else crop
    scaled_relevant_boxes = _scale_rectangles(relevant_boxes, from_size=crop.size, to_size=scaled_size)
    scaled_excluded_boxes = _scale_rectangles(excluded_boxes, from_size=crop.size, to_size=scaled_size)
    chrome = _build_guide_chrome(extraction, render_scale=guide_render_scale)
    layout = _build_guide_canvas_layout(
        content_width=scaled_crop.width,
        content_height=scaled_crop.height,
        chrome=chrome,
    )
    canvas, left_margin, top_margin = _new_guide_canvas(
        layout=layout,
        background=background,
    )
    if transparent_grid_surface:
        _clear_region(
            canvas,
            left=left_margin,
            top=top_margin,
            right=left_margin + scaled_crop.width,
            bottom=top_margin + scaled_crop.height,
        )
    canvas.alpha_composite(scaled_crop, (left_margin, top_margin))
    for left, top, right, bottom in scaled_relevant_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=RELEVANT_FILL_COLOUR,
        )
    for left, top, right, bottom in scaled_excluded_boxes:
        _fill_region(
            canvas,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            fill=EXCLUDED_FILL_COLOUR,
        )
    line_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(line_layer)
    if content_box is None:
        gutter = extraction.transform.gutter_size * guide_render_scale
        for col in range(extraction.columns):
            cell_width = (extraction.x_edges[col + 1] - extraction.x_edges[col]) * guide_render_scale
            x = left_margin + (extraction.x_edges[col] * guide_render_scale) + max(0, cell_width - gutter)
            draw.line((x, top_margin, x, top_margin + scaled_crop.height), fill=guide_colour, width=1)
        for row in range(extraction.rows):
            y = top_margin + (extraction.y_edges[row] * guide_render_scale) + max(0, gutter - 1)
            draw.line((left_margin, y, left_margin + scaled_crop.width, y), fill=guide_colour, width=1)
    else:
        for col in range(extraction.columns):
            cell_width = extraction.x_edges[col + 1] - extraction.x_edges[col]
            vertical_offsets, _ = _content_box_edge_offsets(
                cell_extent=cell_width,
                tile_size=extraction.transform.tile_size,
                content_box=content_box,
                axis="x",
            )
            for offset in vertical_offsets:
                x = left_margin + (extraction.x_edges[col] * guide_render_scale) + (offset * guide_render_scale)
                draw.line((x, top_margin, x, top_margin + scaled_crop.height), fill=guide_colour, width=1)
        for row in range(extraction.rows):
            cell_height = extraction.y_edges[row + 1] - extraction.y_edges[row]
            _, horizontal_offsets = _content_box_edge_offsets(
                cell_extent=cell_height,
                tile_size=extraction.transform.tile_size,
                content_box=content_box,
                axis="y",
            )
            for offset in horizontal_offsets:
                y = top_margin + (extraction.y_edges[row] * guide_render_scale) + (offset * guide_render_scale)
                draw.line((left_margin, y, left_margin + scaled_crop.width, y), fill=guide_colour, width=1)
    canvas.alpha_composite(line_layer)
    draw = ImageDraw.Draw(canvas)
    font, _, _, _ = _guide_font_for_extraction(
        extraction,
        target_label_height=chrome.target_label_height,
        render_scale=guide_render_scale,
    )
    _draw_guide_border(
        draw,
        left_margin=left_margin,
        top_margin=top_margin,
        crop_width=scaled_crop.width,
        crop_height=scaled_crop.height,
        line_colour=guide_colour,
    )
    _draw_guide_labels(
        draw,
        extraction,
        layout=layout,
        render_scale=guide_render_scale,
        guide_line_mode="overlay",
        left_margin=left_margin,
        top_margin=top_margin,
        label_colour=label_colour,
        font=font,
    )
    for left, top, right, bottom in scaled_excluded_boxes:
        _outline_region(
            draw,
            left=left_margin + left,
            top=top_margin + top,
            right=left_margin + right,
            bottom=top_margin + bottom,
            outline=EXCLUDED_OUTLINE_COLOUR,
        )
    return canvas


def render_zoom(
    canvas: Image.Image,
    extraction: GridExtraction,
    cell: tuple[int, int],
    *,
    guide_line_mode: GuideLineMode,
    guide_render_scale: int = 1,
) -> Image.Image:
    col, row = cell
    if not (0 <= col < extraction.columns and 0 <= row < extraction.rows):
        raise ValueError("zoom cell lies outside the extracted grid")
    chrome = _build_guide_chrome(extraction, render_scale=guide_render_scale)
    left_margin = chrome.margin
    top_margin = chrome.margin
    if guide_line_mode == "separated":
        cell_left, cell_top = _mapped_cell_origin_for_separated(
            extraction,
            col,
            row,
            left_margin=left_margin,
            top_margin=top_margin,
            render_scale=guide_render_scale,
        )
        cell_width = (extraction.x_edges[col + 1] - extraction.x_edges[col]) * guide_render_scale
        cell_height = (extraction.y_edges[row + 1] - extraction.y_edges[row]) * guide_render_scale
        x0 = cell_left
        y0 = cell_top
        x1 = cell_left + cell_width
        y1 = cell_top + cell_height
    else:
        cell_width = (extraction.x_edges[col + 1] - extraction.x_edges[col]) * guide_render_scale
        cell_height = (extraction.y_edges[row + 1] - extraction.y_edges[row]) * guide_render_scale
        x0 = left_margin + (extraction.x_edges[col] * guide_render_scale)
        y0 = top_margin + (extraction.y_edges[row] * guide_render_scale)
        x1 = left_margin + (extraction.x_edges[col + 1] * guide_render_scale)
        y1 = top_margin + (extraction.y_edges[row + 1] * guide_render_scale)
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

    if settings.emit_recovered_tile_sheet:
        recovered_tile_crop, recovered_tile_extraction = _crop_and_extraction_for_recovered_tile_grid(
            tile_grid,
            background=background,
        )
        recovered_tile_sheet = render_gutter_overlay(
            recovered_tile_crop,
            recovered_tile_extraction,
            background,
            guide_render_scale=settings.recovered_tile_scale,
            guide_line_mode="separated",
        )
        recovered_tile_path = settings.output_dir / f"{settings.prefix}_recovered_tile_sheet.png"
        recovered_tile_sheet.save(recovered_tile_path)
        outputs.append(recovered_tile_path)

    exact_overlay = render_exact_boundary_overlay(
        prepared_for_outputs.crop,
        prepared_for_outputs.extraction,
        background,
        relevant_boxes=prepared_for_outputs.relevant_boxes,
        excluded_boxes=prepared_for_outputs.excluded_boxes,
        transparent_grid_surface=settings.transparent_grid_surface,
        guide_render_scale=settings.guide_render_scale,
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
        transparent_grid_surface=settings.transparent_grid_surface,
        guide_render_scale=settings.guide_render_scale,
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
            guide_render_scale=settings.guide_render_scale,
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
