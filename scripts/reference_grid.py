from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, ImageColor, ImageDraw, ImageFont


RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class GridTransform:
    origin_x: int
    origin_y: int
    cell_size: int
    tile_size: int = 8

    @property
    def gutter_size(self) -> int:
        return max(1, round(self.cell_size / self.tile_size))


@dataclass(frozen=True)
class GridExtraction:
    transform: GridTransform
    columns: int
    rows: int
    crop_box: tuple[int, int, int, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a rendered reference image onto a stable tile grid, then emit "
            "cropped, contact-sheet, and guide-overlay views."
        )
    )
    parser.add_argument("--image", type=Path, required=True, help="Reference image to slice.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated outputs.")
    parser.add_argument("--prefix", required=True, help="Filename prefix for generated outputs.")
    parser.add_argument("--origin-x", type=int, required=True, help="Render-space x origin of the tile grid.")
    parser.add_argument("--origin-y", type=int, required=True, help="Render-space y origin of the tile grid.")
    parser.add_argument("--cell-size", type=int, required=True, help="Render-space tile size in pixels.")
    parser.add_argument("--tile-size", type=int, default=8, help="Base tile size to recover. Defaults to 8.")
    parser.add_argument("--cols", type=int, help="Optional column count override.")
    parser.add_argument("--rows", type=int, help="Optional row count override.")
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


def compute_extraction(
    image_size: tuple[int, int],
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
) -> GridExtraction:
    width, height = image_size
    if transform.cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if transform.tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if transform.origin_x < 0 or transform.origin_y < 0:
        raise ValueError("grid origin must be non-negative")
    if transform.origin_x >= width or transform.origin_y >= height:
        raise ValueError("grid origin lies outside the reference image")

    max_cols = (width - transform.origin_x) // transform.cell_size
    max_rows = (height - transform.origin_y) // transform.cell_size
    if max_cols <= 0 or max_rows <= 0:
        raise ValueError("grid transform does not leave any full cells inside the image")

    resolved_cols = max_cols if cols is None else cols
    resolved_rows = max_rows if rows is None else rows
    if resolved_cols <= 0 or resolved_rows <= 0:
        raise ValueError("resolved grid dimensions must be positive")
    if resolved_cols > max_cols or resolved_rows > max_rows:
        raise ValueError("requested grid dimensions exceed the available full-cell crop")

    x0 = transform.origin_x
    y0 = transform.origin_y
    x1 = x0 + resolved_cols * transform.cell_size
    y1 = y0 + resolved_rows * transform.cell_size
    return GridExtraction(
        transform=transform,
        columns=resolved_cols,
        rows=resolved_rows,
        crop_box=(x0, y0, x1, y1),
    )


def resolve_background(image: Image.Image, background: str | None) -> RGBA:
    if background is None:
        return cast(RGBA, image.convert("RGBA").getpixel((0, 0)))
    return cast(RGBA, ImageColor.getcolor(background, "RGBA"))


def extract_crop(image: Image.Image, extraction: GridExtraction) -> Image.Image:
    return image.crop(extraction.crop_box)


def resize_nearest(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.NEAREST)  # pyright: ignore[reportUnknownMemberType]


def recover_base_tile(cell_image: Image.Image, tile_size: int) -> Image.Image:
    rgba = cell_image.convert("RGBA")
    if rgba.width != rgba.height:
        raise ValueError("cell images must be square")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if rgba.width % tile_size == 0:
        step = rgba.width // tile_size
        out = Image.new("RGBA", (tile_size, tile_size))
        for y in range(tile_size):
            for x in range(tile_size):
                out.putpixel((x, y), cast(RGBA, rgba.getpixel((x * step, y * step))))
        return out
    return resize_nearest(rgba, (tile_size, tile_size))


