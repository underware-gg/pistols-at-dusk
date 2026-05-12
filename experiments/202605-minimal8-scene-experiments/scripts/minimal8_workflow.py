#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Callable, Sequence, cast

from PIL import Image, ImageDraw


def _image_get_pixels(image: Image.Image) -> Sequence[object]:
    return cast(Callable[[], Sequence[object]], getattr(image, "getdata"))()


def _image_put_pixels(image: Image.Image, pixels: Sequence[object]) -> None:
    cast(Callable[[Sequence[object]], None], getattr(image, "putdata"))(pixels)


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"Could not find repo root from {start}")


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
ROOT = find_repo_root(EXPERIMENT_ROOT)
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tile_families import SourceLayoutIngestion, TileFamily, TileRecord


def _resize_nearest(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    resize = cast(Callable[[tuple[int, int], int], Image.Image], getattr(image, "resize"))
    return resize(size, Image.Resampling.NEAREST)


def _require_source_layout(catalog: TileFamily) -> SourceLayoutIngestion:
    if catalog.source_layout is None:
        raise RuntimeError(f"Tile family {catalog.family_id!r} does not define a source layout")
    return catalog.source_layout

MINIMAL8_FAMILY_DIR = ROOT / "prototypes/minimal8-harness/tile-families/minimal8"
MINIMAL8_VARIANT_ID = "1bit_colored_bg"
WORK_DIR = EXPERIMENT_ROOT / "scratch.local" / "mockups" / "minimal8"
GENERATED_DIR = EXPERIMENT_ROOT / "generated" / "mockups"

BASE_W = 192
BASE_H = 144
EXPORT_SCALE = 4


PLUM = "#24192A"
CREAM = "#F6C37C"
GOLD = "#FFD731"
AMBER = "#EDA41E"
ORANGE = "#F28C3A"
VERMILION = "#DC6250"
BRICK = "#A83737"
SLATE_TEAL = "#5B9D98"
FOREST = "#32A458"
BOTTLE = "#10331B"
MIDNIGHT = "#1C1335"
BLACK_TEAL = "#102728"
PURE_BLACK = "#000000"
DEEP_VIOLET = "#473087"
SKY = "#5A8BDE"
PALE_GREEN = "#82CE63"
BURNT = "#3E150A"
PALE_BLUE = "#B5C8DB"
LINE_BLUE = "#A9D8E8"


def next_generated_path(filename: str) -> Path:
    path = GENERATED_DIR / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    revision = 2
    while True:
        candidate = GENERATED_DIR / f"{stem}-r{revision}{suffix}"
        if not candidate.exists():
            return candidate
        revision += 1


def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red, green, blue, alpha


@dataclass(frozen=True)
class Crop:
    left: int
    top: int
    right: int
    bottom: int


@cache
def _get_catalog() -> TileFamily:
    return TileFamily.load(MINIMAL8_FAMILY_DIR)


def _get_variant_sheet_path() -> Path:
    return _get_catalog().variant(MINIMAL8_VARIANT_ID).sheet_path


class Minimal8:
    def __init__(self) -> None:
        self.catalog = _get_catalog()
        self.sheet = Image.open(_get_variant_sheet_path()).convert("RGBA")
        self.background: tuple[int, int, int, int] = cast(
            tuple[int, int, int, int], self.sheet.getpixel((0, 0))
        )

    def region_crop(self, region_name: str) -> Crop:
        region = _require_source_layout(self.catalog).source_regions[region_name]
        return Crop(
            left=region.bounds.x * 8,
            top=region.bounds.y * 8,
            right=(region.bounds.x + region.bounds.width) * 8,
            bottom=(region.bounds.y + region.bounds.height) * 8,
        )

    def transparent_crop(self, crop: Crop) -> Image.Image:
        image = self.sheet.crop((crop.left, crop.top, crop.right, crop.bottom)).convert("RGBA")
        _image_put_pixels(
            image,
            [(0, 0, 0, 0) if px == self.background else px for px in _image_get_pixels(image)],
        )
        return image

    def raw_region_cell(self, region_name: str, cell_x: int, cell_y: int, cells_w: int = 1, cells_h: int = 1) -> Image.Image:
        region = self.region_crop(region_name)
        left = region.left + cell_x * 8
        top = region.top + cell_y * 8
        right = left + cells_w * 8
        bottom = top + cells_h * 8
        return self.sheet.crop((left, top, right, bottom)).convert("RGBA")

    def transparent_region_cell(self, region_name: str, cell_x: int, cell_y: int, cells_w: int = 1, cells_h: int = 1) -> Image.Image:
        image = self.raw_region_cell(region_name, cell_x, cell_y, cells_w, cells_h)
        _image_put_pixels(
            image,
            [(0, 0, 0, 0) if px == self.background else px for px in _image_get_pixels(image)],
        )
        return image

    def source_region_names(self) -> tuple[str, ...]:
        return tuple(_require_source_layout(self.catalog).source_regions.keys())

    def region_cell_for_tile(self, tile: TileRecord) -> tuple[str, int, int]:
        if tile.sheet_col is None or tile.sheet_row is None:
            raise ValueError(f"Tile {tile.id!r} is not backed by a sheet cell")
        source_region = _require_source_layout(self.catalog).source_region_for_cell(tile.sheet_col, tile.sheet_row)
        if source_region is None:
            raise ValueError(f"Tile {tile.id!r} does not map to a source region")
        return (
            source_region.id,
            tile.sheet_col - source_region.bounds.x,
            tile.sheet_row - source_region.bounds.y,
        )


ASSETS: dict[str, Crop] = {
    "meander_strip": Crop(18, 33, 118, 50),
    "maze_wall": Crop(18, 33, 118, 88),
    "door_arch": Crop(18, 88, 49, 111),
    "small_door": Crop(74, 88, 95, 111),
    "teal_floor": Crop(48, 121, 87, 143),
    "brick_floor": Crop(18, 121, 44, 143),
    "hills": Crop(18, 143, 87, 167),
    "shrub_field": Crop(153, 81, 262, 127),
    "water_lines": Crop(154, 72, 192, 79),
    "void_shapes": Crop(200, 72, 262, 88),
    "mini_buildings": Crop(18, 257, 69, 287),
    "grid_border": Crop(18, 169, 61, 184),
    "green_symbols": Crop(153, 33, 242, 58),
    "dots_and_ornament": Crop(153, 59, 278, 95),
    "char_green": Crop(300, 81, 316, 97),
    "char_teal": Crop(300, 65, 316, 81),
    "char_purple": Crop(324, 81, 340, 97),
    "char_red": Crop(396, 65, 412, 81),
    "char_bartender": Crop(348, 49, 364, 65),
    "char_orange": Crop(348, 49, 364, 65),
    "char_blue": Crop(372, 97, 388, 113),
    "char_yellow": Crop(364, 97, 380, 113),
    "monster_green": Crop(412, 97, 428, 113),
}


HUD_GUIDE_PATH = WORK_DIR / "reference-gold-box-hud-room-base.png"
TEMPLE_GUIDE_PATH = WORK_DIR / "reference-polykromia-temple-composition-base.png"


def paste(canvas: Image.Image, sprite: Image.Image, xy: tuple[int, int], scale: int = 1) -> None:
    if scale != 1:
        sprite = _resize_nearest(sprite, (sprite.width * scale, sprite.height * scale))
    canvas.alpha_composite(sprite, xy)


def draw_frame(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, color: tuple[int, int, int, int]) -> None:
    draw.rectangle((x, y, x + w - 1, y + h - 1), outline=color)
    for dx, dy in ((2, 0), (0, 2), (w - 3, 0), (w - 1, 2), (0, h - 3), (2, h - 1), (w - 3, h - 1), (w - 1, h - 3)):
        draw.point((x + dx, y + dy), fill=color)


TINY_FONT: dict[str, tuple[str, ...]] = {
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "100", "100"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    ".": ("0", "0", "0", "0", "1"),
    ":": ("0", "1", "0", "1", "0"),
    "-": ("0", "0", "1", "0", "0"),
    "+": ("0", "1", "1", "1", "0"),
    "[": ("11", "10", "10", "10", "11"),
    "]": ("11", "01", "01", "01", "11"),
    "/": ("001", "001", "010", "100", "100"),
    " ": ("0", "0", "0", "0", "0"),
}


def draw_bitmap_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int, int],
    *,
    scale: int = 1,
    spacing: int = 1,
) -> int:
    cursor = x
    for raw_char in text.upper():
        glyph = TINY_FONT.get(raw_char, TINY_FONT[" "])
        width = len(glyph[0])
        for gy, row in enumerate(glyph):
            for gx, value in enumerate(row):
                if value != "1":
                    continue
                draw.rectangle(
                    (
                        cursor + gx * scale,
                        y + gy * scale,
                        cursor + gx * scale + scale - 1,
                        y + gy * scale + scale - 1,
                    ),
                    fill=color,
                )
        cursor += width * scale + spacing
    return cursor


def draw_dotted_floor(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    step_x: int = 6,
    step_y: int = 6,
    color: tuple[int, int, int, int],
) -> None:
    for yy in range(y, y + h, step_y):
        for xx in range(x, x + w, step_x):
            draw.point((xx, yy), fill=color)


