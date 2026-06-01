#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal, Mapping, Sequence, TypedDict, TypeVar, Union, cast

from typing_extensions import NotRequired, TypeAlias

from PIL import Image, ImageDraw, ImageOps

from prototype_output import create_staging_output_path, publish_staged_output
from scene_rules import (
    SceneRulesetLibrary,
    SceneRulesetSpec,
    SceneRuleSceneCandidate,
    SceneRuleStampCandidate,
    load_scene_ruleset_library,
)
from scene_templates import (
    AsciiOp,
    BoxOp,
    FillOp,
    MaskFillOp,
    RepeatOp,
    ScatterOp,
    SceneEntityRequest,
    SceneLayers,
    SceneOp,
    SceneTemplate,
    SceneTemplateLibrary,
    SceneTemplateSpec,
    detect_scene_template_cycles,
    expand_data_scene,
    load_scene_template_library,
    SceneTemplateRuntime,
    StampOp,
    TileRefToken,
    validate_scene_template_input,
)
from tile_families import (
    ConstructionAttachmentSet,
    EntityTemplateRecord,
    LoadedTileLibraryUnit,
    MetatileConstruction,
    ParametricRunConstruction,
    ResolvedFamilyTile,
    SheetCell,
    SourceLayoutCollection,
    SourceLayoutCollectionMember,
    SourceLayoutIngestion,
    TileFamily,
    TileFamilyIngestReport,
    TileLibraryUnit,
    TileLibraryRegistry,
    TileClusterRecord,
    TileRecord,
    RuntimeConstructionCatalog,
    bootstrap_family as bootstrap_tile_family,
    collection_member_ref,
    collection_member_to_config,
    compute_non_empty_tile_mask,
    compute_source_layout_coverage,
    detect_source_layout,
)
from source_manifest_bridge import load_bridged_tile_family
from _manifest_utils import GridBounds


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / "prototypes/minimal8-harness/project.minimal8.json"
DEFAULT_LAYOUTS_DIR = ROOT / "prototypes/minimal8-harness/layouts"
DEFAULT_OUTPUT_DIR = ROOT / "prototypes/minimal8-harness/generated"
DEFAULT_INSPECT_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/inspect"
DEFAULT_SCENE_RUNTIME_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/scene-runtime"
DEFAULT_TILED_KIT_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/tiled-kit"
DEFAULT_REVIEW_PACK_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/review-packs"
DEFAULT_COLLECTION_REVIEW_DIR = ROOT / "prototypes/minimal8-harness/reviews/collections"
DEFAULT_COLLECTION_REVIEW_SCRATCH_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/review-collections"
DEFAULT_PUBLIC_TILE_PACK_DIR = ROOT / "prototypes/minimal8-harness/scratch.local/public-tile-packs"

COORD_RE = re.compile(r"^(?P<col>\d+),(?P<row>\d+)$")
TILESET_COORD_RE = re.compile(r"^(?P<tileset>[a-z0-9_.@-]+)#(?P<col>\d+),(?P<row>\d+)$")
VALID_EDGE_MODES = {"seamless", "padded"}
DEFAULT_LAYER_ORDER = [
    "water",
    "backdrop",
    "terrain",
    "detail",
    "rooms",
    "architecture",
    "island",
    "prefabs_back",
    "ornament",
    "actors",
    "prefabs_front",
    "hud",
]

VALID_OCCLUSION_MODES = frozenset({"alpha", "fill_holes", "fill_cell"})


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def _resize_nearest(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    resize = cast(Callable[[tuple[int, int], int], Image.Image], getattr(image, "resize"))
    return resize(size, Image.Resampling.NEAREST)


class ProjectGridConfig(TypedDict, total=False):
    tile_width: int
    tile_height: int
    render_step_width: int
    render_step_height: int


class ProjectTileFamilyConfig(TypedDict, total=False):
    path: str
    source_pack: str
    tileset_id: str
    tilesheet_id: str
    family_id: NotRequired[str]
    variant_id: NotRequired[str]


class ProjectTilesetRegionConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ProjectTilesetConfig(TypedDict):
    sheet: str
    tile_width: NotRequired[int]
    tile_height: NotRequired[int]
    margin: NotRequired[int]
    spacing: NotRequired[int]
    transparent: NotRequired[str]
    catalog_scope: NotRequired[str]
    regions: NotRequired[dict[str, ProjectTilesetRegionConfig]]


class PatternRectConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int
    tileset: NotRequired[str]


class PatternConfig(TypedDict, total=False):
    tileset: str
    rows: list[list[TileRefToken]]
    rect: PatternRectConfig
    trim: bool


class BoxStyleConfig(TypedDict, total=False):
    edge_mode: str
    recommended_scale: str
    min_width_tiles: int
    min_height_tiles: int
    sample_width_tiles: int
    sample_height_tiles: int
    tl: TileRefToken
    t: TileRefToken
    tr: TileRefToken
    l: TileRefToken
    r: TileRefToken
    bl: TileRefToken
    b: TileRefToken
    br: TileRefToken
    fill: TileRefToken
    allow_sub_min: bool
    style: str


class ProjectConfig(TypedDict, total=False):
    tile_family: str | ProjectTileFamilyConfig | None
    tile_families: list[str | ProjectTileFamilyConfig | None]
    default_tileset: str
    scene_templates_dir: str
    scene_rules_dir: str
    grid: ProjectGridConfig
    aliases: dict[str, TileRefToken]
    patterns: dict[str, PatternConfig]
    box_styles: dict[str, BoxStyleConfig]
    tilesets: dict[str, ProjectTilesetConfig]


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


@dataclass(frozen=True)
class TilesetGridMetrics:
    columns: int
    rows: int
    tile_count: int


@dataclass(frozen=True)
class DirectTileRefTarget:
    tileset_id: str
    kind: Literal["coord", "index"]
    col: int | None = None
    row: int | None = None
    index: int | None = None


class LayerSpec(TypedDict):
    name: str
    ops: list[SceneOp]


class ViewportSpec(TypedDict, total=False):
    x: int
    y: int
    width: int
    height: int
    units: str
    scale: int


class MapSpec(TypedDict):
    width: int
    height: int
    background: NotRequired[str]


class LayoutConfig(TypedDict):
    project: str
    map: MapSpec
    output: str
    layers: NotRequired[list[LayerSpec]]
    scenes: NotRequired[list[SceneTemplate]]
    default_tileset: NotRequired[str]
    viewport: NotRequired[ViewportSpec]
    scale: NotRequired[int]


@dataclass(frozen=True)
class GridRegionBounds:
    x: int
    y: int
    width: int
    height: int


def load_project_config(path: Path) -> ProjectConfig:
    return cast(ProjectConfig, _require_mapping(load_json(path), context=str(path)))


def load_layout_config(path: Path) -> LayoutConfig:
    return cast(LayoutConfig, _require_mapping(load_json(path), context=str(path)))


def resolve_path(base: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base / path).resolve()


def parse_hex_colour(value: str) -> tuple[int, int, int, int]:
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError(f"Expected #RRGGBB or #AARRGGBB colour, got {value!r}")
    raw = raw[1:]
    if len(raw) == 6:
        red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
        return red, green, blue, 255
    if len(raw) == 8:
        alpha, red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4, 6))
        return red, green, blue, alpha
    raise ValueError(f"Expected #RRGGBB or #AARRGGBB colour, got {value!r}")


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def slugify_identifier(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "tileset"


def _apply_transparent_key(image: Image.Image, transparent_key: object) -> None:
    """Replace pixels matching `transparent_key` in `image` with full transparency."""
    # Pillow's get_flattened_data / putdata stubs are weakly typed; route through a
    # cast that pyright can fully resolve so the strict checker stays happy.
    get_data = cast(Callable[[], Sequence[object]], getattr(image, "get_flattened_data"))
    put_data = cast(Callable[[Sequence[tuple[int, int, int, int]]], None], getattr(image, "putdata"))
    pixels: list[tuple[int, int, int, int]] = [
        (0, 0, 0, 0) if pixel == transparent_key else cast(tuple[int, int, int, int], pixel)
        for pixel in get_data()
    ]
    put_data(pixels)


def _filled_hole_mask(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    width, height = alpha.size
    opaque = [[cast(int, alpha.getpixel((x, y))) > 0 for x in range(width)] for y in range(height)]
    exterior = [[False for _ in range(width)] for _ in range(height)]
    stack: list[tuple[int, int]] = []

    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))

    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        if exterior[y][x] or opaque[y][x]:
            continue
        exterior[y][x] = True
        stack.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

    mask = Image.new("L", (width, height), 0)
    for y in range(height):
        for x in range(width):
            if opaque[y][x] or not exterior[y][x]:
                mask.putpixel((x, y), 255)
    return mask


def _occlusion_mask_for_image(
    image: Image.Image,
    mode: Literal["alpha", "fill_holes", "fill_cell"],
) -> Image.Image | None:
    if mode == "alpha":
        return None
    if mode == "fill_cell":
        return Image.new("L", image.size, 255)
    if mode == "fill_holes":
        return _filled_hole_mask(image)
    raise ValueError(f"Unsupported occlusion mode: {mode}")


def _normalise_occlusion_mode(value: object, *, context: str) -> Literal["alpha", "fill_holes", "fill_cell"]:
    if value is None:
        return "alpha"
    if not isinstance(value, str) or value not in VALID_OCCLUSION_MODES:
        allowed = ", ".join(sorted(VALID_OCCLUSION_MODES))
        raise ValueError(f"{context} must use one of: {allowed}")
    return cast(Literal["alpha", "fill_holes", "fill_cell"], value)


def _normalise_pixel_offset(value: object, *, context: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int):
        raise ValueError(f"{context} must be an integer pixel offset")
    return value