def build_tile_grid(crop: Image.Image, extraction: GridExtraction) -> list[list[Image.Image]]:
    cell_size = extraction.transform.cell_size
    tile_size = extraction.transform.tile_size
    grid: list[list[Image.Image]] = []
    for row in range(extraction.rows):
        row_tiles: list[Image.Image] = []
        for col in range(extraction.columns):
            x = col * cell_size
            y = row * cell_size
            cell = crop.crop((x, y, x + cell_size, y + cell_size))
            row_tiles.append(recover_base_tile(cell, tile_size))
        grid.append(row_tiles)
    return grid


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
        x = left_margin + pad + col * (tile_size * scale + pad) + (tile_size * scale // 2) - 6
        draw.text((x, 6), str(col), fill=label_colour, font=font)
    for row in range(rows):
        y = top_margin + pad + row * (tile_size * scale + pad) + (tile_size * scale // 2) - 4
        draw.text((6, y), str(row), fill=label_colour, font=font)
    for row_index, row_tiles in enumerate(tile_grid):
        for col_index, tile in enumerate(row_tiles):
            x = left_margin + pad + col_index * (tile_size * scale + pad)
            y = top_margin + pad + row_index * (tile_size * scale + pad)
            scaled_tile = resize_nearest(tile, (tile_size * scale, tile_size * scale))
            canvas.alpha_composite(scaled_tile, (x, y))
    return canvas


def render_exact_boundary_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    line_colour: RGBA = (218, 206, 185, 180),
    label_colour: RGBA = (218, 206, 185, 255),
) -> Image.Image:
    left_margin = 36
    top_margin = 24
    canvas = Image.new("RGBA", (left_margin + crop.width + 1, top_margin + crop.height + 1), background)
    canvas.alpha_composite(crop, (left_margin, top_margin))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    cell_size = extraction.transform.cell_size
    for col in range(extraction.columns + 1):
        x = left_margin + col * cell_size
        draw.line((x, top_margin, x, top_margin + crop.height), fill=line_colour, width=1)
    for row in range(extraction.rows + 1):
        y = top_margin + row * cell_size
        draw.line((left_margin, y, left_margin + crop.width, y), fill=line_colour, width=1)
    for col in range(extraction.columns):
        x = left_margin + col * cell_size + (cell_size // 2) - 6
        draw.text((x, 5), str(col), fill=label_colour, font=font)
    for row in range(extraction.rows):
        y = top_margin + row * cell_size + (cell_size // 2) - 4
        draw.text((6, y), str(row), fill=label_colour, font=font)
    return canvas


def render_gutter_overlay(
    crop: Image.Image,
    extraction: GridExtraction,
    background: RGBA,
    band_colour: RGBA = (218, 206, 185, 40),
    guide_colour: RGBA = (218, 206, 185, 70),
    label_colour: RGBA = (218, 206, 185, 255),
) -> Image.Image:
    left_margin = 36
    top_margin = 24
    canvas = Image.new("RGBA", (left_margin + crop.width + 1, top_margin + crop.height + 1), background)
    canvas.alpha_composite(crop, (left_margin, top_margin))
    cell_size = extraction.transform.cell_size
    gutter = extraction.transform.gutter_size
    for row in range(extraction.rows):
        for col in range(extraction.columns):
            x = left_margin + col * cell_size
            y = top_margin + row * cell_size
            canvas.alpha_composite(Image.new("RGBA", (cell_size, gutter), band_colour), (x, y))
            canvas.alpha_composite(Image.new("RGBA", (gutter, cell_size), band_colour), (x + cell_size - gutter, y))
    line_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(line_layer)
    for col in range(extraction.columns):
        x = left_margin + col * cell_size + (cell_size - gutter)
        draw.line((x, top_margin, x, top_margin + crop.height), fill=guide_colour, width=1)
    for row in range(extraction.rows):
        y = top_margin + row * cell_size + gutter - 1
        draw.line((left_margin, y, left_margin + crop.width, y), fill=guide_colour, width=1)
    canvas.alpha_composite(line_layer)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for col in range(extraction.columns):
        x = left_margin + col * cell_size + (cell_size // 2) - 6
        draw.text((x, 5), str(col), fill=label_colour, font=font)
    for row in range(extraction.rows):
        y = top_margin + row * cell_size + (cell_size // 2) - 4
        draw.text((6, y), str(row), fill=label_colour, font=font)
    return canvas


def parse_zoom_cell(raw: str | None) -> tuple[int, int] | None:
    if raw is None:
        return None
    col_raw, row_raw = raw.split(",", 1)
    return int(col_raw), int(row_raw)


def render_zoom(canvas: Image.Image, extraction: GridExtraction, cell: tuple[int, int]) -> Image.Image:
    col, row = cell
    if not (0 <= col < extraction.columns and 0 <= row < extraction.rows):
        raise ValueError("zoom cell lies outside the extracted grid")
    left_margin = 36
    top_margin = 24
    pad = extraction.transform.cell_size // 2
    x0 = left_margin + col * extraction.transform.cell_size - pad
    y0 = top_margin + row * extraction.transform.cell_size - pad
    x1 = left_margin + (col + 1) * extraction.transform.cell_size + pad
    y1 = top_margin + (row + 1) * extraction.transform.cell_size + pad
    return resize_nearest(canvas.crop((x0, y0, x1, y1)), (256, 256))


def save_outputs(args: argparse.Namespace) -> list[Path]:
    image = Image.open(args.image).convert("RGBA")
    transform = GridTransform(
        origin_x=args.origin_x,
        origin_y=args.origin_y,
        cell_size=args.cell_size,
        tile_size=args.tile_size,
    )
    extraction = compute_extraction(image.size, transform, cols=args.cols, rows=args.rows)
    background = resolve_background(image, args.background)
    crop = extract_crop(image, extraction)
    tile_grid = build_tile_grid(crop, extraction)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    cropped_path = args.output_dir / f"{args.prefix}_cropped.png"
    crop.save(cropped_path)
    outputs.append(cropped_path)

    contact_sheet = render_contact_sheet(tile_grid, background, scale=args.scale)
    contact_path = args.output_dir / f"{args.prefix}_contact_sheet.png"
    contact_sheet.save(contact_path)
    outputs.append(contact_path)

    exact_overlay = render_exact_boundary_overlay(crop, extraction, background)
    exact_path = args.output_dir / f"{args.prefix}_exact_boundary.png"
    exact_overlay.save(exact_path)
    outputs.append(exact_path)

    gutter_overlay = render_gutter_overlay(crop, extraction, background)
    gutter_path = args.output_dir / f"{args.prefix}_gutter_guides.png"
    gutter_overlay.save(gutter_path)
    outputs.append(gutter_path)

    zoom_cell = parse_zoom_cell(args.zoom_cell)
    if zoom_cell is not None:
        zoom = render_zoom(gutter_overlay, extraction, zoom_cell)
        zoom_path = args.output_dir / f"{args.prefix}_zoom_c{zoom_cell[0]}_r{zoom_cell[1]}.png"
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