def draw_meander_tile(draw: ImageDraw.ImageDraw, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    draw.rectangle((x, y, x + 7, y + 7), outline=color)
    draw.line((x + 4, y + 1, x + 4, y + 4), fill=color)
    draw.line((x + 2, y + 3, x + 4, y + 3), fill=color)
    draw.line((x + 2, y + 3, x + 2, y + 6), fill=color)
    draw.line((x + 2, y + 6, x + 6, y + 6), fill=color)


def draw_meander_band(draw: ImageDraw.ImageDraw, x: int, y: int, tiles: int, color: tuple[int, int, int, int]) -> None:
    for index in range(tiles):
        draw_meander_tile(draw, x + index * 8, y, color)


def draw_torch(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.line((x + 1, y + 1, x + 1, y + 6), fill=rgba(VERMILION))
    draw.rectangle((x, y + 2, x + 2, y + 5), outline=rgba(VERMILION))
    draw.point((x + 1, y), fill=rgba(GOLD))
    draw.point((x, y + 1), fill=rgba(AMBER))
    draw.point((x + 2, y + 1), fill=rgba(AMBER))


def draw_health_meter(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    total: int,
    filled: int,
    fill_color: tuple[int, int, int, int],
    empty_color: tuple[int, int, int, int],
    segment_w: int = 4,
    segment_h: int = 4,
    gap: int = 2,
) -> None:
    for index in range(total):
        left = x + index * (segment_w + gap)
        color = fill_color if index < filled else empty_color
        draw.rectangle((left, y, left + segment_w - 1, y + segment_h - 1), outline=color, fill=color if index < filled else None)


def draw_red_baseline(draw: ImageDraw.ImageDraw, x: int, y: int, width: int = 8) -> None:
    draw.line((x, y, x + width - 1, y), fill=rgba(VERMILION))


def draw_stone_bank(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    rows: tuple[tuple[int, int], ...],
    color: tuple[int, int, int, int],
) -> None:
    for row_index, (offset, width) in enumerate(rows):
        yy = y + row_index * 6
        for xx in range(x + offset, x + offset + width, 6):
            draw.rectangle((xx, yy, xx + 5, yy + 5), fill=color)
            draw.point((xx + 2, yy + 2), fill=rgba(PLUM))


def draw_water_band(draw: ImageDraw.ImageDraw, x: int, y: int, width: int) -> None:
    for row in range(0, 14, 4):
        for xx in range(x, x + width, 8):
            draw.line((xx, y + row, min(xx + 5, x + width - 1), y + row), fill=rgba(SKY))


def draw_temple_path(draw: ImageDraw.ImageDraw, x: int, y: int, height: int) -> None:
    for offset in range(0, height, 8):
        draw.point((x, y + offset), fill=rgba(PALE_GREEN))
        draw.point((x + 4, y + offset + 2), fill=rgba(PALE_GREEN))


def nearest_palette_color(
    pixel: tuple[int, int, int, int],
    palette: tuple[tuple[int, int, int, int], ...],
) -> tuple[int, int, int, int]:
    if len(pixel) == 4 and pixel[3] == 0:
        return pixel
    pr, pg, pb = pixel[:3]
    return min(
        palette,
        key=lambda candidate: (candidate[0] - pr) ** 2 + (candidate[1] - pg) ** 2 + (candidate[2] - pb) ** 2,
    )


def normalise_guide(
    guide_path: Path,
    palette: tuple[tuple[int, int, int, int], ...],
) -> Image.Image:
    guide = Image.open(guide_path).convert("RGBA")
    output = Image.new("RGBA", guide.size, (0, 0, 0, 0))
    _image_put_pixels(
        output,
        [
            nearest_palette_color(cast(tuple[int, int, int, int], pixel), palette)
            for pixel in _image_get_pixels(guide)
        ],
    )
    return output


def remap_exact_colors(
    image: Image.Image,
    mapping: dict[tuple[int, int, int, int], tuple[int, int, int, int]],
) -> Image.Image:
    output = image.copy()
    _image_put_pixels(
        output,
        [
            mapping.get(cast(tuple[int, int, int, int], pixel), cast(tuple[int, int, int, int], pixel))
            for pixel in _image_get_pixels(output)
        ],
    )
    return output


def spotlight(image: Image.Image, center: tuple[int, int], radius: int, color_hex: str = AMBER, strength: int = 120) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for r in range(radius, 0, -3):
        alpha = int(strength * (r / radius) * 0.22)
        draw.ellipse((center[0] - r, center[1] - r, center[0] + r, center[1] + r), fill=rgba(color_hex, alpha))
    return Image.alpha_composite(image, overlay)


def export_atlas() -> None:
    tiles = Minimal8()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for name in tiles.source_region_names():
        crop = tiles.region_crop(name)
        image = tiles.transparent_crop(crop)
        image = _resize_nearest(image, (image.width * 8, image.height * 8))
        draw = ImageDraw.Draw(image)
        for x in range(0, crop.right - crop.left + 1, 8):
            sx = x * 8
            draw.line((sx, 0, sx, image.height), fill=(255, 255, 255, 64), width=1)
            draw.text((sx + 1, 1), str(x), fill=(255, 255, 255, 255))
        for y in range(0, crop.bottom - crop.top + 1, 8):
            sy = y * 8
            draw.line((0, sy, image.width, sy), fill=(255, 255, 255, 64), width=1)
            draw.text((1, sy + 1), str(y), fill=(255, 255, 255, 255))
        image.save(WORK_DIR / f"{name}-grid-8x.png")

    atlas = Image.new("RGBA", (1600, 1100), (24, 24, 24, 255))
    positions = {
        "architecture": (16, 16),
        "terrain": (640, 16),
        "characters": (1120, 16),
        "ui": (1120, 520),
        "icons": (640, 640),
    }
    for name in tiles.source_region_names():
        image = Image.open(WORK_DIR / f"{name}-grid-8x.png").convert("RGBA")
        atlas.alpha_composite(image, positions[name])
    atlas.save(WORK_DIR / "atlas-overview.png")


def render_underworld_v2() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    image = Image.new("RGBA", (BASE_W, BASE_H), rgba(MIDNIGHT))
    draw = ImageDraw.Draw(image)

    # top border
    strip = sprites["meander_strip"]
    x = 0
    while x < BASE_W:
        chunk = strip.crop((0, 0, min(strip.width, BASE_W - x), strip.height))
        paste(image, chunk, (x, 0))
        x += chunk.width

    # side void channels and water
    for y in range(16, 136, 8):
        draw.rectangle((0, y, 29, y + 7), fill=rgba(BLACK_TEAL))
        draw.rectangle((162, y, 191, y + 7), fill=rgba(BLACK_TEAL))
        paste(image, sprites["water_lines"], (0, y))
        paste(image, sprites["water_lines"], (154, y))

    # upper green / violet intrusion band
    paste(image, sprites["green_symbols"], (0, 16))
    paste(image, sprites["green_symbols"], (103, 16))
    paste(image, sprites["dots_and_ornament"], (12, 28))
    paste(image, sprites["dots_and_ornament"], (118, 28))

    # central sanctuary
    draw_frame(draw, 44, 24, 104, 88, rgba(CREAM))
    draw_frame(draw, 52, 32, 88, 64, rgba(SLATE_TEAL))

    paste(image, sprites["maze_wall"].crop((0, 0, 76, 42)), (58, 34))
    paste(image, sprites["door_arch"], (80, 44))

    # lanterns
    for lx in (74, 116):
        draw.rectangle((lx, 50, lx + 3, 54), fill=rgba(AMBER))
        draw.point((lx + 1, 48), fill=rgba(GOLD))

    # floor and pillars
    for yy in range(68, 100, 8):
        for xx in range(64, 128, 8):
            draw.point((xx, yy), fill=rgba(CREAM, 180))
    draw.rectangle((64, 78, 72, 86), outline=rgba(FOREST))
    draw.rectangle((120, 78, 128, 86), outline=rgba(FOREST))

    # descent steps
    for i in range(5):
        draw.line((84 - i * 2, 112 + i * 4, 108 + i * 2, 112 + i * 4), fill=rgba(CREAM if i < 2 else SLATE_TEAL))

    # actors
    paste(image, sprites["char_green"], (88, 74))
    paste(image, sprites["char_red"], (92, 58))
    paste(image, sprites["char_purple"], (120, 62))

    # bartender-only hint: tiny gold + violet pairing, isolated
    for i in range(3):
        draw.point((142 + i, 30), fill=rgba(GOLD))
        draw.point((142 + i, 32), fill=rgba(DEEP_VIOLET))

    # lower ceremonial plaque
    draw_frame(draw, 54, 120, 84, 16, rgba(CREAM))
    draw.line((70, 126, 122, 126), fill=rgba(SLATE_TEAL))
    draw.line((76, 130, 116, 130), fill=rgba(SLATE_TEAL))

    image = spotlight(image, (96, 82), 22, AMBER, 160)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-underworld-lantern-descent-v2.png")
    _resize_nearest(image, (BASE_W * EXPORT_SCALE, BASE_H * EXPORT_SCALE)).save(output)
    return output


def render_tavern_v2() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    image = Image.new("RGBA", (BASE_W, BASE_H), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    strip = sprites["meander_strip"]
    x = 0
    while x < BASE_W:
        chunk = strip.crop((0, 0, min(strip.width, BASE_W - x), strip.height))
        paste(image, chunk, (x, 0))
        x += chunk.width

    # Back wall and bar recess.
    paste(image, sprites["maze_wall"].crop((0, 0, 90, 46)), (8, 10))
    paste(image, sprites["maze_wall"].crop((10, 8, 88, 42)), (104, 12))
    paste(image, sprites["door_arch"], (82, 12))
    paste(image, sprites["small_door"], (146, 22))

    # Wall lamps and shelves.
    for lx in (28, 134):
        draw.rectangle((lx, 18, lx + 3, 23), fill=rgba(VERMILION))
        draw.rectangle((lx + 1, 16, lx + 2, 17), fill=rgba(AMBER))
    for sx in (24, 40, 56):
        draw.rectangle((sx, 34, sx + 10, 36), fill=rgba(CREAM))
    for bx, color in ((26, FOREST), (32, SKY), (42, VERMILION), (58, AMBER)):
        draw.rectangle((bx, 30, bx + 2, 33), fill=rgba(color))

    # Bar and room floor.
    draw.rectangle((18, 50, 114, 56), fill=rgba(ORANGE))
    draw.rectangle((18, 56, 114, 60), fill=rgba(BRICK))
    draw.rectangle((0, 60, BASE_W, 96), fill=rgba(PLUM))
    for yy in range(64, 96, 8):
        for xx in range(4, BASE_W, 8):
            draw.point((xx, yy), fill=rgba(SLATE_TEAL, 160))

    # Furniture.
    for tx in (10, 146):
        draw.rectangle((tx, 80, tx + 6, 84), outline=rgba(CREAM))
        draw.point((tx + 3, 86), fill=rgba(CREAM))
    draw.rectangle((130, 76, 136, 82), outline=rgba(CREAM))
    draw.rectangle((8, 78, 14, 84), outline=rgba(CREAM))

    # Characters.
    paste(image, sprites["char_bartender"], (54, 40))
    paste(image, sprites["char_green"], (30, 66))
    paste(image, sprites["char_red"], (82, 68))
    paste(image, sprites["char_teal"], (146, 66))
    paste(image, sprites["char_purple"], (120, 48))
    for fx in (34, 86, 150, 124, 58):
        draw.line((fx, 84, fx + 7, 84), fill=rgba(VERMILION))

    image = spotlight(image, (58, 46), 12, AMBER, 140)
    draw = ImageDraw.Draw(image)

    # HUD panels.
    draw_frame(draw, 118, 4, 68, 20, rgba(CREAM))
    draw_frame(draw, 2, 100, 88, 40, rgba(CREAM))
    draw_frame(draw, 100, 100, 90, 40, rgba(CREAM))
    for i in range(5):
        draw.rectangle((126 + i * 6, 12, 129 + i * 6, 15), fill=rgba(VERMILION if i < 4 else SLATE_TEAL))
    paste(image, sprites["char_green"], (8, 112))
    for i in range(6):
        draw.rectangle((38 + i * 8, 116, 43 + i * 8, 121), outline=rgba(PALE_GREEN if i < 5 else BLACK_TEAL))
    for i in range(5):
        draw.rectangle((38 + i * 6, 126, 41 + i * 6, 133), fill=rgba(VERMILION if i < 4 else SLATE_TEAL))
    for offset in (0, 5, 10):
        draw.line((108, 108 + offset, 176, 108 + offset), fill=rgba(AMBER if offset == 0 else CREAM, 240 if offset == 0 else 180))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-fool-and-flintlock-v2.png")
    _resize_nearest(image, (BASE_W * EXPORT_SCALE, BASE_H * EXPORT_SCALE)).save(output)
    return output


def render_reference_temple_study_v1() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width, height = 160, 128
    image = Image.new("RGBA", (width, height), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    # outer green border rhythm
    border = sprites["green_symbols"].crop((0, 0, 64, 24))
    for x in range(0, width, border.width):
        paste(image, border.crop((0, 0, min(border.width, width - x), border.height)), (x, 18))
    for y in range(18, height, 24):
        paste(image, sprites["green_symbols"].crop((0, 0, 16, 24)), (0, y))
        paste(image, sprites["green_symbols"].crop((0, 0, 16, 24)), (width - 16, y))

    # side rock masses
    rock_fill = rgba("#C6D4E3")
    for side in ("left", "right"):
        x0 = 10 if side == "left" else width - 50
        sign = 1 if side == "left" else -1
        for i in range(4):
            y = 34 + i * 18
            w = 34 - i * 2
            h = 16
            draw.rounded_rectangle if False else None
            draw.ellipse((x0 + sign * (i * 2), y, x0 + sign * (i * 2) + w, y + h), fill=rock_fill)
        for i in range(3):
            y = 86 + i * 14
            w = 28 - i * 2
            draw.ellipse((x0 + sign * (i * 4), y, x0 + sign * (i * 4) + w, y + 12), fill=rock_fill)

    # water channels
    for x in (12, width - 50):
        for y in range(54, height - 8, 10):
            paste(image, sprites["water_lines"], (x, y))

    # central temple / court
    draw_frame(draw, 46, 24, 68, 74, rgba(CREAM))
    draw_frame(draw, 52, 48, 56, 44, rgba(CREAM))
    paste(image, sprites["maze_wall"].crop((0, 0, 60, 18)), (50, 24))
    paste(image, sprites["maze_wall"].crop((0, 18, 60, 36)), (50, 34))
    paste(image, sprites["door_arch"], (72, 42))
    draw.rectangle((77, 42, 83, 44), fill=rgba(PLUM))

    # torches
    for tx in (68, 90):
        draw.rectangle((tx, 46, tx + 2, 49), fill=rgba(AMBER))
        draw.point((tx + 1, 45), fill=rgba(GOLD))

    # court floor and plinths
    for yy in range(58, 96, 4):
        for xx in range(58, 104, 4):
            draw.point((xx, yy), fill=rgba(CREAM, 180))
    draw_frame(draw, 64, 74, 10, 10, rgba(CREAM))
    draw_frame(draw, 86, 74, 10, 10, rgba(CREAM))
    draw.rectangle((67, 76, 71, 82), outline=rgba(FOREST))
    draw.rectangle((89, 76, 93, 82), outline=rgba(FOREST))

    # party figures
    paste(image, sprites["char_red"], (76, 60))
    paste(image, sprites["char_blue"], (72, 68))
    paste(image, sprites["char_green"], (84, 68))
    paste(image, sprites["monster_green"], (66, 64))

    # central path
    for y in range(100, height, 8):
        draw.point((78, y), fill=rgba(PALE_GREEN))
        draw.point((82, y + 2), fill=rgba(PALE_GREEN))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-polychrome-temple-study-v1.png")
    _resize_nearest(image, (width * 5, height * 5)).save(output)
    return output


def render_reference_hud_room_study_v1() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width, height = 120, 80
    image = Image.new("RGBA", (width, height), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    # upper architecture and room border
    paste(image, sprites["maze_wall"].crop((0, 0, 46, 26)), (4, 4))
    paste(image, sprites["maze_wall"].crop((0, 0, 30, 20)), (72, 20))
    paste(image, sprites["maze_wall"].crop((0, 0, 20, 20)), (100, 20))
    draw.rectangle((4, 16, 116, 52), outline=rgba("#A9D8E8"))
    draw.line((4, 52, 72, 52), fill=rgba("#A9D8E8"))
    draw.line((80, 52, 116, 52), fill=rgba("#A9D8E8"))

    # doors and wall features
    paste(image, sprites["small_door"], (2, 34))
    paste(image, sprites["small_door"], (102, 34))
    paste(image, sprites["small_door"], (102, 46))
    paste(image, sprites["grid_border"].crop((0, 0, 10, 8)), (18, 60))
    paste(image, sprites["grid_border"].crop((0, 0, 10, 8)), (28, 60))
    draw.rectangle((70, 26, 78, 38), outline=rgba("#A9D8E8"))

    # floor dots
    for yy in range(20, 52, 4):
        for xx in range(8, 112, 8):
            draw.point((xx, yy), fill=rgba(SLATE_TEAL, 150))

    # top-right status panel
    draw_frame(draw, 58, 2, 58, 18, rgba(CREAM))
    paste(image, sprites["char_red"], (100, 4))
    for i in range(5):
        draw.rectangle((76 + i * 3, 10, 78 + i * 3, 13), fill=rgba(VERMILION))
    draw.line((67, 6, 98, 6), fill=rgba(CREAM))
    draw.line((67, 8, 94, 8), fill=rgba(CREAM))

    # lower panels
    draw_frame(draw, 0, 56, 58, 24, rgba(CREAM))
    draw_frame(draw, 62, 56, 58, 24, rgba(CREAM))
    draw_frame(draw, 18, 46, 38, 6, rgba(CREAM))
    draw_frame(draw, 68, 46, 20, 6, rgba(CREAM))
    paste(image, sprites["char_green"], (2, 64))
    for i in range(6):
        draw.rectangle((30 + i * 4, 68, 32 + i * 4, 70), outline=rgba(PALE_GREEN if i < 5 else BLACK_TEAL))
    for i in range(5):
        draw.rectangle((30 + i * 3, 73, 32 + i * 3, 76), fill=rgba(VERMILION))
    draw.line((68, 64, 108, 64), fill=rgba(CREAM))
    draw.line((68, 68, 108, 68), fill=rgba(CREAM))
    draw.line((68, 72, 108, 72), fill=rgba(CREAM))

    # actors in room
    paste(image, sprites["char_orange"], (16, 28))
    paste(image, sprites["char_teal"], (32, 20))
    paste(image, sprites["char_purple"], (66, 20))
    paste(image, sprites["char_green"], (48, 38))
    paste(image, sprites["char_red"], (66, 38))
    paste(image, sprites["char_teal"], (94, 40))
    for fx, fy in ((18, 40), (34, 32), (68, 32), (48, 50), (66, 50), (94, 50)):
        draw.line((fx, fy, fx + 4, fy), fill=rgba(VERMILION))

    # little loot chests
    draw.rectangle((2, 44, 5, 47), outline=rgba(GOLD))
    draw.rectangle((95, 29, 98, 32), outline=rgba(GOLD))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-gold-box-hud-room-study-v1.png")
    _resize_nearest(image, (width * 6, height * 6)).save(output)
    return output


def render_reference_hud_room_study_v2() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width, height = 120, 80
    image = Image.new("RGBA", (width, height), rgba(PLUM))
    draw = ImageDraw.Draw(image)
    line = rgba("#A9D8E8")

    # top wall blocks
    paste(image, sprites["maze_wall"].crop((0, 0, 34, 16)), (4, 4))
    paste(image, sprites["maze_wall"].crop((0, 0, 18, 16)), (40, 4))
    paste(image, sprites["maze_wall"].crop((0, 0, 18, 16)), (98, 4))
    paste(image, sprites["small_door"], (16, 8))
    paste(image, sprites["small_door"], (44, 8))
    paste(image, sprites["small_door"], (102, 8))
    for lx in (20, 48):
        draw.rectangle((lx, 8, lx + 2, 13), fill=rgba(VERMILION))
        draw.point((lx + 1, 7), fill=rgba(AMBER))

    # main room outline and side alcoves
    draw.rectangle((4, 16, 115, 51), outline=line)
    draw.line((4, 51, 88, 51), fill=line)
    draw.line((100, 51, 115, 51), fill=line)
    draw.rectangle((72, 18, 88, 31), outline=line)
    draw.rectangle((96, 18, 111, 31), outline=line)
    draw.rectangle((96, 40, 111, 51), outline=line)
    draw.rectangle((24, 42, 40, 51), outline=line)

    # floor dots
    for yy in range(20, 50, 4):
        for xx in range(8, 112, 8):
            draw.point((xx, yy), fill=rgba(SLATE_TEAL, 150))

    # top-right commander panel
    draw_frame(draw, 58, 2, 58, 18, rgba(CREAM))
    draw.line((66, 6, 98, 6), fill=rgba(CREAM))
    draw.line((68, 8, 96, 8), fill=rgba(CREAM))
    draw.line((68, 16, 103, 16), fill=rgba(CREAM))
    for i in range(5):
        draw.rectangle((74 + i * 4, 10, 76 + i * 4, 13), fill=rgba(VERMILION if i < 5 else SLATE_TEAL))
    paste(image, sprites["char_red"], (102, 4))

    # lower panels
    draw_frame(draw, 0, 56, 57, 24, rgba(CREAM))
    draw_frame(draw, 63, 56, 57, 24, rgba(CREAM))
    draw_frame(draw, 18, 46, 38, 6, rgba(CREAM))
    draw_frame(draw, 72, 46, 16, 6, rgba(CREAM))
    paste(image, sprites["char_green"], (2, 64))
    for i in range(6):
        draw.rectangle((30 + i * 4, 68, 32 + i * 4, 70), outline=rgba(PALE_GREEN if i < 5 else BLACK_TEAL))
    for i in range(5):
        draw.rectangle((30 + i * 3, 73, 32 + i * 3, 76), fill=rgba(VERMILION))
    draw.line((68, 64, 106, 64), fill=rgba(CREAM))
    draw.line((68, 68, 106, 68), fill=rgba(CREAM))
    draw.line((68, 72, 106, 72), fill=rgba(CREAM))

    # room actors
    paste(image, sprites["char_orange"], (16, 28))
    paste(image, sprites["char_teal"], (44, 20))
    paste(image, sprites["char_purple"], (68, 20))
    paste(image, sprites["char_green"], (52, 38))
    paste(image, sprites["char_red"], (68, 38))
    paste(image, sprites["char_teal"], (94, 40))
    for fx, fy in ((16, 40), (44, 32), (68, 32), (50, 50), (68, 50), (94, 50)):
        draw.line((fx, fy, fx + 4, fy), fill=rgba(VERMILION))

    # small chest hints
    draw.rectangle((2, 44, 5, 47), outline=rgba(GOLD))
    draw.rectangle((98, 24, 101, 27), outline=rgba(GOLD))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-gold-box-hud-room-study-v2.png")
    _resize_nearest(image, (width * 6, height * 6)).save(output)
    return output


def render_reference_temple_study_v2() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width, height = 160, 128
    image = Image.new("RGBA", (width, height), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    draw_bitmap_text(draw, 31, 7, "1-BIT POLYCHROME", rgba(CREAM), scale=2, spacing=2)

    border_y = 22
    for x in range(0, width, 8):
        draw_meander_tile(draw, x, border_y, rgba(FOREST))
    for y in range(border_y + 8, height - 16, 8):
        draw_meander_tile(draw, 0, y, rgba(FOREST))
        draw_meander_tile(draw, width - 8, y, rgba(FOREST))

    draw_stone_bank(draw, 10, 40, ((8, 24), (4, 30), (0, 36), (2, 30)), rgba(PALE_BLUE))
    draw_stone_bank(draw, width - 46, 40, ((4, 24), (0, 30), (0, 36), (4, 28)), rgba(PALE_BLUE))
    draw_stone_bank(draw, 18, 104, ((8, 20), (4, 28)), rgba(PALE_BLUE))
    draw_stone_bank(draw, width - 44, 104, ((4, 20), (0, 28)), rgba(PALE_BLUE))

    draw_water_band(draw, 4, 56, 28)
    draw_water_band(draw, 4, 88, 26)
    draw_water_band(draw, width - 32, 56, 28)
    draw_water_band(draw, width - 30, 88, 26)

    draw_frame(draw, 48, 34, 64, 76, rgba(CREAM))
    draw_frame(draw, 56, 44, 48, 50, rgba(CREAM))
    draw_meander_band(draw, 48, 26, 8, rgba(CREAM))
    draw.line((80, 24, 80, 34), fill=rgba(CREAM))
    draw.line((78, 26, 78, 34), fill=rgba(CREAM))
    draw.line((82, 26, 82, 34), fill=rgba(CREAM))
    draw.line((56, 42, 104, 42), fill=rgba(CREAM))
    draw.line((60, 48, 100, 48), fill=rgba(CREAM))
    draw.line((60, 54, 72, 54), fill=rgba(CREAM))
    draw.line((88, 54, 100, 54), fill=rgba(CREAM))
    draw.line((72, 48, 72, 66), fill=rgba(CREAM))
    draw.line((88, 48, 88, 66), fill=rgba(CREAM))
    draw.line((80, 50, 80, 66), fill=rgba(CREAM))
    draw.rectangle((76, 56, 84, 68), outline=rgba(CREAM))
    draw.rectangle((78, 58, 82, 68), fill=rgba(PLUM))

    for tx in (70, 90):
        draw_torch(draw, tx, 54)
    for wx in (52, 108):
        for yy in range(38, 82, 8):
            draw.line((wx, yy, wx + 3, yy), fill=rgba(LINE_BLUE))

    draw_dotted_floor(draw, 56, 68, 48, 36, step_x=4, step_y=4, color=rgba(CREAM, 180))
    draw_frame(draw, 62, 84, 10, 10, rgba(CREAM))
    draw_frame(draw, 88, 84, 10, 10, rgba(CREAM))
    draw.line((66, 86, 66, 92), fill=rgba(FOREST))
    draw.line((68, 86, 68, 92), fill=rgba(FOREST))
    draw.line((92, 86, 92, 92), fill=rgba(FOREST))
    draw.line((94, 86, 94, 92), fill=rgba(FOREST))
    draw.rectangle((74, 102, 86, 8 + 102), outline=rgba(CREAM))
    draw.line((78, 102, 78, 112), fill=rgba(CREAM))
    draw.line((82, 102, 82, 112), fill=rgba(CREAM))
    draw_temple_path(draw, 78, 112, 16)

    paste(image, sprites["char_red"], (77, 70))
    paste(image, sprites["char_blue"], (72, 74))
    paste(image, sprites["char_green"], (88, 74))
    paste(image, sprites["monster_green"], (82, 76))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-polychrome-temple-study-v2.png")
    _resize_nearest(image, (width * 5, height * 5)).save(output)
    return output


def render_reference_hud_room_study_v3() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width, height = 120, 80
    image = Image.new("RGBA", (width, height), rgba(PLUM))
    draw = ImageDraw.Draw(image)
    line = rgba(LINE_BLUE)

    draw_meander_band(draw, 3, 3, 5, line)
    draw_meander_band(draw, 26, 3, 5, line)
    draw_meander_band(draw, 86, 3, 4, line)
    draw.rectangle((39, 3, 9 + 39, 12), outline=line)
    draw.rectangle((42, 6, 45, 9), fill=rgba(BURNT))
    draw.rectangle((44, 4, 47, 5), fill=rgba(VERMILION))
    draw.rectangle((44, 9, 47, 10), fill=rgba(VERMILION))
    draw.rectangle((39, 3, 48, 12), outline=line)
    draw_frame(draw, 52, 2, 67, 16, rgba(CREAM))
    draw.line((103, 2, 103, 17), fill=rgba(CREAM))
    draw_meander_band(draw, 52, 18, 7, line)
    draw_health_meter(draw, 62, 10, total=6, filled=5, fill_color=rgba(VERMILION), empty_color=rgba(VERMILION), segment_w=3, segment_h=5, gap=1)
    paste(image, sprites["char_red"], (108, 5))

    draw_torch(draw, 8, 8)
    draw_torch(draw, 31, 8)
    draw.rectangle((43, 6, 50, 13), outline=rgba(FOREST))
    for yy in range(7, 13, 2):
        draw.line((44, yy, 49, yy), fill=rgba(FOREST))

    draw.rectangle((3, 19, 116, 51), outline=line)
    draw.line((74, 19, 74, 51), fill=line)
    draw.rectangle((74, 19, 86, 29), outline=line)
    draw.rectangle((105, 35, 115, 49), outline=line)
    draw.rectangle((3, 25, 6, 29), outline=line)
    draw.rectangle((105, 25, 108, 29), outline=line)
    draw.rectangle((105, 43, 108, 47), outline=line)

    draw_dotted_floor(draw, 8, 23, 104, 24, step_x=8, step_y=4, color=rgba(SLATE_TEAL, 180))
    draw.rectangle((12, 43, 15, 46), outline=rgba(GOLD))
    draw.rectangle((113, 21, 116, 24), outline=rgba(GOLD))

    draw.rectangle((12, 46, 17, 50), outline=rgba(CREAM))
    draw.line((14, 50, 14, 54), fill=rgba(CREAM))
    draw.rectangle((18, 46, 23, 50), outline=rgba(CREAM))
    draw.line((20, 50, 20, 54), fill=rgba(CREAM))

    paste(image, sprites["char_orange"], (18, 29))
    paste(image, sprites["char_teal"], (35, 20))
    paste(image, sprites["char_purple"], (62, 20))
    paste(image, sprites["char_green"], (40, 36))
    paste(image, sprites["char_red"], (53, 37))
    paste(image, sprites["char_blue"], (95, 37))
    for x, y in ((18, 41), (35, 32), (62, 32), (40, 48), (53, 49), (95, 49)):
        draw_red_baseline(draw, x, y)

    draw_frame(draw, 0, 56, 60, 24, rgba(CREAM))
    draw_frame(draw, 61, 56, 59, 24, rgba(CREAM))
    draw_frame(draw, 16, 51, 44, 6, rgba(CREAM))
    draw_frame(draw, 72, 51, 20, 6, rgba(CREAM))

    paste(image, sprites["char_green"], (2, 64))
    draw_health_meter(draw, 32, 70, total=6, filled=5, fill_color=rgba(PALE_GREEN), empty_color=rgba(PALE_GREEN), segment_w=3, segment_h=3, gap=2)
    draw_health_meter(draw, 32, 75, total=5, filled=4, fill_color=rgba(VERMILION), empty_color=rgba(VERMILION), segment_w=3, segment_h=4, gap=1)
    final_image = _resize_nearest(image, (width * 6, height * 6))
    final_draw = ImageDraw.Draw(final_image)
    cream = rgba(CREAM)
    draw_bitmap_text(final_draw, 342, 27, "1ST CMDR HARRUK..LVL9", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 350, 98, "4", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 564, 98, "1", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 118, 314, "MOHAM MEKKO", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 460, 314, "SKILLS", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 90, 384, "JEDI CONS. LVL3", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 96, 414, "- AP", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 96, 444, "- HP", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 356, 420, "+2", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 312, 452, "47/82", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 384, "[4] FORCE PUSH", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 414, "[1] MEDITATE", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 444, "[2] ATTACK", cream, scale=3, spacing=1)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-gold-box-hud-room-study-v3.png")
    final_image.save(output)
    return output


def render_reference_temple_study_v3() -> Path:
    palette = (
        rgba(PLUM),
        rgba(MIDNIGHT),
        rgba(BLACK_TEAL),
        rgba(CREAM),
        rgba(PALE_BLUE),
        rgba(LINE_BLUE),
        rgba(SKY),
        rgba(FOREST),
        rgba(PALE_GREEN),
        rgba(VERMILION),
        rgba(ORANGE),
        rgba(GOLD),
    )
    image = normalise_guide(TEMPLE_GUIDE_PATH, palette)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-polychrome-temple-study-v3.png")
    _resize_nearest(image, (image.width * 5, image.height * 5)).save(output)
    return output


def render_reference_hud_room_study_v4() -> Path:
    palette = (
        rgba(PLUM),
        rgba(CREAM),
        rgba(LINE_BLUE),
        rgba(SLATE_TEAL),
        rgba(FOREST),
        rgba(PALE_GREEN),
        rgba(VERMILION),
        rgba(ORANGE),
        rgba(DEEP_VIOLET),
        rgba(SKY),
        rgba(GOLD),
    )
    image = normalise_guide(HUD_GUIDE_PATH, palette)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-gold-box-hud-room-study-v4.png")
    _resize_nearest(image, (image.width * 6, image.height * 6)).save(output)
    return output


def render_reference_temple_template_exact() -> Path:
    image = Image.open(TEMPLE_GUIDE_PATH).convert("RGBA")
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-polychrome-temple-template-exact.png")
    _resize_nearest(image, (image.width * 5, image.height * 5)).save(output)
    return output


def render_reference_hud_room_template_exact() -> Path:
    image = Image.open(HUD_GUIDE_PATH).convert("RGBA")
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-reference-gold-box-hud-room-template-exact.png")
    _resize_nearest(image, (image.width * 6, image.height * 6)).save(output)
    return output


def render_tavern_v3_from_template() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    base = Image.open(HUD_GUIDE_PATH).convert("RGBA")
    image = remap_exact_colors(
        base,
        {
            (36, 25, 42, 255): rgba(PLUM),
            (255, 212, 163, 255): rgba(CREAM),
            (123, 166, 181, 255): rgba(CREAM),
            (77, 120, 137, 255): rgba(BURNT),
            (68, 157, 113, 255): rgba(FOREST),
            (165, 220, 235, 255): rgba(SLATE_TEAL),
            (242, 140, 58, 255): rgba(ORANGE),
            (220, 98, 80, 255): rgba(VERMILION),
            (157, 126, 213, 255): rgba(DEEP_VIOLET),
            (255, 223, 91, 255): rgba(AMBER),
        },
    )
    draw = ImageDraw.Draw(image)

    # Reclaim the interior panels and top card from the reference.
    draw.rectangle((55, 3, 102, 17), fill=rgba(PLUM))
    draw.rectangle((15, 58, 58, 78), fill=rgba(PLUM))
    draw.rectangle((72, 58, 117, 78), fill=rgba(PLUM))

    # Back-bar alcove and counter.
    draw.rectangle((14, 6, 26, 17), fill=rgba(PURE_BLACK))
    draw.rectangle((27, 8, 37, 16), fill=rgba(BOTTLE))
    for yy in (9, 11, 13):
        draw.line((28, yy, 36, yy), fill=rgba(FOREST))
    draw.rectangle((18, 30, 58, 33), fill=rgba(ORANGE))
    draw.rectangle((18, 34, 58, 35), fill=rgba(BRICK))
    draw.rectangle((18, 27, 58, 29), fill=rgba(BURNT))

    # Lanterns and bottle shelf hints.
    for tx in (8, 31):
        draw_torch(draw, tx, 7)
    for bx, by, color in ((40, 8, FOREST), (43, 8, SKY), (46, 8, AMBER), (49, 8, VERMILION)):
        draw.rectangle((bx, by, bx + 1, by + 3), fill=rgba(color))

    # Replace room cast with warmer tavern-specific placements.
    for box in ((17, 29, 24, 40), (34, 22, 38, 31), (63, 20, 70, 30), (40, 36, 48, 46), (52, 35, 58, 45), (94, 36, 100, 46)):
        draw.rectangle(box, fill=rgba(PLUM))
    paste(image, sprites["char_orange"], (18, 29))
    paste(image, sprites["char_bartender"], (36, 18))
    paste(image, sprites["char_purple"], (63, 20))
    paste(image, sprites["char_green"], (40, 36))
    paste(image, sprites["char_red"], (52, 35))
    paste(image, sprites["char_teal"], (94, 36))
    for x, y in ((18, 41), (36, 30), (63, 31), (40, 48), (52, 47), (94, 48)):
        draw_red_baseline(draw, x, y)
    draw_dotted_floor(draw, 8, 22, 102, 24, step_x=8, step_y=4, color=rgba(BURNT))

    # Small tavern furniture from the room scaffold.
    draw.rectangle((12, 43, 17, 46), outline=rgba(CREAM))
    draw.line((14, 46, 14, 50), fill=rgba(CREAM))
    draw.rectangle((18, 43, 23, 46), outline=rgba(CREAM))
    draw.line((20, 46, 20, 50), fill=rgba(CREAM))
    draw.rectangle((96, 42, 101, 45), outline=rgba(CREAM))
    draw.line((98, 45, 98, 49), fill=rgba(CREAM))
    draw.rectangle((74, 31, 77, 47), fill=rgba(BURNT))
    draw.line((76, 31, 76, 47), fill=rgba(CREAM))

    # Bartender-only gold + deep violet pairing.
    draw.point((41, 20), fill=rgba(GOLD))
    draw.point((42, 20), fill=rgba(DEEP_VIOLET))

    final_image = _resize_nearest(image, (image.width * 6, image.height * 6))
    final_draw = ImageDraw.Draw(final_image)
    cream = rgba(CREAM)
    amber = rgba(AMBER)

    draw_bitmap_text(final_draw, 338, 30, "FOOL & FLINTLOCK", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 342, 62, "BARTOP RUCKUS", amber, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 349, 98, "4", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 558, 98, "1", cream, scale=3, spacing=1)
    draw_health_meter(final_draw, 414, 56, total=5, filled=4, fill_color=rgba(VERMILION), empty_color=rgba(BRICK), segment_w=12, segment_h=18, gap=6)

    draw_bitmap_text(final_draw, 112, 314, "WAYFARER", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 450, 314, "ACTIONS", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 92, 384, "DUELIST LVL3", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 96, 414, "- AP", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 96, 444, "- HP", cream, scale=3, spacing=1)
    draw_health_meter(final_draw, 186, 414, total=6, filled=5, fill_color=rgba(PALE_GREEN), empty_color=rgba(BOTTLE), segment_w=14, segment_h=16, gap=8)
    draw_bitmap_text(final_draw, 356, 420, "+2", cream, scale=3, spacing=1)
    draw_health_meter(final_draw, 186, 444, total=5, filled=4, fill_color=rgba(VERMILION), empty_color=rgba(BRICK), segment_w=14, segment_h=18, gap=6)
    draw_bitmap_text(final_draw, 312, 452, "47/82", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 384, "[4] EAVESDROP", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 414, "[1] TALK", cream, scale=3, spacing=1)
    draw_bitmap_text(final_draw, 398, 444, "[2] DUEL", amber, scale=3, spacing=1)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-fool-and-flintlock-v3.png")
    final_image.save(output)
    return output


def render_underworld_v3_from_template() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    image = normalise_guide(
        TEMPLE_GUIDE_PATH,
        (
            rgba(MIDNIGHT),
            rgba(DEEP_VIOLET),
            rgba(BLACK_TEAL),
            rgba(PURE_BLACK),
            rgba(CREAM),
            rgba(LINE_BLUE),
            rgba(SKY),
            rgba(FOREST),
            rgba(PALE_GREEN),
            rgba(VERMILION),
            rgba(AMBER),
            rgba(GOLD),
        ),
    )
    draw = ImageDraw.Draw(image)

    # Strip the reference title and deepen the outer void.
    draw.rectangle((0, 0, 159, 20), fill=rgba(MIDNIGHT))
    draw.rectangle((0, 21, 159, 31), fill=rgba(MIDNIGHT))
    draw_meander_band(draw, 48, 20, 8, rgba(BLACK_TEAL))
    for x in range(64, 97, 8):
        draw.line((x, 0, x, 20), fill=rgba(DEEP_VIOLET))
    draw.line((56, 18, 104, 18), fill=rgba(DEEP_VIOLET))
    for x in range(0, 32):
        draw.rectangle((x, 32, x, 112), fill=rgba(BLACK_TEAL if x % 2 == 0 else MIDNIGHT))
        draw.rectangle((159 - x, 32, 159 - x, 112), fill=rgba(BLACK_TEAL if x % 2 == 0 else MIDNIGHT))

    # Central lantern pool and descent emphasis.
    draw.rectangle((58, 62, 101, 103), fill=rgba(MIDNIGHT))
    draw_dotted_floor(draw, 60, 64, 40, 34, step_x=4, step_y=4, color=rgba(CREAM, 180))
    for y in range(104, 120, 4):
        draw.line((74, y, 86, y), fill=rgba(CREAM if y < 112 else LINE_BLUE))

    # Replace the party cluster with Minimal 8 figures.
    for box in ((73, 68, 90, 82), (90, 66, 104, 82), (66, 70, 78, 82)):
        draw.rectangle(box, fill=rgba(MIDNIGHT))
    paste(image, sprites["char_red"], (79, 66))
    paste(image, sprites["char_blue"], (73, 74))
    paste(image, sprites["char_green"], (90, 74))
    draw_red_baseline(draw, 79, 80)
    draw_red_baseline(draw, 73, 86)
    draw_red_baseline(draw, 90, 86)

    # Lanterns and a subtle bartender omen in the doorway.
    for tx in (65, 95):
        draw_torch(draw, tx, 44)
    draw.point((80, 53), fill=rgba(GOLD))
    draw.point((81, 53), fill=rgba(DEEP_VIOLET))
    draw.line((76, 49, 79, 49), fill=rgba(PURE_BLACK))
    draw.line((82, 49, 85, 49), fill=rgba(PURE_BLACK))

    image = spotlight(image, (80, 76), 24, AMBER, 170)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-underworld-lantern-descent-v3.png")
    _resize_nearest(image, (image.width * 5, image.height * 5)).save(output)
    return output


def tile_xy(tx: int, ty: int, *, size: int = 8) -> tuple[int, int]:
    return tx * size, ty * size


def draw_tile_base(draw: ImageDraw.ImageDraw, tx: int, ty: int, fill: tuple[int, int, int, int], *, size: int = 8) -> None:
    x, y = tile_xy(tx, ty, size=size)
    draw.rectangle((x, y, x + size - 1, y + size - 1), fill=fill)


def draw_tavern_floor(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(PLUM))
    for px, py in ((1, 1), (5, 1), (3, 3), (1, 5), (6, 6)):
        draw.point((x + px, y + py), fill=rgba(BURNT))


def draw_tavern_wall(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(BURNT))
    draw.line((x, y + 1, x + 7, y + 1), fill=rgba(CREAM))
    draw.line((x + 1, y, x + 1, y + 7), fill=rgba(PURE_BLACK))
    draw.line((x + 6, y, x + 6, y + 7), fill=rgba(PURE_BLACK))


def draw_tavern_shelf(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(BOTTLE))
    draw.line((x, y + 1, x + 7, y + 1), fill=rgba(CREAM))
    for bx, color in ((1, FOREST), (3, SKY), (5, AMBER)):
        draw.rectangle((x + bx, y + 3, x + bx + 1, y + 6), fill=rgba(color))


def draw_tavern_alcove(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(PURE_BLACK))
    draw.line((x, y + 7, x + 7, y + 7), fill=rgba(CREAM))


def draw_tavern_counter(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_tavern_floor(draw, tx, ty)
    draw.rectangle((x, y + 2, x + 7, y + 4), fill=rgba(ORANGE))
    draw.rectangle((x, y + 5, x + 7, y + 7), fill=rgba(BRICK))
    draw.line((x, y + 1, x + 7, y + 1), fill=rgba(CREAM))


def draw_tavern_stool(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_tavern_floor(draw, tx, ty)
    draw.rectangle((x + 2, y + 2, x + 5, y + 4), outline=rgba(CREAM))
    draw.line((x + 3, y + 5, x + 3, y + 7), fill=rgba(CREAM))
    draw.line((x + 4, y + 5, x + 4, y + 7), fill=rgba(CREAM))


def draw_tavern_table(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_tavern_floor(draw, tx, ty)
    draw.rectangle((x + 1, y + 2, x + 6, y + 4), outline=rgba(CREAM))
    draw.line((x + 2, y + 5, x + 2, y + 7), fill=rgba(CREAM))
    draw.line((x + 5, y + 5, x + 5, y + 7), fill=rgba(CREAM))


def draw_tavern_door(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_tavern_wall(draw, tx, ty)
    draw.rectangle((x + 2, y + 1, x + 5, y + 7), fill=rgba(PURE_BLACK))
    draw.line((x + 2, y + 1, x + 5, y + 1), fill=rgba(CREAM))


def draw_tavern_entrance(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_tavern_floor(draw, tx, ty)
    draw.line((x, y, x, y + 7), fill=rgba(CREAM))
    draw.line((x + 7, y, x + 7, y + 7), fill=rgba(CREAM))
    draw.line((x + 1, y + 1, x + 6, y + 1), fill=rgba(AMBER))


def draw_tavern_torch(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    draw_tavern_wall(draw, tx, ty)
    x, y = tile_xy(tx, ty)
    draw_torch(draw, x + 2, y + 1)


def draw_underworld_void(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(MIDNIGHT))
    draw.line((x + 3, y, x + 3, y + 7), fill=rgba(DEEP_VIOLET))


def draw_underworld_glyph(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(MIDNIGHT))
    draw_meander_tile(draw, x, y, rgba(FOREST))


def draw_underworld_rock(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(MIDNIGHT))
    draw.rectangle((x + 1, y + 1, x + 6, y + 3), fill=rgba(PALE_BLUE))
    draw.rectangle((x, y + 4, x + 4, y + 7), fill=rgba(PALE_BLUE))
    draw.point((x + 2, y + 2), fill=rgba(PURE_BLACK))
    draw.point((x + 5, y + 5), fill=rgba(PURE_BLACK))


def draw_underworld_water(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(BLACK_TEAL))
    draw.line((x, y + 2, x + 5, y + 2), fill=rgba(SKY))
    draw.line((x + 2, y + 5, x + 7, y + 5), fill=rgba(SKY))


def draw_underworld_wall(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(DEEP_VIOLET))
    draw.rectangle((x + 1, y + 1, x + 6, y + 6), outline=rgba(CREAM))
    draw.line((x + 3, y + 1, x + 3, y + 6), fill=rgba(CREAM))
    draw.line((x + 5, y + 1, x + 5, y + 6), fill=rgba(LINE_BLUE))


def draw_underworld_floor(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(MIDNIGHT))
    for px, py in ((1, 1), (5, 1), (3, 3), (1, 5), (5, 5)):
        draw.point((x + px, y + py), fill=rgba(CREAM))


def draw_underworld_mosaic(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_underworld_floor(draw, tx, ty)
    draw.line((x + 3, y + 1, x + 3, y + 6), fill=rgba(BURNT))
    draw.line((x + 1, y + 3, x + 6, y + 3), fill=rgba(BURNT))


def draw_underworld_pillar(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_underworld_floor(draw, tx, ty)
    draw.rectangle((x + 2, y + 1, x + 5, y + 6), outline=rgba(CREAM))
    draw.line((x + 3, y + 2, x + 3, y + 5), fill=rgba(FOREST))
    draw.line((x + 4, y + 2, x + 4, y + 5), fill=rgba(FOREST))


def draw_underworld_arch(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_underworld_wall(draw, tx, ty)
    draw.rectangle((x + 2, y + 2, x + 5, y + 7), fill=rgba(PURE_BLACK))
    draw.point((x + 3, y + 1), fill=rgba(AMBER))
    draw.point((x + 4, y + 1), fill=rgba(AMBER))


def draw_underworld_stairs(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw_underworld_floor(draw, tx, ty)
    for offset in range(0, 6, 2):
        draw.line((x + 1, y + 1 + offset, x + 6, y + 1 + offset), fill=rgba(CREAM if offset < 4 else LINE_BLUE))


def draw_underworld_path(draw: ImageDraw.ImageDraw, tx: int, ty: int) -> None:
    x, y = tile_xy(tx, ty)
    draw.rectangle((x, y, x + 7, y + 7), fill=rgba(MIDNIGHT))
    draw.point((x + 2, y + 1), fill=rgba(PALE_GREEN))
    draw.point((x + 5, y + 3), fill=rgba(PALE_GREEN))
    draw.point((x + 3, y + 6), fill=rgba(PALE_GREEN))


def render_tavern_v4_grid() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    map_grid = [
        ["W", "W", "W", "W", "W", "W", "L", "D", "L", "W", "W", "W", "W", "W", "W"],
        ["W", "B", "B", "B", "A", "A", "A", "A", "A", "B", "B", "B", "B", "B", "W"],
        ["W", "F", "S", "C", "C", "C", "C", "C", "C", "C", "C", "C", "S", "F", "W"],
        ["W", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "W"],
        ["W", "F", "T", "F", "F", "F", "F", "F", "F", "F", "F", "F", "T", "F", "W"],
        ["W", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "W"],
        ["W", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "F", "W"],
        ["W", "W", "W", "W", "W", "W", "E", "E", "E", "W", "W", "W", "W", "W", "W"],
    ]
    width = 15 * 8
    map_height = 8 * 8
    hud_height = 32
    image = Image.new("RGBA", (width, map_height + hud_height), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    tavern_drawers = {
        "F": draw_tavern_floor,
        "W": draw_tavern_wall,
        "B": draw_tavern_shelf,
        "A": draw_tavern_alcove,
        "C": draw_tavern_counter,
        "S": draw_tavern_stool,
        "T": draw_tavern_table,
        "D": draw_tavern_door,
        "E": draw_tavern_entrance,
        "L": draw_tavern_torch,
    }
    for ty, row in enumerate(map_grid):
        for tx, code in enumerate(row):
            tavern_drawers[code](draw, tx, ty)

    draw.line((0, map_height, width, map_height), fill=rgba(CREAM))

    # Characters only after the room reads as a map.
    placements = [
        ("char_bartender", 7, 1, 0),
        ("char_orange", 3, 3, 0),
        ("char_green", 6, 5, 0),
        ("char_red", 8, 5, 0),
        ("char_teal", 11, 4, 0),
    ]
    for name, tx, ty, dy in placements:
        x, y = tile_xy(tx, ty)
        paste(image, sprites[name], (x, y + dy))
        draw_red_baseline(draw, x, y + 12)

    # Bartender omen: the only gold + deep violet pair.
    draw.point((58, 14), fill=rgba(GOLD))
    draw.point((59, 14), fill=rgba(DEEP_VIOLET))

    hud_top = map_height + 4
    draw_frame(draw, 2, map_height + 2, 54, hud_height - 4, rgba(CREAM))
    draw_frame(draw, 62, map_height + 2, 56, hud_height - 4, rgba(CREAM))
    paste(image, sprites["char_green"], (4, hud_top + 6))
    draw_bitmap_text(draw, 20, hud_top + 2, "FLINTLOCK", rgba(CREAM), spacing=0)
    draw_bitmap_text(draw, 20, hud_top + 10, "MAIN BAR", rgba(CREAM), spacing=0)
    draw_bitmap_text(draw, 20, hud_top + 18, "AP", rgba(CREAM), spacing=0)
    draw_health_meter(draw, 34, hud_top + 17, total=5, filled=4, fill_color=rgba(PALE_GREEN), empty_color=rgba(BOTTLE), segment_w=4, segment_h=4, gap=2)
    draw_bitmap_text(draw, 64, hud_top + 2, "WALK TALK", rgba(CREAM), spacing=0)
    draw_bitmap_text(draw, 64, hud_top + 10, "DUEL SOUTH", rgba(AMBER), spacing=0)
    draw_bitmap_text(draw, 64, hud_top + 18, "BAR BLOCK", rgba(CREAM), spacing=0)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-fool-and-flintlock-v4-map.png")
    _resize_nearest(image, (width * 6, (map_height + hud_height) * 6)).save(output)
    return output


def render_underworld_v4_grid() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    map_grid = [
        ["X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X"],
        ["X", "X", "X", "X", "G", "G", "G", "G", "G", "G", "G", "G", "G", "G", "G", "G", "X", "X", "X", "X"],
        ["X", "X", "R", "R", "R", "S", "S", "S", "S", "S", "S", "S", "S", "S", "S", "R", "R", "R", "X", "X"],
        ["X", "R", "R", "W", "W", "S", "F", "F", "F", "A", "A", "F", "F", "F", "S", "W", "W", "R", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "P", "F", "F", "F", "F", "P", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "F", "F", "F", "F", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "C", "C", "C", "C", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "C", "C", "C", "C", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "C", "C", "C", "C", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "C", "C", "C", "C", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "F", "F", "F", "F", "F", "F", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "W", "W", "W", "S", "F", "P", "F", "F", "F", "F", "P", "F", "S", "W", "W", "W", "R", "X"],
        ["X", "R", "R", "W", "W", "S", "S", "S", "S", "T", "T", "S", "S", "S", "S", "W", "W", "R", "R", "X"],
        ["X", "X", "R", "R", "R", "E", "E", "E", "E", "E", "E", "E", "E", "E", "R", "R", "R", "X", "X", "X"],
        ["X", "X", "X", "R", "R", "E", "E", "E", "E", "T", "T", "E", "E", "E", "R", "R", "X", "X", "X", "X"],
        ["X", "X", "X", "X", "X", "G", "G", "G", "E", "E", "E", "E", "G", "G", "G", "X", "X", "X", "X", "X"],
    ]
    width = 20 * 8
    height = 16 * 8
    image = Image.new("RGBA", (width, height), rgba(MIDNIGHT))
    draw = ImageDraw.Draw(image)

    underworld_drawers = {
        "X": draw_underworld_void,
        "G": draw_underworld_glyph,
        "R": draw_underworld_rock,
        "W": draw_underworld_water,
        "S": draw_underworld_wall,
        "F": draw_underworld_floor,
        "C": draw_underworld_mosaic,
        "P": draw_underworld_pillar,
        "A": draw_underworld_arch,
        "T": draw_underworld_stairs,
        "E": draw_underworld_path,
    }
    for ty, row in enumerate(map_grid):
        for tx, code in enumerate(row):
            underworld_drawers[code](draw, tx, ty)

    for name, tx, ty in (("char_red", 9, 7), ("char_blue", 8, 9), ("char_green", 11, 9)):
        x, y = tile_xy(tx, ty)
        paste(image, sprites[name], (x, y))
        draw_red_baseline(draw, x, y + 12)

    image = spotlight(image, (80, 68), 26, AMBER, 150)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-underworld-lantern-descent-v4-map.png")
    _resize_nearest(image, (width * 5, height * 5)).save(output)
    return output


def render_tavern_v5_large_map() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width_tiles = 40
    height_tiles = 25
    grid = [["F" for _ in range(width_tiles)] for _ in range(height_tiles)]

    for x in range(width_tiles):
        grid[0][x] = "W"
        grid[height_tiles - 1][x] = "W"
    for y in range(height_tiles):
        grid[y][0] = "W"
        grid[y][width_tiles - 1] = "W"

    for x in range(8, 32):
        grid[2][x] = "B"
    for x in range(15, 25):
        grid[2][x] = "A"
        grid[3][x] = "A"
    grid[2][19] = "D"
    grid[2][20] = "D"

    for x in range(9, 31):
        grid[5][x] = "C"
        grid[6][x] = "C"
    for x in (11, 14, 17, 22, 25, 28):
        grid[7][x] = "S"

    for pos in ((6, 10), (10, 12), (30, 10), (33, 13), (8, 18), (31, 18)):
        grid[pos[1]][pos[0]] = "T"
    for pos in ((5, 11), (7, 11), (9, 11), (11, 13), (29, 11), (31, 11), (32, 14), (34, 14), (7, 19), (9, 19), (30, 19), (32, 19)):
        grid[pos[1]][pos[0]] = "S"

    for x in range(17, 23):
        grid[23][x] = "E"
    grid[12][39] = "D"
    grid[13][39] = "D"
    grid[12][0] = "D"
    grid[13][0] = "D"
    grid[1][5] = "L"
    grid[1][34] = "L"

    tavern_drawers = {
        "F": draw_tavern_floor,
        "W": draw_tavern_wall,
        "B": draw_tavern_shelf,
        "A": draw_tavern_alcove,
        "C": draw_tavern_counter,
        "S": draw_tavern_stool,
        "T": draw_tavern_table,
        "D": draw_tavern_door,
        "E": draw_tavern_entrance,
        "L": draw_tavern_torch,
    }

    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), rgba(PLUM))
    draw = ImageDraw.Draw(image)
    for ty, row in enumerate(grid):
        for tx, code in enumerate(row):
            tavern_drawers[code](draw, tx, ty)

    for tx in range(1, width_tiles - 1):
        x, y = tile_xy(tx, 8)
        draw.line((x, y, x + 7, y), fill=rgba(BURNT))

    placements = [
        ("char_bartender", 20, 4),
        ("char_orange", 7, 9),
        ("char_green", 18, 14),
        ("char_red", 22, 14),
        ("char_teal", 33, 12),
        ("char_purple", 28, 9),
        ("char_blue", 19, 21),
    ]
    for name, tx, ty in placements:
        x, y = tile_xy(tx, ty)
        paste(image, sprites[name], (x, y))
        draw_red_baseline(draw, x, y + 12)

    draw.point((163, 36), fill=rgba(GOLD))
    draw.point((164, 36), fill=rgba(DEEP_VIOLET))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-fool-and-flintlock-v5-map-40x25.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v5_large_map() -> Path:
    tiles = Minimal8()
    sprites = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}

    width_tiles = 40
    height_tiles = 25
    grid = [["X" for _ in range(width_tiles)] for _ in range(height_tiles)]

    for x in range(12, 28):
        grid[2][x] = "G"
    for x in range(10, 30):
        grid[4][x] = "S"
        grid[18][x] = "S"
    for y in range(4, 19):
        grid[y][10] = "S"
        grid[y][29] = "S"
    for x in range(18, 22):
        grid[18][x] = "T"
        grid[19][x] = "T"
    for x in range(17, 23):
        for y in range(20, 25):
            if y < height_tiles:
                grid[y][x] = "E"
    for x in range(18, 22):
        grid[4][x] = "A"

    for y in range(5, 18):
        for x in range(11, 29):
            grid[y][x] = "F"
    for y in range(8, 15):
        for x in range(15, 25):
            grid[y][x] = "C"

    for pos in ((15, 8), (24, 8), (15, 14), (24, 14), (18, 6), (21, 6)):
        grid[pos[1]][pos[0]] = "P"

    for y in range(6, 20):
        for x in range(4, 9):
            grid[y][x] = "W"
        for x in range(31, 36):
            grid[y][x] = "W"
    for y in range(5, 21):
        for x in range(2, 10):
            if grid[y][x] == "X":
                grid[y][x] = "R"
        for x in range(30, 38):
            if grid[y][x] == "X":
                grid[y][x] = "R"

    for x in range(14, 26):
        grid[22][x] = "G"
    for x in range(16, 24):
        grid[23][x] = "E"
        grid[24][x] = "E"

    underworld_drawers = {
        "X": draw_underworld_void,
        "G": draw_underworld_glyph,
        "R": draw_underworld_rock,
        "W": draw_underworld_water,
        "S": draw_underworld_wall,
        "F": draw_underworld_floor,
        "C": draw_underworld_mosaic,
        "P": draw_underworld_pillar,
        "A": draw_underworld_arch,
        "T": draw_underworld_stairs,
        "E": draw_underworld_path,
    }

    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), rgba(MIDNIGHT))
    draw = ImageDraw.Draw(image)
    for ty, row in enumerate(grid):
        for tx, code in enumerate(row):
            underworld_drawers[code](draw, tx, ty)

    placements = [
        ("char_red", 19, 11),
        ("char_blue", 17, 13),
        ("char_green", 22, 13),
        ("char_purple", 20, 9),
    ]
    for name, tx, ty in placements:
        x, y = tile_xy(tx, ty)
        paste(image, sprites[name], (x, y))
        draw_red_baseline(draw, x, y + 12)

    draw.point((160, 34), fill=rgba(GOLD))
    draw.point((161, 34), fill=rgba(DEEP_VIOLET))
    image = spotlight(image, (160, 96), 34, AMBER, 150)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output = next_generated_path("20260506-underworld-lantern-descent-v5-map-40x25.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def paste_tile(canvas: Image.Image, tile: Image.Image, tx: int, ty: int) -> None:
    canvas.alpha_composite(tile, (tx * 8, ty * 8))


def raw_tile_from_meta(tiles: Minimal8, meta: TileRecord) -> Image.Image:
    region_name, cell_x, cell_y = tiles.region_cell_for_tile(meta)
    return tiles.raw_region_cell(region_name, cell_x, cell_y)


def transparent_tile_from_meta(tiles: Minimal8, meta: TileRecord) -> Image.Image:
    region_name, cell_x, cell_y = tiles.region_cell_for_tile(meta)
    return tiles.transparent_region_cell(region_name, cell_x, cell_y)


def raw_tile_from_alias(tiles: Minimal8, alias: str) -> Image.Image:
    return raw_tile_from_meta(tiles, _get_catalog().by_alias(alias))


def transparent_tile_from_alias(tiles: Minimal8, alias: str) -> Image.Image:
    return transparent_tile_from_meta(tiles, _get_catalog().by_alias(alias))


def raw_tile_from_ref(tiles: Minimal8, ref: str) -> Image.Image:
    catalog = _get_catalog()
    if ref in catalog.tiles:
        return raw_tile_from_meta(tiles, catalog.by_id(ref))
    return raw_tile_from_alias(tiles, ref)


def meta_from_ref(ref: str) -> TileRecord:
    catalog = _get_catalog()
    if ref in catalog.tiles:
        return catalog.by_id(ref)
    return catalog.by_alias(ref)


@dataclass(frozen=True)
class TileStyle:
    foreground: tuple[int, int, int, int] | None = None
    background: tuple[int, int, int, int] | None = None


def recolor_tile_foreground(
    image: Image.Image,
    *,
    source_background: tuple[int, int, int, int],
    foreground: tuple[int, int, int, int] | None = None,
    background: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    output = image.copy()
    pixels: list[tuple[int, int, int, int]] = []
    for raw in _image_get_pixels(output):
        pixel = cast(tuple[int, int, int, int], raw)
        if pixel == source_background:
            pixels.append(background if background is not None else pixel)
        else:
            pixels.append(foreground if foreground is not None else pixel)
    _image_put_pixels(output, pixels)
    return output


def tile_image_from_ref(
    tiles: Minimal8,
    ref: str,
    *,
    style_rules: dict[str, TileStyle] | None = None,
    preserve_transparency: bool = False,
) -> Image.Image:
    meta = meta_from_ref(ref)
    if preserve_transparency and meta.transparent:
        image = transparent_tile_from_meta(tiles, meta)
    else:
        image = raw_tile_from_meta(tiles, meta)
    if style_rules and ref in style_rules:
        style = style_rules[ref]
        image = recolor_tile_foreground(
            image,
            source_background=tiles.background,
            foreground=style.foreground,
            background=style.background,
        )
    return image


def query_tile_images(
    tiles: Minimal8,
    *,
    region: str | None = None,
    category: str | None = None,
    scene: str | None = None,
    semantics_all: tuple[str, ...] = (),
    semantics_any: tuple[str, ...] = (),
    tags_all: tuple[str, ...] = (),
    tags_any: tuple[str, ...] = (),
    walkable: bool | None = None,
    blocking: bool | None = None,
    layer: str | None = "map",
    noise: str | None = None,
    contrast: str | None = None,
    temperature: str | None = None,
    usage: str | None = None,
    style: str | None = None,
    overlay: str | None = None,
    footprint: str | None = None,
    orientation: str | None = None,
) -> list[tuple[TileRecord, Image.Image]]:
    results: list[tuple[TileRecord, Image.Image]] = []
    for meta in _get_catalog().query(
        region=region,
        category=category,
        scene=scene,
        semantics_all=semantics_all,
        semantics_any=semantics_any,
        tags_all=tags_all,
        tags_any=tags_any,
        walkable=walkable,
        blocking=blocking,
        layer=layer,
        noise=noise,
        contrast=contrast,
        temperature=temperature,
        usage=usage,
        style=style,
        overlay=overlay,
        footprint=footprint,
        orientation=orientation,
    ):
        image = transparent_tile_from_meta(tiles, meta) if meta.transparent else raw_tile_from_meta(tiles, meta)
        results.append((meta, image))
    return results


def cycle_image(items: list[tuple[TileRecord, Image.Image]], index: int) -> Image.Image:
    return items[index % len(items)][1]


def cycle_alias(items: tuple[str, ...], index: int) -> str:
    return items[index % len(items)]


def new_alias_grid(width_tiles: int, height_tiles: int, fill_alias: str) -> list[list[str]]:
    return [[fill_alias for _ in range(width_tiles)] for _ in range(height_tiles)]


def paint_alias_grid(
    tiles: Minimal8,
    grid: list[list[str]],
    *,
    style_rules: dict[str, TileStyle] | None = None,
) -> Image.Image:
    height_tiles = len(grid)
    width_tiles = len(grid[0])
    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 255))
    cache: dict[str, Image.Image] = {}
    for ty, row in enumerate(grid):
        for tx, alias in enumerate(row):
            if alias not in cache:
                cache[alias] = tile_image_from_ref(tiles, alias, style_rules=style_rules)
            paste_tile(image, cache[alias], tx, ty)
    return image


def reserve_cells(grid: list[list[str]], tx: int, ty: int, width_cells: int, height_cells: int, fill_alias: str) -> None:
    for yy in range(ty, ty + height_cells):
        for xx in range(tx, tx + width_cells):
            grid[yy][xx] = fill_alias


def place_alias_block(grid: list[list[str]], tx: int, ty: int, aliases: tuple[tuple[str, ...], ...]) -> None:
    for dy, row in enumerate(aliases):
        for dx, alias in enumerate(row):
            grid[ty + dy][tx + dx] = alias


def recolor_transparent_sprite(
    sprite: Image.Image, *, foreground: tuple[int, int, int, int] | None = None
) -> Image.Image:
    if foreground is None:
        return sprite
    output = sprite.copy()
    pixels: list[tuple[int, int, int, int]] = []
    for raw in _image_get_pixels(output):
        px = cast(tuple[int, int, int, int], raw)
        pixels.append(foreground if px[3] else px)
    _image_put_pixels(output, pixels)
    return output


def paste_character_sprite(
    image: Image.Image,
    tiles: Minimal8,
    asset_name: str,
    tx: int,
    ty: int,
    *,
    foreground: tuple[int, int, int, int] | None = None,
) -> None:
    sprite = tiles.transparent_crop(ASSETS[asset_name])
    sprite = recolor_transparent_sprite(sprite, foreground=foreground)
    paste(image, sprite, (tx * 8, ty * 8))


INDOORS_BAND_RUN = (
    "indoors.band.left.alt_a",
    "indoors.band.left.alt_b",
    "indoors.band.middle",
    "indoors.band.right.alt_b",
    "indoors.band.right.alt_a",
)

INDOORS_LONG_TABLE_RUN = (
    "indoors.table.long.left",
    "indoors.table.long.middle",
    "indoors.table.long.right",
)

TAVERN_SOLID_BACK_WALL_CYCLE = tuple(f"minimal8:architecture:{column},2" for column in range(8))
TAVERN_TOP_WALL_CYCLE = (
    "minimal8:architecture:0,13",
    "minimal8:architecture:1,13",
    "minimal8:architecture:2,13",
    "minimal8:architecture:3,13",
)
TAVERN_SIDE_WALL_CYCLE = (
    "minimal8:architecture:0,14",
    "minimal8:architecture:1,14",
    "minimal8:architecture:2,14",
    "minimal8:architecture:3,14",
)
TAVERN_BACK_WALL_CYCLE_A = (
    "minimal8:architecture:2,4",
    "minimal8:architecture:3,4",
    "minimal8:architecture:2,5",
    "minimal8:architecture:3,5",
)
TAVERN_BACK_WALL_CYCLE_B = (
    "minimal8:architecture:4,4",
    "minimal8:architecture:5,4",
    "minimal8:architecture:6,4",
    "minimal8:architecture:7,4",
)
TAVERN_BAR_TOP_LEFT = "indoors.table.round"
TAVERN_BAR_TOP_MIDDLE = "indoors.table.long.middle"
TAVERN_BAR_TOP_RIGHT = "indoors.table.long.right"
TAVERN_BAR_SUPPORT_LEFT = "minimal8:terrain:0,16"
TAVERN_BAR_SUPPORT_MIDDLE = "minimal8:terrain:1,16"
TAVERN_BAR_SUPPORT_RIGHT = "minimal8:terrain:3,16"


def place_band_run(grid: list[list[str]], tx: int, ty: int, width_cells: int) -> None:
    if width_cells <= 0:
        return
    if width_cells == 1:
        grid[ty][tx] = "indoors.band.middle"
        return
    if width_cells == 2:
        grid[ty][tx] = "indoors.band.left.alt_b"
        grid[ty][tx + 1] = "indoors.band.right.alt_b"
        return
    if width_cells == 3:
        grid[ty][tx] = "indoors.band.left.alt_a"
        grid[ty][tx + 1] = "indoors.band.middle"
        grid[ty][tx + 2] = "indoors.band.right.alt_a"
        return
    grid[ty][tx] = INDOORS_BAND_RUN[0]
    grid[ty][tx + 1] = INDOORS_BAND_RUN[1]
    for offset in range(2, width_cells - 2):
        grid[ty][tx + offset] = INDOORS_BAND_RUN[2]
    grid[ty][tx + width_cells - 2] = INDOORS_BAND_RUN[3]
    grid[ty][tx + width_cells - 1] = INDOORS_BAND_RUN[4]


def place_long_table_run(grid: list[list[str]], tx: int, ty: int, width_cells: int) -> None:
    if width_cells <= 0:
        return
    if width_cells == 1:
        grid[ty][tx] = "indoors.table.round"
        return
    if width_cells == 2:
        grid[ty][tx] = "indoors.table.long.left"
        grid[ty][tx + 1] = "indoors.table.long.right"
        return
    for offset in range(width_cells):
        cell_x = tx + offset
        if offset == 0:
            grid[ty][cell_x] = INDOORS_LONG_TABLE_RUN[0]
        elif offset == width_cells - 1:
            grid[ty][cell_x] = INDOORS_LONG_TABLE_RUN[2]
        else:
            grid[ty][cell_x] = INDOORS_LONG_TABLE_RUN[1]


def place_service_run(grid: list[list[str]], tx: int, ty: int, width_cells: int) -> None:
    place_long_table_run(grid, tx, ty, width_cells)


def place_dining_cluster(grid: list[list[str]], tx: int, ty: int) -> None:
    place_long_table_run(grid, tx, ty, 3)
    grid[ty - 1][tx + 1] = "indoors.seat.tall"
    grid[ty + 1][tx + 1] = "indoors.bench.small"


def paint_quiet_floor(
    grid: list[list[str]],
    *,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    base_alias: str,
    sparse_aliases: tuple[str, ...],
    pattern_mod: int,
) -> None:
    for ty in range(y0, y1):
        for tx in range(x0, x1):
            grid[ty][tx] = base_alias
            if (tx * 3 + ty * 5) % pattern_mod == 0:
                grid[ty][tx] = cycle_alias(sparse_aliases, tx + ty)


def aliases_for_prefix(prefix: str, **query_kwargs: object) -> tuple[str, ...]:
    return tuple(alias for alias in _get_catalog().aliases_for(**query_kwargs) if alias.startswith(prefix))


ACTOR_BLOCK_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "bartender": (
        ("actor.bartender.nw", "actor.bartender.ne"),
        ("actor.bartender.sw", "actor.bartender.se"),
    ),
    "red": (
        ("actor.red.nw", "actor.red.ne"),
        ("actor.red.sw", "actor.red.se"),
    ),
    "gold": (
        ("actor.gold.nw", "actor.gold.ne"),
        ("actor.gold.sw", "actor.gold.se"),
    ),
    "orange": (
        ("actor.orange.nw", "actor.orange.ne"),
        ("actor.orange.sw", "actor.orange.se"),
    ),
    "salmon": (
        ("actor.salmon.nw", "actor.salmon.ne"),
        ("actor.salmon.sw", "actor.salmon.se"),
    ),
    "teal": (
        ("actor.teal.nw", "actor.teal.ne"),
        ("actor.teal.sw", "actor.teal.se"),
    ),
    "blue": (
        ("actor.blue.nw", "actor.blue.ne"),
        ("actor.blue.sw", "actor.blue.se"),
    ),
    "purple": (
        ("actor.purple.nw", "actor.purple.ne"),
        ("actor.purple.sw", "actor.purple.se"),
    ),
    "green": (
        ("actor.green.nw", "actor.green.ne"),
        ("actor.green.sw", "actor.green.se"),
    ),
}


QUIET_TAVERN_FLOOR_ALIASES = (
    "tavern.floor.quiet.sparse.a",
    "tavern.floor.quiet.sparse.b",
    "tavern.floor.quiet.sparse.c",
    "tavern.floor.quiet.sparse.d",
    "tavern.floor.quiet.sparse.e",
)

QUIET_UNDERWORLD_FLOOR_ALIASES = (
    "underworld.floor.quiet.sparse.a",
    "underworld.floor.quiet.sparse.b",
    "underworld.floor.quiet.sparse.c",
    "underworld.floor.quiet.sparse.d",
    "underworld.floor.quiet.sparse.e",
)

PURPLE_BARTENDER_ALIASES = (
    "actor.bartender.nw",
    "actor.bartender.ne",
    "actor.bartender.sw",
    "actor.bartender.se",
)

TAVERN_V8_STYLE_RULES = {alias: TileStyle(foreground=rgba(SLATE_TEAL)) for alias in QUIET_TAVERN_FLOOR_ALIASES}
TAVERN_V8_STYLE_RULES.update({alias: TileStyle(foreground=rgba(DEEP_VIOLET)) for alias in PURPLE_BARTENDER_ALIASES})
UNDERWORLD_V8_STYLE_RULES = {alias: TileStyle(foreground=rgba(CREAM)) for alias in QUIET_UNDERWORLD_FLOOR_ALIASES}

OVERLAY_RULES: dict[str, dict[str, tuple[str, ...] | set[str]]] = {
    "prop.torch": {
        "base_tags_any": ("semantic:wall", "semantic:arch", "semantic:band", "semantic:storage", "semantic:table"),
        "base_categories": {"wall", "door", "fixture"},
    },
}


def apply_overlays(
    image: Image.Image,
    tiles: Minimal8,
    base_grid: list[list[str]],
    overlays: list[tuple[int, int, str]],
) -> None:
    cache: dict[str, Image.Image] = {}
    for tx, ty, overlay_ref in overlays:
        overlay_meta = meta_from_ref(overlay_ref)
        if "overlay:allowed" not in overlay_meta.tags or not overlay_meta.transparent:
            raise ValueError(f"overlay {overlay_ref} is not approved for transparent overlay placement")
        rule = OVERLAY_RULES.get(overlay_ref)
        if rule is None:
            raise ValueError(f"overlay {overlay_ref} has no placement rule")
        base_meta = meta_from_ref(base_grid[ty][tx])
        allowed_tags = set(rule.get("base_tags_any", ()))
        allowed_categories = set(rule.get("base_categories", ()))
        if base_meta.category not in allowed_categories and allowed_tags.isdisjoint(set(base_meta.tags)):
            raise ValueError(f"overlay {overlay_ref} cannot be placed on {base_grid[ty][tx]}")
        if overlay_ref not in cache:
            cache[overlay_ref] = tile_image_from_ref(tiles, overlay_ref, preserve_transparency=True)
        image.alpha_composite(cache[overlay_ref], (tx * 8, ty * 8))


def render_tavern_v6_exact_tiles() -> Path:
    tiles = Minimal8()
    chars = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}
    atlas = {
        "floor_a": raw_tile_from_alias(tiles, "tavern.floor.a"),
        "floor_b": raw_tile_from_alias(tiles, "tavern.floor.b"),
        "floor_c": raw_tile_from_alias(tiles, "tavern.floor.c"),
        "wall_a": raw_tile_from_alias(tiles, "tavern.wall.a"),
        "wall_b": raw_tile_from_alias(tiles, "tavern.wall.b"),
        "wall_c": raw_tile_from_alias(tiles, "tavern.wall.c"),
        "trim_h": raw_tile_from_alias(tiles, "tavern.trim.h"),
        "trim_v": raw_tile_from_alias(tiles, "tavern.trim.v"),
        "band_middle": raw_tile_from_alias(tiles, "indoors.band.middle"),
        "door_l": raw_tile_from_alias(tiles, "tavern.door.l"),
        "door_r": raw_tile_from_alias(tiles, "tavern.door.r"),
        "service_round": raw_tile_from_alias(tiles, "indoors.table.round"),
        "service_left": raw_tile_from_alias(tiles, "indoors.table.long.left"),
        "service_middle": raw_tile_from_alias(tiles, "indoors.table.long.middle"),
        "service_right": raw_tile_from_alias(tiles, "indoors.table.long.right"),
        "seat_tall": raw_tile_from_alias(tiles, "indoors.seat.tall"),
        "bench_small": raw_tile_from_alias(tiles, "indoors.bench.small"),
        "stairs_up": raw_tile_from_alias(tiles, "indoors.stairs.up"),
        "stairs_down": raw_tile_from_alias(tiles, "indoors.stairs.down"),
        "torch": transparent_tile_from_alias(tiles, "prop.torch"),
    }

    width_tiles = 40
    height_tiles = 25
    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 255))

    for ty in range(height_tiles):
        for tx in range(width_tiles):
            paste_tile(image, atlas["floor_a" if (tx + ty) % 3 == 0 else "floor_b" if (tx + ty) % 3 == 1 else "floor_c"], tx, ty)

    for tx in range(width_tiles):
        paste_tile(image, atlas["wall_a" if tx % 3 == 0 else "wall_b" if tx % 3 == 1 else "wall_c"], tx, 0)
        paste_tile(image, atlas["wall_a" if tx % 3 == 0 else "wall_b" if tx % 3 == 1 else "wall_c"], tx, height_tiles - 1)
    for ty in range(height_tiles):
        paste_tile(image, atlas["trim_v"], 0, ty)
        paste_tile(image, atlas["trim_v"], width_tiles - 1, ty)

    for tx in range(8, 32):
        paste_tile(image, atlas["trim_h"], tx, 2)
    for tx in range(9, 15):
        paste_tile(image, atlas["band_middle"], tx, 3)
    for tx in range(25, 32):
        paste_tile(image, atlas["band_middle"], tx, 3)
    for tx in range(15, 25):
        paste_tile(image, atlas["wall_a"], tx, 3)
        paste_tile(image, atlas["wall_b"], tx, 4)
    paste_tile(image, atlas["door_l"], 19, 3)
    paste_tile(image, atlas["door_r"], 20, 3)

    paste_tile(image, atlas["service_left"], 9, 8)
    for tx in range(10, 30):
        paste_tile(image, atlas["service_middle"], tx, 8)
    paste_tile(image, atlas["service_right"], 30, 8)

    for tx in (11, 14, 17, 22, 25, 28):
        paste_tile(image, atlas["seat_tall"], tx, 9)
        paste_tile(image, atlas["bench_small"], tx, 10)

    for tx, ty in ((6, 12), (11, 14), (29, 12), (33, 15), (8, 19), (31, 19)):
        paste_tile(image, atlas["service_left"], tx, ty)
        paste_tile(image, atlas["service_middle"], tx + 1, ty)
        paste_tile(image, atlas["service_right"], tx + 2, ty)
        paste_tile(image, atlas["seat_tall"], tx + 1, ty - 1)
        paste_tile(image, atlas["bench_small"], tx + 1, ty + 1)

    for tx in range(17, 23):
        paste_tile(image, atlas["door_l" if tx % 2 == 1 else "door_r"], tx, 24)
    paste_tile(image, atlas["torch"], 5, 2)
    paste_tile(image, atlas["torch"], 34, 2)

    placements = [
        ("char_bartender", 20, 5),
        ("char_orange", 7, 11),
        ("char_green", 18, 16),
        ("char_red", 22, 16),
        ("char_teal", 34, 13),
        ("char_purple", 28, 10),
        ("char_blue", 19, 22),
    ]
    for name, tx, ty in placements:
        image.alpha_composite(chars[name], (tx * 8, ty * 8))

    output = next_generated_path("20260506-fool-and-flintlock-v6-exact-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v6_exact_tiles() -> Path:
    tiles = Minimal8()
    chars = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}
    atlas = {
        "void": tiles.raw_region_cell("architecture", 10, 0),
        "wall_a": raw_tile_from_alias(tiles, "underworld.wall.a"),
        "wall_b": raw_tile_from_alias(tiles, "underworld.wall.b"),
        "wall_c": raw_tile_from_alias(tiles, "underworld.wall.c"),
        "wall_d": raw_tile_from_alias(tiles, "underworld.wall.d"),
        "wall_v": raw_tile_from_alias(tiles, "underworld.wall.vertical"),
        "floor_a": raw_tile_from_alias(tiles, "underworld.floor.a"),
        "floor_b": raw_tile_from_alias(tiles, "underworld.floor.b"),
        "floor_c": raw_tile_from_alias(tiles, "underworld.floor.c"),
        "floor_d": raw_tile_from_alias(tiles, "underworld.floor.d"),
        "arch_l": raw_tile_from_alias(tiles, "underworld.arch.l"),
        "arch_r": raw_tile_from_alias(tiles, "underworld.arch.r"),
        "stairs": raw_tile_from_alias(tiles, "underworld.stairs"),
        "glyph_a": raw_tile_from_alias(tiles, "underworld.glyph.a"),
        "glyph_b": raw_tile_from_alias(tiles, "underworld.glyph.b"),
        "glyph_c": raw_tile_from_alias(tiles, "underworld.glyph.c"),
        "rock_a": raw_tile_from_alias(tiles, "underworld.rock.a"),
        "rock_b": raw_tile_from_alias(tiles, "underworld.rock.b"),
        "rock_c": raw_tile_from_alias(tiles, "underworld.rock.c"),
        "water_a": raw_tile_from_alias(tiles, "underworld.water.a"),
        "water_b": raw_tile_from_alias(tiles, "underworld.water.b"),
        "water_c": raw_tile_from_alias(tiles, "underworld.water.c"),
        "pillar_a": raw_tile_from_alias(tiles, "underworld.pillar.a"),
        "pillar_b": raw_tile_from_alias(tiles, "underworld.pillar.b"),
    }

    width_tiles = 40
    height_tiles = 25
    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 255))

    for ty in range(height_tiles):
        for tx in range(width_tiles):
            paste_tile(image, atlas["void"], tx, ty)

    for tx in range(12, 28):
        paste_tile(image, atlas["glyph_a" if tx % 3 == 0 else "glyph_b" if tx % 3 == 1 else "glyph_c"], tx, 2)

    for ty in range(5, 21):
        for tx in range(2, 9):
            paste_tile(image, atlas["rock_a" if (tx + ty) % 3 == 0 else "rock_b" if (tx + ty) % 3 == 1 else "rock_c"], tx, ty)
        for tx in range(31, 38):
            paste_tile(image, atlas["rock_a" if (tx + ty) % 3 == 0 else "rock_b" if (tx + ty) % 3 == 1 else "rock_c"], tx, ty)

    for ty in range(6, 20):
        for tx in range(4, 9):
            paste_tile(image, atlas["water_a" if (tx + ty) % 3 == 0 else "water_b" if (tx + ty) % 3 == 1 else "water_c"], tx, ty)
        for tx in range(31, 36):
            paste_tile(image, atlas["water_a" if (tx + ty) % 3 == 0 else "water_b" if (tx + ty) % 3 == 1 else "water_c"], tx, ty)

    wall_cycle = ["wall_a", "wall_b", "wall_c", "wall_d"]
    for tx in range(10, 30):
        paste_tile(image, atlas[wall_cycle[(tx - 10) % 4]], tx, 4)
        paste_tile(image, atlas[wall_cycle[(tx - 10) % 4]], tx, 18)
    for ty in range(4, 19):
        paste_tile(image, atlas["wall_v"], 10, ty)
        paste_tile(image, atlas["wall_v"], 29, ty)

    for ty in range(5, 18):
        for tx in range(11, 29):
            paste_tile(image, atlas["floor_a" if (tx + ty) % 4 == 0 else "floor_b" if (tx + ty) % 4 == 1 else "floor_c" if (tx + ty) % 4 == 2 else "floor_d"], tx, ty)

    for tx in range(18, 22):
        paste_tile(image, atlas["arch_l" if tx % 2 == 0 else "arch_r"], tx, 4)

    for tx, ty in ((15, 8), (24, 8), (15, 14), (24, 14), (18, 6), (21, 6)):
        paste_tile(image, atlas["pillar_a"], tx, ty)
        paste_tile(image, atlas["pillar_b"], tx, ty + 1)

    for y in range(8, 15):
        for x in range(15, 25):
            paste_tile(image, atlas["floor_b" if (x + y) % 2 == 0 else "floor_c"], x, y)

    for tx in range(18, 22):
        paste_tile(image, atlas["stairs"], tx, 19)
        paste_tile(image, atlas["stairs"], tx, 20)
    for tx in range(16, 24):
        paste_tile(image, atlas["glyph_c" if tx % 2 == 0 else "glyph_b"], tx, 23)

    placements = [
        ("char_red", 19, 12),
        ("char_blue", 17, 14),
        ("char_green", 22, 14),
        ("char_purple", 20, 10),
    ]
    for name, tx, ty in placements:
        image.alpha_composite(chars[name], (tx * 8, ty * 8))

    output = next_generated_path("20260506-underworld-lantern-descent-v6-exact-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v7_strict_tiles() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    floor_cycle = ("tavern.floor.a", "tavern.floor.b", "tavern.floor.c")
    wall_cycle = ("tavern.wall.a", "tavern.wall.b", "tavern.wall.c")
    grid = new_alias_grid(width_tiles, height_tiles, "tavern.floor.a")

    for ty in range(height_tiles):
        for tx in range(width_tiles):
            grid[ty][tx] = cycle_alias(floor_cycle, tx + ty)

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(wall_cycle, tx)
        grid[height_tiles - 1][tx] = cycle_alias(wall_cycle, tx + 1)
    for ty in range(height_tiles):
        grid[ty][0] = "tavern.trim.v"
        grid[ty][width_tiles - 1] = "tavern.trim.v"

    for tx in range(8, 32):
        grid[2][tx] = "tavern.trim.h"
    place_band_run(grid, 9, 3, 6)
    place_band_run(grid, 25, 3, 7)
    for tx in range(15, 25):
        grid[3][tx] = "tavern.wall.a"
        grid[4][tx] = "tavern.wall.b"
    grid[3][19] = "tavern.door.l"
    grid[3][20] = "tavern.door.r"

    place_service_run(grid, 9, 8, 22)

    for tx in (11, 14, 17, 22, 25, 28):
        grid[9][tx] = "indoors.seat.tall"
        grid[10][tx] = "indoors.bench.small"

    for tx, ty in ((6, 12), (11, 14), (29, 12), (33, 15), (8, 19), (31, 19)):
        place_dining_cluster(grid, tx, ty)

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    place_alias_block(grid, 19, 5, ACTOR_BLOCK_ALIASES["bartender"])
    place_alias_block(grid, 6, 11, ACTOR_BLOCK_ALIASES["orange"])
    place_alias_block(grid, 17, 16, ACTOR_BLOCK_ALIASES["green"])
    place_alias_block(grid, 22, 16, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 33, 12, ACTOR_BLOCK_ALIASES["teal"])
    place_alias_block(grid, 27, 10, ACTOR_BLOCK_ALIASES["purple"])
    place_alias_block(grid, 18, 21, ACTOR_BLOCK_ALIASES["blue"])

    image = paint_alias_grid(tiles, grid)
    output = next_generated_path("20260506-fool-and-flintlock-v7-strict-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v7_strict_tiles() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    grid = new_alias_grid(width_tiles, height_tiles, "minimal8:architecture:10,0")
    wall_cycle = ("underworld.wall.a", "underworld.wall.b", "underworld.wall.c", "underworld.wall.d")
    floor_cycle = ("underworld.floor.a", "underworld.floor.b", "underworld.floor.c", "underworld.floor.d")
    rock_cycle = ("underworld.rock.a", "underworld.rock.b", "underworld.rock.c")
    water_cycle = ("underworld.water.a", "underworld.water.b", "underworld.water.c")
    glyph_cycle = ("underworld.glyph.a", "underworld.glyph.b", "underworld.glyph.c")

    for tx in range(12, 28):
        grid[2][tx] = cycle_alias(glyph_cycle, tx)

    for ty in range(5, 21):
        for tx in range(2, 9):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)
        for tx in range(31, 38):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)

    for ty in range(6, 20):
        for tx in range(4, 9):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)
        for tx in range(31, 36):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)

    for tx in range(10, 30):
        grid[4][tx] = cycle_alias(wall_cycle, tx - 10)
        grid[18][tx] = cycle_alias(wall_cycle, tx - 10)
    for ty in range(4, 19):
        grid[ty][10] = "underworld.wall.vertical"
        grid[ty][29] = "underworld.wall.vertical"

    for ty in range(5, 18):
        for tx in range(11, 29):
            grid[ty][tx] = cycle_alias(floor_cycle, tx + ty)

    for tx in range(18, 22):
        grid[4][tx] = "underworld.arch.l" if tx % 2 == 0 else "underworld.arch.r"

    for tx, ty in ((15, 8), (24, 8), (15, 14), (24, 14), (18, 6), (21, 6)):
        grid[ty][tx] = "underworld.pillar.a"
        grid[ty + 1][tx] = "underworld.pillar.b"

    for y in range(8, 15):
        for x in range(15, 25):
            grid[y][x] = "underworld.floor.b" if (x + y) % 2 == 0 else "underworld.floor.c"

    for tx in range(18, 22):
        grid[19][tx] = "underworld.stairs"
        grid[20][tx] = "underworld.stairs"
    for tx in range(16, 24):
        grid[23][tx] = "underworld.glyph.c" if tx % 2 == 0 else "underworld.glyph.b"

    place_alias_block(grid, 19, 11, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 16, 13, ACTOR_BLOCK_ALIASES["blue"])
    place_alias_block(grid, 22, 13, ACTOR_BLOCK_ALIASES["green"])
    place_alias_block(grid, 20, 9, ACTOR_BLOCK_ALIASES["orange"])

    image = paint_alias_grid(tiles, grid)
    output = next_generated_path("20260506-underworld-lantern-descent-v7-strict-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v8_styled_tiles() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    grid = new_alias_grid(width_tiles, height_tiles, "tavern.floor.quiet.base")

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias="tavern.floor.quiet.base",
        sparse_aliases=QUIET_TAVERN_FLOOR_ALIASES,
        pattern_mod=13,
    )

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(("tavern.wall.a", "tavern.wall.b", "tavern.wall.c"), tx)
        grid[height_tiles - 1][tx] = cycle_alias(("tavern.wall.a", "tavern.wall.b", "tavern.wall.c"), tx + 1)
    for ty in range(height_tiles):
        grid[ty][0] = "tavern.trim.v"
        grid[ty][width_tiles - 1] = "tavern.trim.v"

    for tx in range(8, 32):
        grid[2][tx] = "tavern.trim.h"
    place_band_run(grid, 9, 3, 5)
    place_band_run(grid, 26, 3, 5)
    for tx in range(14, 26):
        grid[3][tx] = "tavern.wall.a"
    for tx in range(16, 24):
        grid[4][tx] = "tavern.wall.b"
    grid[3][19] = "tavern.door.l"
    grid[3][20] = "tavern.door.r"

    place_service_run(grid, 9, 8, 22)

    for tx in (12, 17, 23, 28):
        grid[9][tx] = "indoors.seat.tall"
        grid[10][tx] = "indoors.bench.small"

    for tx, ty in ((6, 13), (30, 13), (9, 18), (27, 18)):
        place_dining_cluster(grid, tx, ty)

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    place_alias_block(grid, 19, 5, ACTOR_BLOCK_ALIASES["bartender"])
    place_alias_block(grid, 7, 11, ACTOR_BLOCK_ALIASES["orange"])
    place_alias_block(grid, 17, 15, ACTOR_BLOCK_ALIASES["green"])
    place_alias_block(grid, 22, 15, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 31, 11, ACTOR_BLOCK_ALIASES["teal"])
    place_alias_block(grid, 27, 9, ACTOR_BLOCK_ALIASES["purple"])
    place_alias_block(grid, 18, 21, ACTOR_BLOCK_ALIASES["blue"])

    image = paint_alias_grid(tiles, grid, style_rules=TAVERN_V8_STYLE_RULES)
    output = next_generated_path("20260506-fool-and-flintlock-v8-styled-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v8_styled_tiles() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    grid = new_alias_grid(width_tiles, height_tiles, "minimal8:architecture:10,0")
    wall_cycle = ("underworld.wall.a", "underworld.wall.b", "underworld.wall.c", "underworld.wall.d")
    rock_cycle = ("underworld.rock.a", "underworld.rock.b", "underworld.rock.c")
    water_cycle = ("underworld.water.a", "underworld.water.b", "underworld.water.c")
    glyph_cycle = ("underworld.glyph.a", "underworld.glyph.b", "underworld.glyph.c")

    for tx in range(12, 28):
        grid[2][tx] = cycle_alias(glyph_cycle, tx)

    for ty in range(5, 21):
        for tx in range(2, 9):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)
        for tx in range(31, 38):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)

    for ty in range(6, 20):
        for tx in range(4, 9):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)
        for tx in range(31, 36):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)

    for tx in range(10, 30):
        grid[4][tx] = cycle_alias(wall_cycle, tx - 10)
        grid[18][tx] = cycle_alias(wall_cycle, tx - 10)
    for ty in range(4, 19):
        grid[ty][10] = "underworld.wall.vertical"
        grid[ty][29] = "underworld.wall.vertical"

    paint_quiet_floor(
        grid,
        x0=11,
        y0=5,
        x1=29,
        y1=18,
        base_alias="underworld.floor.quiet.base",
        sparse_aliases=QUIET_UNDERWORLD_FLOOR_ALIASES,
        pattern_mod=11,
    )
    paint_quiet_floor(
        grid,
        x0=15,
        y0=8,
        x1=25,
        y1=15,
        base_alias="underworld.floor.quiet.base",
        sparse_aliases=QUIET_UNDERWORLD_FLOOR_ALIASES,
        pattern_mod=5,
    )

    for tx in range(18, 22):
        grid[4][tx] = "underworld.arch.l" if tx % 2 == 0 else "underworld.arch.r"

    for tx, ty in ((15, 8), (24, 8), (15, 13), (24, 13)):
        grid[ty][tx] = "underworld.pillar.a"
        grid[ty + 1][tx] = "underworld.pillar.b"

    for tx in range(18, 22):
        grid[19][tx] = "underworld.stairs"
        grid[20][tx] = "underworld.stairs"
    for tx in range(17, 23):
        grid[23][tx] = cycle_alias(glyph_cycle, tx + 1)

    place_alias_block(grid, 19, 10, ACTOR_BLOCK_ALIASES["orange"])
    place_alias_block(grid, 17, 12, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 14, 14, ACTOR_BLOCK_ALIASES["blue"])
    place_alias_block(grid, 22, 14, ACTOR_BLOCK_ALIASES["green"])

    image = paint_alias_grid(tiles, grid, style_rules=UNDERWORLD_V8_STYLE_RULES)
    apply_overlays(image, tiles, grid, [(18, 4, "prop.torch"), (21, 4, "prop.torch")])
    output = next_generated_path("20260506-underworld-lantern-descent-v8-styled-tiles.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v9_character_focus() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    wall_cycle = aliases_for_prefix("tavern.wall.", scene="tavern", category="wall", usage="structure")
    quiet_floor = aliases_for_prefix("tavern.floor.quiet.", scene="tavern", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "tavern.floor.quiet.base"
    grid = new_alias_grid(width_tiles, height_tiles, base_floor)

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=19,
    )

    for ty in range(11, 18):
        for tx in range(15, 25):
            grid[ty][tx] = base_floor

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(wall_cycle, tx)
        grid[height_tiles - 1][tx] = cycle_alias(wall_cycle, tx + 1)
    for ty in range(height_tiles):
        grid[ty][0] = "tavern.trim.v"
        grid[ty][width_tiles - 1] = "tavern.trim.v"

    for tx in range(8, 32):
        grid[2][tx] = "tavern.trim.h"
    place_band_run(grid, 9, 3, 5)
    place_band_run(grid, 26, 3, 5)
    for tx in range(14, 26):
        grid[3][tx] = "tavern.wall.a"
    for tx in range(16, 24):
        grid[4][tx] = "tavern.wall.b"
    grid[3][19] = "tavern.door.l"
    grid[3][20] = "tavern.door.r"

    place_service_run(grid, 10, 8, 20)

    for tx in (11, 14, 25, 28):
        grid[9][tx] = "indoors.seat.tall"
        grid[10][tx] = "indoors.bench.small"

    for tx, ty in ((5, 12), (31, 12), (7, 18), (29, 18)):
        place_dining_cluster(grid, tx, ty)

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    place_alias_block(grid, 19, 5, ACTOR_BLOCK_ALIASES["bartender"])
    place_alias_block(grid, 19, 13, ACTOR_BLOCK_ALIASES["gold"])
    place_alias_block(grid, 4, 14, ACTOR_BLOCK_ALIASES["teal"])
    place_alias_block(grid, 32, 14, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 30, 9, ACTOR_BLOCK_ALIASES["purple"])

    image = paint_alias_grid(tiles, grid, style_rules=TAVERN_V8_STYLE_RULES)
    output = next_generated_path("20260506-fool-and-flintlock-v9-character-focus.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v9_character_focus() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    grid = new_alias_grid(width_tiles, height_tiles, "minimal8:architecture:10,0")
    wall_cycle = aliases_for_prefix("underworld.wall.", scene="underworld", category="wall", usage="structure")
    rock_cycle = aliases_for_prefix("underworld.rock.", scene="underworld", category="rock", usage="background")
    water_cycle = aliases_for_prefix("underworld.water.", scene="underworld", category="water", usage="background")
    glyph_cycle = aliases_for_prefix("underworld.glyph.", scene="underworld", category="glyph", usage="accent")
    quiet_floor = aliases_for_prefix("underworld.floor.quiet.", scene="underworld", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "underworld.floor.quiet.base"

    for tx in range(12, 28):
        grid[2][tx] = cycle_alias(glyph_cycle, tx)

    for ty in range(5, 21):
        for tx in range(2, 9):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)
        for tx in range(31, 38):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)

    for ty in range(6, 20):
        for tx in range(4, 9):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)
        for tx in range(31, 36):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)

    for tx in range(10, 30):
        grid[4][tx] = cycle_alias(wall_cycle, tx - 10)
        grid[18][tx] = cycle_alias(wall_cycle, tx - 10)
    for ty in range(4, 19):
        grid[ty][10] = "underworld.wall.vertical"
        grid[ty][29] = "underworld.wall.vertical"

    paint_quiet_floor(
        grid,
        x0=11,
        y0=5,
        x1=29,
        y1=18,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=17,
    )
    for ty in range(9, 16):
        for tx in range(16, 24):
            grid[ty][tx] = base_floor
    for ty in range(6, 18):
        if ty != 12:
            grid[ty][20] = cycle_alias(quiet_sparse, ty)

    for tx in range(18, 22):
        grid[4][tx] = "underworld.arch.l" if tx % 2 == 0 else "underworld.arch.r"

    for tx, ty in ((15, 8), (24, 8), (15, 13), (24, 13)):
        grid[ty][tx] = "underworld.pillar.a"
        grid[ty + 1][tx] = "underworld.pillar.b"

    for tx in range(18, 22):
        grid[19][tx] = "underworld.stairs"
        grid[20][tx] = "underworld.stairs"
    for tx in range(17, 23):
        grid[23][tx] = cycle_alias(glyph_cycle, tx + 1)

    place_alias_block(grid, 19, 11, ACTOR_BLOCK_ALIASES["gold"])
    place_alias_block(grid, 19, 7, ACTOR_BLOCK_ALIASES["orange"])
    place_alias_block(grid, 13, 15, ACTOR_BLOCK_ALIASES["blue"])
    place_alias_block(grid, 24, 15, ACTOR_BLOCK_ALIASES["green"])

    image = paint_alias_grid(tiles, grid, style_rules=UNDERWORLD_V8_STYLE_RULES)
    apply_overlays(image, tiles, grid, [(18, 4, "prop.torch"), (21, 4, "prop.torch")])
    output = next_generated_path("20260506-underworld-lantern-descent-v9-character-focus.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v10_clean_focus() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    wall_cycle = aliases_for_prefix("tavern.wall.", scene="tavern", category="wall", usage="structure")
    quiet_floor = aliases_for_prefix("tavern.floor.quiet.", scene="tavern", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "tavern.floor.quiet.base"
    grid = new_alias_grid(width_tiles, height_tiles, base_floor)

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=23,
    )

    for ty in range(11, 18):
        for tx in range(16, 24):
            grid[ty][tx] = base_floor
    for ty in range(9, 15):
        for tx in range(10, 30):
            grid[ty][tx] = base_floor

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(wall_cycle, tx)
        grid[height_tiles - 1][tx] = cycle_alias(wall_cycle, tx + 1)
    for ty in range(height_tiles):
        grid[ty][0] = "tavern.trim.v"
        grid[ty][width_tiles - 1] = "tavern.trim.v"

    # Continuous back wall with no gaps.
    for tx in range(8, 32):
        grid[2][tx] = "tavern.trim.h"
        grid[3][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx - 8)
        grid[4][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx - 4)
    for ty in range(4, 7):
        grid[ty][8] = "minimal8:architecture:0,8"
        grid[ty][31] = "minimal8:architecture:1,8"

    # Bar as one consecutive run rather than mixed end-table pieces.
    grid[7][10] = TAVERN_BAR_TOP_LEFT
    grid[7][29] = TAVERN_BAR_TOP_RIGHT
    grid[8][10] = TAVERN_BAR_SUPPORT_LEFT
    grid[8][29] = TAVERN_BAR_SUPPORT_RIGHT
    for tx in range(11, 29):
        grid[7][tx] = "indoors.table.long.left" if tx % 2 == 0 else TAVERN_BAR_TOP_MIDDLE
        grid[8][tx] = TAVERN_BAR_SUPPORT_MIDDLE

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    # Table clusters to make the room feel inhabited rather than empty.
    for tx, ty in ((4, 13), (30, 13), (7, 18), (27, 18)):
        grid[ty][tx] = "indoors.table.round"
        grid[ty][tx + 1] = "indoors.table.long.right"
        grid[ty + 1][tx] = TAVERN_BAR_SUPPORT_LEFT
        grid[ty + 1][tx + 1] = TAVERN_BAR_SUPPORT_MIDDLE

    # One obvious protagonist in the middle; only one bartender on the bar.
    place_alias_block(grid, 19, 14, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 24, 5, ACTOR_BLOCK_ALIASES["bartender"])
    place_alias_block(grid, 5, 15, ACTOR_BLOCK_ALIASES["teal"])
    place_alias_block(grid, 31, 15, ACTOR_BLOCK_ALIASES["blue"])

    image = paint_alias_grid(tiles, grid, style_rules=TAVERN_V8_STYLE_RULES)
    output = next_generated_path("20260506-fool-and-flintlock-v10-clean-focus.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v11_single_sprites() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    wall_cycle = aliases_for_prefix("tavern.wall.", scene="tavern", category="wall", usage="structure")
    quiet_floor = aliases_for_prefix("tavern.floor.quiet.", scene="tavern", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "tavern.floor.quiet.base"
    grid = new_alias_grid(width_tiles, height_tiles, base_floor)

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=29,
    )

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(wall_cycle, tx)
        grid[height_tiles - 1][tx] = cycle_alias(wall_cycle, tx + 1)
    for ty in range(height_tiles):
        grid[ty][0] = "tavern.trim.v"
        grid[ty][width_tiles - 1] = "tavern.trim.v"

    for tx in range(6, 34):
        grid[2][tx] = "tavern.trim.h"
        grid[3][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx - 6)
        grid[4][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx - 2)
        grid[5][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx + 1)
        grid[6][tx] = cycle_alias(TAVERN_SOLID_BACK_WALL_CYCLE, tx + 4)
    for ty in range(3, 7):
        grid[ty][6] = "minimal8:architecture:0,8"
        grid[ty][33] = "minimal8:architecture:1,8"

    for tx in range(10, 31):
        if tx == 10:
            grid[8][tx] = TAVERN_BAR_TOP_LEFT
        elif tx == 30:
            grid[8][tx] = TAVERN_BAR_TOP_RIGHT
        else:
            grid[8][tx] = "indoors.table.long.left" if tx % 2 == 0 else TAVERN_BAR_TOP_MIDDLE

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    for start_x, start_y, width in ((4, 13, 3), (30, 13, 3), (8, 18, 4), (24, 18, 4), (16, 20, 3)):
        for offset in range(width):
            tx = start_x + offset
            if offset == 0:
                grid[start_y][tx] = "indoors.table.round"
            elif offset == width - 1:
                grid[start_y][tx] = "indoors.table.long.right"
            else:
                grid[start_y][tx] = "indoors.table.long.left"

    hero_ref = "minimal8:characters:2,3"
    bartender_ref = "minimal8:characters:10,3"
    grid[15][20] = hero_ref
    grid[6][25] = bartender_ref

    tavern_style_rules = dict(TAVERN_V8_STYLE_RULES)
    tavern_style_rules[bartender_ref] = TileStyle(foreground=rgba(DEEP_VIOLET))

    image = paint_alias_grid(tiles, grid, style_rules=tavern_style_rules)

    output = next_generated_path("20260506-fool-and-flintlock-v11-single-sprites.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v12_sheet_vocab() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    quiet_floor = aliases_for_prefix("tavern.floor.quiet.", scene="tavern", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "tavern.floor.quiet.base"
    grid = new_alias_grid(width_tiles, height_tiles, base_floor)

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=31,
    )

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(TAVERN_TOP_WALL_CYCLE, tx)
        grid[height_tiles - 1][tx] = cycle_alias(TAVERN_TOP_WALL_CYCLE, tx + 1)
    for ty in range(1, height_tiles - 1):
        grid[ty][0] = cycle_alias(TAVERN_SIDE_WALL_CYCLE, ty - 1)
        grid[ty][width_tiles - 1] = cycle_alias(TAVERN_SIDE_WALL_CYCLE, ty + 1)

    for tx in range(7, 33):
        grid[2][tx] = "tavern.trim.h"
    for ty in range(3, 8):
        grid[ty][7] = "minimal8:architecture:0,8"
        grid[ty][32] = "minimal8:architecture:1,8"

    for tx in range(8, 32):
        grid[3][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_A, tx - 8)
        grid[4][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_B, tx - 8)
        grid[5][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_A, tx - 6)
        grid[6][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_B, tx - 6)

    place_band_run(grid, 11, 5, 18)
    place_band_run(grid, 13, 6, 14)

    place_service_run(grid, 10, 8, 21)

    for tx in range(17, 23):
        grid[24][tx] = "tavern.door.l" if tx % 2 == 1 else "tavern.door.r"

    place_dining_cluster(grid, 6, 13)
    place_dining_cluster(grid, 27, 13)
    place_dining_cluster(grid, 10, 18)
    place_dining_cluster(grid, 23, 18)
    place_long_table_run(grid, 17, 21, 3)

    hero_ref = "minimal8:characters:2,3"
    bartender_ref = "minimal8:characters:10,3"
    grid[15][20] = hero_ref
    grid[7][24] = bartender_ref

    tavern_style_rules = dict(TAVERN_V8_STYLE_RULES)
    tavern_style_rules[bartender_ref] = TileStyle(foreground=rgba(DEEP_VIOLET))
    for alias in INDOORS_BAND_RUN:
        tavern_style_rules[alias] = TileStyle(foreground=rgba(BLACK_TEAL), background=rgba(SLATE_TEAL))

    image = paint_alias_grid(tiles, grid, style_rules=tavern_style_rules)
    output = next_generated_path("20260506-fool-and-flintlock-v12-sheet-vocab.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_tavern_v13_layout_cleanup() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    quiet_floor = aliases_for_prefix("tavern.floor.quiet.", scene="tavern", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "tavern.floor.quiet.base"
    grid = new_alias_grid(width_tiles, height_tiles, base_floor)

    paint_quiet_floor(
        grid,
        x0=1,
        y0=1,
        x1=width_tiles - 1,
        y1=height_tiles - 1,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=31,
    )

    for tx in range(width_tiles):
        grid[0][tx] = cycle_alias(TAVERN_TOP_WALL_CYCLE, tx)
        grid[height_tiles - 1][tx] = cycle_alias(TAVERN_TOP_WALL_CYCLE, tx + 1)
    for ty in range(1, height_tiles - 1):
        grid[ty][0] = cycle_alias(TAVERN_SIDE_WALL_CYCLE, ty - 1)
        grid[ty][width_tiles - 1] = cycle_alias(TAVERN_SIDE_WALL_CYCLE, ty + 1)

    for tx in range(7, 33):
        grid[2][tx] = "tavern.trim.h"
    for ty in range(3, 8):
        grid[ty][7] = "minimal8:architecture:0,8"
        grid[ty][32] = "minimal8:architecture:1,8"

    for tx in range(8, 32):
        grid[3][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_A, tx - 8)
        grid[4][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_B, tx - 8)
        grid[5][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_A, tx - 6)
        grid[6][tx] = cycle_alias(TAVERN_BACK_WALL_CYCLE_B, tx - 6)

    place_band_run(grid, 13, 5, 16)
    place_band_run(grid, 16, 6, 12)

    # Hidden stairwell behind the bar on the left.
    grid[5][9] = "indoors.stairs.up"
    grid[5][10] = "indoors.stairs.down"
    grid[6][10] = "indoors.stairs.up"
    grid[6][11] = "indoors.stairs.down"

    # Long continuous bar: one left end, one right end, no interior endcaps.
    place_service_run(grid, 10, 8, 21)

    # Front door in the south wall using the two normal-sized door tiles.
    grid[24][19] = "indoors.door.small.open"
    grid[24][20] = "indoors.door.small.closed"

    # Tables for patrons.
    place_dining_cluster(grid, 6, 13)
    place_dining_cluster(grid, 27, 13)
    place_dining_cluster(grid, 10, 18)
    place_dining_cluster(grid, 23, 18)

    hero_ref = "minimal8:characters:2,3"
    bartender_ref = "minimal8:characters:10,3"
    patrons = {
        (7, 12): "minimal8:characters:1,9",
        (7, 14): "minimal8:characters:13,5",
        (28, 12): "minimal8:characters:4,10",
        (28, 14): "minimal8:characters:10,6",
        (11, 17): "minimal8:characters:13,11",
        (24, 17): "minimal8:characters:10,10",
        (26, 9): "minimal8:characters:10,4",
    }

    grid[15][20] = hero_ref
    grid[7][25] = bartender_ref
    for (tx, ty), ref in patrons.items():
        grid[ty][tx] = ref

    tavern_style_rules = dict(TAVERN_V8_STYLE_RULES)
    tavern_style_rules[bartender_ref] = TileStyle(foreground=rgba(DEEP_VIOLET))
    for alias in INDOORS_BAND_RUN:
        tavern_style_rules[alias] = TileStyle(foreground=rgba(BLACK_TEAL), background=rgba(SLATE_TEAL))

    image = paint_alias_grid(tiles, grid, style_rules=tavern_style_rules)
    output = next_generated_path("20260506-fool-and-flintlock-v13-layout-cleanup.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_underworld_v10_clean_focus() -> Path:
    tiles = Minimal8()
    width_tiles = 40
    height_tiles = 25
    grid = new_alias_grid(width_tiles, height_tiles, "minimal8:architecture:10,0")
    wall_cycle = aliases_for_prefix("underworld.wall.", scene="underworld", category="wall", usage="structure")
    rock_cycle = aliases_for_prefix("underworld.rock.", scene="underworld", category="rock", usage="background")
    water_cycle = aliases_for_prefix("underworld.water.", scene="underworld", category="water", usage="background")
    glyph_cycle = aliases_for_prefix("underworld.glyph.", scene="underworld", category="glyph", usage="accent")
    quiet_floor = aliases_for_prefix("underworld.floor.quiet.", scene="underworld", category="floor", usage="background", contrast="low")
    quiet_sparse = tuple(alias for alias in quiet_floor if ".sparse." in alias)
    base_floor = "underworld.floor.quiet.base"

    for tx in range(12, 28):
        grid[2][tx] = cycle_alias(glyph_cycle, tx)

    for ty in range(5, 21):
        for tx in range(2, 9):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)
        for tx in range(31, 38):
            grid[ty][tx] = cycle_alias(rock_cycle, tx + ty)

    for ty in range(6, 20):
        for tx in range(4, 9):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)
        for tx in range(31, 36):
            grid[ty][tx] = cycle_alias(water_cycle, tx + ty)

    for tx in range(10, 30):
        grid[4][tx] = cycle_alias(wall_cycle, tx - 10)
        grid[18][tx] = cycle_alias(wall_cycle, tx - 10)
    for ty in range(4, 19):
        grid[ty][10] = "underworld.wall.vertical"
        grid[ty][29] = "underworld.wall.vertical"

    paint_quiet_floor(
        grid,
        x0=11,
        y0=5,
        x1=29,
        y1=18,
        base_alias=base_floor,
        sparse_aliases=quiet_sparse,
        pattern_mod=19,
    )
    for ty in range(9, 16):
        for tx in range(16, 24):
            grid[ty][tx] = base_floor

    for tx in range(18, 22):
        grid[4][tx] = "underworld.arch.l" if tx % 2 == 0 else "underworld.arch.r"

    for tx, ty in ((15, 8), (24, 8), (15, 13), (24, 13)):
        grid[ty][tx] = "underworld.pillar.a"
        grid[ty + 1][tx] = "underworld.pillar.b"

    for tx in range(18, 22):
        grid[19][tx] = "underworld.stairs"
        grid[20][tx] = "underworld.stairs"
    for tx in range(17, 23):
        grid[23][tx] = cycle_alias(glyph_cycle, tx + 1)

    # One clear center-stage protagonist.
    place_alias_block(grid, 19, 11, ACTOR_BLOCK_ALIASES["red"])
    place_alias_block(grid, 13, 7, ACTOR_BLOCK_ALIASES["orange"])
    place_alias_block(grid, 13, 15, ACTOR_BLOCK_ALIASES["blue"])
    place_alias_block(grid, 24, 15, ACTOR_BLOCK_ALIASES["green"])

    image = paint_alias_grid(tiles, grid, style_rules=UNDERWORLD_V8_STYLE_RULES)
    apply_overlays(image, tiles, grid, [(18, 4, "prop.torch"), (21, 4, "prop.torch")])
    output = next_generated_path("20260506-underworld-lantern-descent-v10-clean-focus.png")
    _resize_nearest(image, (image.width * 4, image.height * 4)).save(output)
    return output


def render_catalog_vocabulary_board() -> Path:
    tiles = Minimal8()
    sections = [
        ("TAVERN FLOOR", query_tile_images(tiles, tags_all=("scene:tavern", "semantic:floor"), walkable=True)),
        ("TAVERN FIX", query_tile_images(tiles, tags_any=("semantic:band", "semantic:seat", "semantic:storage", "semantic:table"), layer="map")),
        ("UNDER WALL", query_tile_images(tiles, tags_all=("scene:underworld", "semantic:wall"), layer="map")),
        ("UNDER TERR", query_tile_images(tiles, tags_any=("semantic:water", "semantic:rock", "semantic:glyph"), layer="map")),
        ("DOOR/PROP", query_tile_images(tiles, category="door", layer="map") + query_tile_images(tiles, tags_all=("semantic:torch",), layer=None)),
    ]

    panel_w = 160
    panel_h = 56
    gap = 8
    image = Image.new("RGBA", (panel_w * 2 + gap * 3, panel_h * 3 + gap * 4), rgba(PLUM))
    draw = ImageDraw.Draw(image)

    for index, (title, items) in enumerate(sections):
        px = gap + (index % 2) * (panel_w + gap)
        py = gap + (index // 2) * (panel_h + gap)
        draw_frame(draw, px, py, panel_w, panel_h, rgba(CREAM))
        draw_bitmap_text(draw, px + 6, py + 4, title, rgba(CREAM), spacing=0)
        for item_index, (_, tile_image) in enumerate(items[:10]):
            tx = px + 6 + (item_index % 5) * 28
            ty = py + 16 + (item_index // 5) * 20
            preview = _resize_nearest(tile_image, (16, 16))
            image.alpha_composite(preview, (tx, ty))

    output = next_generated_path("20260506-catalog-vocabulary-board-v1.png")
    _resize_nearest(image, (image.width * 3, image.height * 3)).save(output)
    return output


def render_catalog_tavern_sample() -> Path:
    tiles = Minimal8()
    chars = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}
    floor_tiles = query_tile_images(tiles, tags_all=("scene:tavern", "semantic:floor"), walkable=True)
    wall_tiles = query_tile_images(tiles, tags_all=("scene:tavern", "semantic:wall"), blocking=True)
    band_tiles = [raw_tile_from_alias(tiles, alias) for alias in INDOORS_BAND_RUN]
    service_left = raw_tile_from_alias(tiles, "indoors.table.long.left")
    service_middle = raw_tile_from_alias(tiles, "indoors.table.long.middle")
    service_right = raw_tile_from_alias(tiles, "indoors.table.long.right")
    seat_tall = raw_tile_from_alias(tiles, "indoors.seat.tall")
    bench_small = raw_tile_from_alias(tiles, "indoors.bench.small")
    torch_tiles = query_tile_images(tiles, tags_all=("semantic:torch",), layer=None)

    width_tiles = 24
    height_tiles = 16
    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 255))

    for ty in range(height_tiles):
        for tx in range(width_tiles):
            paste_tile(image, cycle_image(floor_tiles, tx + ty), tx, ty)

    for tx in range(width_tiles):
        paste_tile(image, cycle_image(wall_tiles, tx), tx, 0)
        paste_tile(image, cycle_image(wall_tiles, tx + 1), tx, height_tiles - 1)
    trim_v = raw_tile_from_alias(tiles, "tavern.trim.v")
    trim_h = raw_tile_from_alias(tiles, "tavern.trim.h")
    for ty in range(height_tiles):
        paste_tile(image, trim_v, 0, ty)
        paste_tile(image, trim_v, width_tiles - 1, ty)
    for tx in range(5, 19):
        paste_tile(image, trim_h, tx, 2)

    for tx in range(6, 11):
        paste_tile(image, band_tiles[(tx - 6) % len(band_tiles)], tx, 3)
    for tx in range(13, 18):
        paste_tile(image, band_tiles[(tx - 13) % len(band_tiles)], tx, 3)
    for tx in range(11, 13):
        paste_tile(image, cycle_image(wall_tiles, tx), tx, 3)
        paste_tile(image, cycle_image(wall_tiles, tx + 1), tx, 4)

    paste_tile(image, service_left, 5, 7)
    for tx in range(6, 18):
        paste_tile(image, service_middle, tx, 7)
    paste_tile(image, service_right, 18, 7)

    for tx in (7, 10, 13, 16):
        paste_tile(image, seat_tall, tx, 8)
        paste_tile(image, bench_small, tx, 9)

    for tx, ty in ((4, 11), (8, 12), (17, 11), (19, 12)):
        paste_tile(image, service_left, tx, ty)
        paste_tile(image, service_middle, tx + 1, ty)
        paste_tile(image, service_right, tx + 2, ty)
        paste_tile(image, seat_tall, tx + 1, ty - 1)
        paste_tile(image, bench_small, tx + 1, ty + 1)

    for tx in range(10, 14):
        paste_tile(image, raw_tile_from_alias(tiles, "tavern.door.l" if tx % 2 == 0 else "tavern.door.r"), tx, height_tiles - 1)

    for tx in (3, 20):
        paste_tile(image, cycle_image(torch_tiles, tx), tx, 2)

    for name, tx, ty in (
        ("char_bartender", 12, 5),
        ("char_green", 11, 10),
        ("char_red", 13, 10),
        ("char_teal", 20, 9),
        ("char_orange", 6, 9),
    ):
        image.alpha_composite(chars[name], (tx * 8, ty * 8))

    output = next_generated_path("20260506-catalog-tavern-sample-v1.png")
    _resize_nearest(image, (image.width * 5, image.height * 5)).save(output)
    return output


def render_catalog_underworld_sample() -> Path:
    tiles = Minimal8()
    chars = {name: tiles.transparent_crop(crop) for name, crop in ASSETS.items()}
    floor_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:floor"), walkable=True)
    wall_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:wall"), blocking=True)
    rock_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:rock"), blocking=True)
    water_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:water"), blocking=True)
    glyph_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:glyph"), blocking=True)
    pillar_tiles = query_tile_images(tiles, tags_all=("scene:underworld", "semantic:pillar"), blocking=True)

    width_tiles = 24
    height_tiles = 18
    image = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 255))

    void = raw_tile_from_meta(tiles, _get_catalog().by_id("minimal8:architecture:10,0"))
    for ty in range(height_tiles):
        for tx in range(width_tiles):
            paste_tile(image, void, tx, ty)

    for tx in range(7, 17):
        paste_tile(image, cycle_image(glyph_tiles, tx), tx, 1)

    for ty in range(3, 15):
        for tx in range(1, 5):
            paste_tile(image, cycle_image(rock_tiles, tx + ty), tx, ty)
        for tx in range(19, 23):
            paste_tile(image, cycle_image(rock_tiles, tx + ty), tx, ty)
    for ty in range(4, 14):
        for tx in range(2, 5):
            paste_tile(image, cycle_image(water_tiles, tx + ty), tx, ty)
        for tx in range(19, 22):
            paste_tile(image, cycle_image(water_tiles, tx + ty), tx, ty)

    for tx in range(6, 18):
        paste_tile(image, cycle_image(wall_tiles, tx), tx, 3)
        paste_tile(image, cycle_image(wall_tiles, tx + 1), tx, 14)
    for ty in range(3, 15):
        paste_tile(image, raw_tile_from_alias(tiles, "underworld.wall.vertical"), 6, ty)
        paste_tile(image, raw_tile_from_alias(tiles, "underworld.wall.vertical"), 17, ty)

    for ty in range(4, 14):
        for tx in range(7, 17):
            paste_tile(image, cycle_image(floor_tiles, tx + ty), tx, ty)

    for tx, ty in ((9, 5), (14, 5), (9, 11), (14, 11)):
        top = cycle_image(pillar_tiles, tx + ty)
        bottom = cycle_image(pillar_tiles, tx + ty + 1)
        paste_tile(image, top, tx, ty)
        paste_tile(image, bottom, tx, ty + 1)

    for tx in range(10, 14):
        paste_tile(image, raw_tile_from_alias(tiles, "underworld.stairs"), tx, 15)
    for tx in range(9, 15):
        paste_tile(image, cycle_image(glyph_tiles, tx), tx, 17)

    for name, tx, ty in (
        ("char_red", 11, 8),
        ("char_blue", 10, 10),
        ("char_green", 13, 10),
        ("char_orange", 12, 7),
    ):
        image.alpha_composite(chars[name], (tx * 8, ty * 8))

    output = next_generated_path("20260506-catalog-underworld-sample-v1.png")
    _resize_nearest(image, (image.width * 5, image.height * 5)).save(output)
    return output


