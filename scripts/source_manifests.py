#!/usr/bin/env python3
"""Source-side pack / tileset / tilesheet manifests for the staged ingest model.

`source_layout` references remain intentionally opaque at this layer. This module
validates only that a referenced file exists, while callers that need to
interpret source-layout structure still use the family-side ingestion loader
until that parser is extracted into the source-side hierarchy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Literal, Mapping, TypeVar

from PIL import Image

from _manifest_utils import GridBounds, bounds_inside, check_required_keys, load_json, require_list, require_mapping, resolve_path
from compatibility_family import CompatibilityFamilyPaths
from tile_library import CellContentInset
from tile_metadata import ModuleContextValue, RenderTraits

MANIFEST_ID_RE = re.compile(r"^[a-z0-9_.-]+$")

ChildT = TypeVar("ChildT")


@dataclass(frozen=True)
class GridSize:
    tile_width: int
    tile_height: int


@dataclass(frozen=True)
class PackProvenance:
    author: str | None = None
    licence: str | None = None
    source_links: tuple[str, ...] = ()
    naming_conventions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackIngestRules:
    tileset_discovery: tuple[str, ...] = ()
    tilesheet_classification: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompatibilityFamilySource:
    paths: CompatibilityFamilyPaths
    family_id: str
    render_step_width: int | None = None
    render_step_height: int | None = None
    siblings_share_semantics: bool | None = None
    cell_content_inset: CellContentInset | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderVariantCoverage:
    mode: Literal["full", "sparse"]
    areas: tuple[GridBounds, ...] = ()

    def single_area(self) -> GridBounds | None:
        if len(self.areas) == 1:
            return self.areas[0]
        return None


@dataclass(frozen=True)
class RenderVariantTilesheetManifest:
    id: str
    sheet_path: Path
    coverage: RenderVariantCoverage
    declared_render_traits: RenderTraits
    render_traits: RenderTraits
    transparent_mode: str | None = None
    palette_family: str | None = None
    colorway: str | None = None
    background_mode: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LogicalTilesheetManifest:
    manifest_path: Path
    id: str
    title: str | None
    bounds: GridBounds
    default_variant_id: str
    source_layout_path: Path | None
    compatibility_family: CompatibilityFamilySource | None
    declared_render_traits: RenderTraits
    render_traits: RenderTraits
    notes: tuple[str, ...] | None
    render_variants: Mapping[str, RenderVariantTilesheetManifest] = field(repr=False)

    def variant(self, variant_id: str | None = None) -> RenderVariantTilesheetManifest:
        resolved_variant_id = variant_id or self.default_variant_id
        try:
            return self.render_variants[resolved_variant_id]
        except KeyError as exc:
            raise KeyError(
                f"Logical tilesheet {self.id!r} does not define render variant {resolved_variant_id!r}"
            ) from exc

    def require_compatibility_family(self) -> CompatibilityFamilySource:
        if self.compatibility_family is None:
            raise ValueError(f"Logical tilesheet {self.id!r} does not declare a compatibility_family bridge")
        return self.compatibility_family


@dataclass(frozen=True)
class TilesetManifest:
    manifest_path: Path
    id: str
    title: str | None
    module_context: Mapping[str, ModuleContextValue] = field(repr=False)
    logical_tilesheets: Mapping[str, LogicalTilesheetManifest] = field(repr=False)
    declared_render_traits: RenderTraits = field(default_factory=RenderTraits)
    render_traits: RenderTraits = field(default_factory=RenderTraits)
    notes: tuple[str, ...] = ()

    def logical_tilesheet(self, tilesheet_id: str) -> LogicalTilesheetManifest:
        try:
            return self.logical_tilesheets[tilesheet_id]
        except KeyError as exc:
            raise KeyError(f"Tileset {self.id!r} does not define logical tilesheet {tilesheet_id!r}") from exc


@dataclass(frozen=True)
class TilePackManifest:
    manifest_path: Path
    id: str
    title: str | None
    grid: GridSize
    tilesets: Mapping[str, TilesetManifest] = field(repr=False)
    provenance: PackProvenance = field(default_factory=PackProvenance)
    ingest_rules: PackIngestRules = field(default_factory=PackIngestRules)
    declared_render_traits: RenderTraits = field(default_factory=RenderTraits)
    render_traits: RenderTraits = field(default_factory=RenderTraits)
    notes: tuple[str, ...] = ()

    def tileset(self, tileset_id: str) -> TilesetManifest:
        try:
            return self.tilesets[tileset_id]
        except KeyError as exc:
            raise KeyError(f"Tile pack {self.id!r} does not define tileset {tileset_id!r}") from exc


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_string(value: object | None, *, context: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, context=context)


def _require_manifest_id(value: object, *, context: str) -> str:
    raw = _require_string(value, context=context)
    if MANIFEST_ID_RE.fullmatch(raw) is None:
        raise ValueError(f"{context} must match {MANIFEST_ID_RE.pattern!r}; got {raw!r}")
    return raw


def _require_string_tuple(value: object, *, context: str) -> tuple[str, ...]:
    items = require_list(value, context=context)
    return tuple(_require_string(item, context=f"{context}[{index}]") for index, item in enumerate(items))


def _optional_notes(mapping: dict[str, object], *, context: str) -> tuple[str, ...]:
    notes = _optional_declared_notes(mapping, context=context)
    if notes is None:
        return ()
    return notes


def _optional_declared_notes(mapping: dict[str, object], *, context: str) -> tuple[str, ...] | None:
    if "notes" not in mapping:
        return None
    return _require_string_tuple(mapping["notes"], context=f"{context}: notes")


def _optional_string_tuple(value: object | None, *, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    return _require_string_tuple(value, context=context)


def _require_bool(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _require_non_negative_int(value: object, *, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    if value < 0:
        raise ValueError(f"{context} must be >= 0")
    return value


def _require_positive_int(value: object, *, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    if value <= 0:
        raise ValueError(f"{context} must be > 0")
    return value


def _load_grid(value: object, *, context: str) -> GridSize:
    mapping = require_mapping(value, context=context)
    check_required_keys(mapping, ("tile_width", "tile_height"), context=context)
    return GridSize(
        tile_width=_require_positive_int(mapping["tile_width"], context=f"{context}.tile_width"),
        tile_height=_require_positive_int(mapping["tile_height"], context=f"{context}.tile_height"),
    )


def _load_render_traits(value: object | None, *, context: str) -> RenderTraits:
    if value is None:
        return RenderTraits()
    mapping = require_mapping(value, context=context)
    return RenderTraits(
        occupancy_style=_optional_string(mapping.get("occupancy_style"), context=f"{context}.occupancy_style"),
        gutter_policy=_optional_string(mapping.get("gutter_policy"), context=f"{context}.gutter_policy"),
        background_treatment=_optional_string(
            mapping.get("background_treatment"),
            context=f"{context}.background_treatment",
        ),
        alignment_origin=_optional_string(mapping.get("alignment_origin"), context=f"{context}.alignment_origin"),
        occlusion_mode=_optional_string(mapping.get("occlusion_mode"), context=f"{context}.occlusion_mode"),
    )


def _load_bounds(value: object, *, context: str) -> GridBounds:
    mapping = require_mapping(value, context=context)
    check_required_keys(mapping, ("x", "y", "width", "height"), context=context)
    return GridBounds(
        x=_require_non_negative_int(mapping["x"], context=f"{context}.x"),
        y=_require_non_negative_int(mapping["y"], context=f"{context}.y"),
        width=_require_positive_int(mapping["width"], context=f"{context}.width"),
        height=_require_positive_int(mapping["height"], context=f"{context}.height"),
    )


def _load_pack_provenance(value: object | None, *, context: str) -> PackProvenance:
    if value is None:
        return PackProvenance()
    mapping = require_mapping(value, context=context)
    return PackProvenance(
        author=_optional_string(mapping.get("author"), context=f"{context}.author"),
        licence=_optional_string(mapping.get("licence"), context=f"{context}.licence"),
        source_links=_optional_string_tuple(mapping.get("source_links"), context=f"{context}.source_links"),
        naming_conventions=_optional_string_tuple(
            mapping.get("naming_conventions"),
            context=f"{context}.naming_conventions",
        ),
        notes=_optional_notes(mapping, context=context),
    )


def _load_pack_ingest_rules(value: object | None, *, context: str) -> PackIngestRules:
    if value is None:
        return PackIngestRules()
    mapping = require_mapping(value, context=context)
    return PackIngestRules(
        tileset_discovery=_optional_string_tuple(
            mapping.get("tileset_discovery"),
            context=f"{context}.tileset_discovery",
        ),
        tilesheet_classification=_optional_string_tuple(
            mapping.get("tilesheet_classification"),
            context=f"{context}.tilesheet_classification",
        ),
        notes=_optional_notes(mapping, context=context),
    )


def _load_module_context(value: object | None, *, context: str) -> Mapping[str, ModuleContextValue]:
    if value is None:
        return MappingProxyType({})
    items = require_list(value, context=context)
    loaded: dict[str, ModuleContextValue] = {}
    for index, item in enumerate(items):
        item_context = f"{context}[{index}]"
        mapping = require_mapping(item, context=item_context)
        check_required_keys(mapping, ("axis_id", "value_id"), context=item_context)
        axis_id = _require_manifest_id(mapping["axis_id"], context=f"{item_context}.axis_id")
        if axis_id in loaded:
            raise ValueError(f"{context} declares axis_id {axis_id!r} more than once")
        loaded[axis_id] = ModuleContextValue(
            axis_id=axis_id,
            value_id=_require_manifest_id(mapping["value_id"], context=f"{item_context}.value_id"),
            label=_optional_string(mapping.get("label"), context=f"{item_context}.label"),
            notes=_optional_string(mapping.get("notes"), context=f"{item_context}.notes"),
        )
    return MappingProxyType(dict(loaded))


def _load_indexed_children(
    items_raw: object,
    *,
    context: str,
    parent_context: str,
    empty_message: str,
    duplicate_label: str,
    load_one: Callable[[dict[str, object], str], tuple[str, ChildT]],
) -> Mapping[str, ChildT]:
    items = require_list(items_raw, context=context)
    if not items:
        raise ValueError(empty_message)
    loaded: dict[str, ChildT] = {}
    for index, item in enumerate(items):
        item_context = f"{context}[{index}]"
        item_id, child = load_one(require_mapping(item, context=item_context), item_context)
        if item_id in loaded:
            raise ValueError(f"Duplicate {duplicate_label} in {parent_context}: {item_id}")
        loaded[item_id] = child
    return MappingProxyType(dict(loaded))


def _grid_dimensions_for_image(path: Path, *, grid: GridSize, context: str) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            width_px, height_px = image.size
    # Treat any local sheet-image read failure as a validation error at the ingest
    # boundary so callers do not need PIL- or filesystem-specific exception logic.
    except OSError as exc:
        raise ValueError(f"{context} could not read image {path}: {exc}") from exc
    if width_px % grid.tile_width != 0 or height_px % grid.tile_height != 0:
        raise ValueError(
            f"{context} image {path} size {width_px}x{height_px} is not aligned to "
            f"{grid.tile_width}x{grid.tile_height} tiles"
        )
    return (width_px // grid.tile_width, height_px // grid.tile_height)


def _load_sparse_areas(value: object, *, context: str) -> tuple[GridBounds, ...]:
    areas = tuple(_load_bounds(item, context=f"{context}[{index}]") for index, item in enumerate(require_list(value, context=context)))
    if not areas:
        raise ValueError(f"{context} must define at least one entry")
    return areas


def _load_render_variant_coverage(
    value: object,
    *,
    logical_bounds: GridBounds,
    context: str,
) -> RenderVariantCoverage:
    mapping = require_mapping(value, context=context)
    check_required_keys(mapping, ("mode",), context=context)
    mode = _require_string(mapping["mode"], context=f"{context}.mode")
    if mode == "full":
        if mapping.get("bounds") is not None or mapping.get("areas") is not None:
            raise ValueError(f"{context}.bounds and {context}.areas are not allowed when mode is 'full'")
        return RenderVariantCoverage(mode="full")
    if mode != "sparse":
        raise ValueError(f"{context}.mode must be 'full' or 'sparse'; got {mode!r}")
    bounds_value = mapping.get("bounds")
    areas_value = mapping.get("areas")
    if bounds_value is not None and areas_value is not None:
        raise ValueError(f"{context} cannot define both bounds and areas")
    if bounds_value is not None:
        areas = (_load_bounds(bounds_value, context=f"{context}.bounds"),)
    elif areas_value is not None:
        areas = _load_sparse_areas(areas_value, context=f"{context}.areas")
    else:
        raise ValueError(f"{context}.bounds or {context}.areas is required when mode is 'sparse'")
    for area in areas:
        if not bounds_inside(logical_bounds, area):
            raise ValueError(f"{context} area {area} must stay inside logical bounds {logical_bounds}")
    return RenderVariantCoverage(mode="sparse", areas=areas)


def _validate_render_variant_sheet_dimensions(
    coverage: RenderVariantCoverage,
    *,
    image_dimensions: tuple[int, int],
    logical_dimensions: tuple[int, int],
    context: str,
) -> None:
    if coverage.mode == "full":
        if image_dimensions != logical_dimensions:
            raise ValueError(
                f"{context}.sheet dimensions {image_dimensions[0]}x{image_dimensions[1]} do not cover "
                f"logical bounds {logical_dimensions[0]}x{logical_dimensions[1]}; declare explicit sparse coverage instead"
            )
        return
    if image_dimensions == logical_dimensions:
        return
    single_area = coverage.single_area()
    if single_area is not None and image_dimensions == (single_area.width, single_area.height):
        return
    raise ValueError(
        f"{context}.sheet dimensions {image_dimensions[0]}x{image_dimensions[1]} must match either logical bounds "
        f"{logical_dimensions[0]}x{logical_dimensions[1]} or a single declared sparse area"
    )


def _load_file_reference(value: object, *, base_dir: Path, context: str) -> Path:
    path = resolve_path(base_dir, _require_string(value, context=context))
    if not path.exists():
        raise ValueError(f"{context} path does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"{context} is not a regular file: {path}")
    return path


def _load_directory_reference(value: object, *, base_dir: Path, context: str) -> Path:
    path = resolve_path(base_dir, _require_string(value, context=context))
    if not path.exists():
        raise ValueError(f"{context} path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"{context} is not a directory: {path}")
    return path


def _load_compatibility_family_source(
    value: object | None,
    *,
    base_dir: Path,
    context: str,
) -> CompatibilityFamilySource | None:
    if value is None:
        return None
    mapping = require_mapping(value, context=context)
    check_required_keys(mapping, ("root", "family_id", "tiles", "aliases", "clusters"), context=context)
    compatibility_root = _load_directory_reference(mapping["root"], base_dir=base_dir, context=f"{context}.root")
    return CompatibilityFamilySource(
        paths=CompatibilityFamilyPaths(
            root=compatibility_root,
            tiles_path=_load_file_reference(mapping["tiles"], base_dir=compatibility_root, context=f"{context}.tiles"),
            aliases_path=_load_file_reference(mapping["aliases"], base_dir=compatibility_root, context=f"{context}.aliases"),
            clusters_path=_load_file_reference(mapping["clusters"], base_dir=compatibility_root, context=f"{context}.clusters"),
            constructions_path=(
                _load_file_reference(mapping["constructions"], base_dir=compatibility_root, context=f"{context}.constructions")
                if mapping.get("constructions") is not None
                else None
            ),
            attachments_path=(
                _load_file_reference(mapping["attachments"], base_dir=compatibility_root, context=f"{context}.attachments")
                if mapping.get("attachments") is not None
                else None
            ),
        ),
        family_id=_require_manifest_id(mapping["family_id"], context=f"{context}.family_id"),
        render_step_width=(
            _require_positive_int(mapping["render_step_width"], context=f"{context}.render_step_width")
            if mapping.get("render_step_width") is not None
            else None
        ),
        render_step_height=(
            _require_positive_int(mapping["render_step_height"], context=f"{context}.render_step_height")
            if mapping.get("render_step_height") is not None
            else None
        ),
        siblings_share_semantics=(
            _require_bool(mapping["siblings_share_semantics"], context=f"{context}.siblings_share_semantics")
            if mapping.get("siblings_share_semantics") is not None
            else None
        ),
        cell_content_inset=(
            CellContentInset.from_mapping(mapping["cell_content_inset"], context=f"{context}.cell_content_inset")
            if mapping.get("cell_content_inset") is not None
            else None
        ),
        notes=_optional_notes(mapping, context=context),
    )


def _load_render_variant_tilesheet_manifest(
    mapping: dict[str, object],
    *,
    base_dir: Path,
    grid: GridSize,
    logical_bounds: GridBounds,
    inherited_render_traits: RenderTraits,
    context: str,
) -> tuple[str, RenderVariantTilesheetManifest]:
    check_required_keys(mapping, ("variant_id", "sheet", "coverage"), context=context)
    variant_id = _require_manifest_id(mapping["variant_id"], context=f"{context}.variant_id")
    coverage = _load_render_variant_coverage(
        mapping["coverage"],
        logical_bounds=logical_bounds,
        context=f"{context}.coverage",
    )
    sheet_path = resolve_path(base_dir, _require_string(mapping["sheet"], context=f"{context}.sheet"))
    image_dimensions = _grid_dimensions_for_image(sheet_path, grid=grid, context=f"{context}.sheet")
    _validate_render_variant_sheet_dimensions(
        coverage,
        image_dimensions=image_dimensions,
        logical_dimensions=(logical_bounds.width, logical_bounds.height),
        context=context,
    )
    declared_render_traits = _load_render_traits(mapping.get("render_traits"), context=f"{context}.render_traits")
    return (
        variant_id,
        RenderVariantTilesheetManifest(
            id=variant_id,
            sheet_path=sheet_path,
            coverage=coverage,
            declared_render_traits=declared_render_traits,
            render_traits=inherited_render_traits.merged(declared_render_traits),
            transparent_mode=_optional_string(mapping.get("transparent"), context=f"{context}.transparent"),
            palette_family=_optional_string(mapping.get("palette_family"), context=f"{context}.palette_family"),
            colorway=_optional_string(mapping.get("colorway"), context=f"{context}.colorway"),
            background_mode=_optional_string(mapping.get("background_mode"), context=f"{context}.background_mode"),
            notes=_optional_string(mapping.get("notes"), context=f"{context}.notes"),
        ),
    )


def load_logical_tilesheet_manifest(
    path: Path,
    *,
    grid: GridSize,
    inherited_render_traits: RenderTraits | None = None,
) -> LogicalTilesheetManifest:
    manifest_path = path.resolve()
    raw = require_mapping(load_json(manifest_path), context=str(manifest_path))
    check_required_keys(raw, ("tilesheet_id", "bounds", "default_variant_id", "render_variants"), context=str(manifest_path))
    tilesheet_id = _require_manifest_id(raw["tilesheet_id"], context=f"{manifest_path}: tilesheet_id")
    bounds = _load_bounds(raw["bounds"], context=f"{manifest_path}: bounds")
    default_variant_id = _require_manifest_id(raw["default_variant_id"], context=f"{manifest_path}: default_variant_id")
    declared_render_traits = _load_render_traits(raw.get("render_traits"), context=f"{manifest_path}: render_traits")
    base_render_traits = inherited_render_traits if inherited_render_traits is not None else RenderTraits()
    render_traits = base_render_traits.merged(declared_render_traits)

    render_variants = _load_indexed_children(
        raw["render_variants"],
        context=f"{manifest_path}: render_variants",
        parent_context=str(manifest_path),
        empty_message=f"{manifest_path}: render_variants must define at least one entry",
        duplicate_label="render variant_id",
        load_one=lambda mapping, item_context: _load_render_variant_tilesheet_manifest(
            mapping,
            base_dir=manifest_path.parent,
            grid=grid,
            logical_bounds=bounds,
            inherited_render_traits=render_traits,
            context=item_context,
        ),
    )
    if default_variant_id not in render_variants:
        raise ValueError(f"{manifest_path}: default_variant_id {default_variant_id!r} is not defined by render_variants")

    source_layout_path: Path | None = None
    source_layout_raw = raw.get("source_layout")
    if source_layout_raw is not None:
        source_layout_path = _load_file_reference(
            source_layout_raw,
            base_dir=manifest_path.parent,
            context=f"{manifest_path}: source_layout",
        )
    compatibility_family = _load_compatibility_family_source(
        raw.get("compatibility_family"),
        base_dir=manifest_path.parent,
        context=f"{manifest_path}: compatibility_family",
    )

    return LogicalTilesheetManifest(
        manifest_path=manifest_path,
        id=tilesheet_id,
        title=_optional_string(raw.get("title"), context=f"{manifest_path}: title"),
        bounds=bounds,
        default_variant_id=default_variant_id,
        source_layout_path=source_layout_path,
        compatibility_family=compatibility_family,
        declared_render_traits=declared_render_traits,
        render_traits=render_traits,
        notes=_optional_declared_notes(raw, context=str(manifest_path)),
        render_variants=render_variants,
    )


def load_tileset_manifest(
    path: Path,
    *,
    grid: GridSize,
    inherited_render_traits: RenderTraits | None = None,
) -> TilesetManifest:
    manifest_path = path.resolve()
    raw = require_mapping(load_json(manifest_path), context=str(manifest_path))
    check_required_keys(raw, ("tileset_id", "logical_tilesheets"), context=str(manifest_path))
    tileset_id = _require_manifest_id(raw["tileset_id"], context=f"{manifest_path}: tileset_id")
    declared_render_traits = _load_render_traits(raw.get("render_traits"), context=f"{manifest_path}: render_traits")
    base_render_traits = inherited_render_traits if inherited_render_traits is not None else RenderTraits()
    render_traits = base_render_traits.merged(declared_render_traits)

    logical_tilesheets = _load_indexed_children(
        raw["logical_tilesheets"],
        context=f"{manifest_path}: logical_tilesheets",
        parent_context=str(manifest_path),
        empty_message=f"{manifest_path}: logical_tilesheets must define at least one entry",
        duplicate_label="logical tilesheet_id",
        load_one=lambda mapping, item_context: _load_logical_tilesheet_reference(
            mapping,
            base_dir=manifest_path.parent,
            grid=grid,
            inherited_render_traits=render_traits,
            context=item_context,
        ),
    )

    return TilesetManifest(
        manifest_path=manifest_path,
        id=tileset_id,
        title=_optional_string(raw.get("title"), context=f"{manifest_path}: title"),
        module_context=_load_module_context(raw.get("module_context"), context=f"{manifest_path}: module_context"),
        logical_tilesheets=logical_tilesheets,
        declared_render_traits=declared_render_traits,
        render_traits=render_traits,
        notes=_optional_notes(raw, context=str(manifest_path)),
    )


def _load_logical_tilesheet_reference(
    mapping: dict[str, object],
    *,
    base_dir: Path,
    grid: GridSize,
    inherited_render_traits: RenderTraits,
    context: str,
) -> tuple[str, LogicalTilesheetManifest]:
    check_required_keys(mapping, ("tilesheet_id", "manifest"), context=context)
    tilesheet_id = _require_manifest_id(mapping["tilesheet_id"], context=f"{context}.tilesheet_id")
    logical_tilesheet = load_logical_tilesheet_manifest(
        resolve_path(base_dir, _require_string(mapping["manifest"], context=f"{context}.manifest")),
        grid=grid,
        inherited_render_traits=inherited_render_traits,
    )
    if logical_tilesheet.id != tilesheet_id:
        raise ValueError(
            f"{context} expected id {tilesheet_id!r}, but manifest declares {logical_tilesheet.id!r}"
        )
    return (tilesheet_id, logical_tilesheet)


def _load_tileset_reference(
    mapping: dict[str, object],
    *,
    base_dir: Path,
    grid: GridSize,
    inherited_render_traits: RenderTraits,
    context: str,
) -> tuple[str, TilesetManifest]:
    check_required_keys(mapping, ("tileset_id", "manifest"), context=context)
    tileset_id = _require_manifest_id(mapping["tileset_id"], context=f"{context}.tileset_id")
    tileset = load_tileset_manifest(
        resolve_path(base_dir, _require_string(mapping["manifest"], context=f"{context}.manifest")),
        grid=grid,
        inherited_render_traits=inherited_render_traits,
    )
    if tileset.id != tileset_id:
        raise ValueError(f"{context} expected id {tileset_id!r}, but manifest declares {tileset.id!r}")
    return (tileset_id, tileset)


def load_tile_pack_manifest(path: Path) -> TilePackManifest:
    manifest_path = path.resolve()
    raw = require_mapping(load_json(manifest_path), context=str(manifest_path))
    check_required_keys(raw, ("pack_id", "grid", "tilesets"), context=str(manifest_path))
    pack_id = _require_manifest_id(raw["pack_id"], context=f"{manifest_path}: pack_id")
    grid = _load_grid(raw["grid"], context=f"{manifest_path}: grid")
    declared_render_traits = _load_render_traits(raw.get("render_traits"), context=f"{manifest_path}: render_traits")
    render_traits = declared_render_traits

    tilesets = _load_indexed_children(
        raw["tilesets"],
        context=f"{manifest_path}: tilesets",
        parent_context=str(manifest_path),
        empty_message=f"{manifest_path}: tilesets must define at least one entry",
        duplicate_label="tileset_id",
        load_one=lambda mapping, item_context: _load_tileset_reference(
            mapping,
            base_dir=manifest_path.parent,
            grid=grid,
            inherited_render_traits=render_traits,
            context=item_context,
        ),
    )

    return TilePackManifest(
        manifest_path=manifest_path,
        id=pack_id,
        title=_optional_string(raw.get("title"), context=f"{manifest_path}: title"),
        grid=grid,
        tilesets=tilesets,
        provenance=_load_pack_provenance(raw.get("provenance"), context=f"{manifest_path}: provenance"),
        ingest_rules=_load_pack_ingest_rules(raw.get("ingest_rules"), context=f"{manifest_path}: ingest_rules"),
        declared_render_traits=declared_render_traits,
        render_traits=render_traits,
        notes=_optional_notes(raw, context=str(manifest_path)),
    )
