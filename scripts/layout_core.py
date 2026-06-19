#!/usr/bin/env python3
"""Layout core: LayoutProject, the project/layout config and tile data types,
and the shared rendering / drawing / geometry primitives the harness and the
source-ingest operators build on. This is the shared base layer over
tile_library / tile_family_runtime / scene_* / _manifest_utils. During the IRS
transition it still imports source_manifest_bridge and tile_family_ingest, which
read ingest source_layout data for source-pack and legacy-path families; Phase
2/3 removes those dependencies from the runtime load path.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, TypedDict, TypeVar, cast

from typing_extensions import NotRequired

from PIL import Image, ImageOps

from tile_normalisation import apply_transparent_key, transparent_key_for_sheet

from scene_rules import (
    SceneRulesetLibrary,
    SceneRulesetSpec,
    SceneRuleSceneCandidate,
    SceneRuleStampCandidate,
    load_scene_ruleset_library,
)
from scene_templates import (
    AsciiOp,
    SceneOp,
    SceneTemplate,
    SceneTemplateLibrary,
    SceneTemplateSpec,
    detect_scene_template_cycles,
    load_scene_template_library,
    TileRefToken,
)
from tile_library import (
    LoadedTileLibraryUnit,
    ResolvedFamilyTile,
    TileLibraryRegistry,
    TileLibraryUnit,
    TileRecord,
)
from tile_family_runtime import (
    TileFamily,
)
# TODO(IRS Phase 2/3): decouple layout_core from ingest; legacy-path families
# still need source_layout / ingestion.json until runtime assets are promoted.
from tile_family_ingest import load_source_tile_family
from source_manifest_bridge import load_bridged_tile_family


COORD_RE = re.compile(r"^(?P<col>\d+),(?P<row>\d+)$")
TILESET_COORD_RE = re.compile(r"^(?P<tileset>[a-z0-9_.@-]+)#(?P<col>\d+),(?P<row>\d+)$")
VALID_OCCLUSION_MODES = frozenset({"alpha", "fill_holes", "fill_cell"})
def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def resize_nearest(image: Image.Image, size: tuple[int, int]) -> Image.Image:
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


class ProjectConfig(TypedDict, total=False):
    tile_family: str | ProjectTileFamilyConfig | None
    tile_families: list[str | ProjectTileFamilyConfig | None]
    default_tileset: str
    scene_templates_dir: str
    scene_rules_dir: str
    grid: ProjectGridConfig
    aliases: dict[str, TileRefToken]
    patterns: dict[str, PatternConfig]
    tilesets: dict[str, ProjectTilesetConfig]


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
    return family_dir, load_source_tile_family(family_dir)


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
        self.transparent_key = transparent_key_for_sheet(self.image, self.transparent_mode)

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
                apply_transparent_key(image, self.transparent_key)
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
                        if candidate.construction_id is not None:
                            raise ValueError(
                                f"{context} references construction {candidate.construction_id!r}, "
                                "but the project has no tile family loaded"
                            )
                        raise ValueError(
                            f"{context} references placeable "
                            f"{candidate.placeable_ref.kind}:{candidate.placeable_ref.id!r}, "
                            "but the project has no tile family loaded"
                        )
                    if tile_library_registry.lookup_placeable(candidate.placeable_ref) is None:
                        if candidate.construction_id is not None:
                            raise ValueError(
                                f"{context} references unknown construction "
                                f"{candidate.construction_id!r}"
                            )
                        raise ValueError(
                            f"{context} references unknown placeable "
                            f"{candidate.placeable_ref.kind}:{candidate.placeable_ref.id!r}"
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


def trim_rows(rows: list[tuple[_TrimCell | None, ...]]) -> list[tuple[_TrimCell | None, ...]]:
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
    return trim_rows(rows)


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


def composite_render_spec(
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
    composite_render_spec(
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
        composite_render_spec(
            image,
            spec,
            anchor_left=anchor_left - min_left,
            anchor_top=anchor_top - min_top,
            background=(0, 0, 0, 0),
        )
    return image


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