def print_catalog_summary() -> None:
    catalog = _get_catalog()
    summary = catalog.summary()
    print(summary)
    print("sample tavern floor ids:", [tile.id for tile in catalog.query(tags_all=("scene:tavern", "semantic:floor"))[:6]])
    print("sample underworld walls:", [tile.id for tile in catalog.query(tags_all=("scene:underworld", "semantic:wall"))[:6]])
    print(
        "quiet tavern floor aliases:",
        catalog.aliases_for(scene="tavern", category="floor", usage="background", contrast="low", style="quiet")[:12],
    )
    print(
        "warm tavern fixtures:",
        catalog.aliases_for(scene="tavern", usage="fixture", temperature="warm")[:12],
    )
    print(
        "validated overlays:",
        catalog.aliases_for(usage="overlay", overlay="allowed"),
    )
    print("aliases:", sorted(list(catalog.aliases))[:12], "...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local workflow for Minimal 8-based Pistols at Dusk mockups.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("atlas", help="Export local atlas and grid inspection images under the experiment scratch.local/mockups/minimal8/ folder.")
    sub.add_parser("reference-temple-study-v1", help="Render a local study that recreates the polychrome temple reference composition.")
    sub.add_parser("reference-temple-study-v2", help="Render a tighter second-pass polychrome temple reconstruction.")
    sub.add_parser("reference-temple-study-v3", help="Render a guide-locked temple reconstruction from the base reference.")
    sub.add_parser("reference-temple-template-exact", help="Export an exact upscaled template from the temple base guide.")
    sub.add_parser("reference-hud-room-study-v1", help="Render a local study that recreates the gold-box HUD room reference composition.")
    sub.add_parser("reference-hud-room-study-v2", help="Render a cleaner second-pass gold-box HUD room reference study.")
    sub.add_parser("reference-hud-room-study-v3", help="Render a tighter third-pass gold-box HUD room reconstruction.")
    sub.add_parser("reference-hud-room-study-v4", help="Render a guide-locked HUD room reconstruction from the base reference.")
    sub.add_parser("reference-hud-room-template-exact", help="Export an exact upscaled template from the HUD base guide.")
    sub.add_parser("tavern-v3-template", help="Render a Fool & Flintlock tavern pass derived from the HUD-room template.")
    sub.add_parser("underworld-v3-template", help="Render an underworld lantern-descent pass derived from the temple template.")
    sub.add_parser("tavern-v4-map", help="Render a coherent tavern map on a strict 8x8 grid.")
    sub.add_parser("underworld-v4-map", help="Render a coherent underworld map on a strict 8x8 grid.")
    sub.add_parser("tavern-v5-map", help="Render a larger 40x25 tavern map on a strict 8x8 grid.")
    sub.add_parser("underworld-v5-map", help="Render a larger 40x25 underworld map on a strict 8x8 grid.")
    sub.add_parser("tavern-v6-exact", help="Render a tavern map using only exact 8x8 atlas tiles and grid-aligned sprites.")
    sub.add_parser("underworld-v6-exact", help="Render an underworld map using only exact 8x8 atlas tiles and grid-aligned sprites.")
    sub.add_parser("tavern-v7-strict", help="Render a tavern map with strict single-owner 8x8 cell occupancy.")
    sub.add_parser("underworld-v7-strict", help="Render an underworld map with strict single-owner 8x8 cell occupancy.")
    sub.add_parser("tavern-v8-styled", help="Render a quieter tavern scene with styled floor tiles and validated decor overlays.")
    sub.add_parser("underworld-v8-styled", help="Render a quieter underworld scene with styled floor tiles and validated decor overlays.")
    sub.add_parser("tavern-v9-character-focus", help="Render a tavern scene with a central focal protagonist and calmer staging.")
    sub.add_parser("underworld-v9-character-focus", help="Render an underworld scene with a central focal protagonist and calmer staging.")
    sub.add_parser("tavern-v10-clean-focus", help="Render a cleaner tavern with continuous bar/walls and a single clear protagonist.")
    sub.add_parser("tavern-v11-single-sprites", help="Render a tavern with one protagonist, one purple bartender, and single-sprite 2x2 actors.")
    sub.add_parser("tavern-v12-sheet-vocab", help="Render a tavern using sheet-native shelf, counter, table, and stool vocabulary.")
    sub.add_parser("tavern-v13-layout-cleanup", help="Render a tavern with a coherent bar, patrons, front door, and hidden stairwell.")
    sub.add_parser("underworld-v10-clean-focus", help="Render a cleaner underworld with one clear central protagonist.")
    sub.add_parser("catalog-summary", help="Print a summary of the exhaustive tile catalogue and sample semantic queries.")
    sub.add_parser("catalog-vocab-board", help="Render a vocabulary board from semantic catalogue queries.")
    sub.add_parser("catalog-tavern-sample", help="Render a tavern sample composed via semantic catalogue queries.")
    sub.add_parser("catalog-underworld-sample", help="Render an underworld sample composed via semantic catalogue queries.")
    sub.add_parser("tavern-v2", help="Render a corrected tavern mockup under this experiment's generated/mockups/")
    sub.add_parser("underworld-v2", help="Render a corrected underworld mockup under this experiment's generated/mockups/")
    args = parser.parse_args()

    if args.command == "atlas":
        export_atlas()
        print(WORK_DIR)
    elif args.command == "reference-temple-study-v1":
        print(render_reference_temple_study_v1())
    elif args.command == "reference-temple-study-v2":
        print(render_reference_temple_study_v2())
    elif args.command == "reference-temple-study-v3":
        print(render_reference_temple_study_v3())
    elif args.command == "reference-temple-template-exact":
        print(render_reference_temple_template_exact())
    elif args.command == "reference-hud-room-study-v1":
        print(render_reference_hud_room_study_v1())
    elif args.command == "reference-hud-room-study-v2":
        print(render_reference_hud_room_study_v2())
    elif args.command == "reference-hud-room-study-v3":
        print(render_reference_hud_room_study_v3())
    elif args.command == "reference-hud-room-study-v4":
        print(render_reference_hud_room_study_v4())
    elif args.command == "reference-hud-room-template-exact":
        print(render_reference_hud_room_template_exact())
    elif args.command == "tavern-v3-template":
        print(render_tavern_v3_from_template())
    elif args.command == "underworld-v3-template":
        print(render_underworld_v3_from_template())
    elif args.command == "tavern-v4-map":
        print(render_tavern_v4_grid())
    elif args.command == "underworld-v4-map":
        print(render_underworld_v4_grid())
    elif args.command == "tavern-v5-map":
        print(render_tavern_v5_large_map())
    elif args.command == "underworld-v5-map":
        print(render_underworld_v5_large_map())
    elif args.command == "tavern-v6-exact":
        print(render_tavern_v6_exact_tiles())
    elif args.command == "underworld-v6-exact":
        print(render_underworld_v6_exact_tiles())
    elif args.command == "tavern-v7-strict":
        print(render_tavern_v7_strict_tiles())
    elif args.command == "underworld-v7-strict":
        print(render_underworld_v7_strict_tiles())
    elif args.command == "tavern-v8-styled":
        print(render_tavern_v8_styled_tiles())
    elif args.command == "underworld-v8-styled":
        print(render_underworld_v8_styled_tiles())
    elif args.command == "tavern-v9-character-focus":
        print(render_tavern_v9_character_focus())
    elif args.command == "underworld-v9-character-focus":
        print(render_underworld_v9_character_focus())
    elif args.command == "tavern-v10-clean-focus":
        print(render_tavern_v10_clean_focus())
    elif args.command == "tavern-v11-single-sprites":
        print(render_tavern_v11_single_sprites())
    elif args.command == "tavern-v12-sheet-vocab":
        print(render_tavern_v12_sheet_vocab())
    elif args.command == "tavern-v13-layout-cleanup":
        print(render_tavern_v13_layout_cleanup())
    elif args.command == "underworld-v10-clean-focus":
        print(render_underworld_v10_clean_focus())
    elif args.command == "catalog-summary":
        print_catalog_summary()
    elif args.command == "catalog-vocab-board":
        print(render_catalog_vocabulary_board())
    elif args.command == "catalog-tavern-sample":
        print(render_catalog_tavern_sample())
    elif args.command == "catalog-underworld-sample":
        print(render_catalog_underworld_sample())
    elif args.command == "tavern-v2":
        print(render_tavern_v2())
    elif args.command == "underworld-v2":
        print(render_underworld_v2())


if __name__ == "__main__":
    main()
