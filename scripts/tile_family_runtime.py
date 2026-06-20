#!/usr/bin/env python3
"""Runtime tile-family loading and validation.

Runtime base-layer modules (`layout_core.py`, `tile_family_runtime.py`,
`tile_library.py`, `seam_*`, `compatibility_family.py`, `_manifest_utils.py`,
and `tile_normalisation.py`) must not import the ingest layer or the transitional
`tile_families.py` facade. Operator-side tools such as `harness.py`,
`source_ingest_ops.py`, `source_manifest_bridge.py`, and
`reference_tile_match.py` may use ingest metadata at their boundary and pass
plain runtime data in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, fields, replace
from difflib import get_close_matches
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, TypedDict, Union, cast

from typing_extensions import NotRequired

from PIL import Image

from _manifest_utils import (
    GridBounds,
    bounds_inside as _bounds_inside,
    check_required_keys,
    load_json,
    require_exactly_one,
    require_list,
    require_mapping,
    resolve_path,
)
from compatibility_family import CompatibilityFamilyPaths
from seam_matching import MatchPolicy
from seam_profiles import derive_side_masks
from tile_normalisation import apply_transparent_key, transparent_key_for_sheet
from source_layout_model import (
    SourceLayoutIngestion,
    bounds_contains,
    collection_member_ref,
    sheet_cell_ref_within_bounds,
    source_layout_region_contains_bounds,
)
from tile_library import (
    CellContentInset,
    CompositeTileCell,
    CompositeTileRecord,
    FRAME_FILL_MODES,
    FixedConstruction,
    FixedConstructionSeamOverride,
    FixedSeamOverrideSide,
    ParametricRunConstruction,
    FrameSlot,
    FrameCornerSlot,
    ParametricFrameConstruction,
    Construction,
    ConstructionAttachmentVariant,
    ConstructionAttachmentSet,
    EntityTemplateRecord,
    LoweredTileCell,
    Placeable,
    PlaceableKind,
    PlaceableRef,
    TileFamilyVariant,
    TileFamilyHeader,
    TileLibraryPromotedMetadata,
    EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
    TileClusterRecord,
    TileGenesis,
    TileRecord,
    ResolvedFamilyTile,
    attachment_sets_by_target,
    fixed_placeable_bounds,
    index_tiles_by_sheet_cell,
    require_variant_sheet_path,
    resolve_tile_image_override_path,
    TileLibraryUnit,
)

DEFAULT_TRANSPARENT_MODE = "top_left"


class FamilyGridConfig(TypedDict):
    tile_width: int
    tile_height: int


class FamilyRenderDefaultsConfig(TypedDict, total=False):
    render_step_width: int
    render_step_height: int


class FamilyVariantConfig(TypedDict):
    variant_id: str
    sheet: str
    transparent: NotRequired[str]
    palette_family: NotRequired[str]
    colorway: NotRequired[str]
    background_mode: NotRequired[str]
    notes: NotRequired[str]


class FamilyManifest(TypedDict):
    family_id: str
    grid: FamilyGridConfig
    variants: list[FamilyVariantConfig]
    title: NotRequired[str]
    render_defaults: NotRequired[FamilyRenderDefaultsConfig]
    siblings_share_semantics: NotRequired[bool]
    notes: NotRequired[list[str]]
    default_variant_id: NotRequired[str]
    ingestion_spec: NotRequired[str]
    cell_content_inset: NotRequired[Mapping[str, int]]
    runtime_flippable: NotRequired[bool]


class ClusterConfig(TypedDict):
    id: str
    scope: NotRequired[str]
    members: NotRequired[list[str]]
    kind_guess: NotRequired[str]
    evidence: NotRequired[list[str]]
    source_label: NotRequired[str]
    source_notes: NotRequired[str]


class TileConfig(TypedDict):
    id: str
    layer: str
    category: str
    transparent: bool
    sheet_col: NotRequired[int]
    sheet_row: NotRequired[int]
    exact_duplicate_of: NotRequired[str]
    image_override: NotRequired[str]
    tags: NotRequired[list[str]]
    walkable: NotRequired[bool]
    blocking: NotRequired[bool]
    scenes: NotRequired[list[str]]
    semantics: NotRequired[list[str]]
    motifs: NotRequired[list[str]]
    cluster_ids: NotRequired[list[str]]
    source_group: NotRequired[str]
    noise: NotRequired[str]
    contrast: NotRequired[str]
    temperature: NotRequired[str]
    usage: NotRequired[str]
    style: NotRequired[str]
    overlay: NotRequired[str]
    footprint: NotRequired[str]
    orientation: NotRequired[str]
    facing: NotRequired[str]
    pose: NotRequired[str]
    compose_group: NotRequired[str]
    compose_role: NotRequired[str]
    state_group: NotRequired[str]
    state_role: NotRequired[str]
    animation_group: NotRequired[str]
    animation_frame: NotRequired[int]
    animation_frame_count: NotRequired[int]
    connects_on: NotRequired[list[str]]
    cell_content_inset: NotRequired[Mapping[str, int]]
    requires_exposed_on: NotRequired[list[str]]
    affordances: NotRequired[list[str]]
    alt_uses: NotRequired[list[str]]
    meaning: NotRequired[str]
    meaning_confidence: NotRequired[str]
    source_notes: NotRequired[str]


class TileFamilyIngestSourceRegionReport(TypedDict):
    total: int
    missing_source_group: int
    missing_cluster_ids: int
    missing_meaning: int
    missing_meaning_confidence: int
    uncertain_meaning: int
    by_meaning_confidence: dict[str, int]


class TileFamilyIngestReport(TypedDict):
    family_id: str
    tile_count: int
    cluster_count: int
    complete: bool
    missing_source_group: list[str]
    missing_cluster_ids: list[str]
    missing_meaning: list[str]
    missing_meaning_confidence: list[str]
    uncertain_meaning: list[str]
    by_meaning_confidence: dict[str, int]
    by_source_region: dict[str, TileFamilyIngestSourceRegionReport]
    by_cluster: dict[str, int]


FamilyAliasesManifest = dict[str, str]


class ConstructionCellConfig(TypedDict):
    role: str


class FixedConstructionSeamOverrideCellConfig(TypedDict):
    x: int
    y: int


class FixedConstructionSeamOverrideConfig(TypedDict):
    cell: FixedConstructionSeamOverrideCellConfig
    side: FixedSeamOverrideSide
    reason: str


class FixedConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["fixed"]
    cells: list[list[ConstructionCellConfig | str]]
    seam_overrides: NotRequired[list[FixedConstructionSeamOverrideConfig]]
    expose_as_entity: NotRequired[bool]


class CompositeTileConfig(TypedDict):
    id: str
    collection_id: str
    cells: list[list[ConstructionCellConfig | str]]
    expose_as_entity: NotRequired[bool]
    tags: NotRequired[list[str]]


class ParametricRunConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["parametric_run"]
    axis: str
    length_param: str
    start_role: str
    repeat_role: str
    end_role: str
    expose_as_entity: NotRequired[bool]


class FrameSlotConfig(TypedDict):
    fill_mode: NotRequired[str]
    role: NotRequired[str]
    tile: NotRequired[str]
    flip_x: NotRequired[bool]
    flip_y: NotRequired[bool]


class FrameCornerSlotConfig(TypedDict):
    role: NotRequired[str]
    tile: NotRequired[str]
    cells: NotRequired[list[list[str]]]
    flip_x: NotRequired[bool]
    flip_y: NotRequired[bool]


class ParametricFrameConstructionConfig(TypedDict):
    id: str
    collection_id: str
    kind: Literal["parametric_frame"]
    corners: list[str] | dict[str, FrameCornerSlotConfig]
    edges: NotRequired[dict[str, FrameSlotConfig]]
    fill: NotRequired[FrameSlotConfig]
    min_width: NotRequired[int]
    min_height: NotRequired[int]
    width_param: NotRequired[str]
    height_param: NotRequired[str]
    expose_as_entity: NotRequired[bool]


class AttachmentCanvasConfig(TypedDict):
    x: int
    y: int
    width: int
    height: int


class PlaceableRefConfig(TypedDict):
    kind: PlaceableKind
    id: str


class ConstructionAttachmentVariantConfig(TypedDict):
    id: str
    construction_id: NotRequired[str]
    placeable: NotRequired[PlaceableRefConfig]
    label: NotRequired[str]
    notes: NotRequired[str]


class ConstructionAttachmentSetConfig(TypedDict):
    id: str
    param: str
    target_construction_ids: NotRequired[list[str]]
    target_placeables: NotRequired[list[PlaceableRefConfig]]
    canvas: AttachmentCanvasConfig
    variants: list[ConstructionAttachmentVariantConfig]
    required: NotRequired[bool]
    default_variant_id: NotRequired[str]
    label: NotRequired[str]
    notes: NotRequired[str]


ConstructionConfig = Union[
    FixedConstructionConfig,
    ParametricRunConstructionConfig,
    ParametricFrameConstructionConfig,
]


def load_family_manifest(path: Path) -> FamilyManifest:
    raw = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw, ("family_id", "grid", "variants"), context=str(path))
    grid_raw = require_mapping(raw["grid"], context=f"{path}: grid")
    check_required_keys(grid_raw, ("tile_width", "tile_height"), context=f"{path}: grid")
    variants_raw = require_list(raw["variants"], context=f"{path}: variants")
    for index, variant_value in enumerate(variants_raw):
        variant_mapping = require_mapping(variant_value, context=f"{path}: variants[{index}]")
        check_required_keys(
            variant_mapping,
            ("variant_id", "sheet"),
            context=f"{path}: variants[{index}]",
        )
    return cast(FamilyManifest, raw)


def load_family_variants_from_manifest(
    *,
    root: Path,
    variants_data: list[FamilyVariantConfig],
) -> dict[str, TileFamilyVariant]:
    variants: dict[str, TileFamilyVariant] = {}
    for spec in variants_data:
        variant_id = str(spec["variant_id"])
        if variant_id in variants:
            raise ValueError(f"Duplicate variant_id in {root}: {variant_id}")
        variants[variant_id] = TileFamilyVariant(
            id=variant_id,
            sheet_path=resolve_path(root, str(spec["sheet"])),
            transparent_mode=str(spec.get("transparent", DEFAULT_TRANSPARENT_MODE)),
            palette_family=spec.get("palette_family"),
            colorway=spec.get("colorway"),
            background_mode=spec.get("background_mode"),
            notes=spec.get("notes"),
        )
    return variants


def load_family_header_from_manifest(
    *,
    root: Path,
    family_data: FamilyManifest,
    variants: Mapping[str, TileFamilyVariant],
) -> TileFamilyHeader:
    grid = family_data.get("grid", {})
    render_defaults = family_data.get("render_defaults", {})
    declared_default_variant_id = family_data.get("default_variant_id")
    if declared_default_variant_id is None and not variants:
        raise ValueError(f"Tile family {root} must define at least one variant")
    default_variant_id = (
        str(declared_default_variant_id)
        if declared_default_variant_id is not None
        else next(iter(variants.keys()))
    )
    # Shape/sign is validated here; the inset-vs-tile-dimension check lives in
    # TileFamilyHeader.__post_init__ so it covers the staged bridge path too.
    cell_content_inset = CellContentInset.from_mapping(
        family_data.get("cell_content_inset"), context=f"{root}: family cell_content_inset"
    )
    runtime_flippable = _parse_family_runtime_flippable(family_data, root=root)
    return TileFamilyHeader(
        root=root,
        family_id=str(family_data["family_id"]),
        title=family_data.get("title"),
        tile_width=int(grid["tile_width"]),
        tile_height=int(grid["tile_height"]),
        render_step_width=render_defaults.get("render_step_width"),
        render_step_height=render_defaults.get("render_step_height"),
        siblings_share_semantics=family_data.get("siblings_share_semantics"),
        notes=(
            _tuple(cast(Iterable[str], family_data["notes"]))
            if "notes" in family_data
            else None
        ),
        default_variant_id=default_variant_id,
        cell_content_inset=cell_content_inset,
        runtime_flippable=runtime_flippable,
    )


def load_family_header_and_variants(
    root: Path,
) -> tuple[TileFamilyHeader, dict[str, TileFamilyVariant], FamilyManifest]:
    family_data = load_family_manifest(root / "family.json")
    variants = load_family_variants_from_manifest(
        root=root,
        variants_data=family_data.get("variants", []),
    )
    header = load_family_header_from_manifest(
        root=root,
        family_data=family_data,
        variants=variants,
    )
    return header, variants, family_data


def load_cluster_manifest(path: Path) -> list[ClusterConfig]:
    raw = require_list(load_json(path), context=str(path))
    for index, value in enumerate(raw):
        mapping = require_mapping(value, context=f"{path}[{index}]")
        check_required_keys(mapping, ("id",), context=f"{path}[{index}]")
    return cast(list[ClusterConfig], raw)


def load_tile_manifest(path: Path) -> list[TileConfig]:
    raw = require_list(load_json(path), context=str(path))
    for index, value in enumerate(raw):
        mapping = require_mapping(value, context=f"{path}[{index}]")
        check_required_keys(
            mapping,
            ("id", "layer", "category", "transparent"),
            context=f"{path}[{index}]",
        )
    return cast(list[TileConfig], raw)


def load_alias_manifest(path: Path) -> FamilyAliasesManifest:
    return cast(FamilyAliasesManifest, require_mapping(load_json(path), context=str(path)))


def load_construction_manifest(path: Path) -> tuple[ConstructionConfig, ...]:
    raw_file = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw_file, ("constructions",), context=str(path))
    raw_list = require_list(raw_file["constructions"], context=f"{path}: constructions")
    loaded: list[ConstructionConfig] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_list):
        item_context = f"{path}: constructions[{index}]"
        item_mapping = require_mapping(raw_item, context=item_context)
        check_required_keys(item_mapping, ("id", "collection_id", "kind"), context=item_context)
        construction_kind = str(item_mapping["kind"])
        if construction_kind == "fixed":
            check_required_keys(item_mapping, ("cells",), context=item_context)
        elif construction_kind == "parametric_run":
            check_required_keys(
                item_mapping,
                ("axis", "length_param", "start_role", "repeat_role", "end_role"),
                context=item_context,
            )
        elif construction_kind == "parametric_frame":
            check_required_keys(item_mapping, ("corners",), context=item_context)
        else:
            raise ValueError(f"{item_context}: unsupported construction kind {construction_kind!r}")
        construction_id = str(item_mapping["id"])
        if construction_id in seen_ids:
            raise ValueError(f"Duplicate construction id in {path}: {construction_id!r}")
        seen_ids.add(construction_id)
        loaded.append(cast(ConstructionConfig, item_mapping))
    return tuple(loaded)


def load_composite_tile_manifest(path: Path) -> tuple[CompositeTileConfig, ...]:
    raw_file = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw_file, ("composite_tiles",), context=str(path))
    raw_list = require_list(raw_file["composite_tiles"], context=f"{path}: composite_tiles")
    loaded: list[CompositeTileConfig] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_list):
        item_context = f"{path}: composite_tiles[{index}]"
        item_mapping = require_mapping(raw_item, context=item_context)
        check_required_keys(item_mapping, ("id", "collection_id", "cells"), context=item_context)
        composite_id = str(item_mapping["id"])
        if composite_id in seen_ids:
            raise ValueError(f"Duplicate composite tile id in {path}: {composite_id!r}")
        seen_ids.add(composite_id)
        loaded.append(cast(CompositeTileConfig, item_mapping))
    return tuple(loaded)


def load_attachment_manifest(path: Path) -> tuple[ConstructionAttachmentSetConfig, ...]:
    raw_file = require_mapping(load_json(path), context=str(path))
    check_required_keys(raw_file, ("attachment_sets",), context=str(path))
    raw_list = require_list(raw_file["attachment_sets"], context=f"{path}: attachment_sets")
    loaded: list[ConstructionAttachmentSetConfig] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_list):
        item_context = f"{path}: attachment_sets[{index}]"
        item_mapping = require_mapping(raw_item, context=item_context)
        check_required_keys(item_mapping, ("id", "param", "canvas", "variants"), context=item_context)
        attachment_id = str(item_mapping["id"])
        if attachment_id in seen_ids:
            raise ValueError(f"Duplicate attachment set id in {path}: {attachment_id!r}")
        seen_ids.add(attachment_id)
        loaded.append(cast(ConstructionAttachmentSetConfig, item_mapping))
    return tuple(loaded)


def load_family_catalog_sources(
    paths: CompatibilityFamilyPaths,
) -> FamilyCatalogSources:
    constructions_data: tuple[ConstructionConfig, ...] = ()
    if paths.constructions_path is not None:
        constructions_data = load_construction_manifest(paths.constructions_path)
    composite_tiles_data: tuple[CompositeTileConfig, ...] = ()
    if paths.composite_tiles_path is not None:
        composite_tiles_data = load_composite_tile_manifest(paths.composite_tiles_path)
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...] = ()
    if paths.attachments_path is not None:
        attachments_data = load_attachment_manifest(paths.attachments_path)
    return FamilyCatalogSources(
        paths=paths,
        clusters_data=tuple(load_cluster_manifest(paths.clusters_path)),
        tiles_data=tuple(load_tile_manifest(paths.tiles_path)),
        aliases_data=MappingProxyType(dict(load_alias_manifest(paths.aliases_path))),
        constructions_data=constructions_data,
        composite_tiles_data=composite_tiles_data,
        attachments_data=attachments_data,
    )


def _tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(values or ())


def _group_aliases_by_tile(aliases: dict[str, str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for alias, tile_id in aliases.items():
        grouped[tile_id].append(alias)
    return {tile_id: tuple(sorted(items)) for tile_id, items in grouped.items()}


@dataclass(frozen=True)
class FamilyCatalogSources:
    paths: CompatibilityFamilyPaths
    clusters_data: tuple[ClusterConfig, ...]
    tiles_data: tuple[TileConfig, ...]
    aliases_data: Mapping[str, str]
    constructions_data: tuple[ConstructionConfig, ...]
    composite_tiles_data: tuple[CompositeTileConfig, ...]
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...]


TILE_SEQUENCE_FIELDS = frozenset(
    {
        "aliases",
        "tags",
        "scenes",
        "semantics",
        "motifs",
        "cluster_ids",
        "connects_on",
        "requires_exposed_on",
        "affordances",
        "alt_uses",
    }
)
# Provenance facts that moved onto TileGenesis (ADR 0005) but remain query-able;
# `cluster_ids` is a sequence field, the rest are equality fields.
TILE_GENESIS_EQUALITY_FIELDS = frozenset({"sheet_col", "sheet_row", "source_group"})
TILE_GENESIS_QUERY_FIELDS = TILE_GENESIS_EQUALITY_FIELDS | {"cluster_ids"}
TILE_EQUALITY_FIELDS = (
    frozenset(
        field.name
        for field in fields(TileRecord)
        if field.name not in TILE_SEQUENCE_FIELDS and field.name != "genesis"
    )
    | TILE_GENESIS_EQUALITY_FIELDS
)
TILE_QUERY_ALIASES = {
    "scene": "scenes",
    "semantic_cluster_id": "cluster_ids",
}


def _tile_query_value(tile: TileRecord, field_name: str) -> object:
    """Read a query field, routing genesis-backed provenance facts to `tile.genesis`."""
    if field_name in TILE_GENESIS_QUERY_FIELDS:
        return getattr(tile.genesis, field_name)
    return getattr(tile, field_name)
TILE_QUERY_FIELDS_FOR_SUGGESTION = TILE_EQUALITY_FIELDS | TILE_SEQUENCE_FIELDS | set(TILE_QUERY_ALIASES)
MEANING_CONFIDENCE_VALUES = frozenset({"confirmed", "tentative", "unknown"})
EXACT_DUPLICATE_INHERITED_SEQUENCE_FIELDS = frozenset(
    {
        "tags",
        "scenes",
        "semantics",
        "motifs",
        "connects_on",
        "requires_exposed_on",
        "affordances",
        "alt_uses",
    }
)
EXACT_DUPLICATE_INHERITED_SCALAR_FIELDS = frozenset(
    {
        "image_override",
        "layer",
        "category",
        "transparent",
        "walkable",
        "blocking",
        "noise",
        "contrast",
        "temperature",
        "usage",
        "style",
        "overlay",
        "footprint",
        "orientation",
        "compose_group",
        "compose_role",
        "meaning",
        "meaning_confidence",
        "source_notes",
    }
)


def _normalise_query_values(raw: object) -> set[str]:
    if isinstance(raw, str):
        return {raw}
    if not isinstance(raw, Iterable):
        raise TypeError(
            f"query value must be str or iterable of str, got {type(raw).__name__}"
        )
    return {str(value) for value in cast(Iterable[object], raw)}


def _unknown_query_field_error(raw_key: str) -> TypeError:
    suggestion = get_close_matches(
        raw_key.removesuffix("_all").removesuffix("_any"),
        list(TILE_QUERY_FIELDS_FOR_SUGGESTION),
        n=1,
    )
    if suggestion:
        return TypeError(f"Unknown tile query field {raw_key!r}; did you mean {suggestion[0]!r}?")
    return TypeError(f"Unknown tile query field {raw_key!r}")


def _meaning_is_uncertain(meaning: str | None) -> bool:
    if meaning is None:
        return False
    lower = meaning.lower()
    return any(marker in lower for marker in ("uncertain", "first-pass", "likely", "provisional"))


def _normalise_meaning_confidence(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context} meaning_confidence must be a string when present")
    if value not in MEANING_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(MEANING_CONFIDENCE_VALUES))
        raise ValueError(f"{context} meaning_confidence must be one of: {allowed}")
    return value


def _crop_tile_from_sheet(
    sheet: Image.Image,
    *,
    sheet_col: int,
    sheet_row: int,
    tile_width: int,
    tile_height: int,
) -> Image.Image:
    """The tile-sized region of ``sheet`` at grid cell ``(sheet_col, sheet_row)``."""
    left = sheet_col * tile_width
    top = sheet_row * tile_height
    return sheet.crop((left, top, left + tile_width, top + tile_height))


def sheet_tile_image(
    sheet: Image.Image,
    *,
    sheet_col: int,
    sheet_row: int,
    tile_width: int,
    tile_height: int,
    transparent_mode: str,
) -> Image.Image:
    image = _crop_tile_from_sheet(
        sheet,
        sheet_col=sheet_col,
        sheet_row=sheet_row,
        tile_width=tile_width,
        tile_height=tile_height,
    ).convert("RGBA")
    transparent_key = transparent_key_for_sheet(sheet, transparent_mode)
    if transparent_key is not None:
        apply_transparent_key(image, transparent_key)
    return image


def resolve_canonical_tile_image(
    tile: TileRecord,
    *,
    variant: TileFamilyVariant,
    root: Path,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
    require_tile_size: bool = True,
) -> Image.Image:
    if tile.image_override is not None:
        image_override_path = resolve_tile_image_override_path(
            root=root,
            image_override=tile.image_override,
            variant_id=variant.id,
        )
        image = image_cache.get(image_override_path)
        if image is None:
            image = Image.open(image_override_path).convert("RGBA")
            image_cache[image_override_path] = image
        if require_tile_size and image.size != (tile_width, tile_height):
            raise ValueError(
                f"Tile {tile.id!r} image_override {image_override_path} is {image.size}, "
                f"expected {(tile_width, tile_height)}"
            )
        return image.copy()

    if tile.genesis.sheet_col is None or tile.genesis.sheet_row is None:
        raise ValueError(f"Sheet-backed tile {tile.id!r} requires sheet_col and sheet_row")
    sheet_path = require_variant_sheet_path(variant, context=f"canonical tile image {tile.id!r}")
    image = image_cache.get(sheet_path)
    if image is None:
        image = Image.open(sheet_path).convert("RGBA")
        image_cache[sheet_path] = image
    return sheet_tile_image(
        image,
        sheet_col=tile.genesis.sheet_col,
        sheet_row=tile.genesis.sheet_row,
        tile_width=tile_width,
        tile_height=tile_height,
        transparent_mode=variant.transparent_mode,
    )


def _tile_image_bytes(
    *,
    tile: TileRecord,
    variant: TileFamilyVariant,
    root: Path,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
) -> bytes:
    return resolve_canonical_tile_image(
        tile,
        variant=variant,
        root=root,
        tile_width=tile_width,
        tile_height=tile_height,
        image_cache=image_cache,
    ).tobytes()


def _tile_occupancy_grid(
    *,
    tile: TileRecord,
    variant: TileFamilyVariant,
    root: Path,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
) -> list[list[bool]]:
    """A tile's per-pixel occupancy (``True`` = painted) from its *normalised* art.

    Background normalisation runs first (ADR 0007 precondition): a sheet-backed
    tile's keyed background becomes transparent before occupancy is read, so a
    gutter resolves to "no seam" rather than a false painted run. Synthetic
    override images already carry genuine alpha, so they are read as-is. The grid
    follows the tile's own pixel dimensions — a sheet crop is
    ``tile_width × tile_height``; an override is read at its native size.
    """
    image = resolve_canonical_tile_image(
        tile,
        variant=variant,
        root=root,
        tile_width=tile_width,
        tile_height=tile_height,
        image_cache=image_cache,
        require_tile_size=False,
    )
    width, height = image.size
    alpha = image.getchannel("A")
    return [
        [cast(int, alpha.getpixel((x, y))) > 0 for x in range(width)]
        for y in range(height)
    ]


def _attach_seam_profiles(
    *,
    tiles: dict[str, TileRecord],
    default_variant: TileFamilyVariant,
    root: Path,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
    default_inset: CellContentInset,
) -> dict[str, TileRecord]:
    """Derive each tile's per-side seam profile from its own normalised pixels.

    Runtime-derived (see the [[Ingestion–Runtime Separation]] invariant): the
    seam profile is a pure function of the runtime sheet, never read back from
    ingest-side data, so deleting all ingest data leaves it intact. Silhouette
    is colour-blind (D2), so the family default variant's pixels suffice. The
    caller supplies ``image_cache`` so the default variant's sheet — already
    loaded for bounds-checking — is not re-opened.

    The contact line is read at the content-box edge using the tile's own
    ``cell_content_inset`` override when present, otherwise the family
    ``default_inset`` (ADR 0008), so a consistent gutter is matched as painted-
    to-painted rather than as a null edge.
    """
    enriched: dict[str, TileRecord] = {}
    for tile_id, tile in tiles.items():
        grid = _tile_occupancy_grid(
            tile=tile,
            variant=default_variant,
            root=root,
            tile_width=tile_width,
            tile_height=tile_height,
            image_cache=image_cache,
        )
        inset = tile.cell_content_inset if tile.cell_content_inset is not None else default_inset
        masks = derive_side_masks(grid, top=inset.top, right=inset.right, bottom=inset.bottom, left=inset.left)
        enriched[tile_id] = replace(tile, seam_profiles=masks)
    return enriched


def _sheet_bounds_for_variant(
    *,
    variant: TileFamilyVariant,
    tile_width: int,
    tile_height: int,
    image_cache: dict[Path, Image.Image],
) -> GridBounds:
    sheet_path = require_variant_sheet_path(variant, context="variant sheet bounds")
    image = image_cache.get(sheet_path)
    if image is None:
        image = Image.open(sheet_path).convert("RGBA")
        image_cache[sheet_path] = image
    if image.width % tile_width != 0 or image.height % tile_height != 0:
        raise ValueError(
            f"Variant sheet {sheet_path} size {image.width}x{image.height} is not aligned to"
            f" tile size {tile_width}x{tile_height}"
        )
    return GridBounds(
        x=0,
        y=0,
        width=image.width // tile_width,
        height=image.height // tile_height,
    )


DEFAULT_SEAM_MATCH_POLICY = MatchPolicy()


class ConstructionValidationError(ValueError):
    pass


def _seam_fit_scores(
    *,
    construction_id: str,
    a: TileRecord,
    a_side: str,
    b: TileRecord,
    b_side: str,
    where: str,
) -> tuple[bool, Mapping[str, float]]:
    mask_a = a.seam_profiles.get(a_side) if a.seam_profiles is not None else None
    mask_b = b.seam_profiles.get(b_side) if b.seam_profiles is not None else None
    if mask_a is None or mask_b is None:
        raise ConstructionValidationError(
            f"construction {construction_id!r} {where}: seam profile missing"
            f" ({a.id!r}.{a_side} or {b.id!r}.{b_side}) - tiles must be seam-enriched before validation"
        )
    return DEFAULT_SEAM_MATCH_POLICY.fits(mask_a, mask_b), DEFAULT_SEAM_MATCH_POLICY.scores(mask_a, mask_b)


def _score_text(scores: Mapping[str, float]) -> str:
    return ", ".join(f"{name}={value:.3f}" for name, value in sorted(scores.items()))


_CANONICAL_CONTACTS: tuple[tuple[FixedSeamOverrideSide, int, int, str], ...] = (
    ("east", 0, 1, "west"),
    ("south", 1, 0, "north"),
)


def _assert_seam_fits(
    *,
    construction_id: str,
    a: TileRecord,
    a_side: str,
    b: TileRecord,
    b_side: str,
    where: str,
) -> None:
    """Assert tile ``a``'s ``a_side`` seam fits tile ``b``'s ``b_side``."""
    fits, scores = _seam_fit_scores(
        construction_id=construction_id,
        a=a,
        a_side=a_side,
        b=b,
        b_side=b_side,
        where=where,
    )
    if fits:
        return
    raise ConstructionValidationError(
        f"construction {construction_id!r} {where}: seams do not fit"
        f" ({a.id!r}.{a_side} vs {b.id!r}.{b_side}; {_score_text(scores)}). Fix the art so the"
        f" pieces tile, or model this as a fixed construction rather than a dynamic run"
    )


def _validate_fixed_construction(construction: FixedConstruction) -> None:
    rows = construction.cells
    n_rows = len(rows)
    override_map = {
        (override.x, override.y, override.side): override
        for override in construction.seam_overrides
    }
    for override_key, override in override_map.items():
        col_idx, row_idx, direction = override_key
        _, d_row, d_col, _ = next(contact for contact in _CANONICAL_CONTACTS if contact[0] == direction)
        if not (0 <= row_idx < n_rows and 0 <= col_idx < len(rows[row_idx])):
            raise ConstructionValidationError(
                f"construction {construction.id!r} seam override at (col={col_idx}, row={row_idx})"
                f" {direction!r} is outside the fixed construction grid"
            )
        if rows[row_idx][col_idx] is None:
            raise ConstructionValidationError(
                f"construction {construction.id!r} seam override at (col={col_idx}, row={row_idx})"
                f" {direction!r} references an empty cell"
            )
        n_row = row_idx + d_row
        n_col = col_idx + d_col
        if not (0 <= n_row < n_rows and 0 <= n_col < len(rows[n_row])) or rows[n_row][n_col] is None:
            raise ConstructionValidationError(
                f"construction {construction.id!r} seam override at (col={col_idx}, row={row_idx})"
                f" {direction!r} does not reference a filled internal neighbour"
            )

    for row_idx, row in enumerate(rows):
        for col_idx, cell in enumerate(row):
            if cell is None:
                continue
            for direction, d_row, d_col, opposite in _CANONICAL_CONTACTS:
                n_row = row_idx + d_row
                n_col = col_idx + d_col
                if not (0 <= n_row < n_rows and 0 <= n_col < len(rows[n_row])):
                    continue
                neighbour = rows[n_row][n_col]
                if neighbour is None:
                    continue
                where = (
                    f"cell (col={col_idx}, row={row_idx}) {direction} to"
                    f" neighbour at (col={n_col}, row={n_row})"
                )
                fits, scores = _seam_fit_scores(
                    construction_id=construction.id,
                    a=cell,
                    a_side=direction,
                    b=neighbour,
                    b_side=opposite,
                    where=where,
                )
                override_key = (col_idx, row_idx, direction)
                override = override_map.get(override_key)
                if fits and override is not None:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} {where}: seam override is unnecessary"
                        f" because the seam now fits ({_score_text(scores)}). Remove the stale override."
                    )
                if not fits and override is None:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} {where}: seams do not fit"
                        f" ({cell.id!r}.{direction} vs {neighbour.id!r}.{opposite}; {_score_text(scores)})."
                        f" Fix the art so the pieces tile, or add a recorded seam override with a reason."
                    )
            for direction, d_row, d_col in (
                ("north", -1, 0),
                ("south", 1, 0),
                ("east", 0, 1),
                ("west", 0, -1),
            ):
                if direction not in cell.requires_exposed_on:
                    continue
                n_row = row_idx + d_row
                n_col = col_idx + d_col
                if not (0 <= n_row < n_rows and 0 <= n_col < len(rows[n_row])):
                    continue
                neighbour = rows[n_row][n_col]
                if neighbour is not None:
                    raise ConstructionValidationError(
                        f"construction {construction.id!r} cell (col={col_idx}, row={row_idx})"
                        f" requires_exposed_on={list(cell.requires_exposed_on)!r}"
                        f" but internal neighbour at (col={n_col}, row={n_row}) is filled"
                    )


def _validate_parametric_run_construction(construction: ParametricRunConstruction) -> None:
    cid = construction.id
    start = construction.start_tile
    repeat = construction.repeat_tile
    end = construction.end_tile
    forward, backward = ("east", "west") if construction.axis == "x" else ("south", "north")
    # The run lays out start | repeat ... repeat | end along the axis: each tile's
    # forward seam abuts the next tile's backward seam.
    _assert_seam_fits(
        construction_id=cid, a=start, a_side=forward, b=repeat, b_side=backward,
        where="start_role to repeat_role",
    )
    _assert_seam_fits(
        construction_id=cid, a=repeat, a_side=forward, b=repeat, b_side=backward,
        where="repeat_role to repeat_role",
    )
    _assert_seam_fits(
        construction_id=cid, a=repeat, a_side=forward, b=end, b_side=backward,
        where="repeat_role to end_role",
    )


def _validate_parametric_frame_construction(construction: ParametricFrameConstruction) -> None:
    if not construction.corners:
        raise ConstructionValidationError(
            f"construction {construction.id!r} parametric_frame must declare at least one corner"
        )
    if construction.min_width < 2 or construction.min_height < 2:
        raise ConstructionValidationError(
            f"construction {construction.id!r} parametric_frame min_width/min_height must be >= 2"
        )


def validate_construction(construction: Construction) -> None:
    if isinstance(construction, ParametricRunConstruction):
        _validate_parametric_run_construction(construction)
    elif isinstance(construction, ParametricFrameConstruction):
        _validate_parametric_frame_construction(construction)
    else:
        _validate_fixed_construction(construction)


def _resolve_role(
    role: str,
    *,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
) -> TileRecord:
    matches = [
        t for t in tiles.values()
        if t.compose_group == collection_id and t.compose_role == role
    ]
    if len(matches) > 1:
        ids = [t.id for t in matches]
        raise ValueError(
            f"construction {construction_id!r} role {role!r}: "
            f"multiple tiles match compose_group={collection_id!r} + compose_role={role!r}: {ids}"
        )
    if not matches:
        raise ValueError(
            f"construction {construction_id!r} role {role!r}: "
            f"no tile found with compose_group={collection_id!r} + compose_role={role!r}"
        )
    return matches[0]


def _parse_expose_as_entity(
    raw: Mapping[str, object],
    subject_id: str,
    *,
    subject: str = "construction",
    default: bool = True,
) -> bool:
    return _parse_optional_bool(
        raw,
        "expose_as_entity",
        context=f"{subject} {subject_id!r}",
        default=default,
    )


def _parse_optional_bool(raw: Mapping[str, object], key: str, *, context: str, default: bool = False) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{context} {key} must be a boolean")
    return value


def _parse_family_runtime_flippable(family_data: Mapping[str, object], *, root: Path) -> bool:
    return _parse_optional_bool(
        family_data,
        "runtime_flippable",
        context=f"{root}: family",
        default=True,
    )


def _reject_runtime_flip_on_non_flippable(
    flip_x: bool,
    flip_y: bool,
    runtime_flippable: bool,
    *,
    context: str,
) -> None:
    if (flip_x or flip_y) and not runtime_flippable:
        raise ValueError(f"{context} uses runtime flip on non-flippable family")


def _build_composite_tile(
    raw: CompositeTileConfig,
    *,
    family_id: str,
    tiles: dict[str, TileRecord],
) -> CompositeTileRecord:
    composite_id = str(raw["id"])
    collection_id = str(raw["collection_id"])
    raw_rows = raw["cells"]

    if not raw_rows:
        raise ValueError(f"composite tile {composite_id!r} has no rows in cells")

    row_width = len(raw_rows[0])
    for row_idx, raw_row in enumerate(raw_rows):
        if len(raw_row) != row_width:
            raise ValueError(
                f"composite tile {composite_id!r} has ragged cells: "
                f"row 0 has {row_width} columns, row {row_idx} has {len(raw_row)}"
            )

    resolved_rows: list[tuple[CompositeTileCell | None, ...]] = []
    for y, raw_row in enumerate(raw_rows):
        resolved_cells: list[CompositeTileCell | None] = []
        for x, raw_cell in enumerate(raw_row):
            if raw_cell == ".":
                resolved_cells.append(None)
                continue
            if not isinstance(raw_cell, dict):
                raise ValueError(
                    f"composite tile {composite_id!r} cell must be a dict with 'role' or the string '.'"
                )
            role = str(raw_cell["role"])
            tile = _resolve_role(role, construction_id=composite_id, collection_id=collection_id, tiles=tiles)
            resolved_cells.append(CompositeTileCell(tile=tile, x=x, y=y, role=role))
        resolved_rows.append(tuple(resolved_cells))

    return CompositeTileRecord(
        id=composite_id,
        family_id=family_id,
        collection_id=collection_id,
        cells=tuple(resolved_rows),
        tags=_tuple(raw.get("tags")),
        expose_as_entity=_parse_expose_as_entity(raw, composite_id, subject="placeable"),
    )


def _parse_fixed_seam_overrides(
    raw: Mapping[str, object],
    *,
    construction_id: str,
) -> tuple[FixedConstructionSeamOverride, ...]:
    raw_overrides = raw.get("seam_overrides", [])
    overrides: list[FixedConstructionSeamOverride] = []
    for index, raw_override in enumerate(require_list(raw_overrides, context=f"construction {construction_id!r} seam_overrides")):
        context = f"construction {construction_id!r} seam_overrides[{index}]"
        override = require_mapping(raw_override, context=context)
        check_required_keys(override, ("cell", "side", "reason"), context=context)
        cell = require_mapping(override["cell"], context=f"{context}: cell")
        check_required_keys(cell, ("x", "y"), context=f"{context}: cell")
        x = cell["x"]
        y = cell["y"]
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            raise ValueError(f"{context}: cell x and y must be integers")
        side = override["side"]
        if not isinstance(side, str):
            raise ValueError(f"{context}: side must be a string")
        reason = override["reason"]
        if not isinstance(reason, str):
            raise ValueError(f"{context}: reason must be a string")
        try:
            seam_override = FixedConstructionSeamOverride(
                x=x,
                y=y,
                side=cast(FixedSeamOverrideSide, side),
                reason=reason,
            )
        except ValueError as exc:
            raise ValueError(f"{context}: {exc}") from exc
        overrides.append(seam_override)
    return tuple(overrides)


def _build_fixed_construction(
    raw: FixedConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> FixedConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]
    raw_rows = raw["cells"]

    if not raw_rows:
        raise ValueError(f"construction {construction_id!r} has no rows in cells")

    row_width = len(raw_rows[0])
    for row_idx, raw_row in enumerate(raw_rows):
        if len(raw_row) != row_width:
            raise ValueError(
                f"construction {construction_id!r} has ragged cells: "
                f"row 0 has {row_width} columns, row {row_idx} has {len(raw_row)}"
            )

    resolved_rows: list[tuple[TileRecord | None, ...]] = []
    for raw_row in raw_rows:
        resolved_cells: list[TileRecord | None] = []
        for raw_cell in raw_row:
            if raw_cell == ".":
                resolved_cells.append(None)
                continue
            if not isinstance(raw_cell, dict):
                raise ValueError(
                    f"construction {construction_id!r} cell must be a dict with 'role' or the string '.'"
                )
            role = str(raw_cell["role"])
            resolved_cells.append(_resolve_role(role, construction_id=construction_id, collection_id=collection_id, tiles=tiles))
        resolved_rows.append(tuple(resolved_cells))

    construction = FixedConstruction(
        id=construction_id,
        collection_id=collection_id,
        cells=tuple(resolved_rows),
        seam_overrides=_parse_fixed_seam_overrides(cast(Mapping[str, object], raw), construction_id=construction_id),
        expose_as_entity=_parse_expose_as_entity(raw, construction_id),
    )
    validate_construction(construction)
    return construction


def _build_parametric_run_construction(
    raw: ParametricRunConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
) -> ParametricRunConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]
    axis = raw["axis"]
    if axis not in ("x", "y"):
        raise ValueError(
            f"construction {construction_id!r} parametric_run axis must be 'x' or 'y', got {axis!r}"
        )
    length_param = raw["length_param"]

    start_tile = _resolve_role(raw["start_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    repeat_tile = _resolve_role(raw["repeat_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    end_tile = _resolve_role(raw["end_role"], construction_id=construction_id, collection_id=collection_id, tiles=tiles)

    construction = ParametricRunConstruction(
        id=construction_id,
        collection_id=collection_id,
        axis=axis,
        length_param=length_param,
        start_tile=start_tile,
        repeat_tile=repeat_tile,
        end_tile=end_tile,
        expose_as_entity=_parse_expose_as_entity(raw, construction_id),
    )
    validate_construction(construction)
    return construction


def _frame_slot(
    raw_slot: object,
    *,
    role: str,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
    runtime_flippable: bool,
) -> FrameSlot:
    if not isinstance(raw_slot, Mapping):
        raise ValueError(
            f"construction {construction_id!r} slot {role!r} must be a mapping with optional "
            f"'fill_mode'; got {type(raw_slot).__name__}"
        )
    slot_mapping: Mapping[str, object] = cast(Mapping[str, object], raw_slot)
    fill_mode = str(slot_mapping.get("fill_mode", "repeat"))
    if fill_mode not in FRAME_FILL_MODES:
        raise ValueError(
            f"construction {construction_id!r} slot {role!r} has invalid fill_mode {fill_mode!r}; "
            f"expected one of {FRAME_FILL_MODES}"
        )
    context = f"construction {construction_id!r} slot {role!r}"
    flip_x = _parse_optional_bool(slot_mapping, "flip_x", context=context)
    flip_y = _parse_optional_bool(slot_mapping, "flip_y", context=context)
    raw_tile = slot_mapping.get("tile")
    if raw_tile is not None:
        tile_id = str(raw_tile)
        if tile_id not in tiles:
            raise ValueError(f"construction {construction_id!r} slot {role!r} references unknown tile {tile_id!r}")
        tile = tiles[tile_id]
    else:
        # An explicit 'role' lets one edge borrow the opposite edge's art
        # (e.g. edge_right resolves edge_left's tile, then flips it).
        resolve_role = str(slot_mapping.get("role", role))
        tile = _resolve_role(resolve_role, construction_id=construction_id, collection_id=collection_id, tiles=tiles)
    _reject_runtime_flip_on_non_flippable(
        flip_x,
        flip_y,
        runtime_flippable,
        context=context,
    )
    return FrameSlot(tile=tile, fill_mode=fill_mode, flip_x=flip_x, flip_y=flip_y)


def _frame_corner_slot(
    key: str,
    raw_corner: object,
    *,
    construction_id: str,
    collection_id: str,
    tiles: dict[str, TileRecord],
    runtime_flippable: bool,
) -> FrameCornerSlot:
    """Resolve one corner slot.

    List-form sugar (``raw_corner is None``) resolves a single tile by the
    canonical ``corner_<key>`` role. The dict form takes an optional ``role``
    (single 1x1 tile) or a ``cells`` grid (fat corner), plus ``flip_x``/
    ``flip_y`` to derive a corner from another's art.
    """
    default_role = f"corner_{key}"

    def _tile(role: str) -> TileRecord:
        return _resolve_role(role, construction_id=construction_id, collection_id=collection_id, tiles=tiles)

    def _cell(token: str) -> TileRecord:
        # A fat-corner cell may name a tile by id (to borrow art already owned by
        # another kit) or by a compose role within this kit's collection.
        return tiles[token] if token in tiles else _tile(token)

    if raw_corner is None:
        return FrameCornerSlot(cells=((_tile(default_role),),))
    if not isinstance(raw_corner, Mapping):
        raise ValueError(
            f"construction {construction_id!r} corner {key!r} must be a mapping with "
            f"'role'/'cells' and optional flip_x/flip_y; got {type(raw_corner).__name__}"
        )
    corner_cfg = cast(Mapping[str, object], raw_corner)
    context = f"construction {construction_id!r} corner {key!r}"
    flip_x = _parse_optional_bool(corner_cfg, "flip_x", context=context)
    flip_y = _parse_optional_bool(corner_cfg, "flip_y", context=context)
    _reject_runtime_flip_on_non_flippable(
        flip_x,
        flip_y,
        runtime_flippable,
        context=context,
    )
    raw_tile = corner_cfg.get("tile")
    if raw_tile is not None:
        # Direct tile reference — lets a kit borrow another kit's corner art
        # (interchangeability) without re-binding compose roles.
        tile_id = str(raw_tile)
        if tile_id not in tiles:
            raise ValueError(
                f"construction {construction_id!r} corner {key!r} references unknown tile {tile_id!r}"
            )
        return FrameCornerSlot(cells=((tiles[tile_id],),), flip_x=flip_x, flip_y=flip_y)
    raw_cells = corner_cfg.get("cells")
    if raw_cells is not None:
        if not isinstance(raw_cells, list) or not raw_cells:
            raise ValueError(f"construction {construction_id!r} corner {key!r} 'cells' must be a non-empty grid")
        grid: list[tuple[TileRecord | None, ...]] = []
        width: int | None = None
        for raw_row in cast(list[object], raw_cells):
            if not isinstance(raw_row, list):
                raise ValueError(f"construction {construction_id!r} corner {key!r} 'cells' rows must be lists")
            row: list[object] = cast(list[object], raw_row)
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ValueError(f"construction {construction_id!r} corner {key!r} has a ragged 'cells' grid")
            grid.append(tuple(None if r == "." else _cell(str(r)) for r in row))
        return FrameCornerSlot(cells=tuple(grid), flip_x=flip_x, flip_y=flip_y)
    role = str(corner_cfg.get("role", default_role))
    return FrameCornerSlot(cells=((_tile(role),),), flip_x=flip_x, flip_y=flip_y)


def _build_parametric_frame_construction(
    raw: ParametricFrameConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
    runtime_flippable: bool,
) -> ParametricFrameConstruction:
    construction_id = raw["id"]
    collection_id = raw["collection_id"]

    corners: dict[str, FrameCornerSlot] = {}
    raw_corners = raw.get("corners", [])
    if isinstance(raw_corners, Mapping):
        corner_items: list[tuple[str, object]] = [(key, raw_corners[key]) for key in raw_corners]
    else:
        corner_items = [(key, None) for key in raw_corners]
    for key, raw_corner in corner_items:
        corners[f"corner_{key}"] = _frame_corner_slot(
            key,
            raw_corner,
            construction_id=construction_id,
            collection_id=collection_id,
            tiles=tiles,
            runtime_flippable=runtime_flippable,
        )

    edges: dict[str, FrameSlot] = {}
    for key, raw_slot in (raw.get("edges") or {}).items():
        role = f"edge_{key}"
        edges[role] = _frame_slot(
            raw_slot,
            role=role,
            construction_id=construction_id,
            collection_id=collection_id,
            tiles=tiles,
            runtime_flippable=runtime_flippable,
        )

    fill: FrameSlot | None = None
    raw_fill = raw.get("fill")
    if raw_fill is not None:
        fill = _frame_slot(
            raw_fill,
            role="fill",
            construction_id=construction_id,
            collection_id=collection_id,
            tiles=tiles,
            runtime_flippable=runtime_flippable,
        )

    construction = ParametricFrameConstruction(
        id=construction_id,
        collection_id=collection_id,
        corners=MappingProxyType(corners),
        edges=MappingProxyType(edges),
        fill=fill,
        min_width=int(raw.get("min_width", 2)),
        min_height=int(raw.get("min_height", 2)),
        width_param=str(raw.get("width_param", "width")),
        height_param=str(raw.get("height_param", "height")),
        expose_as_entity=_parse_expose_as_entity(cast(Mapping[str, object], raw), construction_id),
    )
    validate_construction(construction)
    return construction


def build_construction(
    raw: ConstructionConfig,
    *,
    tiles: dict[str, TileRecord],
    runtime_flippable: bool,
) -> Construction:
    kind = raw["kind"]
    if kind == "fixed":
        return _build_fixed_construction(cast(FixedConstructionConfig, raw), tiles=tiles)
    if kind == "parametric_run":
        return _build_parametric_run_construction(cast(ParametricRunConstructionConfig, raw), tiles=tiles)
    if kind == "parametric_frame":
        return _build_parametric_frame_construction(
            cast(ParametricFrameConstructionConfig, raw),
            tiles=tiles,
            runtime_flippable=runtime_flippable,
        )
    raise ValueError(f"construction {raw['id']!r} has unsupported kind {kind!r}")


def _load_clusters(
    *,
    root: Path,
    clusters_data: Iterable[ClusterConfig],
) -> dict[str, TileClusterRecord]:
    clusters: dict[str, TileClusterRecord] = {}
    for spec in clusters_data:
        cluster_id = str(spec["id"])
        if cluster_id in clusters:
            raise ValueError(f"Duplicate cluster id in {root}: {cluster_id}")
        clusters[cluster_id] = TileClusterRecord(
            id=cluster_id,
            scope=str(spec.get("scope", "family")),
            members=_tuple(spec.get("members")),
            kind_guess=spec.get("kind_guess"),
            evidence=_tuple(spec.get("evidence")),
            source_label=spec.get("source_label"),
            source_notes=spec.get("source_notes"),
        )
    return clusters


def _validate_tile_override_images(
    *,
    root: Path,
    tiles: Mapping[str, TileRecord],
    variants: Mapping[str, TileFamilyVariant],
    tile_width: int,
    tile_height: int,
) -> None:
    override_image_cache: dict[Path, Image.Image] = {}
    for tile in tiles.values():
        if tile.image_override is None:
            continue
        for variant in variants.values():
            image_path = resolve_tile_image_override_path(
                root=root,
                image_override=tile.image_override,
                variant_id=variant.id,
            )
            if not image_path.exists():
                raise ValueError(
                    f"Tile {tile.id} references missing image_override {tile.image_override!r} for variant {variant.id!r}"
                )
            image = override_image_cache.get(image_path)
            if image is None:
                image = Image.open(image_path).convert("RGBA")
                override_image_cache[image_path] = image
            if image.width <= 0 or image.height <= 0:
                raise ValueError(
                    f"Tile {tile.id} image_override {tile.image_override!r} is {image.size}, "
                    "expected a non-empty image"
                )


def _validate_exact_duplicate_pixels(
    *,
    root: Path,
    tiles: Mapping[str, TileRecord],
    variants: Mapping[str, TileFamilyVariant],
    tile_width: int,
    tile_height: int,
) -> None:
    # Compare rendered pixels: sheet-backed tiles are read after keyed-background
    # normalisation, while override tiles are read as authored RGBA. The
    # asymmetry intentionally mirrors the render paths.
    variant_image_cache: dict[Path, Image.Image] = {}
    for tile in tiles.values():
        if tile.exact_duplicate_of is None:
            continue
        canonical_tile = tiles[tile.exact_duplicate_of]
        for variant in variants.values():
            tile_bytes = _tile_image_bytes(
                tile=tile,
                variant=variant,
                root=root,
                tile_width=tile_width,
                tile_height=tile_height,
                image_cache=variant_image_cache,
            )
            canonical_bytes = _tile_image_bytes(
                tile=canonical_tile,
                variant=variant,
                root=root,
                tile_width=tile_width,
                tile_height=tile_height,
                image_cache=variant_image_cache,
            )
            if tile_bytes != canonical_bytes:
                raise ValueError(
                    f"Tile {tile.id} declares exact_duplicate_of {canonical_tile.id!r}, "
                    f"but their pixels differ in variant {variant.id!r}"
                )


def _validate_variant_sheet_bounds(
    *,
    variant_sheet_bounds: Mapping[str, GridBounds],
    family_sheet_bounds: GridBounds,
) -> None:
    for variant_id, bounds in variant_sheet_bounds.items():
        if not _bounds_inside(bounds, family_sheet_bounds):
            raise ValueError(
                f"Variant {variant_id!r} sheet bounds {bounds} do not cover family sheet bounds {family_sheet_bounds}"
            )


def _resolve_tiles_from_catalog(
    *,
    header: TileFamilyHeader,
    family_sheet_bounds: GridBounds,
    catalog: FamilyCatalogSources,
    aliases_by_tile: Mapping[str, tuple[str, ...]],
) -> dict[str, TileRecord]:
    raw_tile_specs: dict[str, TileConfig] = {}
    for spec in catalog.tiles_data:
        tile_id = str(spec["id"])
        if tile_id in raw_tile_specs:
            raise ValueError(f"Duplicate tile id in {header.root}: {tile_id}")
        raw_tile_specs[tile_id] = spec

    tiles: dict[str, TileRecord] = {}
    resolving_tile_ids: set[str] = set()

    def resolve_tile(tile_id: str) -> TileRecord:
        if tile_id in tiles:
            return tiles[tile_id]
        if tile_id in resolving_tile_ids:
            raise ValueError(f"Exact-duplicate cycle detected while resolving tile {tile_id!r}")
        if tile_id not in raw_tile_specs:
            raise ValueError(f"Unknown tile id {tile_id!r}")

        resolving_tile_ids.add(tile_id)
        try:
            spec = raw_tile_specs[tile_id]
            duplicate_of_raw = spec.get("exact_duplicate_of")
            inherited_tile: TileRecord | None = None
            resolved_duplicate_of: str | None = None
            if duplicate_of_raw is not None:
                resolved_duplicate_of = str(duplicate_of_raw)
                if resolved_duplicate_of == tile_id:
                    raise ValueError(f"Tile {tile_id} cannot exact_duplicate_of itself")
                if resolved_duplicate_of not in raw_tile_specs:
                    raise ValueError(
                        f"Tile {tile_id} references unknown exact_duplicate_of tile {resolved_duplicate_of!r}"
                    )
                inherited_tile = resolve_tile(resolved_duplicate_of)

            def inherited_scalar(field_name: str, default: object) -> object:
                if field_name in spec:
                    return spec.get(field_name)
                if inherited_tile is not None and field_name in EXACT_DUPLICATE_INHERITED_SCALAR_FIELDS:
                    return getattr(inherited_tile, field_name)
                return default

            def inherited_sequence(field_name: str) -> tuple[str, ...]:
                if field_name in spec:
                    raw_value = spec.get(field_name)
                    return _tuple(cast(Iterable[str], raw_value) if raw_value is not None else None)
                if inherited_tile is not None and field_name in EXACT_DUPLICATE_INHERITED_SEQUENCE_FIELDS:
                    return cast(tuple[str, ...], getattr(inherited_tile, field_name))
                return ()

            meaning_confidence_raw = (
                inherited_scalar("meaning_confidence", None)
                if inherited_tile is not None or "meaning_confidence" in spec
                else None
            )
            meaning_confidence = _normalise_meaning_confidence(meaning_confidence_raw, context=tile_id)
            walkable_raw = inherited_scalar("walkable", None)
            blocking_raw = inherited_scalar("blocking", None)
            cluster_ids_raw = spec.get("cluster_ids")
            noise_raw = inherited_scalar("noise", None)
            contrast_raw = inherited_scalar("contrast", None)
            temperature_raw = inherited_scalar("temperature", None)
            usage_raw = inherited_scalar("usage", None)
            style_raw = inherited_scalar("style", None)
            overlay_raw = inherited_scalar("overlay", None)
            footprint_raw = inherited_scalar("footprint", None)
            orientation_raw = inherited_scalar("orientation", None)
            facing_raw = inherited_scalar("facing", None)
            pose_raw = inherited_scalar("pose", None)
            compose_group_raw = inherited_scalar("compose_group", None)
            compose_role_raw = inherited_scalar("compose_role", None)
            state_group_raw = inherited_scalar("state_group", None)
            state_role_raw = inherited_scalar("state_role", None)
            animation_group_raw = inherited_scalar("animation_group", None)
            animation_frame_raw = inherited_scalar("animation_frame", None)
            animation_frame_count_raw = inherited_scalar("animation_frame_count", None)
            image_override_raw = inherited_scalar("image_override", None)
            meaning_raw = inherited_scalar("meaning", None)
            source_notes_raw = inherited_scalar("source_notes", None)
            cell_content_inset_raw = inherited_scalar("cell_content_inset", None)
            tile_cell_content_inset = (
                CellContentInset.from_mapping(cell_content_inset_raw, context=f"tile {tile_id} cell_content_inset")
                if cell_content_inset_raw is not None
                else None
            )
            if tile_cell_content_inset is not None:
                tile_cell_content_inset.validate_against(
                    tile_width=header.tile_width,
                    tile_height=header.tile_height,
                    context=f"tile {tile_id} cell_content_inset",
                )
            raw_sheet_col = spec.get("sheet_col")
            raw_sheet_row = spec.get("sheet_row")
            image_override = cast(str, image_override_raw) if image_override_raw is not None else None
            if image_override is None:
                if raw_sheet_col is None or raw_sheet_row is None:
                    raise ValueError(f"Tile {tile_id} must define sheet_col and sheet_row")
                sheet_col = int(cast(Union[int, str], raw_sheet_col))
                sheet_row = int(cast(Union[int, str], raw_sheet_row))
                if not bounds_contains(family_sheet_bounds, sheet_col, sheet_row):
                    raise ValueError(
                        f"Tile {tile_id} has sheet coordinate ({sheet_col}, {sheet_row}) outside family sheet bounds"
                    )
            else:
                if raw_sheet_col is not None or raw_sheet_row is not None:
                    raise ValueError(f"Synthetic tile {tile_id} must not define sheet_col or sheet_row")
                sheet_col = None
                sheet_row = None

            cluster_ids_value = _tuple(cast(Iterable[str], cluster_ids_raw) if cluster_ids_raw is not None else None)
            source_group_value = spec.get("source_group")
            source_notes_value = cast(str, source_notes_raw) if source_notes_raw is not None else None
            if image_override is None:
                genesis = TileGenesis(
                    kind="sheet",
                    sheet_col=sheet_col,
                    sheet_row=sheet_row,
                    source_group=source_group_value,
                    cluster_ids=cluster_ids_value,
                )
            else:
                # A synthetic tile that is a cell of a construction (compose_group set)
                # records that construction as a parent link — a derivable structural
                # fact, so its provenance is non-empty without authoring prose.
                parent_construction_ids = (
                    (cast(str, compose_group_raw),) if compose_group_raw is not None else ()
                )
                genesis = TileGenesis(
                    kind="synthetic",
                    source_group=source_group_value,
                    cluster_ids=cluster_ids_value,
                    derivation="image_override",
                    parent_construction_ids=parent_construction_ids,
                    authored_notes=source_notes_value,
                )

            tile = TileRecord(
                id=tile_id,
                family_id=header.family_id,
                genesis=genesis,
                exact_duplicate_of=resolved_duplicate_of,
                image_override=image_override,
                layer=str(spec["layer"]),
                category=str(spec["category"]),
                transparent=bool(spec["transparent"]),
                tags=inherited_sequence("tags"),
                aliases=aliases_by_tile.get(tile_id, ()),
                walkable=cast(bool, walkable_raw) if walkable_raw is not None else None,
                blocking=cast(bool, blocking_raw) if blocking_raw is not None else None,
                scenes=inherited_sequence("scenes"),
                semantics=inherited_sequence("semantics"),
                motifs=inherited_sequence("motifs"),
                noise=cast(str, noise_raw) if noise_raw is not None else None,
                contrast=cast(str, contrast_raw) if contrast_raw is not None else None,
                temperature=cast(str, temperature_raw) if temperature_raw is not None else None,
                usage=cast(str, usage_raw) if usage_raw is not None else None,
                style=cast(str, style_raw) if style_raw is not None else None,
                overlay=cast(str, overlay_raw) if overlay_raw is not None else None,
                footprint=cast(str, footprint_raw) if footprint_raw is not None else None,
                orientation=cast(str, orientation_raw) if orientation_raw is not None else None,
                facing=cast(str, facing_raw) if facing_raw is not None else None,
                pose=cast(str, pose_raw) if pose_raw is not None else None,
                compose_group=cast(str, compose_group_raw) if compose_group_raw is not None else None,
                compose_role=cast(str, compose_role_raw) if compose_role_raw is not None else None,
                state_group=cast(str, state_group_raw) if state_group_raw is not None else None,
                state_role=cast(str, state_role_raw) if state_role_raw is not None else None,
                animation_group=cast(str, animation_group_raw) if animation_group_raw is not None else None,
                animation_frame=int(cast(Union[int, str], animation_frame_raw)) if animation_frame_raw is not None else None,
                animation_frame_count=int(cast(Union[int, str], animation_frame_count_raw))
                if animation_frame_count_raw is not None
                else None,
                connects_on=inherited_sequence("connects_on"),
                cell_content_inset=tile_cell_content_inset,
                requires_exposed_on=inherited_sequence("requires_exposed_on"),
                affordances=inherited_sequence("affordances"),
                alt_uses=inherited_sequence("alt_uses"),
                meaning=cast(str, meaning_raw) if meaning_raw is not None else None,
                meaning_confidence=meaning_confidence,
                source_notes=source_notes_value,
            )
            tiles[tile_id] = tile
            return tile
        finally:
            resolving_tile_ids.remove(tile_id)

    for tile_id in raw_tile_specs:
        resolve_tile(tile_id)
    return tiles


def _validate_alias_targets(
    *,
    alias_map: Mapping[str, str],
    tiles: Mapping[str, TileRecord],
) -> None:
    for alias, tile_id in alias_map.items():
        if alias in tiles:
            raise ValueError(
                f"Alias {alias!r} collides with tile id of the same name in the loaded family"
            )
        if tile_id not in tiles:
            raise ValueError(f"Alias {alias!r} points at unknown tile id {tile_id!r}")


def _validate_clusters_against_tiles(
    *,
    clusters: Mapping[str, TileClusterRecord],
    tiles: Mapping[str, TileRecord],
) -> None:
    for cluster in clusters.values():
        for tile_id in cluster.members:
            if tile_id not in tiles:
                raise ValueError(f"Cluster {cluster.id} references unknown tile {tile_id!r}")
    for tile in tiles.values():
        for cluster_id in tile.genesis.cluster_ids:
            if cluster_id not in clusters:
                raise ValueError(f"Tile {tile.id} references unknown cluster {cluster_id!r}")


def _validate_source_layout_catalog_references(
    *,
    source_layout: SourceLayoutIngestion,
    tiles: Mapping[str, TileRecord],
    alias_map: Mapping[str, str],
) -> None:
    for source_cluster in source_layout.source_clusters.values():
        parent_region = source_layout.source_regions[source_cluster.source_region_id]
        if not source_layout_region_contains_bounds(parent_region, source_cluster.bounds):
            raise ValueError(
                f"Ingestion cluster {source_cluster.id} falls outside ingestion region {source_cluster.source_region_id}"
            )
    for collection in source_layout.source_collections.values():
        for member in collection.members:
            member_ref = collection_member_ref(member)
            if member.kind == "tile_id":
                if member_ref not in tiles:
                    raise ValueError(
                        f"Ingestion collection {collection.id} references unknown member tile {member_ref!r}"
                    )
                continue
            if member.kind == "alias":
                if member_ref not in alias_map:
                    raise ValueError(
                        f"Ingestion collection {collection.id} references unknown member alias {member_ref!r}"
                    )
                continue
            if not sheet_cell_ref_within_bounds(member_ref, source_layout.sheet_bounds):
                raise ValueError(
                    f"Ingestion collection {collection.id} references unknown member sheet cell {member_ref!r}"
                )


def load_constructions_from_data(
    constructions_data: tuple[ConstructionConfig, ...],
    *,
    constructions_path: Path | None,
    tiles: dict[str, TileRecord],
    runtime_flippable: bool,
) -> dict[str, Construction]:
    constructions: dict[str, Construction] = {}
    for raw_config in constructions_data:
        construction_id = str(raw_config["id"])
        constructions[construction_id] = build_construction(
            raw_config,
            tiles=tiles,
            runtime_flippable=runtime_flippable,
        )

    return constructions


def load_composite_tiles_from_data(
    composite_tiles_data: tuple[CompositeTileConfig, ...],
    *,
    family_id: str,
    tiles: dict[str, TileRecord],
) -> dict[str, CompositeTileRecord]:
    composite_tiles: dict[str, CompositeTileRecord] = {}
    for raw_config in composite_tiles_data:
        composite_id = str(raw_config["id"])
        composite_tiles[composite_id] = _build_composite_tile(raw_config, family_id=family_id, tiles=tiles)

    return composite_tiles


def _validate_source_layout_construction_references(
    *,
    source_layout: SourceLayoutIngestion | None,
    constructions: Mapping[str, Construction],
    composite_tiles: Mapping[str, CompositeTileRecord],
    constructions_path: Path | None,
    composite_tiles_path: Path | None,
) -> None:
    if source_layout is not None:
        for collection in source_layout.source_collections.values():
            for construction_id in collection.constructions:
                if construction_id not in constructions and construction_id not in composite_tiles:
                    if constructions_path is None and composite_tiles_path is None:
                        raise ValueError(
                            f"Ingestion collection {collection.id!r} references unknown construction "
                            f"{construction_id!r}, but no constructions or composite tiles manifest was loaded"
                        )
                    raise ValueError(
                        f"Ingestion collection {collection.id!r} references unknown construction "
                        f"{construction_id!r} in loaded constructions/composite tile manifests"
                    )


def _parse_attachment_param(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
) -> str:
    param_raw = raw["param"]
    if not isinstance(param_raw, str) or param_raw == "":
        raise ValueError(f"attachment set {attachment_id!r} param must be a non-empty string")
    return param_raw


def _parse_attachment_target_ids(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
) -> tuple[str, ...]:
    target_ids_raw = require_list(
        raw["target_construction_ids"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} target_construction_ids",
    )
    if not target_ids_raw:
        raise ValueError(f"attachment set {attachment_id!r} target_construction_ids must be a non-empty list")
    return tuple(str(value) for value in target_ids_raw)


def _parse_placeable_ref(raw: object, *, context: str) -> PlaceableRef:
    return PlaceableRef.from_mapping(raw, context=context)


def _parse_attachment_target_refs(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
) -> tuple[PlaceableRef, ...]:
    require_exactly_one(
        raw,
        "target_construction_ids",
        "target_placeables",
        context=f"attachment set {attachment_id!r}",
    )
    if "target_placeables" in raw:
        target_refs_raw = require_list(
            raw["target_placeables"],
            context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} target_placeables",
        )
        if not target_refs_raw:
            raise ValueError(f"attachment set {attachment_id!r} target_placeables must be a non-empty list")
        return tuple(
            _parse_placeable_ref(
                raw_ref,
                context=(
                    f"{attachments_path or '<attachments>'}: attachment set {attachment_id} "
                    f"target_placeables[{index}]"
                ),
            )
            for index, raw_ref in enumerate(target_refs_raw)
        )
    return tuple(PlaceableRef.construction(target_id) for target_id in _parse_attachment_target_ids(
        raw,
        attachment_id=attachment_id,
        attachments_path=attachments_path,
    ))


def _parse_attachment_canvas(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
) -> GridBounds:
    canvas_raw = require_mapping(
        raw["canvas"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} canvas",
    )
    check_required_keys(canvas_raw, ("x", "y", "width", "height"), context=f"attachment set {attachment_id!r} canvas")
    canvas = GridBounds(
        x=int(cast(Union[int, str], canvas_raw["x"])),
        y=int(cast(Union[int, str], canvas_raw["y"])),
        width=int(cast(Union[int, str], canvas_raw["width"])),
        height=int(cast(Union[int, str], canvas_raw["height"])),
    )
    if canvas.x < 0 or canvas.y < 0 or canvas.width <= 0 or canvas.height <= 0:
        raise ValueError(f"attachment set {attachment_id!r} canvas must have non-negative origin and positive size")
    return canvas


def _validate_attachment_targets(
    *,
    attachment_id: str,
    target_refs: tuple[PlaceableRef, ...],
    canvas: GridBounds,
    placeables: Mapping[PlaceableRef, Placeable],
) -> None:
    for target_ref in target_refs:
        target = placeables.get(target_ref)
        if target is None:
            raise ValueError(
                f"attachment set {attachment_id!r} references unknown target placeable "
                f"{target_ref.kind}:{target_ref.id!r}"
            )
        target_bounds = fixed_placeable_bounds(
            target,
            context=f"attachment set {attachment_id!r} target {target_ref.kind}:{target_ref.id!r}",
        )
        if not _bounds_inside(target_bounds, canvas):
            raise ValueError(
                f"attachment set {attachment_id!r} canvas {canvas} must stay inside target placeable "
                f"{target_ref.kind}:{target_ref.id!r} bounds {target_bounds}"
            )


def _parse_attachment_variants(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    attachments_path: Path | None,
    placeables: Mapping[PlaceableRef, Placeable],
    canvas: GridBounds,
) -> Mapping[str, ConstructionAttachmentVariant]:
    raw_variants = require_list(
        raw["variants"],
        context=f"{attachments_path or '<attachments>'}: attachment set {attachment_id} variants",
    )
    if not raw_variants:
        raise ValueError(f"attachment set {attachment_id!r} must define at least one variant")
    variants: dict[str, ConstructionAttachmentVariant] = {}
    for index, raw_variant in enumerate(raw_variants):
        variant_context = f"attachment set {attachment_id!r} variants[{index}]"
        mapping = require_mapping(raw_variant, context=variant_context)
        check_required_keys(mapping, ("id",), context=variant_context)
        require_exactly_one(mapping, "construction_id", "placeable", context=variant_context)
        variant_id = str(mapping["id"])
        if variant_id in variants:
            raise ValueError(f"attachment set {attachment_id!r} declares duplicate variant id {variant_id!r}")
        if "placeable" in mapping:
            variant_ref = _parse_placeable_ref(
                mapping["placeable"],
                context=f"attachment set {attachment_id!r} variants[{index}].placeable",
            )
            construction_id: str | None = None
        else:
            construction_id = str(mapping["construction_id"])
            variant_ref = PlaceableRef.construction(construction_id)
        variant_placeable = placeables.get(variant_ref)
        if variant_placeable is None:
            raise ValueError(
                f"attachment set {attachment_id!r} variant {variant_id!r} references unknown placeable "
                f"{variant_ref.kind}:{variant_ref.id!r}"
            )
        attachment_bounds = fixed_placeable_bounds(
            variant_placeable,
            context=f"attachment set {attachment_id!r} variant {variant_id!r}",
        )
        if attachment_bounds.width > canvas.width or attachment_bounds.height > canvas.height:
            raise ValueError(
                f"attachment set {attachment_id!r} variant {variant_id!r} placeable {variant_ref.kind}:{variant_ref.id!r} "
                f"size {attachment_bounds.width}x{attachment_bounds.height} exceeds canvas "
                f"{canvas.width}x{canvas.height}"
            )
        variants[variant_id] = ConstructionAttachmentVariant(
            id=variant_id,
            construction_id=construction_id,
            placeable_kind=variant_ref.kind,
            placeable_id=variant_ref.id,
            label=cast(str | None, mapping.get("label")),
            notes=cast(str | None, mapping.get("notes")),
        )
    return MappingProxyType(variants)


def _parse_attachment_default_variant_id(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
    variants: Mapping[str, ConstructionAttachmentVariant],
) -> str | None:
    default_variant_id_raw = raw.get("default_variant_id")
    if default_variant_id_raw is None:
        return None
    default_variant_id = str(default_variant_id_raw)
    if default_variant_id == "":
        raise ValueError(f"attachment set {attachment_id!r} default_variant_id must be a non-empty string")
    if default_variant_id not in variants:
        raise ValueError(
            f"attachment set {attachment_id!r} default_variant_id {default_variant_id!r} "
            "must match a declared variant id"
        )
    return default_variant_id


def _parse_attachment_required(
    raw: Mapping[str, object],
    *,
    attachment_id: str,
) -> bool:
    return _parse_optional_bool(raw, "required", context=f"attachment set {attachment_id!r}")


def load_attachment_sets_from_data(
    attachments_data: tuple[ConstructionAttachmentSetConfig, ...],
    *,
    attachments_path: Path | None,
    placeables: Mapping[PlaceableRef, Placeable],
) -> dict[str, ConstructionAttachmentSet]:
    attachment_sets: dict[str, ConstructionAttachmentSet] = {}
    for raw in attachments_data:
        attachment_id = str(raw["id"])
        param = _parse_attachment_param(raw, attachment_id=attachment_id)
        target_refs = _parse_attachment_target_refs(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
        )
        canvas = _parse_attachment_canvas(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
        )
        _validate_attachment_targets(
            attachment_id=attachment_id,
            target_refs=target_refs,
            canvas=canvas,
            placeables=placeables,
        )
        variants = _parse_attachment_variants(
            raw,
            attachment_id=attachment_id,
            attachments_path=attachments_path,
            placeables=placeables,
            canvas=canvas,
        )
        default_variant_id = _parse_attachment_default_variant_id(
            raw,
            attachment_id=attachment_id,
            variants=variants,
        )

        attachment_sets[attachment_id] = ConstructionAttachmentSet(
            id=attachment_id,
            param=param,
            canvas=canvas,
            variants=variants,
            target_placeable_refs=target_refs,
            required=_parse_attachment_required(raw, attachment_id=attachment_id),
            default_variant_id=default_variant_id,
            label=raw.get("label"),
            notes=raw.get("notes"),
        )
    return attachment_sets


class TileFamily:
    def __init__(
        self,
        *,
        header: TileFamilyHeader,
        promoted_metadata: TileLibraryPromotedMetadata = EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
        source_layout: SourceLayoutIngestion | None,
        variants: dict[str, TileFamilyVariant],
        clusters: dict[str, TileClusterRecord],
        tiles: dict[str, TileRecord],
        aliases: dict[str, str],
        tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord] | None = None,
        constructions: Mapping[str, Construction] | None = None,
        composite_tiles: Mapping[str, CompositeTileRecord] | None = None,
        attachment_sets: Mapping[str, ConstructionAttachmentSet] | None = None,
    ) -> None:
        self.header = header
        self.promoted_metadata = promoted_metadata
        self.source_layout = source_layout
        self.variants = MappingProxyType(dict(variants))
        self.clusters = MappingProxyType(dict(clusters))
        self.tiles = MappingProxyType(dict(tiles))
        self.aliases = MappingProxyType(dict(aliases))
        self.aliases_by_tile = _group_aliases_by_tile(aliases)
        self.tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord] = (
            MappingProxyType(dict(tiles_by_sheet_cell))
            if tiles_by_sheet_cell is not None
            else MappingProxyType({})
        )
        self.constructions: Mapping[str, Construction] = (
            MappingProxyType(dict(constructions)) if constructions is not None else MappingProxyType({})
        )
        self.composite_tiles: Mapping[str, CompositeTileRecord] = (
            MappingProxyType(dict(composite_tiles)) if composite_tiles is not None else MappingProxyType({})
        )
        self.attachment_sets: Mapping[str, ConstructionAttachmentSet] = (
            MappingProxyType(dict(attachment_sets)) if attachment_sets is not None else MappingProxyType({})
        )
        self.attachment_sets_by_target: Mapping[PlaceableRef, tuple[ConstructionAttachmentSet, ...]] = (
            attachment_sets_by_target(self.attachment_sets)
        )

    @property
    def root(self) -> Path:
        return self.header.root

    @property
    def family_id(self) -> str:
        return self.header.family_id

    @property
    def title(self) -> str | None:
        return self.header.title

    @property
    def tile_width(self) -> int:
        return self.header.tile_width

    @property
    def tile_height(self) -> int:
        return self.header.tile_height

    @property
    def render_step_width(self) -> int | None:
        return self.header.render_step_width

    @property
    def render_step_height(self) -> int | None:
        return self.header.render_step_height

    @property
    def siblings_share_semantics(self) -> bool:
        return bool(self.header.siblings_share_semantics)

    @property
    def notes(self) -> tuple[str, ...]:
        return self.header.notes or ()

    @property
    def default_variant_id(self) -> str:
        return self.header.default_variant_id

    @cached_property
    def runtime_unit(self) -> TileLibraryUnit:
        return TileLibraryUnit(
            family_id=self.family_id,
            tile_width=self.tile_width,
            tile_height=self.tile_height,
            render_step_width=self.render_step_width,
            render_step_height=self.render_step_height,
            default_variant_id=self.default_variant_id,
            runtime_flippable=self.header.runtime_flippable,
            promoted_metadata=self.promoted_metadata,
            root=self.root,
            variants=self.variants,
            tiles=self.tiles,
            aliases=self.aliases,
            tiles_by_sheet_cell_index=self.tiles_by_sheet_cell,
            constructions=self.constructions,
            composite_tiles=self.composite_tiles,
            clusters=self.clusters,
            attachment_sets=self.attachment_sets,
            attachment_sets_by_target=attachment_sets_by_target(self.attachment_sets),
        )

    def lookup_construction(self, construction_id: str) -> Construction | None:
        return self.constructions.get(construction_id)

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        return self.runtime_unit.entity_template(construction_id)

    def lookup_placeable(self, placeable_ref: PlaceableRef) -> Placeable | None:
        return self.runtime_unit.lookup_placeable(placeable_ref)

    def entity_template_for_placeable(self, placeable_ref: PlaceableRef) -> EntityTemplateRecord | None:
        return self.runtime_unit.entity_template_for_placeable(placeable_ref)

    def lower_placeable_to_tile_cells(self, placeable_ref: PlaceableRef) -> tuple[LoweredTileCell, ...] | None:
        return self.runtime_unit.lower_placeable_to_tile_cells(placeable_ref)

    def entity_templates(self) -> list[EntityTemplateRecord]:
        return self.runtime_unit.entity_templates()

    def attachment_sets_for_placeable(self, placeable_ref: PlaceableRef) -> tuple[ConstructionAttachmentSet, ...]:
        return self.runtime_unit.attachment_sets_for_placeable(placeable_ref)

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.runtime_unit.attachment_sets_for_construction(construction_id)

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        return self.runtime_unit.runtime_tileset_id_for_construction(construction_id, variant_id=variant_id)

    def runtime_tileset_id_for_placeable(
        self,
        placeable_ref: PlaceableRef,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        return self.runtime_unit.runtime_tileset_id_for_placeable(placeable_ref, variant_id=variant_id)

    @classmethod
    def from_catalog_sources(
        cls,
        *,
        header: TileFamilyHeader,
        variants: Mapping[str, TileFamilyVariant],
        catalog: FamilyCatalogSources,
        source_layout: SourceLayoutIngestion | None,
        promoted_metadata: TileLibraryPromotedMetadata = EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
    ) -> TileFamily:
        root = header.root
        if not variants:
            raise ValueError(f"Tile family {root} must define at least one variant")

        variant_sheet_image_cache: dict[Path, Image.Image] = {}
        variant_sheet_bounds = {
            variant_id: _sheet_bounds_for_variant(
                variant=variant,
                tile_width=header.tile_width,
                tile_height=header.tile_height,
                image_cache=variant_sheet_image_cache,
            )
            for variant_id, variant in variants.items()
        }
        # Runtime loads no ingest source layout, so they fall back to the full
        # sheet bounds; this equals declared source bounds only when the
        # ingestion sheet_bounds span the whole sheet.
        family_sheet_bounds = source_layout.sheet_bounds if source_layout is not None else next(iter(variant_sheet_bounds.values()))

        clusters = _load_clusters(root=root, clusters_data=catalog.clusters_data)
        _validate_variant_sheet_bounds(
            variant_sheet_bounds=variant_sheet_bounds,
            family_sheet_bounds=family_sheet_bounds,
        )

        alias_map: dict[str, str] = {str(alias): str(target) for alias, target in catalog.aliases_data.items()}
        aliases_by_tile = _group_aliases_by_tile(alias_map)
        tiles = _resolve_tiles_from_catalog(
            header=header,
            family_sheet_bounds=family_sheet_bounds,
            catalog=catalog,
            aliases_by_tile=aliases_by_tile,
        )
        if header.default_variant_id not in variants:
            raise ValueError(
                f"Unknown default_variant_id {header.default_variant_id!r} in family {header.family_id!r}"
            )
        _validate_alias_targets(alias_map=alias_map, tiles=tiles)

        _validate_tile_override_images(
            root=root,
            tiles=tiles,
            variants=variants,
            tile_width=header.tile_width,
            tile_height=header.tile_height,
        )
        _validate_clusters_against_tiles(clusters=clusters, tiles=tiles)

        # Derive seam profiles after override images are validated to exist, so a
        # missing override surfaces as the diagnostic ValueError above rather than
        # a bare FileNotFoundError here. Reuses the already-loaded sheet cache.
        tiles = _attach_seam_profiles(
            tiles=tiles,
            default_variant=variants[header.default_variant_id],
            root=root,
            tile_width=header.tile_width,
            tile_height=header.tile_height,
            image_cache=variant_sheet_image_cache,
            default_inset=header.cell_content_inset,
        )

        tiles_by_sheet_cell = index_tiles_by_sheet_cell(tiles, context=f"family {header.family_id!r}")
        _validate_exact_duplicate_pixels(
            root=root,
            tiles=tiles,
            variants=variants,
            tile_width=header.tile_width,
            tile_height=header.tile_height,
        )

        if source_layout is not None:
            _validate_source_layout_catalog_references(
                source_layout=source_layout,
                tiles=tiles,
                alias_map=alias_map,
            )

        constructions = load_constructions_from_data(
            catalog.constructions_data,
            constructions_path=catalog.paths.constructions_path,
            tiles=tiles,
            runtime_flippable=header.runtime_flippable,
        )
        composite_tiles = load_composite_tiles_from_data(
            catalog.composite_tiles_data,
            family_id=header.family_id,
            tiles=tiles,
        )
        _validate_source_layout_construction_references(
            source_layout=source_layout,
            constructions=constructions,
            composite_tiles=composite_tiles,
            constructions_path=catalog.paths.constructions_path,
            composite_tiles_path=catalog.paths.composite_tiles_path,
        )
        placeables: dict[PlaceableRef, Placeable] = {
            **{PlaceableRef(kind="tile", id=tile_id): tile for tile_id, tile in tiles.items()},
            **{PlaceableRef.construction(construction_id): construction for construction_id, construction in constructions.items()},
            **{
                PlaceableRef(kind="composite_tile", id=composite_id): composite
                for composite_id, composite in composite_tiles.items()
            },
        }
        attachment_sets = load_attachment_sets_from_data(
            catalog.attachments_data,
            attachments_path=catalog.paths.attachments_path,
            placeables=placeables,
        )

        return cls(
            header=header,
            promoted_metadata=promoted_metadata,
            source_layout=source_layout,
            variants=dict(variants),
            clusters=clusters,
            tiles=tiles,
            aliases=alias_map,
            tiles_by_sheet_cell=tiles_by_sheet_cell,
            constructions=constructions,
            composite_tiles=composite_tiles,
            attachment_sets=attachment_sets,
        )

    @classmethod
    def load(cls, family_dir: Path) -> TileFamily:
        root = family_dir.resolve()
        header, variants, _family_data = load_family_header_and_variants(root)
        return cls.from_catalog_sources(
            header=header,
            variants=variants,
            catalog=load_family_catalog_sources(CompatibilityFamilyPaths.for_legacy_root(root)),
            source_layout=None,
        )

    def variant(self, variant_id: str | None = None) -> TileFamilyVariant:
        resolved_variant_id = variant_id or self.default_variant_id
        return self.variants[resolved_variant_id]

    def runtime_tileset_id(self, variant_id: str | None = None) -> str:
        resolved_variant_id = variant_id or self.default_variant_id
        return f"{self.family_id}@{resolved_variant_id}"

    def physical_tile_id(self, *, sheet_col: int, sheet_row: int) -> str:
        return f"{self.family_id}:{sheet_col},{sheet_row}"

    def variant_ref_for_tile(self, tile: TileRecord, *, variant_id: str | None = None) -> str:
        """Return the concrete variant ref, defaulting to the family's default variant when omitted."""
        resolved = self.resolve_ref(tile.id, variant_id=variant_id)
        if resolved is None:
            raise ValueError(f"Unable to resolve tile {tile.id!r} in family {self.family_id!r}")
        return resolved.variant_ref

    def by_id(self, tile_id: str) -> TileRecord:
        return self.tiles[tile_id]

    def by_alias(self, alias: str) -> TileRecord:
        return self.tiles[self.aliases[alias]]

    def canonical_tile_id(self, tile_id: str) -> str:
        seen: set[str] = set()
        current = tile_id
        while True:
            if current in seen:
                raise ValueError(f"Exact-duplicate cycle detected while resolving canonical tile for {tile_id!r}")
            seen.add(current)
            tile = self.tiles[current]
            if tile.exact_duplicate_of is None:
                return current
            current = tile.exact_duplicate_of

    def canonical_tile(self, tile_or_id: TileRecord | str) -> TileRecord:
        tile_id = tile_or_id.id if isinstance(tile_or_id, TileRecord) else tile_or_id
        return self.tiles[self.canonical_tile_id(tile_id)]

    def aliases_for_tile(self, tile_id: str) -> tuple[str, ...]:
        return self.aliases_by_tile.get(tile_id, ())

    def tile_at_sheet_cell(self, *, sheet_col: int, sheet_row: int) -> TileRecord | None:
        return self.tiles_by_sheet_cell.get((sheet_col, sheet_row))

    def _source_region_id_for_tile(self, tile: TileRecord) -> str | None:
        if self.source_layout is None or tile.genesis.sheet_col is None or tile.genesis.sheet_row is None:
            return None
        source_region = self.source_layout.source_region_for_cell(tile.genesis.sheet_col, tile.genesis.sheet_row)
        return None if source_region is None else source_region.id

    def source_region_id_for_tile(self, tile: TileRecord) -> str | None:
        return self._source_region_id_for_tile(tile)

    @staticmethod
    def _sheet_sort_key(tile: TileRecord) -> tuple[int, int, int, str]:
        sheet_row = tile.genesis.sheet_row if tile.genesis.sheet_row is not None else 10**9
        sheet_col = tile.genesis.sheet_col if tile.genesis.sheet_col is not None else 10**9
        return (1 if tile.genesis.sheet_row is None or tile.genesis.sheet_col is None else 0, sheet_row, sheet_col, tile.id)

    def summary(self) -> dict[str, object]:
        by_source_region: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_usage: dict[str, int] = {}
        by_noise: dict[str, int] = {}
        by_contrast: dict[str, int] = {}
        by_temperature: dict[str, int] = {}
        by_scene: dict[str, int] = {}
        tagged = 0
        for tile in self.tiles.values():
            bucket = self._source_region_id_for_tile(tile) or ("synthetic" if tile.genesis.sheet_col is None else "unmapped")
            by_source_region[bucket] = by_source_region.get(bucket, 0) + 1
            by_category[tile.category] = by_category.get(tile.category, 0) + 1
            if tile.usage is not None:
                by_usage[tile.usage] = by_usage.get(tile.usage, 0) + 1
            if tile.noise is not None:
                by_noise[tile.noise] = by_noise.get(tile.noise, 0) + 1
            if tile.contrast is not None:
                by_contrast[tile.contrast] = by_contrast.get(tile.contrast, 0) + 1
            if tile.temperature is not None:
                by_temperature[tile.temperature] = by_temperature.get(tile.temperature, 0) + 1
            for scene in tile.scenes:
                by_scene[scene] = by_scene.get(scene, 0) + 1
            if len(tile.tags) > 3:
                tagged += 1
        return {
            "family_id": self.family_id,
            "tile_count": len(self.tiles),
            "alias_count": len(self.aliases),
            "variant_count": len(self.variants),
            "cluster_count": len(self.clusters),
            "source_layout_region_count": 0 if self.source_layout is None else len(self.source_layout.source_regions),
            "source_layout_cluster_count": 0 if self.source_layout is None else len(self.source_layout.source_clusters),
            "source_layout_collection_count": 0 if self.source_layout is None else len(self.source_layout.source_collections),
            "by_source_region": dict(sorted(by_source_region.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_usage": dict(sorted(by_usage.items())),
            "by_noise": dict(sorted(by_noise.items())),
            "by_contrast": dict(sorted(by_contrast.items())),
            "by_temperature": dict(sorted(by_temperature.items())),
            "by_scene": dict(sorted(by_scene.items())),
            "semantically_tagged": tagged,
        }

    def ingest_report(self) -> TileFamilyIngestReport:
        by_source_region: dict[str, TileFamilyIngestSourceRegionReport] = {
            region_id: {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            }
            for region_id in (() if self.source_layout is None else self.source_layout.source_regions.keys())
        }
        by_source_region.setdefault(
            "synthetic",
            {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            },
        )
        by_source_region.setdefault(
            "unmapped",
            {
                "total": 0,
                "missing_source_group": 0,
                "missing_cluster_ids": 0,
                "missing_meaning": 0,
                "missing_meaning_confidence": 0,
                "uncertain_meaning": 0,
                "by_meaning_confidence": {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)},
            },
        )
        by_cluster: dict[str, int] = {}
        by_meaning_confidence: dict[str, int] = {value: 0 for value in sorted(MEANING_CONFIDENCE_VALUES)}
        missing_source_group: list[str] = []
        missing_cluster_ids: list[str] = []
        missing_meaning: list[str] = []
        missing_meaning_confidence: list[str] = []
        uncertain_meaning: list[str] = []

        for tile in self.tiles.values():
            bucket = self._source_region_id_for_tile(tile) or ("synthetic" if tile.genesis.sheet_col is None else "unmapped")
            region_report = by_source_region[bucket]
            region_report["total"] += 1
            if tile.genesis.source_group is None or not tile.genesis.source_group.strip():
                missing_source_group.append(tile.id)
                region_report["missing_source_group"] += 1
            if not tile.genesis.cluster_ids:
                missing_cluster_ids.append(tile.id)
                region_report["missing_cluster_ids"] += 1
            else:
                for cluster_id in tile.genesis.cluster_ids:
                    by_cluster[cluster_id] = by_cluster.get(cluster_id, 0) + 1
            if tile.meaning is None or not tile.meaning.strip():
                missing_meaning.append(tile.id)
                region_report["missing_meaning"] += 1
            confidence = tile.meaning_confidence
            if confidence is None or not confidence.strip():
                missing_meaning_confidence.append(tile.id)
                region_report["missing_meaning_confidence"] += 1
            else:
                by_meaning_confidence[confidence] = by_meaning_confidence.get(confidence, 0) + 1
                region_report["by_meaning_confidence"][confidence] = (
                    region_report["by_meaning_confidence"].get(confidence, 0) + 1
                )
            is_uncertain = (
                confidence in {"tentative", "unknown"}
                if confidence is not None
                else _meaning_is_uncertain(tile.meaning)
            )
            if tile.meaning is not None and tile.meaning.strip() and is_uncertain:
                uncertain_meaning.append(tile.id)
                region_report["uncertain_meaning"] += 1

        return {
            "family_id": self.family_id,
            "tile_count": len(self.tiles),
            "cluster_count": len(self.clusters),
            "complete": not (
                missing_source_group
                or missing_cluster_ids
                or missing_meaning
                or missing_meaning_confidence
            ),
            "missing_source_group": sorted(missing_source_group),
            "missing_cluster_ids": sorted(missing_cluster_ids),
            "missing_meaning": sorted(missing_meaning),
            "missing_meaning_confidence": sorted(missing_meaning_confidence),
            "uncertain_meaning": sorted(uncertain_meaning),
            "by_meaning_confidence": dict(sorted(by_meaning_confidence.items())),
            "by_source_region": dict(sorted(by_source_region.items())),
            "by_cluster": dict(sorted(by_cluster.items())),
        }

    def query(
        self,
        **query_kwargs: object,
    ) -> list[TileRecord]:
        """Return tiles matching the provided filters.

        Passing `None` omits a filter; it does not mean "match records whose field is None".
        Sequence fields use `*_all` / `*_any`, while singular convenience aliases like
        `scene=` and `semantic_cluster_id=` map onto their underlying tuple fields.
        """
        equality_filters: dict[str, object] = {}
        contains_all: dict[str, set[str]] = {}
        contains_any: dict[str, set[str]] = {}

        for raw_key, raw_value in query_kwargs.items():
            if raw_value is None:
                continue
            if raw_key == "cluster_id":
                raise TypeError("Ambiguous tile query field 'cluster_id'; use 'semantic_cluster_id' for semantic cluster membership")
            if raw_key in TILE_QUERY_ALIASES:
                contains_any[TILE_QUERY_ALIASES[raw_key]] = _normalise_query_values(raw_value)
                continue
            if raw_key.endswith("_all"):
                field_name = raw_key[:-4]
                if field_name not in TILE_SEQUENCE_FIELDS:
                    raise _unknown_query_field_error(raw_key)
                values = _normalise_query_values(raw_value)
                if values:
                    contains_all[field_name] = values
                continue
            if raw_key.endswith("_any"):
                field_name = raw_key[:-4]
                if field_name not in TILE_SEQUENCE_FIELDS:
                    raise _unknown_query_field_error(raw_key)
                values = _normalise_query_values(raw_value)
                if values:
                    contains_any[field_name] = values
                continue
            if raw_key not in TILE_EQUALITY_FIELDS:
                raise _unknown_query_field_error(raw_key)
            equality_filters[raw_key] = raw_value

        results: list[TileRecord] = []
        for tile in self.tiles.values():
            if any(_tile_query_value(tile, field_name) != expected for field_name, expected in equality_filters.items()):
                continue
            failed = False
            for field_name, required in contains_all.items():
                values = set(cast("Iterable[object]", _tile_query_value(tile, field_name)))
                if not required.issubset(values):
                    failed = True
                    break
            if failed:
                continue
            for field_name, allowed in contains_any.items():
                values = set(cast("Iterable[object]", _tile_query_value(tile, field_name)))
                if values.isdisjoint(allowed):
                    failed = True
                    break
            if failed:
                continue
            results.append(tile)
        return sorted(results, key=self._sheet_sort_key)

    def aliases_for(self, **query_kwargs: object) -> list[str]:
        aliases: list[str] = []
        for tile in self.query(**query_kwargs):
            aliases.extend(tile.aliases)
        return aliases

    def resolve_ref(self, ref: str, *, variant_id: str | None = None) -> ResolvedFamilyTile | None:
        return self.runtime_unit.resolve_ref(ref, variant_id=variant_id)