def _offset_crop_bounds(
    base_size: tuple[int, int],
    overlay_size: tuple[int, int],
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[int, int, int, int, int, int] | None:
    base_width, base_height = base_size
    overlay_width, overlay_height = overlay_size
    left = max(0, offset_x)
    top = max(0, offset_y)
    source_left = max(0, -offset_x)
    source_top = max(0, -offset_y)
    width = min(base_width - left, overlay_width - source_left)
    height = min(base_height - top, overlay_height - source_top)
    if width <= 0 or height <= 0:
        return None
    return left, top, source_left, source_top, width, height


def _alpha_composite_with_offset(
    base: Image.Image,
    overlay: Image.Image,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    bounds = _offset_crop_bounds(base.size, overlay.size, offset_x=offset_x, offset_y=offset_y)
    if bounds is None:
        return
    left, top, source_left, source_top, width, height = bounds
    cropped = overlay.crop((source_left, source_top, source_left + width, source_top + height))
    if base.mode == "RGBA" and cropped.mode == "RGBA":
        base.alpha_composite(cropped, (left, top))
    else:
        base.paste(cropped, (left, top))


def _paste_with_mask_offset(
    base: Image.Image,
    fill: tuple[int, int, int, int],
    mask: Image.Image,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    bounds = _offset_crop_bounds(base.size, mask.size, offset_x=offset_x, offset_y=offset_y)
    if bounds is None:
        return
    left, top, source_left, source_top, width, height = bounds
    cropped_mask = mask.crop((source_left, source_top, source_left + width, source_top + height))
    base.paste(fill, (left, top, left + width, top + height), cropped_mask)


def _union_mask_with_offset(
    base: Image.Image,
    mask: Image.Image,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    bounds = _offset_crop_bounds(base.size, mask.size, offset_x=offset_x, offset_y=offset_y)
    if bounds is None:
        return
    left, top, source_left, source_top, width, height = bounds
    cropped_mask = mask.crop((source_left, source_top, source_left + width, source_top + height))
    base.paste(255, (left, top, left + width, top + height), cropped_mask)


def humanize_identifier(value: str) -> str:
    parts = [part for part in re.split(r"[._-]+", value.strip()) if part]
    uppercase_tokens = {"tl", "tr", "bl", "br", "nw", "ne", "sw", "se"}
    words: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in uppercase_tokens:
            words.append(lowered.upper())
        elif lowered.isdigit():
            words.append(lowered)
        else:
            words.append(lowered.capitalize())
    return " ".join(words) or value

@dataclass(frozen=True)
class TileFamilySelection:
    path: Path
    source_family: TileFamily
    selected_variant_id: str

    @property
    def runtime_unit(self) -> TileLibraryUnit:
        return self.source_family.runtime_unit

    @property
    def selected_tileset_id(self) -> str:
        return self.runtime_unit.runtime_tileset_id(self.selected_variant_id)

    @property
    def loaded_tile_library(self) -> LoadedTileLibraryUnit:
        return LoadedTileLibraryUnit(
            unit=self.runtime_unit,
            selected_variant_id=self.selected_variant_id,
        )


def _load_family_from_legacy_path(
    *,
    base_dir: Path,
    spec: ProjectTileFamilyConfig,
) -> tuple[Path, TileFamily]:
    raw_path = spec.get("path")
    if raw_path is None:
        raise ValueError("tile_family legacy path config must define path")
    family_dir = resolve_path(base_dir, raw_path)
    return family_dir, TileFamily.load(family_dir)


def _load_family_from_source_pack(
    *,
    base_dir: Path,
    spec: ProjectTileFamilyConfig,
) -> tuple[Path, TileFamily]:
    if "tileset_id" not in spec or "tilesheet_id" not in spec:
        raise ValueError("tile_family source_pack config must define tileset_id and tilesheet_id")
    raw_pack_path = spec.get("source_pack")
    if raw_pack_path is None:
        raise ValueError("tile_family source_pack config must define source_pack")
    pack_path = resolve_path(base_dir, raw_pack_path)
    return (
        pack_path,
        load_bridged_tile_family(
            pack_path,
            tileset_id=spec["tileset_id"],
            tilesheet_id=spec["tilesheet_id"],
        ),
    )


def load_tile_family_selection(
    base_dir: Path,
    spec: str | ProjectTileFamilyConfig | None,
) -> TileFamilySelection | None:
    if spec is None or spec == "":
        return None
    if isinstance(spec, str):
        spec = cast(ProjectTileFamilyConfig, {"path": spec})
    if "path" in spec and "source_pack" in spec:
        raise ValueError("tile_family config must define either path or source_pack, not both")
    if "path" in spec:
        selection_path, family = _load_family_from_legacy_path(base_dir=base_dir, spec=spec)
    elif "source_pack" in spec:
        selection_path, family = _load_family_from_source_pack(base_dir=base_dir, spec=spec)
    else:
        raise ValueError("tile_family config must define path or source_pack")
    family_id = spec.get("family_id")
    if family_id is not None and family_id != family.family_id:
        raise ValueError(
            f"Configured family_id {family_id!r} does not match loaded family {family.family_id!r}"
        )
    selected_variant_id = spec.get("variant_id") or family.default_variant_id
    if selected_variant_id not in family.variants:
        raise ValueError(
            f"Configured variant_id {selected_variant_id!r} is not defined in tile family {family.family_id!r}"
        )
    return TileFamilySelection(
        path=selection_path,
        source_family=family,
        selected_variant_id=selected_variant_id,
    )


def load_tile_family_selections(
    base_dir: Path,
    *,
    singular_spec: str | ProjectTileFamilyConfig | None,
    plural_specs: list[str | ProjectTileFamilyConfig | None] | None,
) -> tuple[TileFamilySelection, ...]:
    if singular_spec not in (None, "") and plural_specs:
        raise ValueError("Project config may define either tile_family or tile_families, not both")
    if plural_specs:
        loaded: list[TileFamilySelection] = []
        for index, spec in enumerate(plural_specs):
            if spec is None or spec == "":
                raise ValueError(f"tile_families[{index}] must not be empty")
            selection = load_tile_family_selection(base_dir, spec)
            if selection is None:
                raise ValueError(f"tile_families[{index}] must not be empty")
            loaded.append(selection)
        return tuple(loaded)
    selection = load_tile_family_selection(base_dir, singular_spec)
    if selection is None:
        return ()
    return (selection,)


@dataclass(frozen=True)
class ResolvedTile:
    tileset_id: str
    index: int | None = None
    flip_x: bool = False
    flip_y: bool = False
    image_override_path: Path | None = None
    family_tile_id: str | None = None
    underpaint: "ResolvedTile | None" = None
    occlusion_mode: Literal["alpha", "fill_holes", "fill_cell"] = "alpha"
    overlay_offset_x: int = 0
    overlay_offset_y: int = 0

    def require_index(self) -> int:
        if self.index is None:
            raise ValueError(f"Tile {self.tileset_id!r} does not have a sheet index")
        return self.index


@dataclass(frozen=True)
class TileRenderSpec:
    image: Image.Image
    occlusion_mask: Image.Image | None
    origin_x: int = 0
    origin_y: int = 0

    @property
    def left(self) -> int:
        return self.origin_x

    @property
    def top(self) -> int:
        return self.origin_y

    @property
    def right(self) -> int:
        return self.origin_x + self.image.width

    @property
    def bottom(self) -> int:
        return self.origin_y + self.image.height


@dataclass(frozen=True)
class EntityBounds:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class EntityAnchor:
    kind: Literal["top_left"]
    x: int
    y: int


@dataclass(frozen=True)
class EntityTilePlacement:
    tile_id: str
    ref: str
    x: int
    y: int
    compose_role: str | None = None
    walkable: bool | None = None
    blocking: bool | None = None
    affordances: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityOccupancyCell:
    x: int
    y: int
    relative_x: int
    relative_y: int
    tile_id: str
    compose_role: str | None = None
    walkable: bool | None = None
    blocking: bool | None = None
    affordances: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityInstance:
    entity_id: str
    source_template_id: str
    template: EntityTemplateRecord
    layer: str
    x: int
    y: int
    placement_anchor: EntityAnchor
    bounds: EntityBounds
    params: dict[str, object]
    tiles: tuple[EntityTilePlacement, ...]
    occupied_cells: tuple[EntityOccupancyCell, ...]
    affordance_cells: tuple[EntityOccupancyCell, ...]


@dataclass(frozen=True)
class SceneExpansionResult:
    layers: SceneLayers
    entities: tuple[EntityInstance, ...]


@dataclass(frozen=True)
class LayoutScene:
    layers: list[LayerSpec]
    entities: tuple[EntityInstance, ...]


@dataclass(frozen=True)
class Pattern:
    width: int
    height: int
    cells: tuple[tuple[ResolvedTile | None, ...], ...]


class GridTileset:
    def __init__(
        self,
        tileset_id: str,
        *,
        sheet_path: Path,
        tile_width: int,
        tile_height: int,
        margin: int = 0,
        spacing: int = 0,
        transparent_mode: str = "top_left",
        catalog_scope: str = "regions",
        regions: dict[str, GridRegionBounds] | None = None,
    ) -> None:
        self.id = tileset_id
        self.sheet_path = sheet_path.resolve()
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.margin = margin
        self.spacing = spacing
        self.transparent_mode = transparent_mode
        self.catalog_scope = catalog_scope
        if self.catalog_scope not in {"regions", "all"}:
            raise ValueError(f"Unsupported catalog_scope for {tileset_id}: {self.catalog_scope!r}")
        self.regions = regions or {}
        self.image = Image.open(self.sheet_path).convert("RGBA")
        if self.transparent_mode == "top_left":
            self.transparent_key = self.image.getpixel((0, 0))
        elif self.transparent_mode == "none":
            self.transparent_key = None
        else:
            raise ValueError(f"Unsupported transparent mode: {self.transparent_mode}")

        step_x = self.tile_width + self.spacing
        step_y = self.tile_height + self.spacing
        self.columns = (self.image.width - self.margin * 2 + self.spacing) // step_x
        self.rows = (self.image.height - self.margin * 2 + self.spacing) // step_y
        self.tile_count = self.columns * self.rows
        self._image_cache: dict[tuple[int, bool, bool], Image.Image] = {}
        self._empty_cache: dict[int, bool] = {}

    def index_from_col_row(self, col: int, row: int) -> int:
        if not (0 <= col < self.columns and 0 <= row < self.rows):
            raise ValueError(f"Tile coordinate out of bounds for {self.id}: ({col}, {row})")
        return row * self.columns + col

    def col_row_from_index(self, index: int) -> tuple[int, int]:
        if not (0 <= index < self.tile_count):
            raise ValueError(f"Tile index out of bounds for {self.id}: {index}")
        return index % self.columns, index // self.columns

    def tile_box(self, col: int, row: int) -> tuple[int, int, int, int]:
        left = self.margin + col * (self.tile_width + self.spacing)
        top = self.margin + row * (self.tile_height + self.spacing)
        return left, top, left + self.tile_width, top + self.tile_height

    def tile_image(self, index: int, *, flip_x: bool = False, flip_y: bool = False) -> Image.Image:
        key = (index, flip_x, flip_y)
        if key in self._image_cache:
            return self._image_cache[key]

        base_key = (index, False, False)
        if base_key not in self._image_cache:
            col, row = self.col_row_from_index(index)
            image = self.image.crop(self.tile_box(col, row)).convert("RGBA")
            if self.transparent_key is not None:
                _apply_transparent_key(image, self.transparent_key)
            self._image_cache[base_key] = image

        image = self._image_cache[base_key]
        if flip_x:
            image = ImageOps.mirror(image)
        if flip_y:
            image = ImageOps.flip(image)
        self._image_cache[key] = image
        return image

    def is_empty(self, index: int) -> bool:
        if index not in self._empty_cache:
            self._empty_cache[index] = self.tile_image(index).getbbox() is None
        return self._empty_cache[index]

    def iter_indices(self, *, restricted_to_regions: bool = True) -> list[int]:
        if not restricted_to_regions or not self.regions:
            return list(range(self.tile_count))
        indices: set[int] = set()
        for region in self.regions.values():
            for row in range(region.y, region.y + region.height):
                for col in range(region.x, region.x + region.width):
                    if 0 <= col < self.columns and 0 <= row < self.rows:
                        indices.add(self.index_from_col_row(col, row))
        return sorted(indices)

    def region_name_for_col_row(self, col: int, row: int) -> str | None:
        for region_name, region in self.regions.items():
            if (
                region.x <= col < region.x + region.width
                and region.y <= row < region.y + region.height
            ):
                return region_name
        return None

    def catalog_indices(self) -> list[int]:
        return self.iter_indices(restricted_to_regions=self.catalog_scope != "all")

    @classmethod
    def from_project_spec(
        cls,
        tileset_id: str,
        spec: ProjectTilesetConfig,
        *,
        base_dir: Path,
        grid_width: int,
        grid_height: int,
    ) -> GridTileset:
        return cls(
            tileset_id,
            sheet_path=resolve_path(base_dir, spec["sheet"]),
            tile_width=int(spec.get("tile_width", grid_width)),
            tile_height=int(spec.get("tile_height", grid_height)),
            margin=int(spec.get("margin", 0)),
            spacing=int(spec.get("spacing", 0)),
            transparent_mode=spec.get("transparent", "top_left"),
            catalog_scope=spec.get("catalog_scope", "regions"),
            regions={
                region_name: GridRegionBounds(
                    x=region["x"],
                    y=region["y"],
                    width=region["width"],
                    height=region["height"],
                )
                for region_name, region in spec.get("regions", {}).items()
            },
        )

    @classmethod
    def from_variant(
        cls,
        *,
        tile_library: TileLibraryUnit,
        variant_id: str,
    ) -> GridTileset:
        variant = tile_library.variant(variant_id)
        return cls(
            tile_library.runtime_tileset_id(variant_id),
            sheet_path=variant.sheet_path,
            tile_width=tile_library.tile_width,
            tile_height=tile_library.tile_height,
            transparent_mode=variant.transparent_mode,
            catalog_scope="all",
        )


class LayoutProject:
    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path.resolve()
        self.config = load_project_config(self.project_path)
        self.base_dir = self.project_path.parent
        self.tile_family_selections = load_tile_family_selections(
            self.base_dir,
            singular_spec=self.config.get("tile_family"),
            plural_specs=self.config.get("tile_families"),
        )
        self.tile_library_registry = self._build_tile_library_registry()
        self._scene_template_library: SceneTemplateLibrary | None = None
        self._scene_rules_library: SceneRulesetLibrary | None = None
        self._runtime_ready = False
        grid = self.config.get("grid", {})
        self.grid_width, self.grid_height, self.render_step_width, self.render_step_height = self._resolve_grid_dimensions(grid)
        self.aliases: dict[str, TileRefToken] = dict(self.config.get("aliases", {}))
        if "metatiles" in self.config:
            raise ValueError(
                f"{self.project_path} config key `metatiles` is not supported; use `patterns`"
            )
        self.pattern_specs: dict[str, PatternConfig] = dict(self.config.get("patterns", {}))
        self.box_styles: dict[str, BoxStyleConfig] = dict(self.config.get("box_styles", {}))
        self.tilesets: dict[str, GridTileset] = self._build_project_tilesets()
        self._family_variant_ids_by_tileset: dict[str, str] = {}
        self._family_selections_by_tileset: dict[str, TileFamilySelection] = {}
        self._register_family_tilesets()
        if not self.tilesets and not self._family_variant_ids_by_tileset:
            raise ValueError("Project must define either a tile_family or at least one tileset")
        self._default_tileset_id = self._resolve_default_tileset_id()
        self._pattern_cache: dict[str, Pattern] = {}
        self._custom_tile_image_cache: dict[tuple[Path, bool, bool], Image.Image] = {}
        self._resolved_tile_render_spec_cache: dict[ResolvedTile, TileRenderSpec] = {}
        self._tileset_grid_metrics_cache: dict[str, TilesetGridMetrics] = {}

    @property
    def scene_template_library(self) -> SceneTemplateLibrary:
        self._ensure_runtime_ready()
        assert self._scene_template_library is not None
        return self._scene_template_library

    @property
    def scene_rules_library(self) -> SceneRulesetLibrary:
        self._ensure_runtime_ready()
        assert self._scene_rules_library is not None
        return self._scene_rules_library

    def _ensure_runtime_ready(self) -> None:
        if self._runtime_ready:
            return
        scene_template_library = load_scene_template_library(
            self.base_dir,
            self.config.get("scene_templates_dir"),
        )
        scene_rules_library = load_scene_ruleset_library(
            self.base_dir,
            self.config.get("scene_rules_dir"),
        )
        self._validate_scene_rules(
            scene_template_library=scene_template_library,
            scene_rules_library=scene_rules_library,
        )
        detect_scene_template_cycles(
            scene_template_library.specs,
            scene_rules_library=scene_rules_library,
        )
        self._scene_template_library = scene_template_library
        self._scene_rules_library = scene_rules_library
        self._runtime_ready = True

    def _resolve_grid_dimensions(self, grid: ProjectGridConfig) -> tuple[int, int, int, int]:
        tile_library_registry = self.tile_library_registry
        family_grid_width = tile_library_registry.tile_width if tile_library_registry is not None else 8
        family_grid_height = tile_library_registry.tile_height if tile_library_registry is not None else 8
        configured_grid_width = grid.get("tile_width")
        configured_grid_height = grid.get("tile_height")
        if tile_library_registry is not None:
            if configured_grid_width not in (None, family_grid_width):
                raise ValueError("Project grid tile_width must match the loaded tile family tile width")
            if configured_grid_height not in (None, family_grid_height):
                raise ValueError("Project grid tile_height must match the loaded tile family tile height")
        grid_width = int(configured_grid_width or family_grid_width)
        grid_height = int(configured_grid_height or family_grid_height)
        default_render_step_width = tile_library_registry.render_step_width if tile_library_registry is not None else grid_width
        default_render_step_height = (
            tile_library_registry.render_step_height if tile_library_registry is not None else grid_height
        )
        return (
            grid_width,
            grid_height,
            int(grid.get("render_step_width", default_render_step_width)),
            int(grid.get("render_step_height", default_render_step_height)),
        )

    def _register_family_tilesets(self) -> None:
        for selection in self.tile_family_selections:
            tile_library = selection.runtime_unit
            for variant_id in tile_library.variant_ids:
                tileset_id = tile_library.runtime_tileset_id(variant_id)
                self._family_variant_ids_by_tileset[tileset_id] = variant_id
                self._family_selections_by_tileset[tileset_id] = selection

    def _build_tile_library_registry(self) -> TileLibraryRegistry | None:
        if not self.tile_family_selections:
            return None
        return TileLibraryRegistry.from_loaded_units(
            selection.loaded_tile_library for selection in self.tile_family_selections
        )

    def _build_project_tilesets(self) -> dict[str, GridTileset]:
        return {
            tileset_id: GridTileset.from_project_spec(
                tileset_id,
                spec,
                base_dir=self.base_dir,
                grid_width=self.grid_width,
                grid_height=self.grid_height,
            )
            for tileset_id, spec in self.config.get("tilesets", {}).items()
        }

    def has_tileset(self, tileset_id: str) -> bool:
        return tileset_id in self.tilesets or tileset_id in self._family_variant_ids_by_tileset

    def family_variant_tileset_ids(self) -> list[str]:
        """Tileset ids registered for the project's tile family variants."""
        return list(self._family_variant_ids_by_tileset.keys())

    def _resolve_default_tileset_id(self) -> str:
        explicit_default = self.config.get("default_tileset")
        if explicit_default is not None:
            if not self.has_tileset(explicit_default):
                available = sorted(set(self.tilesets) | set(self._family_variant_ids_by_tileset))
                raise ValueError(
                    f"Configured default_tileset {explicit_default!r} is unknown. "
                    f"Available tilesets: {', '.join(available)}"
                )
            return explicit_default
        if len(self.tile_family_selections) == 1:
            return self.tile_family_selections[0].selected_tileset_id
        if len(self.tile_family_selections) > 1:
            raise ValueError(
                "Project with multiple tile_families must define default_tileset for bare ref resolution"
            )
        return next(iter(self.tilesets.keys()))

    def scene_template_spec(self, template_id: str) -> SceneTemplateSpec:
        return self.scene_template_library.require(template_id)

    def scene_ruleset_spec(self, ruleset_id: str) -> SceneRulesetSpec:
        return self.scene_rules_library.require(ruleset_id)

    def _validate_scene_rules(
        self,
        *,
        scene_template_library: SceneTemplateLibrary,
        scene_rules_library: SceneRulesetLibrary,
    ) -> None:
        tile_library_registry = self.tile_library_registry
        default_tileset = self.default_tileset_id()
        for ruleset in scene_rules_library.specs.values():
            for catalogue_id, candidates in ruleset.catalogues.items():
                for candidate in candidates:
                    context = (
                        f"Scene ruleset {ruleset.ruleset_id!r} catalogue {catalogue_id!r} "
                        f"candidate {candidate.candidate_id!r}"
                    )
                    if isinstance(candidate, SceneRuleStampCandidate):
                        try:
                            self.validate_ref_without_loading(
                                candidate.ref,
                                default_tileset=default_tileset,
                            )
                        except Exception as exc:  # noqa: BLE001 - keep context on invalid authoring
                            raise ValueError(f"{context} references an unknown stamp ref") from exc
                        continue
                    if isinstance(candidate, SceneRuleSceneCandidate):
                        scene_template_library.require(candidate.scene_id)
                        continue
                    if tile_library_registry is None:
                        raise ValueError(
                            f"{context} references construction {candidate.construction_id!r}, "
                            "but the project has no tile family loaded"
                        )
                    if tile_library_registry.lookup_construction(candidate.construction_id) is None:
                        raise ValueError(
                            f"{context} references unknown construction "
                            f"{candidate.construction_id!r}"
                        )

    def get_tileset(self, tileset_id: str) -> GridTileset:
        if tileset_id in self.tilesets:
            return self.tilesets[tileset_id]
        if tileset_id not in self._family_variant_ids_by_tileset:
            available = sorted(set(self.tilesets) | set(self._family_variant_ids_by_tileset))
            raise KeyError(f"Unknown tileset: {tileset_id}. Available tilesets: {', '.join(available)}")
        selection = self._family_selections_by_tileset[tileset_id]
        tile_library = selection.runtime_unit
        variant_id = self._family_variant_ids_by_tileset[tileset_id]
        tileset = GridTileset.from_variant(
            tile_library=tile_library,
            variant_id=variant_id,
        )
        self.tilesets[tileset.id] = tileset
        return tileset

    def default_tileset_id(self) -> str:
        return self._default_tileset_id

    def _family_selection_for_tileset(self, tileset_id: str) -> TileFamilySelection | None:
        return self._family_selections_by_tileset.get(tileset_id)

    def source_family_for_tileset(self, tileset_id: str) -> TileFamily | None:
        selection = self._family_selection_for_tileset(tileset_id)
        if selection is None:
            return None
        return selection.source_family

    def tile_library_unit_for_tileset(self, tileset_id: str) -> TileLibraryUnit | None:
        selection = self._family_selection_for_tileset(tileset_id)
        if selection is None:
            return None
        return selection.runtime_unit

    def family_tile_record_for_resolved_tile(self, tile: ResolvedTile) -> TileRecord | None:
        tile_library = self.tile_library_unit_for_tileset(tile.tileset_id)
        if tile_library is None:
            return None
        if tile.family_tile_id is not None:
            return tile_library.tile_record(tile.family_tile_id)
        if tile.index is None:
            return None
        tileset = self.get_tileset(tile.tileset_id)
        col, row = tileset.col_row_from_index(tile.index)
        return tile_library.tile_at_sheet_cell(sheet_col=col, sheet_row=row)

    def _effective_occlusion_mode_for_tile(
        self,
        tile: ResolvedTile,
    ) -> Literal["alpha", "fill_holes", "fill_cell"]:
        if tile.occlusion_mode != "alpha":
            return tile.occlusion_mode
        record = self.family_tile_record_for_resolved_tile(tile)
        if record is not None and not record.transparent:
            return "fill_cell"
        return "alpha"

    def _extra_bottom_overlay_offset_for_underpaint(self, underpaint: ResolvedTile | None) -> int:
        if underpaint is None:
            return 0
        record = self.family_tile_record_for_resolved_tile(underpaint)
        if record is None:
            return 0
        semantics = set(record.semantics)
        tags = set(record.tags)
        requires_exposed_on = set(record.requires_exposed_on)
        if "table" not in semantics:
            return 0
        if "south" in requires_exposed_on:
            return 2
        if "table:legged" in tags or "compose:bottom_edge_only" in tags:
            return 2
        return 0

    def variant_id_for_tileset(self, tileset_id: str) -> str | None:
        return self._family_variant_ids_by_tileset.get(tileset_id)

    def _resolve_family_ref(
        self,
        ref: str,
        *,
        tileset_id: str,
    ) -> ResolvedFamilyTile | None:
        tile_library_registry = self.tile_library_registry
        if tile_library_registry is not None:
            default_unit_id = None
            selection = self._family_selection_for_tileset(tileset_id)
            if selection is not None:
                tile_library = self.tile_library_unit_for_tileset(tileset_id)
                variant_id = self.variant_id_for_tileset(tileset_id)
                if tile_library is not None and variant_id is not None:
                    resolved = tile_library.resolve_ref(ref, variant_id=variant_id)
                    if resolved is not None:
                        return resolved
                default_unit_id = selection.runtime_unit.family_id
            return tile_library_registry.resolve_ref(ref, default_unit_id=default_unit_id)
        tile_library = self.tile_library_unit_for_tileset(tileset_id)
        variant_id = self.variant_id_for_tileset(tileset_id)
        if tile_library is None or variant_id is None:
            return None
        return tile_library.resolve_ref(ref, variant_id=variant_id)

    def family_tile_for_ref(self, ref: str, *, tileset_id: str) -> ResolvedTile | None:
        resolved = self._resolve_family_ref(ref, tileset_id=tileset_id)
        if resolved is None:
            return None
        runtime_tileset_id = f"{resolved.family_id}@{resolved.variant_id}"
        tileset = self.get_tileset(runtime_tileset_id)
        if resolved.sheet_col is None or resolved.sheet_row is None:
            return ResolvedTile(
                tileset_id=runtime_tileset_id,
                image_override_path=resolved.image_override_path,
                family_tile_id=resolved.tile_id,
            )
        col = resolved.sheet_col
        row = resolved.sheet_row
        return ResolvedTile(
            tileset_id=runtime_tileset_id,
            index=tileset.index_from_col_row(col, row),
            family_tile_id=resolved.tile_id,
            image_override_path=resolved.image_override_path,
        )

    def _tileset_grid_metrics(
        self,
        tileset_id: str,
        *,
        allow_family_tileset_load: bool,
    ) -> TilesetGridMetrics:
        if tileset_id in self._tileset_grid_metrics_cache:
            return self._tileset_grid_metrics_cache[tileset_id]

        tile_library = self.tile_library_unit_for_tileset(tileset_id)
        if tile_library is not None and not allow_family_tileset_load and tileset_id not in self.tilesets:
            variant_id = self._family_variant_ids_by_tileset[tileset_id]
            variant = tile_library.variant(variant_id)
            with Image.open(variant.sheet_path) as image:
                columns = image.width // tile_library.tile_width
                rows = image.height // tile_library.tile_height
            metrics = TilesetGridMetrics(columns=columns, rows=rows, tile_count=columns * rows)
        else:
            tileset = self.get_tileset(tileset_id)
            metrics = TilesetGridMetrics(
                columns=tileset.columns,
                rows=tileset.rows,
                tile_count=tileset.tile_count,
            )
        self._tileset_grid_metrics_cache[tileset_id] = metrics
        return metrics

    def _direct_tile_ref_target(
        self,
        token: str,
        *,
        default_tileset: str | None = None,
    ) -> DirectTileRefTarget | None:
        explicit_tileset_coord_match = TILESET_COORD_RE.match(token)
        if explicit_tileset_coord_match:
            explicit_tileset_id = explicit_tileset_coord_match.group("tileset")
            if not self.has_tileset(explicit_tileset_id):
                raise ValueError(f"Unknown tileset in raw coordinate ref: {explicit_tileset_id!r}")
            return DirectTileRefTarget(
                tileset_id=explicit_tileset_id,
                kind="coord",
                col=int(explicit_tileset_coord_match.group("col")),
                row=int(explicit_tileset_coord_match.group("row")),
            )

        tileset_id = default_tileset or self.default_tileset_id()
        raw = token
        if ":" in token:
            maybe_tileset, maybe_raw = token.split(":", 1)
            if self.has_tileset(maybe_tileset):
                if self.tile_library_unit_for_tileset(maybe_tileset) is not None and COORD_RE.match(maybe_raw):
                    raise ValueError(
                        "Raw coordinates on family-backed tilesets must use "
                        f"`{maybe_tileset}#{maybe_raw}`, not `{token}`"
                    )
                tileset_id = maybe_tileset
                raw = maybe_raw

        coord_match = COORD_RE.match(raw)
        if coord_match:
            return DirectTileRefTarget(
                tileset_id=tileset_id,
                kind="coord",
                col=int(coord_match.group("col")),
                row=int(coord_match.group("row")),
            )
        if raw.isdigit():
            return DirectTileRefTarget(
                tileset_id=tileset_id,
                kind="index",
                index=int(raw),
            )
        return None

    def _resolve_or_validate_direct_tile_ref(
        self,
        target: DirectTileRefTarget,
        *,
        materialise: bool,
    ) -> ResolvedTile | None:
        metrics = self._tileset_grid_metrics(
            target.tileset_id,
            allow_family_tileset_load=materialise,
        )
        if target.kind == "coord":
            assert target.col is not None
            assert target.row is not None
            if not (0 <= target.col < metrics.columns and 0 <= target.row < metrics.rows):
                raise ValueError(
                    f"Tile coordinate out of bounds for {target.tileset_id}: ({target.col}, {target.row})"
                )
            if not materialise:
                return None
            return ResolvedTile(
                tileset_id=target.tileset_id,
                index=target.row * metrics.columns + target.col,
            )

        assert target.index is not None
        if not (0 <= target.index < metrics.tile_count):
            raise ValueError(f"Tile index out of bounds for {target.tileset_id}: {target.index}")
        if not materialise:
            return None
        return ResolvedTile(
            tileset_id=target.tileset_id,
            index=target.index,
        )

    def _validate_pattern_without_loading(
        self,
        name: str,
        *,
        seen: tuple[str, ...] = (),
    ) -> None:
        if name in seen:
            cycle_start = seen.index(name)
            cycle_path = " -> ".join((*seen[cycle_start:], name))
            raise ValueError(f"Pattern cycle detected: {cycle_path}")
        if name not in self.pattern_specs:
            raise ValueError(f"Unknown pattern: {name}")
        spec = self.pattern_specs[name]
        default_tileset = spec.get("tileset", self.default_tileset_id())
        if "rows" in spec:
            for row in spec["rows"]:
                for cell in row:
                    self.validate_ref_without_loading(
                        cell,
                        default_tileset=default_tileset,
                        seen_patterns=(*seen, name),
                    )
            return
        if "rect" in spec:
            rect = spec["rect"]
            tileset_id = rect.get("tileset", default_tileset)
            metrics = self._tileset_grid_metrics(tileset_id, allow_family_tileset_load=False)
            x = rect["x"]
            y = rect["y"]
            width = rect["width"]
            height = rect["height"]
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                raise ValueError(f"Pattern {name!r} rect must use positive in-bounds dimensions")
            if x + width > metrics.columns or y + height > metrics.rows:
                raise ValueError(
                    f"Pattern {name!r} rect exceeds tileset bounds for {tileset_id}: "
                    f"origin=({x}, {y}) size=({width}, {height})"
                )
            return
        raise ValueError(f"Pattern {name!r} must define either rows or rect")

    def _base_image_for_tile(self, tile: ResolvedTile) -> Image.Image:
        if tile.image_override_path is None:
            return self.get_tileset(tile.tileset_id).tile_image(
                tile.require_index(),
                flip_x=tile.flip_x,
                flip_y=tile.flip_y,
            )

        resolved_path = tile.image_override_path.resolve()
        key = (resolved_path, tile.flip_x, tile.flip_y)
        if key in self._custom_tile_image_cache:
            return self._custom_tile_image_cache[key]

        base_key = (resolved_path, False, False)
        if base_key not in self._custom_tile_image_cache:
            self._custom_tile_image_cache[base_key] = Image.open(resolved_path).convert("RGBA")

        image = self._custom_tile_image_cache[base_key]
        if tile.flip_x:
            image = ImageOps.mirror(image)
        if tile.flip_y:
            image = ImageOps.flip(image)
        self._custom_tile_image_cache[key] = image
        return image

    def render_spec_for_tile(self, tile: ResolvedTile) -> TileRenderSpec:
        if tile in self._resolved_tile_render_spec_cache:
            return self._resolved_tile_render_spec_cache[tile]

        image = self._base_image_for_tile(tile)
        effective_occlusion_mode = self._effective_occlusion_mode_for_tile(tile)
        if tile.underpaint is None and tile.overlay_offset_x == 0 and tile.overlay_offset_y == 0:
            spec = TileRenderSpec(
                image=image,
                occlusion_mask=_occlusion_mask_for_image(image, effective_occlusion_mode),
                origin_x=0,
                origin_y=0,
            )
            self._resolved_tile_render_spec_cache[tile] = spec
            return spec

        underpaint_spec = self.render_spec_for_tile(tile.underpaint) if tile.underpaint is not None else None
        components: list[tuple[int, int, int, int]] = [
            (tile.overlay_offset_x, tile.overlay_offset_y, tile.overlay_offset_x + image.width, tile.overlay_offset_y + image.height)
        ]
        if underpaint_spec is not None:
            components.append(
                (
                    underpaint_spec.left,
                    underpaint_spec.top,
                    underpaint_spec.right,
                    underpaint_spec.bottom,
                )
            )
        left = min(component[0] for component in components)
        top = min(component[1] for component in components)
        right = max(component[2] for component in components)
        bottom = max(component[3] for component in components)

        composed = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        if underpaint_spec is not None:
            _alpha_composite_with_offset(
                composed,
                underpaint_spec.image,
                offset_x=underpaint_spec.origin_x - left,
                offset_y=underpaint_spec.origin_y - top,
            )
        overlay_occlusion_mask = _occlusion_mask_for_image(image, effective_occlusion_mode)
        if overlay_occlusion_mask is not None:
            _paste_with_mask_offset(
                composed,
                (0, 0, 0, 0),
                overlay_occlusion_mask,
                offset_x=tile.overlay_offset_x - left,
                offset_y=tile.overlay_offset_y - top,
            )
        _alpha_composite_with_offset(
            composed,
            image,
            offset_x=tile.overlay_offset_x - left,
            offset_y=tile.overlay_offset_y - top,
        )
        composed_occlusion_mask: Image.Image | None = None
        if underpaint_spec is not None and underpaint_spec.occlusion_mask is not None:
            composed_occlusion_mask = Image.new("L", composed.size, 0)
            _union_mask_with_offset(
                composed_occlusion_mask,
                underpaint_spec.occlusion_mask,
                offset_x=underpaint_spec.origin_x - left,
                offset_y=underpaint_spec.origin_y - top,
            )
        if overlay_occlusion_mask is not None:
            if composed_occlusion_mask is None:
                composed_occlusion_mask = Image.new("L", composed.size, 0)
            _union_mask_with_offset(
                composed_occlusion_mask,
                overlay_occlusion_mask,
                offset_x=tile.overlay_offset_x - left,
                offset_y=tile.overlay_offset_y - top,
            )
        spec = TileRenderSpec(
            image=composed,
            occlusion_mask=composed_occlusion_mask,
            origin_x=left,
            origin_y=top,
        )
        self._resolved_tile_render_spec_cache[tile] = spec
        return spec

    def occlusion_mask_for_tile(self, tile: ResolvedTile) -> Image.Image | None:
        return self.render_spec_for_tile(tile).occlusion_mask

    def image_for_tile(self, tile: ResolvedTile) -> Image.Image:
        return self.render_spec_for_tile(tile).image

    def _flip_resolved_tile(self, tile: ResolvedTile, *, flip_x: bool, flip_y: bool) -> ResolvedTile:
        if not flip_x and not flip_y:
            return tile
        underpaint = tile.underpaint
        flipped_underpaint = (
            self._flip_resolved_tile(underpaint, flip_x=flip_x, flip_y=flip_y) if underpaint is not None else None
        )
        return ResolvedTile(
            tileset_id=tile.tileset_id,
            index=tile.index,
            flip_x=tile.flip_x ^ flip_x,
            flip_y=tile.flip_y ^ flip_y,
            image_override_path=tile.image_override_path,
            family_tile_id=tile.family_tile_id,
            underpaint=flipped_underpaint,
            occlusion_mode=tile.occlusion_mode,
            overlay_offset_x=(-tile.overlay_offset_x if flip_x else tile.overlay_offset_x),
            overlay_offset_y=(-tile.overlay_offset_y if flip_y else tile.overlay_offset_y),
        )

    def _with_occlusion_mode(
        self,
        tile: ResolvedTile,
        *,
        occlusion_mode: Literal["alpha", "fill_holes", "fill_cell"],
    ) -> ResolvedTile:
        if tile.occlusion_mode == occlusion_mode:
            return tile
        return ResolvedTile(
            tileset_id=tile.tileset_id,
            index=tile.index,
            flip_x=tile.flip_x,
            flip_y=tile.flip_y,
            image_override_path=tile.image_override_path,
            family_tile_id=tile.family_tile_id,
            underpaint=tile.underpaint,
            occlusion_mode=occlusion_mode,
            overlay_offset_x=tile.overlay_offset_x,
            overlay_offset_y=tile.overlay_offset_y,
        )

    def _apply_occlusion_to_pattern(
        self,
        pattern: Pattern,
        *,
        occlusion_mode: Literal["alpha", "fill_holes", "fill_cell"],
    ) -> Pattern:
        if occlusion_mode == "alpha":
            return pattern
        rows: list[list[ResolvedTile | None]] = []
        for row in pattern.cells:
            rows.append(
                [
                    None if cell is None else self._with_occlusion_mode(cell, occlusion_mode=occlusion_mode)
                    for cell in row
                ]
            )
        return Pattern(width=pattern.width, height=pattern.height, cells=tuple(tuple(row) for row in rows))

    def _single_tile_from_token(self, token: TileRefToken, *, default_tileset: str | None = None) -> ResolvedTile:
        pattern = self.pattern_from_ref(token, default_tileset=default_tileset)
        if pattern.width != 1 or pattern.height != 1:
            raise ValueError(f"Composite tile refs must resolve to a single tile: {token!r}")
        tile = pattern.cells[0][0]
        if tile is None:
            raise ValueError(f"Composite tile refs cannot resolve to a blank cell: {token!r}")
        return tile

    def expand_alias(self, token: TileRefToken) -> TileRefToken:
        current: TileRefToken = token
        seen: set[str] = set()
        while isinstance(current, str) and current in self.aliases:
            if current in seen:
                raise ValueError(f"Alias cycle detected at {current!r}")
            seen.add(current)
            current = self.aliases[current]
        return current

    def resolve_tile(self, token: TileRefToken, *, default_tileset: str | None = None) -> ResolvedTile:
        token = self.expand_alias(token)
        if isinstance(token, int):
            target = DirectTileRefTarget(
                tileset_id=default_tileset or self.default_tileset_id(),
                kind="index",
                index=token,
            )
            resolved = self._resolve_or_validate_direct_tile_ref(target, materialise=True)
            assert resolved is not None
            return resolved
        if isinstance(token, dict):
            ref = token.get("ref")
            if ref is None:
                raise ValueError(f"Pattern transform is missing a ref: {token!r}")
            base_tile = self._single_tile_from_token(cast(TileRefToken, ref), default_tileset=default_tileset)
            underpaint_raw = token.get("underpaint")
            underpaint = (
                self._single_tile_from_token(cast(TileRefToken, underpaint_raw), default_tileset=default_tileset)
                if underpaint_raw is not None
                else None
            )
            offset_left = _normalise_pixel_offset(
                token.get("offset_left"),
                context=f"tile ref {token!r} offset_left",
            )
            offset_bottom = _normalise_pixel_offset(
                token.get("offset_bottom"),
                context=f"tile ref {token!r} offset_bottom",
            )
            offset_bottom += self._extra_bottom_overlay_offset_for_underpaint(underpaint)
            occlusion_mode = _normalise_occlusion_mode(
                token.get("occlusion"),
                context=f"tile ref {token!r} occlusion",
            )
            resolved = ResolvedTile(
                tileset_id=base_tile.tileset_id,
                index=base_tile.index,
                flip_x=base_tile.flip_x,
                flip_y=base_tile.flip_y,
                image_override_path=base_tile.image_override_path,
                family_tile_id=base_tile.family_tile_id,
                underpaint=underpaint,
                occlusion_mode=occlusion_mode,
                overlay_offset_x=offset_left,
                overlay_offset_y=-offset_bottom,
            )
            return self._flip_resolved_tile(
                resolved,
                flip_x=bool(token.get("flip_x", False)),
                flip_y=bool(token.get("flip_y", False)),
            )
        if not isinstance(token, str):
            raise ValueError(f"Unsupported tile reference: {token!r}")

        tileset_id = default_tileset or self.default_tileset_id()
        if ":" in token:
            maybe_tileset, maybe_raw = token.split(":", 1)
            if self.has_tileset(maybe_tileset):
                family_tile = self.family_tile_for_ref(maybe_raw, tileset_id=maybe_tileset)
                if family_tile is not None:
                    return family_tile
                tileset_id = maybe_tileset
        family_tile = self.family_tile_for_ref(token, tileset_id=tileset_id)
        if family_tile is not None:
            return family_tile

        target = self._direct_tile_ref_target(token, default_tileset=default_tileset)
        if target is not None:
            resolved = self._resolve_or_validate_direct_tile_ref(target, materialise=True)
            assert resolved is not None
            return resolved
        raise ValueError(f"Unsupported tile reference syntax: {token!r}")

    def validate_ref_without_loading(
        self,
        token: TileRefToken,
        *,
        default_tileset: str | None = None,
        seen_patterns: tuple[str, ...] = (),
    ) -> None:
        token = self.expand_alias(token)
        if token in (None, ".", " "):
            return
        if isinstance(token, int):
            target = DirectTileRefTarget(
                tileset_id=default_tileset or self.default_tileset_id(),
                kind="index",
                index=token,
            )
            self._resolve_or_validate_direct_tile_ref(target, materialise=False)
            return
        if isinstance(token, dict):
            ref = token.get("ref")
            if ref is None:
                raise ValueError(f"Pattern transform is missing a ref: {token!r}")
            self.validate_ref_without_loading(
                cast(TileRefToken, ref),
                default_tileset=default_tileset,
                seen_patterns=seen_patterns,
            )
            underpaint = token.get("underpaint")
            if underpaint is not None:
                self.validate_ref_without_loading(
                    cast(TileRefToken, underpaint),
                    default_tileset=default_tileset,
                    seen_patterns=seen_patterns,
                )
            _normalise_pixel_offset(token.get("offset_left"), context=f"tile ref {token!r} offset_left")
            _normalise_pixel_offset(token.get("offset_bottom"), context=f"tile ref {token!r} offset_bottom")
            _normalise_occlusion_mode(token.get("occlusion"), context=f"tile ref {token!r} occlusion")
            return
        if not isinstance(token, str):
            raise ValueError(f"Unsupported tile reference: {token!r}")

        if token.startswith("@"):
            self._validate_pattern_without_loading(token[1:], seen=seen_patterns)
            return

        tileset_id = default_tileset or self.default_tileset_id()
        if self._resolve_family_ref(token, tileset_id=tileset_id) is not None:
            return

        target = self._direct_tile_ref_target(token, default_tileset=default_tileset)
        if target is not None:
            self._resolve_or_validate_direct_tile_ref(target, materialise=False)
            return
        raise ValueError(f"Unsupported tile reference syntax: {token!r}")

    def pattern_from_ref(self, token: TileRefToken, *, default_tileset: str | None = None) -> Pattern:
        """Resolve any pattern-capable ref token, including `@name`, transforms, and single tiles."""
        token = self.expand_alias(token)
        if token in (None, ".", " "):
            return Pattern(width=1, height=1, cells=((None,),))
        if isinstance(token, dict):
            if "underpaint" in token or "offset_left" in token or "offset_bottom" in token:
                tile = self.resolve_tile(token, default_tileset=default_tileset)
                return Pattern(width=1, height=1, cells=((tile,),))
            ref = token.get("ref")
            if ref is None:
                raise ValueError(f"Pattern transform is missing a ref: {token!r}")
            pattern = self.pattern_from_ref(cast(TileRefToken, ref), default_tileset=default_tileset)
            pattern = transform_pattern(
                pattern,
                flip_x=bool(token.get("flip_x", False)),
                flip_y=bool(token.get("flip_y", False)),
            )
            occlusion_mode = _normalise_occlusion_mode(
                token.get("occlusion"),
                context=f"tile ref {token!r} occlusion",
            )
            return self._apply_occlusion_to_pattern(pattern, occlusion_mode=occlusion_mode)
        if isinstance(token, str) and token.startswith("@"):
            return self.pattern_from_name(token[1:])
        tile = self.resolve_tile(token, default_tileset=default_tileset)
        return Pattern(width=1, height=1, cells=((tile,),))

    def pattern_from_name(self, name: str) -> Pattern:
        """Resolve one bare project pattern key from `pattern_specs` without ref-token parsing."""
        if name in self._pattern_cache:
            return self._pattern_cache[name]
        if name not in self.pattern_specs:
            raise ValueError(f"Unknown pattern: {name}")
        spec = self.pattern_specs[name]
        default_tileset = spec.get("tileset", self.default_tileset_id())

        rows: list[tuple[ResolvedTile | None, ...]]
        if "rows" in spec:
            rows_spec = spec["rows"]
            rows = []
            for row_spec in rows_spec:
                row: list[ResolvedTile | None] = []
                for cell in row_spec:
                    pattern = self.pattern_from_ref(cell, default_tileset=default_tileset)
                    if pattern.width != 1 or pattern.height != 1:
                        raise ValueError(f"Pattern rows must resolve to single tiles: {name}")
                    row.append(pattern.cells[0][0])
                rows.append(tuple(row))
        elif "rect" in spec:
            rect = spec["rect"]
            tileset_id = rect.get("tileset", default_tileset)
            tileset = self.get_tileset(tileset_id)
            rows = []
            for row_index in range(rect["y"], rect["y"] + rect["height"]):
                cells: list[ResolvedTile | None] = []
                for col_index in range(rect["x"], rect["x"] + rect["width"]):
                    tile = ResolvedTile(
                        tileset_id=tileset_id,
                        index=tileset.index_from_col_row(col_index, row_index),
                    )
                    cells.append(None if tileset.is_empty(tile.require_index()) else tile)
                rows.append(tuple(cells))
            if spec.get("trim", False):
                rows = trim_pattern_rows(rows)
        else:
            raise ValueError(f"Pattern {name!r} must define either rows or rect")

        if not rows or not rows[0]:
            raise ValueError(f"Pattern {name!r} resolved to an empty pattern")
        pattern = Pattern(width=len(rows[0]), height=len(rows), cells=tuple(rows))
        self._pattern_cache[name] = pattern
        return pattern

    def pattern_names(self) -> list[str]:
        return sorted(self.pattern_specs.keys())

    def resolve_box_style(self, op: BoxOp) -> BoxOp:
        style_name = op.get("style")
        if style_name is None:
            return op
        if style_name not in self.box_styles:
            raise ValueError(f"Unknown box style: {style_name}")
        merged: dict[str, object] = dict(self.box_styles[style_name])
        merged.update(op)
        return cast(BoxOp, merged)

    def pixel_x_for_tile(self, x: int) -> int:
        return x * self.render_step_width

    def pixel_y_for_tile(self, y: int) -> int:
        return y * self.render_step_height

    def pixel_width_for_tiles(self, width_tiles: int) -> int:
        if width_tiles <= 0:
            return 0
        return self.grid_width + (width_tiles - 1) * self.render_step_width

    def pixel_height_for_tiles(self, height_tiles: int) -> int:
        if height_tiles <= 0:
            return 0
        return self.grid_height + (height_tiles - 1) * self.render_step_height


_TrimCell = TypeVar("_TrimCell")


def _trim_rows(rows: list[tuple[_TrimCell | None, ...]]) -> list[tuple[_TrimCell | None, ...]]:
    if not rows:
        return rows
    non_empty_positions = [
        (x, y)
        for y, row in enumerate(rows)
        for x, cell in enumerate(row)
        if cell is not None
    ]
    if not non_empty_positions:
        return []
    min_x = min(x for x, _ in non_empty_positions)
    max_x = max(x for x, _ in non_empty_positions)
    min_y = min(y for _, y in non_empty_positions)
    max_y = max(y for _, y in non_empty_positions)
    trimmed: list[tuple[_TrimCell | None, ...]] = []
    for row in rows[min_y : max_y + 1]:
        trimmed.append(tuple(row[min_x : max_x + 1]))
    return trimmed


def trim_pattern_rows(rows: list[tuple[ResolvedTile | None, ...]]) -> list[tuple[ResolvedTile | None, ...]]:
    return _trim_rows(rows)


def transform_pattern(pattern: Pattern, *, flip_x: bool = False, flip_y: bool = False) -> Pattern:
    if not flip_x and not flip_y:
        return pattern

    def flip_tile(cell: ResolvedTile) -> ResolvedTile:
        underpaint = cell.underpaint
        flipped_underpaint = flip_tile(underpaint) if underpaint is not None else None
        return ResolvedTile(
            tileset_id=cell.tileset_id,
            index=cell.index,
            flip_x=cell.flip_x ^ flip_x,
            flip_y=cell.flip_y ^ flip_y,
            image_override_path=cell.image_override_path,
            family_tile_id=cell.family_tile_id,
            underpaint=flipped_underpaint,
            occlusion_mode=cell.occlusion_mode,
            overlay_offset_x=(-cell.overlay_offset_x if flip_x else cell.overlay_offset_x),
            overlay_offset_y=(-cell.overlay_offset_y if flip_y else cell.overlay_offset_y),
        )

    rows = list(pattern.cells)
    if flip_y:
        rows = list(reversed(rows))
    if flip_x:
        rows = [tuple(reversed(row)) for row in rows]

    transformed_rows: list[tuple[ResolvedTile | None, ...]] = []
    for row in rows:
        transformed_row: list[ResolvedTile | None] = []
        for cell in row:
            if cell is None:
                transformed_row.append(None)
                continue
            transformed_row.append(flip_tile(cell))
        transformed_rows.append(tuple(transformed_row))
    return Pattern(width=pattern.width, height=pattern.height, cells=tuple(transformed_rows))


def crop_pattern(pattern: Pattern, *, x: int = 0, y: int = 0, width: int | None = None, height: int | None = None) -> Pattern:
    crop_width = pattern.width - x if width is None else width
    crop_height = pattern.height - y if height is None else height
    if x < 0 or y < 0 or crop_width < 0 or crop_height < 0:
        raise ValueError("Pattern crop must use non-negative coordinates and size")
    if x + crop_width > pattern.width or y + crop_height > pattern.height:
        raise ValueError("Pattern crop exceeds the source pattern bounds")
    rows = tuple(tuple(row[x : x + crop_width]) for row in pattern.cells[y : y + crop_height])
    return Pattern(width=crop_width, height=crop_height, cells=rows)


class AlphaBoundsInfo(TypedDict):
    alpha_bbox_pixels: list[int] | None
    inset_left_pixels: int
    inset_top_pixels: int
    inset_right_pixels: int
    inset_bottom_pixels: int


def analyse_alpha_bounds(image: Image.Image) -> AlphaBoundsInfo:
    bbox = image.getbbox()
    if bbox is None:
        return {
            "alpha_bbox_pixels": None,
            "inset_left_pixels": image.width,
            "inset_top_pixels": image.height,
            "inset_right_pixels": image.width,
            "inset_bottom_pixels": image.height,
        }
    left, top, right, bottom = bbox
    return {
        "alpha_bbox_pixels": [left, top, right, bottom],
        "inset_left_pixels": left,
        "inset_top_pixels": top,
        "inset_right_pixels": image.width - right,
        "inset_bottom_pixels": image.height - bottom,
    }


def pattern_tileset_ids(pattern: Pattern) -> set[str]:
    return {cell.tileset_id for row in pattern.cells for cell in row if cell is not None}


def _composite_render_spec(
    base: Image.Image,
    spec: TileRenderSpec,
    *,
    anchor_left: int,
    anchor_top: int,
    background: tuple[int, int, int, int],
) -> None:
    draw_left = anchor_left + spec.origin_x
    draw_top = anchor_top + spec.origin_y
    if spec.occlusion_mask is not None:
        _paste_with_mask_offset(
            base,
            background,
            spec.occlusion_mask,
            offset_x=draw_left,
            offset_y=draw_top,
        )
    _alpha_composite_with_offset(
        base,
        spec.image,
        offset_x=draw_left,
        offset_y=draw_top,
    )


def render_tile_preview_image(
    project: LayoutProject,
    tile: ResolvedTile,
    *,
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> Image.Image:
    spec = project.render_spec_for_tile(tile)
    left = min(0, spec.left)
    top = min(0, spec.top)
    right = max(project.grid_width, spec.right)
    bottom = max(project.grid_height, spec.bottom)
    image = Image.new("RGBA", (right - left, bottom - top), background)
    _composite_render_spec(
        image,
        spec,
        anchor_left=-left,
        anchor_top=-top,
        background=background,
    )
    return image


def render_pattern_image(
    project: LayoutProject,
    pattern: Pattern,
    *,
    snap_to_grid: bool = False,
) -> Image.Image:
    step_width = project.grid_width if snap_to_grid else project.render_step_width
    step_height = project.grid_height if snap_to_grid else project.render_step_height
    base_width = project.grid_width + (pattern.width - 1) * step_width
    base_height = project.grid_height + (pattern.height - 1) * step_height
    min_left = 0
    min_top = 0
    max_right = base_width
    max_bottom = base_height
    specs: list[tuple[int, int, TileRenderSpec]] = []
    for row_index, row in enumerate(pattern.cells):
        for col_index, cell in enumerate(row):
            if cell is None:
                continue
            anchor_left = col_index * step_width
            anchor_top = row_index * step_height
            spec = project.render_spec_for_tile(cell)
            specs.append((anchor_left, anchor_top, spec))
            min_left = min(min_left, anchor_left + spec.left)
            min_top = min(min_top, anchor_top + spec.top)
            max_right = max(max_right, anchor_left + spec.right)
            max_bottom = max(max_bottom, anchor_top + spec.bottom)
    image = Image.new(
        "RGBA",
        (max_right - min_left, max_bottom - min_top),
        (0, 0, 0, 0),
    )
    for anchor_left, anchor_top, spec in specs:
        _composite_render_spec(
            image,
            spec,
            anchor_left=anchor_left - min_left,
            anchor_top=anchor_top - min_top,
            background=(0, 0, 0, 0),
        )
    return image


def render_layer_image(
    project: LayoutProject,
    layer: list[list[ResolvedTile | None]],
    *,
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> Image.Image:
    width_tiles = len(layer[0]) if layer else 0
    height_tiles = len(layer)
    image = Image.new(
        "RGBA",
        (project.pixel_width_for_tiles(width_tiles), project.pixel_height_for_tiles(height_tiles)),
        background,
    )
    for row_index, row in enumerate(layer):
        for col_index, tile in enumerate(row):
            if tile is None:
                continue
            _composite_render_spec(
                image,
                project.render_spec_for_tile(tile),
                anchor_left=project.pixel_x_for_tile(col_index),
                anchor_top=project.pixel_y_for_tile(row_index),
                background=background,
            )
    return image


def render_box_style_image(project: LayoutProject, style_name: str, *, width_tiles: int, height_tiles: int) -> Image.Image:
    layer = new_layer(width_tiles, height_tiles)
    op: BoxOp = {
        "kind": "box",
        "style": style_name,
        "x": 0,
        "y": 0,
        "width": width_tiles,
        "height": height_tiles,
    }
    apply_box(
        layer,
        project,
        op,
        default_tileset=project.default_tileset_id(),
    )
    return render_layer_image(project, layer)


def new_layer(width: int, height: int) -> list[list[ResolvedTile | None]]:
    return [[None for _ in range(width)] for _ in range(height)]


def place_pattern(layer: list[list[ResolvedTile | None]], pattern: Pattern, x: int, y: int) -> None:
    height = len(layer)
    width = len(layer[0]) if layer else 0
    for py, row in enumerate(pattern.cells):
        gy = y + py
        if not (0 <= gy < height):
            continue
        for px, cell in enumerate(row):
            gx = x + px
            if cell is None or not (0 <= gx < width):
                continue
            layer[gy][gx] = cell


def apply_fill(layer: list[list[ResolvedTile | None]], pattern: Pattern, x: int, y: int, width: int, height: int) -> None:
    max_height = len(layer)
    max_width = len(layer[0]) if layer else 0
    for offset_y in range(height):
        gy = y + offset_y
        if not (0 <= gy < max_height):
            continue
        source_row = pattern.cells[offset_y % pattern.height]
        for offset_x in range(width):
            gx = x + offset_x
            if not (0 <= gx < max_width):
                continue
            cell = source_row[offset_x % pattern.width]
            if cell is not None:
                layer[gy][gx] = cell


def apply_mask_fill(
    layer: list[list[ResolvedTile | None]],
    pattern: Pattern,
    x: int,
    y: int,
    rows: list[str],
) -> None:
    max_height = len(layer)
    max_width = len(layer[0]) if layer else 0
    for offset_y, row in enumerate(rows):
        gy = y + offset_y
        if not (0 <= gy < max_height):
            continue
        source_row = pattern.cells[offset_y % pattern.height]
        for offset_x, char in enumerate(row):
            if char in (" ", "."):
                continue
            gx = x + offset_x
            if not (0 <= gx < max_width):
                continue
            cell = source_row[offset_x % pattern.width]
            if cell is not None:
                layer[gy][gx] = cell


def apply_scatter(
    layer: list[list[ResolvedTile | None]],
    patterns: list[Pattern],
    x: int,
    y: int,
    rows: list[str],
    *,
    density: float,
    seed: int,
) -> None:
    if not patterns:
        return
    rng = random.Random(seed)
    max_height = len(layer)
    max_width = len(layer[0]) if layer else 0
    for offset_y, row in enumerate(rows):
        gy = y + offset_y
        if not (0 <= gy < max_height):
            continue
        for offset_x, char in enumerate(row):
            if char in (" ", "."):
                continue
            if rng.random() > density:
                continue
            gx = x + offset_x
            if not (0 <= gx < max_width):
                continue
            place_pattern(layer, rng.choice(patterns), gx, gy)


def apply_ascii(
    layer: list[list[ResolvedTile | None]],
    project: LayoutProject,
    op: AsciiOp,
    *,
    default_tileset: str | None,
) -> None:
    legend = op["legend"]
    rows = op["rows"]
    origin_x = int(op["x"])
    origin_y = int(op["y"])
    for row_index, row in enumerate(rows):
        for col_index, char in enumerate(row):
            if char not in legend:
                if char in (" ", "."):
                    continue
                raise ValueError(f"ASCII legend missing entry for {char!r}")
            token = legend[char]
            pattern = project.pattern_from_ref(token, default_tileset=default_tileset)
            place_pattern(layer, pattern, origin_x + col_index, origin_y + row_index)


def _box_corner(spec: BoxOp, key: str) -> TileRefToken:
    spec_dict = cast(dict[str, TileRefToken], spec)
    if key not in spec_dict:
        raise ValueError(f"Box style is missing required edge ref {key!r}")
    return spec_dict[key]


def apply_box(
    layer: list[list[ResolvedTile | None]],
    project: LayoutProject,
    op: BoxOp,
    *,
    default_tileset: str | None,
) -> None:
    spec = project.resolve_box_style(op)
    x = int(spec["x"])
    y = int(spec["y"])
    width = int(spec["width"])
    height = int(spec["height"])
    edge_mode = spec.get("edge_mode", "seamless")
    if edge_mode not in VALID_EDGE_MODES:
        raise ValueError(f"Unsupported box edge_mode: {edge_mode!r}")

    if width < 2 or height < 2:
        raise ValueError("Box width/height must be at least 2 tiles")

    allow_sub_min = bool(spec.get("allow_sub_min", False))
    min_width_tiles = int(spec.get("min_width_tiles", 2))
    min_height_tiles = int(spec.get("min_height_tiles", 2))
    if not allow_sub_min and (width < min_width_tiles or height < min_height_tiles):
        raise ValueError(
            f"Box style {spec.get('style', '<inline>')} expects at least "
            f"{min_width_tiles}x{min_height_tiles} tiles, got {width}x{height}"
        )

    tl = project.pattern_from_ref(_box_corner(spec, "tl"), default_tileset=default_tileset)
    tr = project.pattern_from_ref(_box_corner(spec, "tr"), default_tileset=default_tileset)
    bl = project.pattern_from_ref(_box_corner(spec, "bl"), default_tileset=default_tileset)
    br = project.pattern_from_ref(_box_corner(spec, "br"), default_tileset=default_tileset)
    top_ref = _box_corner(spec, "t")
    left_ref = _box_corner(spec, "l")
    top = project.pattern_from_ref(top_ref, default_tileset=default_tileset)
    bottom = project.pattern_from_ref(spec.get("b", top_ref), default_tileset=default_tileset)
    left = project.pattern_from_ref(left_ref, default_tileset=default_tileset)
    right = project.pattern_from_ref(spec.get("r", left_ref), default_tileset=default_tileset)

    left_width = max(tl.width, left.width, bl.width)
    right_width = max(tr.width, right.width, br.width)
    top_height = max(tl.height, top.height, tr.height)
    bottom_height = max(bl.height, bottom.height, br.height)
    if width < left_width + right_width or height < top_height + bottom_height:
        raise ValueError("Box dimensions are too small for the chosen style")

    place_pattern(layer, tl, x, y)
    place_pattern(layer, tr, x + width - tr.width, y)
    place_pattern(layer, bl, x, y + height - bl.height)
    place_pattern(layer, br, x + width - br.width, y + height - br.height)

    current_x = x + tl.width
    top_limit = x + width - tr.width
    while current_x < top_limit:
        remaining = top_limit - current_x
        edge = top if remaining >= top.width else crop_pattern(top, width=remaining)
        place_pattern(layer, edge, current_x, y)
        current_x += top.width

    current_x = x + bl.width
    bottom_limit = x + width - br.width
    while current_x < bottom_limit:
        remaining = bottom_limit - current_x
        edge = bottom if remaining >= bottom.width else crop_pattern(bottom, width=remaining)
        place_pattern(layer, edge, current_x, y + height - bottom.height)
        current_x += bottom.width

    current_y = y + tl.height
    left_limit = y + height - bl.height
    while current_y < left_limit:
        remaining = left_limit - current_y
        edge = left if remaining >= left.height else crop_pattern(left, height=remaining)
        place_pattern(layer, edge, x, current_y)
        current_y += left.height

    current_y = y + tr.height
    right_limit = y + height - br.height
    while current_y < right_limit:
        remaining = right_limit - current_y
        edge = right if remaining >= right.height else crop_pattern(right, height=remaining)
        place_pattern(layer, edge, x + width - right.width, current_y)
        current_y += right.height

    fill_ref = spec.get("fill")
    if fill_ref not in (None, ".", " "):
        fill_pattern = project.pattern_from_ref(fill_ref, default_tileset=default_tileset)
        fill_x = x + left_width
        fill_y = y + top_height
        fill_width = width - left_width - right_width
        fill_height = height - top_height - bottom_height
        if fill_width > 0 and fill_height > 0:
            apply_fill(layer, fill_pattern, fill_x, fill_y, fill_width, fill_height)


def pattern_dimensions(project: LayoutProject, ref: TileRefToken, *, default_tileset: str | None) -> tuple[int, int]:
    pattern = project.pattern_from_ref(ref, default_tileset=default_tileset)
    return pattern.width, pattern.height


def centred_pattern_x(
    project: LayoutProject,
    ref: TileRefToken,
    *,
    x: int,
    width: int,
    default_tileset: str | None,
) -> int:
    pattern_width, _ = pattern_dimensions(project, ref, default_tileset=default_tileset)
    return x + max(0, (width - pattern_width) // 2)


def _scene_str(scene: SceneTemplate, key: str, default: str) -> str:
    value = scene.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"Scene field {key!r} must be a string, got {value!r}")
    return value


def _construction_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: MetatileConstruction | ParametricRunConstruction,
    construction_id: str,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    def _placement_ref(tile_id: str) -> str:
        if variant_id is None:
            return tile_id
        runtime_tileset_id = tile_library.runtime_tileset_id_for_construction(
            construction_id,
            variant_id=variant_id,
        )
        if runtime_tileset_id is None:
            raise ValueError(
                f"{context} references unknown construction {construction_id!r} "
                f"for variant {variant_id!r}"
            )
        return f"{runtime_tileset_id}:{tile_id}"

    if isinstance(construction, ParametricRunConstruction):
        return _parametric_run_tile_placements(
            tile_library,
            construction,
            construction_id,
            x,
            y,
            params=params,
            context=context,
            variant_id=variant_id,
        )
    placements: list[EntityTilePlacement] = []
    for row_index, row in enumerate(construction.cells):
        for col_index, cell in enumerate(row):
            if cell is not None:
                placements.append(
                    EntityTilePlacement(
                        tile_id=cell.id,
                        ref=_placement_ref(cell.id),
                        x=x + col_index,
                        y=y + row_index,
                        compose_role=cell.compose_role,
                        walkable=cell.walkable,
                        blocking=cell.blocking,
                        affordances=cell.affordances,
                    )
                )
    return placements


def _attachment_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction_id: str,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object],
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    def _resolve_attachment_variant_id(attachment_set: ConstructionAttachmentSet) -> str | None:
        if attachment_set.param in params:
            raw_variant_id: object = params[attachment_set.param]
        elif attachment_set.default_variant_id is not None:
            raw_variant_id = attachment_set.default_variant_id
        elif attachment_set.required:
            raise ValueError(
                f"{context} requires attachment param {attachment_set.param!r} "
                f"for construction {construction_id!r}"
            )
        else:
            return None
        if not isinstance(raw_variant_id, str) or raw_variant_id == "":
            raise ValueError(
                f"{context} attachment param {attachment_set.param!r} for construction "
                f"{construction_id!r} must be a non-empty string"
            )
        return raw_variant_id

    placements: list[EntityTilePlacement] = []
    for attachment_set in tile_library.attachment_sets_for_construction(construction_id):
        raw_variant_id = _resolve_attachment_variant_id(attachment_set)
        if raw_variant_id is None:
            continue
        variant = attachment_set.variant(raw_variant_id)
        if variant is None:
            available = ", ".join(sorted(attachment_set.variants.keys())) or "<none>"
            raise ValueError(
                f"{context} attachment param {attachment_set.param!r} for construction {construction_id!r} "
                f"requested unknown variant {raw_variant_id!r}; available: {available}"
            )
        attachment = tile_library.lookup_construction(variant.construction_id)
        if attachment is None:
            raise ValueError(
                f"{context} attachment set {attachment_set.id!r} references unknown construction "
                f"{variant.construction_id!r}"
            )
        placements.extend(
            _construction_tile_placements(
                tile_library,
                attachment,
                variant.construction_id,
                x + attachment_set.canvas.x,
                y + attachment_set.canvas.y,
                context=f"{context} attachment {attachment_set.id!r} variant {raw_variant_id!r}",
                params=params,
                variant_id=variant_id,
            )
        )
    return placements


def _entity_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: MetatileConstruction | ParametricRunConstruction,
    x: int,
    y: int,
    *,
    construction_id: str,
    context: str,
    params: Mapping[str, object],
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    placements = _construction_tile_placements(
        tile_library,
        construction,
        construction_id,
        x,
        y,
        context=context,
        params=params,
        variant_id=variant_id,
    )
    placements.extend(
        _attachment_tile_placements(
            tile_library,
            construction_id,
            x,
            y,
            context=context,
            params=params,
            variant_id=variant_id,
        )
    )
    return placements


def _parametric_run_tile_placements(
    tile_library: RuntimeConstructionCatalog,
    construction: ParametricRunConstruction,
    construction_id: str,
    x: int,
    y: int,
    *,
    params: Mapping[str, object] | None,
    context: str,
    variant_id: str | None = None,
) -> list[EntityTilePlacement]:
    def _placement_ref(tile_id: str) -> str:
        if variant_id is None:
            return tile_id
        runtime_tileset_id = tile_library.runtime_tileset_id_for_construction(
            construction_id,
            variant_id=variant_id,
        )
        if runtime_tileset_id is None:
            raise ValueError(
                f"{context} references unknown construction {construction_id!r} "
                f"for variant {variant_id!r}"
            )
        return f"{runtime_tileset_id}:{tile_id}"

    length_param = construction.length_param
    if params is None or length_param not in params:
        raise ValueError(
            f"Construction {construction.id!r} parametric_run requires params[{length_param!r}] ({context})"
        )
    length = int(params[length_param])  # type: ignore[arg-type]
    if length < 2:
        raise ValueError(
            f"Construction {construction.id!r} parametric_run length must be >= 2, got {length} ({context})"
        )
    axis = construction.axis
    placements: list[EntityTilePlacement] = []
    for i in range(length):
        if axis == "x":
            cx, cy = x + i, y
        else:
            cx, cy = x, y + i
        if i == 0:
            tile = construction.start_tile
        elif i == length - 1:
            tile = construction.end_tile
        else:
            tile = construction.repeat_tile
        placements.append(
            EntityTilePlacement(
                tile_id=tile.id,
                ref=_placement_ref(tile.id),
                x=cx,
                y=cy,
                compose_role=tile.compose_role,
                walkable=tile.walkable,
                blocking=tile.blocking,
                affordances=tile.affordances,
            )
        )
    return placements


def _entity_anchor(*, x: int, y: int) -> EntityAnchor:
    return EntityAnchor(kind="top_left", x=x, y=y)


def _entity_bounds_from_tile_placements(placements: Sequence[EntityTilePlacement]) -> EntityBounds:
    if not placements:
        return EntityBounds(x=0, y=0, width=0, height=0)
    min_x = min(placement.x for placement in placements)
    max_x = max(placement.x for placement in placements)
    min_y = min(placement.y for placement in placements)
    max_y = max(placement.y for placement in placements)
    return EntityBounds(
        x=min_x,
        y=min_y,
        width=max_x - min_x + 1,
        height=max_y - min_y + 1,
    )


def _entity_occupancy_cells(
    *,
    origin_x: int,
    origin_y: int,
    placements: Sequence[EntityTilePlacement],
) -> tuple[EntityOccupancyCell, ...]:
    return tuple(
        EntityOccupancyCell(
            x=placement.x,
            y=placement.y,
            relative_x=placement.x - origin_x,
            relative_y=placement.y - origin_y,
            tile_id=placement.tile_id,
            compose_role=placement.compose_role,
            walkable=placement.walkable,
            blocking=placement.blocking,
            affordances=placement.affordances,
        )
        for placement in placements
    )


def expand_entity_stamps(
    tile_library: RuntimeConstructionCatalog,
    construction_id: str,
    x: int,
    y: int,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    variant_id: str | None = None,
) -> list[StampOp]:
    construction = tile_library.lookup_construction(construction_id)
    if construction is None:
        raise ValueError(
            f"Unknown construction {construction_id!r} ({context})"
        )
    resolved_params = {} if params is None else dict(params)
    placements = _entity_tile_placements(
        tile_library,
        construction,
        x,
        y,
        construction_id=construction_id,
        context=context,
        params=resolved_params,
        variant_id=variant_id,
    )
    return [
        {"kind": "stamp", "ref": placement.ref, "x": placement.x, "y": placement.y}
        for placement in placements
    ]


def _resolve_scene_entity_request(
    tile_library: RuntimeConstructionCatalog,
    request: SceneEntityRequest,
) -> EntityInstance:
    construction = tile_library.lookup_construction(request.construction_id)
    if construction is None:
        raise ValueError(
            f"Unknown construction {request.construction_id!r} (scene entity {request.entity_id!r})"
        )
    template = tile_library.entity_template(request.construction_id)
    if template is None:
        raise ValueError(
            f"Unable to derive entity template for construction {request.construction_id!r}"
        )
    params = {} if request.params is None else dict(request.params)
    placements = tuple(
        _entity_tile_placements(
            tile_library,
            construction,
            request.x,
            request.y,
            construction_id=request.construction_id,
            context=f"scene entity {request.entity_id!r}",
            params=params,
            variant_id=request.variant_id,
        )
    )
    occupied_cells = _entity_occupancy_cells(
        origin_x=request.x,
        origin_y=request.y,
        placements=placements,
    )
    return EntityInstance(
        entity_id=request.entity_id,
        source_template_id=request.source_template_id,
        template=template,
        layer=request.layer,
        x=request.x,
        y=request.y,
        placement_anchor=_entity_anchor(x=request.x, y=request.y),
        bounds=_entity_bounds_from_tile_placements(placements),
        params=params,
        tiles=placements,
        occupied_cells=occupied_cells,
        affordance_cells=tuple(cell for cell in occupied_cells if cell.affordances),
    )


def _lower_entity_instance_to_stamp_ops(entity: EntityInstance) -> list[StampOp]:
    return [
        {"kind": "stamp", "ref": placement.ref, "x": placement.x, "y": placement.y}
        for placement in entity.tiles
    ]




def expand_scene_runtime(
    project: LayoutProject,
    scene: SceneTemplate,
    *,
    default_tileset: str | None,
) -> SceneExpansionResult:
    template = _scene_str(scene, "template", "")
    if not template:
        raise ValueError("Scene is missing required 'template' field")
    template_spec = project.scene_template_spec(template)
    validate_scene_template_input(scene, template_spec)
    tile_library = project.tile_library_registry

    runtime = SceneTemplateRuntime(
        pattern_dimensions=lambda ref: pattern_dimensions(
            project,
            ref,
            default_tileset=default_tileset,
        ),
        centered_pattern_x=lambda ref, x, width: centred_pattern_x(
            project,
            ref,
            x=x,
            width=width,
            default_tileset=default_tileset,
        ),
        scene_library=project.scene_template_library,
        scene_rules_library=project.scene_rules_library,
    )
    expanded = expand_data_scene(
        scene,
        template_spec,
        runtime=runtime,
    )
    if not expanded.entities:
        resolved_entities = ()
    else:
        if tile_library is None:
            raise ValueError(
                f"entity op requires a tile family; scene template {template_spec.template_id!r} "
                "requested entity constructions but no tile family is loaded"
            )
        resolved_entities = tuple(
            _resolve_scene_entity_request(tile_library, request)
            for request in expanded.entities
        )
    merged_layers: SceneLayers = {
        layer_name: list(ops)
        for layer_name, ops in expanded.layers.items()
    }
    for entity in resolved_entities:
        merged_layers.setdefault(entity.layer, []).extend(_lower_entity_instance_to_stamp_ops(entity))
    return SceneExpansionResult(
        layers=merged_layers,
        entities=resolved_entities,
    )


def expand_scene(project: LayoutProject, scene: SceneTemplate, *, default_tileset: str | None) -> SceneLayers:
    return expand_scene_runtime(project, scene, default_tileset=default_tileset).layers


def layer_sort_key(name: str) -> tuple[int, str]:
    try:
        index = DEFAULT_LAYER_ORDER.index(name)
    except ValueError:
        index = len(DEFAULT_LAYER_ORDER)
    return index, name


def build_layout_scene(
    layout: LayoutConfig,
    project: LayoutProject,
    *,
    default_tileset: str | None,
) -> LayoutScene:
    merged_layers: dict[str, list[SceneOp]] = {}
    entities: list[EntityInstance] = []
    for layer_spec in layout.get("layers", []):
        merged_layers.setdefault(layer_spec["name"], []).extend(layer_spec.get("ops", []))

    for scene in layout.get("scenes", []):
        expanded = expand_scene_runtime(project, scene, default_tileset=default_tileset)
        for layer_name, ops in expanded.layers.items():
            merged_layers.setdefault(layer_name, []).extend(ops)
        entities.extend(expanded.entities)

    return LayoutScene(
        layers=[{"name": name, "ops": merged_layers[name]} for name in sorted(merged_layers.keys(), key=layer_sort_key)],
        entities=tuple(entities),
    )


def build_layout_layers(
    layout: LayoutConfig,
    project: LayoutProject,
    *,
    default_tileset: str | None,
) -> list[LayerSpec]:
    return build_layout_scene(layout, project, default_tileset=default_tileset).layers


def _entity_instance_payload(entity: EntityInstance) -> dict[str, object]:
    def _occupancy_cell_payload(cell: EntityOccupancyCell) -> dict[str, object]:
        return {
            "tile_id": cell.tile_id,
            "x": cell.x,
            "y": cell.y,
            "relative_x": cell.relative_x,
            "relative_y": cell.relative_y,
            "compose_role": cell.compose_role,
            "walkable": cell.walkable,
            "blocking": cell.blocking,
            "affordances": list(cell.affordances),
        }

    return {
        "id": entity.entity_id,
        "source_template_id": entity.source_template_id,
        "template": entity.template.to_payload(),
        "layer": entity.layer,
        "origin": {"x": entity.x, "y": entity.y},
        "placement_anchor": {
            "kind": entity.placement_anchor.kind,
            "x": entity.placement_anchor.x,
            "y": entity.placement_anchor.y,
        },
        "bounds": {
            "x": entity.bounds.x,
            "y": entity.bounds.y,
            "width": entity.bounds.width,
            "height": entity.bounds.height,
        },
        "params": dict(entity.params),
        "tiles": [
            {
                "tile_id": placement.tile_id,
                "ref": placement.ref,
                "x": placement.x,
                "y": placement.y,
                "compose_role": placement.compose_role,
            }
            for placement in entity.tiles
        ],
        "occupancy": {
            "cell_count": len(entity.occupied_cells),
            "cells": [_occupancy_cell_payload(cell) for cell in entity.occupied_cells],
            "blocking_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.blocking is True
            ],
            "walkable_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.walkable is True
            ],
            "unknown_cells": [
                {"x": cell.x, "y": cell.y}
                for cell in entity.occupied_cells
                if cell.walkable is None and cell.blocking is None
            ],
        },
        "affordance_cells": [_occupancy_cell_payload(cell) for cell in entity.affordance_cells],
    }


def export_layout_scene_runtime(layout_path: Path, output_path: Path) -> Path:
    layout_path = layout_path.resolve()
    layout = load_layout_config(layout_path)
    project_path = resolve_path(layout_path.parent, layout["project"])
    project = LayoutProject(project_path)
    default_tileset = layout.get("default_tileset", project.default_tileset_id())
    layout_scene = build_layout_scene(layout, project, default_tileset=default_tileset)

    payload = {
        "layout": str(layout_path),
        "project": str(project_path),
        "default_tileset": default_tileset,
        "layer_count": len(layout_scene.layers),
        "entity_count": len(layout_scene.entities),
        "layers": [
            {
                "name": layer["name"],
                "op_count": len(layer["ops"]),
                "kinds": sorted({cast(str, op["kind"]) for op in layer["ops"]}),
            }
            for layer in layout_scene.layers
        ],
        "entities": [_entity_instance_payload(entity) for entity in layout_scene.entities],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def _apply_stamp_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(StampOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    place_pattern(layer, pattern, op["x"], op["y"])


def _apply_fill_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(FillOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    apply_fill(layer, pattern, op["x"], op["y"], op["width"], op["height"])


def _apply_mask_fill_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(MaskFillOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    apply_mask_fill(layer, pattern, op["x"], op["y"], list(op["rows"]))


def _apply_scatter_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(ScatterOp, op)
    refs = op.get("refs")
    if refs is None:
        single_ref = op.get("ref")
        if single_ref is None:
            raise ValueError("scatter op requires either 'ref' or 'refs'")
        refs = [single_ref]
    patterns = [project.pattern_from_ref(ref, default_tileset=default_tileset) for ref in refs]
    apply_scatter(
        layer,
        patterns,
        op["x"],
        op["y"],
        list(op["rows"]),
        density=float(op.get("density", 0.25)),
        seed=int(op.get("seed", 0)),
    )


def _apply_repeat_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    op = cast(RepeatOp, op)
    pattern = project.pattern_from_ref(op["ref"], default_tileset=default_tileset)
    dx = op.get("dx", 0)
    dy = op.get("dy", 0)
    for index in range(op["count"]):
        place_pattern(layer, pattern, op["x"] + index * dx, op["y"] + index * dy)


def _apply_box_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    apply_box(layer, project, cast(BoxOp, op), default_tileset=default_tileset)


def _apply_ascii_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp, *, default_tileset: str | None) -> None:
    apply_ascii(layer, project, cast(AsciiOp, op), default_tileset=default_tileset)


# Each handler receives the SceneOp as the union, casts to its specific
# TypedDict variant, and applies it to the layer.
LayerOpHandler: TypeAlias = Callable[
    [list[list[Union[ResolvedTile, None]]], "LayoutProject", SceneOp],
    None,
]


def _make_layer_op_handlers(default_tileset: str | None) -> dict[str, LayerOpHandler]:
    def stamp(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_stamp_op(layer, project, op, default_tileset=default_tileset)

    def fill(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_fill_op(layer, project, op, default_tileset=default_tileset)

    def mask_fill(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_mask_fill_op(layer, project, op, default_tileset=default_tileset)

    def scatter(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_scatter_op(layer, project, op, default_tileset=default_tileset)

    def repeat(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_repeat_op(layer, project, op, default_tileset=default_tileset)

    def box(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_box_op(layer, project, op, default_tileset=default_tileset)

    def ascii_op(layer: list[list[ResolvedTile | None]], project: LayoutProject, op: SceneOp) -> None:
        _apply_ascii_op(layer, project, op, default_tileset=default_tileset)

    return {
        "stamp": stamp,
        "fill": fill,
        "mask_fill": mask_fill,
        "scatter": scatter,
        "repeat": repeat,
        "box": box,
        "ascii": ascii_op,
    }


def render_layout(layout_path: Path, output_override: Path | None = None) -> Path:
    layout_path = layout_path.resolve()
    layout = load_layout_config(layout_path)
    project_path = resolve_path(layout_path.parent, layout["project"])
    project = LayoutProject(project_path)

    map_spec = layout["map"]
    map_width = map_spec["width"]
    map_height = map_spec["height"]
    background = parse_hex_colour(map_spec.get("background", "#00000000"))
    default_tileset = layout.get("default_tileset", project.default_tileset_id())

    handlers = _make_layer_op_handlers(default_tileset)
    layout_scene = build_layout_scene(layout, project, default_tileset=default_tileset)

    logical_layers: list[list[list[ResolvedTile | None]]] = []
    for layer_spec in layout_scene.layers:
        layer = new_layer(map_width, map_height)
        for op in layer_spec["ops"]:
            kind = op["kind"]
            handler = handlers.get(kind)
            if handler is None:
                raise ValueError(f"Unsupported layer operation: {kind}")
            handler(layer, project, op)
        logical_layers.append(layer)

    full_image = Image.new(
        "RGBA",
        (project.pixel_width_for_tiles(map_width), project.pixel_height_for_tiles(map_height)),
        background,
    )

    for layer in logical_layers:
        for row_index, row in enumerate(layer):
            for col_index, tile in enumerate(row):
                if tile is None:
                    continue
                _composite_render_spec(
                    full_image,
                    project.render_spec_for_tile(tile),
                    anchor_left=project.pixel_x_for_tile(col_index),
                    anchor_top=project.pixel_y_for_tile(row_index),
                    background=background,
                )

    viewport: ViewportSpec = layout.get(
        "viewport",
        {"x": 0, "y": 0, "width": map_width, "height": map_height, "units": "tiles", "scale": 1},
    )
    units = viewport.get("units", "tiles")
    if units == "tiles":
        left = project.pixel_x_for_tile(int(viewport.get("x", 0)))
        top = project.pixel_y_for_tile(int(viewport.get("y", 0)))
        width_px = project.pixel_width_for_tiles(int(viewport.get("width", map_width)))
        height_px = project.pixel_height_for_tiles(int(viewport.get("height", map_height)))
    elif units == "pixels":
        left = int(viewport.get("x", 0))
        top = int(viewport.get("y", 0))
        width_px = int(viewport.get("width", project.pixel_width_for_tiles(map_width)))
        height_px = int(viewport.get("height", project.pixel_height_for_tiles(map_height)))
    else:
        raise ValueError(f"Unsupported viewport units: {units}")

    cropped = full_image.crop((left, top, left + width_px, top + height_px))
    scale = int(viewport.get("scale", layout.get("scale", 1)))
    if scale != 1:
        cropped = _resize_nearest(cropped, (cropped.width * scale, cropped.height * scale))

    output_path = output_override or resolve_path(layout_path.parent, layout["output"])
    staged_path = create_staging_output_path(output_path)
    try:
        cropped.save(staged_path)
        return publish_staged_output(output_path, staged_path)
    finally:
        if staged_path.exists():
            staged_path.unlink()


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
        index: int | None = None
        empty = False
        if meta.sheet_col is not None and meta.sheet_row is not None:
            if not (0 <= meta.sheet_col < tileset.columns and 0 <= meta.sheet_row < tileset.rows):
                continue
            index = tileset.index_from_col_row(meta.sheet_col, meta.sheet_row)
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
            "sheet_col": meta.sheet_col,
            "sheet_row": meta.sheet_row,
            "exact_duplicate_of": meta.exact_duplicate_of,
            "image_override": meta.image_override,
            "aliases": list(meta.aliases),
            "walkable": meta.walkable,
            "blocking": meta.blocking,
            "scenes": list(meta.scenes),
            "semantics": list(meta.semantics),
            "motifs": list(meta.motifs),
            "cluster_ids": list(meta.cluster_ids),
            "source_group": meta.source_group,
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
        tile = _resize_nearest(tileset.tile_image(entry["index"]), (tileset.tile_width * scale, tileset.tile_height * scale))
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


class BoxStyleCatalogEntry(AlphaBoundsInfo):
    name: str
    edge_mode: str
    recommended_scale: str
    min_width_tiles: int
    min_height_tiles: int
    sample_width_tiles: int
    sample_height_tiles: int
    sample_width_pixels: int
    sample_height_pixels: int
    warnings: list[str]


def build_box_style_catalog(project: LayoutProject) -> list[BoxStyleCatalogEntry]:
    catalog: list[BoxStyleCatalogEntry] = []
    for name in sorted(project.box_styles.keys()):
        spec = project.box_styles[name]
        edge_mode = spec.get("edge_mode", "seamless")
        if edge_mode not in VALID_EDGE_MODES:
            raise ValueError(f"Unsupported box edge_mode for {name}: {edge_mode!r}")

        min_width_tiles = int(spec.get("min_width_tiles", 2))
        min_height_tiles = int(spec.get("min_height_tiles", 2))
        sample_width_tiles = int(spec.get("sample_width_tiles", max(12, min_width_tiles)))
        sample_height_tiles = int(spec.get("sample_height_tiles", max(8, min_height_tiles)))
        sample = render_box_style_image(
            project,
            name,
            width_tiles=sample_width_tiles,
            height_tiles=sample_height_tiles,
        )
        bounds = analyse_alpha_bounds(sample)
        inset_keys: tuple[Literal["inset_left_pixels", "inset_top_pixels", "inset_right_pixels", "inset_bottom_pixels"], ...] = (
            "inset_left_pixels",
            "inset_top_pixels",
            "inset_right_pixels",
            "inset_bottom_pixels",
        )
        warnings: list[str] = []
        if edge_mode == "seamless" and any(bounds[key] > 0 for key in inset_keys):
            warnings.append("Declared seamless but sample render has visible outer insets.")
        if edge_mode == "padded" and all(bounds[key] == 0 for key in inset_keys):
            warnings.append("Declared padded but sample render fills its outer bounds.")

        catalog.append(
            {
                "name": name,
                "edge_mode": edge_mode,
                "recommended_scale": spec.get("recommended_scale", "any"),
                "min_width_tiles": min_width_tiles,
                "min_height_tiles": min_height_tiles,
                "sample_width_tiles": sample_width_tiles,
                "sample_height_tiles": sample_height_tiles,
                "sample_width_pixels": sample.width,
                "sample_height_pixels": sample.height,
                "alpha_bbox_pixels": bounds["alpha_bbox_pixels"],
                "inset_left_pixels": bounds["inset_left_pixels"],
                "inset_top_pixels": bounds["inset_top_pixels"],
                "inset_right_pixels": bounds["inset_right_pixels"],
                "inset_bottom_pixels": bounds["inset_bottom_pixels"],
                "warnings": warnings,
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
        trimmed = _trim_rows(tuple_rows)
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
        sprite = _resize_nearest(
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


def inspect_box_styles(project: LayoutProject, output_dir: Path) -> None:
    catalog = build_box_style_catalog(project)
    (output_dir / "box_styles.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    if not catalog:
        return

    scale = 3
    previews = [
        (
            entry,
            _resize_nearest(
                render_box_style_image(
                    project,
                    entry["name"],
                    width_tiles=entry["sample_width_tiles"],
                    height_tiles=entry["sample_height_tiles"],
                ),
                (entry["sample_width_pixels"] * scale, entry["sample_height_pixels"] * scale),
            ),
        )
        for entry in catalog
    ]
    card_width = max(max(preview.width for _, preview in previews) + 16, 220)
    card_height = max(max(preview.height for _, preview in previews) + 54, 120)
    columns = 2
    rows = (len(previews) + columns - 1) // columns
    contact = Image.new("RGBA", (columns * card_width, rows * card_height), (24, 25, 32, 255))
    draw = ImageDraw.Draw(contact)

    for idx, (entry, preview) in enumerate(previews):
        row = idx // columns
        col = idx % columns
        left = col * card_width
        top = row * card_height
        draw.rectangle((left + 4, top + 4, left + card_width - 5, top + card_height - 5), outline=(246, 195, 124, 255))
        px = left + (card_width - preview.width) // 2
        py = top + 10
        contact.alpha_composite(preview, (px, py))
        draw.text((left + 8, top + card_height - 40), entry["name"], fill=(255, 255, 255, 255))
        draw.text(
            (left + 8, top + card_height - 28),
            f'{entry["edge_mode"]} • min {entry["min_width_tiles"]}x{entry["min_height_tiles"]}',
            fill=(180, 220, 255, 255),
        )
        draw.text(
            (left + 8, top + card_height - 16),
            (
                f'inset L{entry["inset_left_pixels"]} T{entry["inset_top_pixels"]} '
                f'R{entry["inset_right_pixels"]} B{entry["inset_bottom_pixels"]}'
            ),
            fill=(190, 200, 190, 255),
        )
    contact.save(output_dir / "box_styles.png")


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

    preview = _resize_nearest(image, (image.width * scale, image.height * scale))
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
    preview = _resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
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
    preview = _resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
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
        previews.append(_resize_nearest(preview, (preview.width * scale, preview.height * scale)))
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
        previews.append(_resize_nearest(preview, (preview.width * scale, preview.height * scale)))
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
    if tile.sheet_col is None or tile.sheet_row is None:
        return None
    return (tile.sheet_col, tile.sheet_row)


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
        (tile.sheet_col, tile.sheet_row)
        for tile_id in cluster.members
        for tile in [family.tiles.get(tile_id)]
        if tile is not None and tile.sheet_col is not None and tile.sheet_row is not None
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
    overlay = _resize_nearest(tileset.image, (tileset.image.width * overlay_scale, tileset.image.height * overlay_scale))
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
    project_path: Path,
    tileset_id: str,
    output_dir: Path,
    *,
    scale: int = 8,
    scratch_output_root: Path | None = None,
    project: LayoutProject | None = None,
) -> Path:
    project = project or LayoutProject(project_path)
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
        f"- project: `{project_path}`",
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
            preview = _resize_nearest(
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
        "project": str(project_path),
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
        project_path=project_path,
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
        previews.append(_resize_nearest(preview, (preview.width * scale, preview.height * scale)))
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
    return _resize_nearest(
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
    construction: MetatileConstruction | ParametricRunConstruction,
    *,
    scale: int,
    preview_length: int = 4,
) -> Image.Image:
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
    return _resize_nearest(rendered, (rendered.width * scale, rendered.height * scale))


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
    preview = _resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
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
        f"- constructions: `{len(public_constructions)}`",
        "",
        "Files:",
        "",
        "- `manifest.json`: pack summary and art convention metadata",
        "- `tiles.json`: one public semantic record per tile",
        "- `tiles.csv`: flat spreadsheet-friendly view of the tiles",
        "- `tile_clusters.json`: semantic/taxonomic cluster metadata",
        "- `entity_templates.json`: derived runtime entity templates backed by constructions",
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
    project_path: Path,
    tileset_id: str,
    output_dir: Path,
    *,
    scene: str | None = None,
    categories: list[str] | None = None,
    alias_prefix: str | None = None,
    scale: int = 8,
    project: LayoutProject | None = None,
) -> Path:
    project = project or LayoutProject(project_path)
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
        tile = _resize_nearest(
            _image_for_semantic_entry(project, tileset_id, entry),
            (tileset.tile_width * scale, tileset.tile_height * scale),
        )
        tile.save(tiles_dir / filename)
        enriched["file"] = f"tiles/{filename}"
        exported.append(enriched)

    payload = {
        "project": str(project_path),
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
        f"- Project: `{project_path}`",
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
    project_path: Path,
    tileset_id: str,
    *,
    sheet_col: int,
    sheet_row: int,
    project: LayoutProject | None = None,
) -> dict[str, object]:
    project = project or LayoutProject(project_path)
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
                "col": tile.sheet_col,
                "row": tile.sheet_row,
                "label_col": None if tile.sheet_col is None else tile.sheet_col + 1,
                "label_row": None if tile.sheet_row is None else tile.sheet_row + 1,
            },
            "source_group": tile.source_group,
            "semantic_cluster_ids": list(tile.cluster_ids),
            "aliases": list(family.aliases_for_tile(tile.id)),
            "semantics": list(tile.semantics),
            "meaning": tile.meaning,
            "meaning_confidence": tile.meaning_confidence,
        }

    return {
        "project": str(project_path),
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
    project_path: Path,
    tileset_id: str,
    output_dir: Path,
    *,
    project: LayoutProject | None = None,
) -> Path:
    project = project or LayoutProject(project_path)
    tileset = project.get_tileset(tileset_id)
    family = project.source_family_for_tileset(tileset_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_catalog = build_catalog(project, tileset_id)
    semantic_catalog = build_semantic_catalog(project, tileset_id)
    catalog = merge_semantic_catalog(raw_catalog, semantic_catalog)
    (output_dir / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    scale = 4
    preview = _resize_nearest(tileset.image, (tileset.image.width * scale, tileset.image.height * scale))
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
        tile = _resize_nearest(tileset.tile_image(index), (tileset.tile_width * 6, tileset.tile_height * 6))
        tile_left = card_left + (card_width - tile.width) // 2
        tile_top = card_top + 12
        contact.alpha_composite(tile, (tile_left, tile_top))
        draw.text((card_left + 8, card_top + 56), f'id {index}', fill=(255, 255, 255, 255))
        draw.text((card_left + 8, card_top + 68), f'{entry_col},{entry_row}', fill=(180, 220, 255, 255))
    contact.save(output_dir / "non_empty_tiles.png")
    inspect_tile_edges(project, tileset_id, output_dir)
    inspect_patterns(project, tileset_id, output_dir)
    inspect_box_styles(project, output_dir)
    inspect_source_layout(project, tileset_id, output_dir)
    inspect_clusters(project, tileset_id, output_dir)
    inspect_semantic_catalog(project, tileset_id, output_dir)
    return output_dir


def detect_family_source_layout(
    project_path: Path,
    tileset_id: str,
    output_dir: Path,
    *,
    project: LayoutProject | None = None,
) -> Path:
    project = project or LayoutProject(project_path)
    tileset = project.get_tileset(tileset_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    detected = detect_source_layout(image=tileset.image, tile_width=project.grid_width, tile_height=project.grid_height)
    (output_dir / "source_layout.detected.json").write_text(json.dumps(detected, indent=2) + "\n", encoding="utf-8")
    return output_dir


def validate_family_ingest(
    project_path: Path,
    tileset_id: str,
    *,
    project: LayoutProject | None = None,
) -> TileFamilyIngestReport:
    project = project or LayoutProject(project_path)
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

    box_ref_keys = ("tl", "t", "tr", "l", "r", "bl", "b", "br", "fill")
    for style_name, style in sorted(project.box_styles.items()):
        for key in box_ref_keys:
            ref = style.get(key)
            if ref is not None:
                yield (f"box style {style_name}.{key}", ref)

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
    project_path: Path,
    tileset_id: str,
    *,
    layouts_dir: Path | None = None,
    project: LayoutProject | None = None,
) -> SemanticUsageAuditReport:
    project = project or LayoutProject(project_path)
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
        "project": str(project_path),
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


def bootstrap_project(
    *,
    sheet_path: Path,
    output_path: Path,
    tile_width: int,
    tile_height: int,
    transparent: str,
    tileset_id: str | None,
) -> Path:
    sheet_path = sheet_path.resolve()
    output_path = output_path.resolve()
    image = Image.open(sheet_path).convert("RGBA")
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError(
            f"Sheet size {image.width}x{image.height} is not divisible by tile size {tile_width}x{tile_height}"
        )
    columns = image.width // tile_width
    rows = image.height // tile_height
    resolved_tileset_id = tileset_id or slugify_identifier(sheet_path.stem)
    relative_sheet = os.path.relpath(sheet_path, output_path.parent)
    data = {
        "grid": {"tile_width": tile_width, "tile_height": tile_height},
        "tilesets": {
            resolved_tileset_id: {
                "sheet": relative_sheet,
                "transparent": transparent,
                "regions": {"all": {"x": 0, "y": 0, "width": columns, "height": rows}},
            }
        },
        "patterns": {},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-based layout engine for sprite sheets / tilesets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render-layout", help="Render one layout JSON file.")
    render_parser.add_argument("layout", type=Path)
    render_parser.add_argument("--output", type=Path, default=None)

    inspect_layout_scene_parser = subparsers.add_parser(
        "inspect-layout-scene",
        help="Export the resolved scene runtime, including first-class entity instances, for one layout JSON file.",
    )
    inspect_layout_scene_parser.add_argument("layout", type=Path)
    inspect_layout_scene_parser.add_argument("--output", type=Path, default=None)

    render_all_parser = subparsers.add_parser("render-all", help="Render all layouts from a directory.")
    render_all_parser.add_argument("layouts_dir", nargs="?", type=Path, default=DEFAULT_LAYOUTS_DIR)

    tiled_parser = subparsers.add_parser("export-tiled-kit", help="Export the selected tileset as a Tiled-ready 8x8 kit.")
    tiled_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    tiled_parser.add_argument("--tileset", required=True)
    tiled_parser.add_argument("--output-dir", type=Path, default=None)

    public_pack_parser = subparsers.add_parser(
        "export-public-tile-pack",
        help="Export an engine-light annotated tile pack with public JSON/CSV metadata and PNG overviews.",
    )
    public_pack_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    public_pack_parser.add_argument("--tileset", required=True)
    public_pack_parser.add_argument("--output-dir", type=Path, default=None)
    public_pack_parser.add_argument("--slug", default=None)
    public_pack_parser.add_argument("--scale", type=int, default=8)

    semantic_query_parser = subparsers.add_parser(
        "query-semantic",
        help="Query the canonical semantic tile metadata for a project tileset.",
    )
    semantic_query_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    semantic_query_parser.add_argument("--tileset", required=True)
    semantic_query_parser.add_argument("--region", default=None)
    semantic_query_parser.add_argument("--category", default=None)
    semantic_query_parser.add_argument("--scene", default=None)
    semantic_query_parser.add_argument("--usage", default=None)
    semantic_query_parser.add_argument("--contrast", default=None)
    semantic_query_parser.add_argument("--temperature", default=None)
    semantic_query_parser.add_argument("--style", default=None)
    semantic_query_parser.add_argument("--orientation", default=None)
    semantic_query_parser.add_argument("--compose-group", default=None)
    semantic_query_parser.add_argument("--compose-role", default=None)
    semantic_query_parser.add_argument("--semantic", action="append", default=[])
    semantic_query_parser.add_argument("--tag", action="append", default=[])
    semantic_query_parser.add_argument("--walkable", choices=["true", "false"], default=None)
    semantic_query_parser.add_argument("--blocking", choices=["true", "false"], default=None)
    semantic_query_parser.add_argument("--alias-prefix", default=None)
    semantic_query_parser.add_argument("--limit", type=int, default=None)

    scaffold_parser = subparsers.add_parser(
        "scaffold-pattern",
        help="Emit a JSON pattern snippet from a selected rectangle of grid cells.",
    )
    scaffold_parser.add_argument("project", nargs="?", type=Path, default=DEFAULT_PROJECT)
    scaffold_parser.add_argument("--tileset", required=True)
    scaffold_parser.add_argument("--name", required=True)
    scaffold_parser.add_argument("--x", type=int, required=True)
    scaffold_parser.add_argument("--y", type=int, required=True)
    scaffold_parser.add_argument("--width", type=int, required=True)
    scaffold_parser.add_argument("--height", type=int, required=True)
    scaffold_parser.add_argument("--trim", action="store_true")

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-project",
        help="Create a starter project spec from any grid-aligned spritesheet.",
    )
    bootstrap_parser.add_argument("sheet", type=Path)
    bootstrap_parser.add_argument("output", type=Path)
    bootstrap_parser.add_argument("--tile-width", type=int, default=8)
    bootstrap_parser.add_argument("--tile-height", type=int, default=8)
    bootstrap_parser.add_argument("--transparent", default="top_left", choices=["top_left", "none"])
    bootstrap_parser.add_argument("--tileset-id", default=None)

    bootstrap_family_parser = subparsers.add_parser(
        "bootstrap-family",
        help="Create a starter tile-family package from any grid-aligned spritesheet.",
    )
    bootstrap_family_parser.add_argument("sheet", type=Path)
    bootstrap_family_parser.add_argument("output_dir", type=Path)
    bootstrap_family_parser.add_argument("--tile-width", type=int, default=8)
    bootstrap_family_parser.add_argument("--tile-height", type=int, default=8)
    bootstrap_family_parser.add_argument("--transparent", default="top_left", choices=["top_left", "none"])
    bootstrap_family_parser.add_argument("--family-id", default=None)
    bootstrap_family_parser.add_argument("--variant-id", default="default")

    args = parser.parse_args()

    if args.command == "render-layout":
        print(render_layout(args.layout, args.output))
    elif args.command == "inspect-layout-scene":
        output_path = args.output or (DEFAULT_SCENE_RUNTIME_DIR / f"{args.layout.stem}.scene_runtime.json")
        print(export_layout_scene_runtime(args.layout, output_path))
    elif args.command == "render-all":
        for layout_path in sorted(args.layouts_dir.glob("*.json")):
            print(render_layout(layout_path))
    elif args.command == "export-tiled-kit":
        output_dir = args.output_dir or (DEFAULT_TILED_KIT_DIR / args.tileset)
        print(export_tiled_kit(args.project, args.tileset, output_dir))
    elif args.command == "export-public-tile-pack":
        output_dir = args.output_dir
        if output_dir is None:
            slug = args.slug or slugify_identifier(args.tileset)
            output_dir = DEFAULT_PUBLIC_TILE_PACK_DIR / slug
        print(export_public_tile_pack(args.project, args.tileset, output_dir, scale=args.scale))
    elif args.command == "query-semantic":
        walkable = None if args.walkable is None else args.walkable == "true"
        blocking = None if args.blocking is None else args.blocking == "true"
        print(
            json.dumps(
                query_semantic_catalog(
                    args.project,
                    args.tileset,
                    region=args.region,
                    category=args.category,
                    scene=args.scene,
                    usage=args.usage,
                    contrast=args.contrast,
                    temperature=args.temperature,
                    style=args.style,
                    orientation=args.orientation,
                    compose_group=args.compose_group,
                    compose_role=args.compose_role,
                    semantics_all=args.semantic,
                    tags_all=args.tag,
                    walkable=walkable,
                    blocking=blocking,
                    alias_prefix=args.alias_prefix,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
    elif args.command == "scaffold-pattern":
        print(
            json.dumps(
                {
                    args.name: json.loads(
                        scaffold_pattern(
                            args.project,
                            tileset_id=args.tileset,
                            name=args.name,
                            x=args.x,
                            y=args.y,
                            width=args.width,
                            height=args.height,
                            trim=args.trim,
                        )
                    )
                },
                indent=2,
            )
        )
    elif args.command == "bootstrap-project":
        print(
            bootstrap_project(
                sheet_path=args.sheet,
                output_path=args.output,
                tile_width=args.tile_width,
                tile_height=args.tile_height,
                transparent=args.transparent,
                tileset_id=args.tileset_id,
            )
        )
    elif args.command == "bootstrap-family":
        family_id = args.family_id or slugify_identifier(args.sheet.stem)
        print(
            bootstrap_tile_family(
                sheet_path=args.sheet,
                output_dir=args.output_dir,
                tile_width=args.tile_width,
                tile_height=args.tile_height,
                transparent=args.transparent,
                family_id=family_id,
                variant_id=args.variant_id,
            )
        )


if __name__ == "__main__":
    main()
