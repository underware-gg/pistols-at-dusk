#!/usr/bin/env python3
"""Runtime tile-library surface: the data and construction records the runtime
holds, plus the catalog containers (TileLibraryUnit / LoadedTileLibraryUnit /
TileLibraryRegistry) and the pure derivation helpers over them.

This module is the stable library layer. It must not import from
``tile_families`` (the ingest layer) — the dependency runs ingest -> library.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Protocol, Union, cast

from typing_extensions import TypeAlias

from _manifest_utils import GridBounds, bounds_inside, require_mapping, resolve_path
from tile_metadata import ModuleContextValue, RenderTraits


Side: TypeAlias = Literal["north", "south", "east", "west"]
FixedSeamOverrideSide: TypeAlias = Literal["east", "south"]
PlaceableKind: TypeAlias = Literal["tile", "composite_tile", "construction"]
EntityTemplateKind: TypeAlias = Literal["tile", "composite_tile", "fixed", "parametric_run", "parametric_frame"]
SIDES: tuple[Side, ...] = ("north", "south", "east", "west")
LegacySemanticFactValue: TypeAlias = Union[str, tuple[str, ...], None]


@dataclass(frozen=True)
class PlaceableRef:
    kind: PlaceableKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in ("tile", "composite_tile", "construction"):
            raise ValueError(f"PlaceableRef.kind is invalid: {self.kind!r}")
        if self.id == "":
            raise ValueError("PlaceableRef.id must not be empty")

    @classmethod
    def construction(cls, construction_id: str) -> PlaceableRef:
        return cls(kind="construction", id=construction_id)

    @classmethod
    def from_mapping(cls, raw: object, *, context: str) -> PlaceableRef:
        mapping = require_mapping(raw, context=context)
        kind = mapping.get("kind")
        if not isinstance(kind, str):
            raise ValueError(f"{context} kind must be a string")
        placeable_id = mapping.get("id")
        if not isinstance(placeable_id, str):
            raise ValueError(f"{context} id must be a string")
        return cls(kind=cast(PlaceableKind, kind), id=placeable_id)

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "id": self.id,
        }


PHYSICAL_TILE_RE = re.compile(r"^(?P<family>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$")
VARIANT_TILE_RE = re.compile(
    r"^(?P<family>[a-z0-9_.-]+)@(?P<variant>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$"
)


@dataclass(frozen=True)
class CellContentInset:
    """Per-side transparent margin ("gutter") a tileset draws inside each cell.

    Seam derivation reads the contact line this many pixels in from each edge —
    the content-box edge — so a consistent gutter is matched as painted-to-painted
    rather than read as a null edge (ADR 0008). All sides default to 0 (flush art).
    """

    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0

    def __post_init__(self) -> None:
        for name in ("top", "right", "bottom", "left"):
            if getattr(self, name) < 0:
                raise ValueError(f"cell_content_inset.{name} must be non-negative")

    @classmethod
    def from_mapping(cls, raw: object, *, context: str = "cell_content_inset") -> CellContentInset:
        """Build from a JSON-style mapping; ``None`` yields the flush default.

        Parses at a manifest trust boundary, so invalid values fail with context
        rather than silently flattening to a flush edge and deriving wrong seams.
        """
        if raw is None:
            return cls()
        mapping = require_mapping(raw, context=context)
        unknown = set(mapping) - {"top", "right", "bottom", "left"}
        if unknown:
            raise ValueError(f"{context} has unknown keys {sorted(unknown)}; expected top/right/bottom/left")

        def _side(name: str) -> int:
            value = mapping.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{context}.{name} must be a non-negative integer, got {value!r}")
            if value < 0:
                raise ValueError(f"{context}.{name} must be non-negative, got {value}")
            return value

        return cls(top=_side("top"), right=_side("right"), bottom=_side("bottom"), left=_side("left"))

    def validate_against(self, *, tile_width: int, tile_height: int, context: str) -> None:
        """Raise if any side's inset cannot fit the tile — a manifest-boundary diagnostic.

        ``seam_profiles.contact_mask`` keeps its own grid-centric bounds check as the
        module contract; this gives a manifest-path message before derivation runs.
        """
        if self.top >= tile_height or self.bottom >= tile_height:
            raise ValueError(
                f"{context}: top/bottom inset ({self.top}/{self.bottom}) must be less than tile height {tile_height}"
            )
        if self.left >= tile_width or self.right >= tile_width:
            raise ValueError(
                f"{context}: left/right inset ({self.left}/{self.right}) must be less than tile width {tile_width}"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "left": self.left,
        }


@dataclass(frozen=True)
class FixedConstructionSeamOverride:
    x: int
    y: int
    side: FixedSeamOverrideSide
    reason: str

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("FixedConstructionSeamOverride coordinates must be non-negative")
        if self.side not in ("east", "south"):
            raise ValueError(f"FixedConstructionSeamOverride.side must be 'east' or 'south', got {self.side!r}")
        if self.reason.strip() == "":
            raise ValueError("FixedConstructionSeamOverride.reason must not be empty")


@dataclass(frozen=True)
class FixedConstruction:
    id: str
    collection_id: str
    cells: tuple[tuple[TileRecord | None, ...], ...]
    seam_overrides: tuple[FixedConstructionSeamOverride, ...] = ()
    expose_as_entity: bool = True
    kind: Literal["fixed"] = "fixed"

    def __post_init__(self) -> None:
        seen: set[tuple[int, int, FixedSeamOverrideSide]] = set()
        for override in self.seam_overrides:
            key = (override.x, override.y, override.side)
            if key in seen:
                raise ValueError(f"FixedConstruction {self.id!r} has duplicate seam override {key!r}")
            seen.add(key)
        object.__setattr__(self, "seam_overrides", tuple(self.seam_overrides))


@dataclass(frozen=True)
class ParametricRunConstruction:
    id: str
    collection_id: str
    axis: Literal["x", "y"]
    length_param: str
    start_tile: TileRecord
    repeat_tile: TileRecord
    end_tile: TileRecord
    expose_as_entity: bool = True
    kind: Literal["parametric_run"] = "parametric_run"

    def __post_init__(self) -> None:
        if self.axis not in ("x", "y"):
            raise ValueError(f"ParametricRunConstruction.axis must be 'x' or 'y', got {self.axis!r}")


FRAME_FILL_MODES: tuple[str, ...] = ("repeat", "round", "space", "stretch")


@dataclass(frozen=True)
class FrameSlot:
    """A resizable frame slot (edge or fill): the tile plus how it fills its span.

    ``flip_x``/``flip_y`` let one edge derive from the opposite edge's art (e.g.
    ``edge_right`` = ``edge_left`` mirrored on x), so a symmetric kit declares it once.
    """

    tile: TileRecord
    fill_mode: str = "repeat"
    flip_x: bool = False
    flip_y: bool = False

    def __post_init__(self) -> None:
        if self.fill_mode not in FRAME_FILL_MODES:
            raise ValueError(f"FrameSlot.fill_mode must be one of {FRAME_FILL_MODES}, got {self.fill_mode!r}")


@dataclass(frozen=True)
class FrameCornerSlot:
    """A frame corner: a grid of tiles, optionally flipped.

    Thin frames use a 1x1 grid; fat ("thick") corners use an NxM grid. A flipped
    slot derives one corner from another (e.g. ``corner_tr`` = ``corner_tl``
    mirrored on x), so a symmetric kit declares its art once.
    """

    cells: tuple[tuple[TileRecord | None, ...], ...]
    flip_x: bool = False
    flip_y: bool = False

    @property
    def width(self) -> int:
        return len(self.cells[0]) if self.cells else 0

    @property
    def height(self) -> int:
        return len(self.cells)

    def tiles(self) -> tuple[TileRecord, ...]:
        return tuple(cell for row in self.cells for cell in row if cell is not None)


@dataclass(frozen=True)
class FrameCell:
    tile: TileRecord
    x: int
    y: int
    flip_x: bool = False
    flip_y: bool = False


@dataclass(frozen=True)
class ParametricFrameConstruction:
    """A resizable border/UI frame — the 2-D analogue of a parametric run.

    Corners are placed once; present edges tile between them per ``fill_mode``;
    an optional ``fill`` tiles the interior. Absent slots render transparent,
    so a corner-only kit is simply a frame with empty ``edges`` and no ``fill``.
    """

    id: str
    collection_id: str
    corners: Mapping[str, FrameCornerSlot]
    edges: Mapping[str, FrameSlot]
    fill: FrameSlot | None = None
    min_width: int = 2
    min_height: int = 2
    width_param: str = "width"
    height_param: str = "height"
    expose_as_entity: bool = True
    kind: Literal["parametric_frame"] = "parametric_frame"


def project_parametric_frame(
    construction: ParametricFrameConstruction,
    *,
    width: int,
    height: int,
) -> tuple[FrameCell, ...]:
    """Project a parametric frame to local tile cells for one concrete size.

    The harness renderer and construction validator share this geometry so
    placement and seam-check adjacency cannot drift.
    """
    cells: list[FrameCell] = []

    def _emit(tile: TileRecord, cx: int, cy: int, *, flip_x: bool = False, flip_y: bool = False) -> None:
        cells.append(FrameCell(tile=tile, x=cx, y=cy, flip_x=flip_x, flip_y=flip_y))

    def _place_corner(corner: FrameCornerSlot, anchor_x: int, anchor_y: int) -> None:
        h, w = corner.height, corner.width
        for r, row in enumerate(corner.cells):
            for c, tile in enumerate(row):
                if tile is None:
                    continue
                dx = (w - 1 - c) if corner.flip_x else c
                dy = (h - 1 - r) if corner.flip_y else r
                _emit(tile, anchor_x + dx, anchor_y + dy, flip_x=corner.flip_x, flip_y=corner.flip_y)

    tl = construction.corners.get("corner_tl")
    tr = construction.corners.get("corner_tr")
    bl = construction.corners.get("corner_bl")
    br = construction.corners.get("corner_br")

    def _w(corner: FrameCornerSlot | None) -> int:
        return corner.width if corner is not None else 0

    def _h(corner: FrameCornerSlot | None) -> int:
        return corner.height if corner is not None else 0

    if tl is not None:
        _place_corner(tl, 0, 0)
    if tr is not None:
        _place_corner(tr, width - tr.width, 0)
    if bl is not None:
        _place_corner(bl, 0, height - bl.height)
    if br is not None:
        _place_corner(br, width - br.width, height - br.height)

    top = construction.edges.get("edge_top")
    bottom = construction.edges.get("edge_bottom")
    left = construction.edges.get("edge_left")
    right = construction.edges.get("edge_right")
    if top is not None:
        for col in range(_w(tl), width - _w(tr)):
            _emit(top.tile, col, 0, flip_x=top.flip_x, flip_y=top.flip_y)
    if bottom is not None:
        for col in range(_w(bl), width - _w(br)):
            _emit(bottom.tile, col, height - 1, flip_x=bottom.flip_x, flip_y=bottom.flip_y)
    if left is not None:
        for row in range(_h(tl), height - _h(bl)):
            _emit(left.tile, 0, row, flip_x=left.flip_x, flip_y=left.flip_y)
    if right is not None:
        for row in range(_h(tr), height - _h(br)):
            _emit(right.tile, width - 1, row, flip_x=right.flip_x, flip_y=right.flip_y)

    if construction.fill is not None:
        for row in range(1, height - 1):
            for col in range(1, width - 1):
                _emit(construction.fill.tile, col, row)

    return tuple(cells)


Construction: TypeAlias = Union[
    FixedConstruction,
    ParametricRunConstruction,
    ParametricFrameConstruction,
]


@dataclass(frozen=True)
class ConstructionAttachmentVariant:
    id: str
    construction_id: str | None = None
    placeable_kind: PlaceableKind = "construction"
    placeable_id: str | None = None
    label: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        resolved_placeable_id = self.placeable_id
        if resolved_placeable_id is None and self.placeable_kind == "construction":
            resolved_placeable_id = self.construction_id
        if resolved_placeable_id is None:
            raise ValueError("ConstructionAttachmentVariant.placeable_id is required for non-construction placeables")
        if resolved_placeable_id == "":
            raise ValueError("ConstructionAttachmentVariant.placeable_id must not be empty")
        object.__setattr__(self, "placeable_id", resolved_placeable_id)
        if self.construction_id is not None and (
            self.placeable_kind != "construction" or self.construction_id != resolved_placeable_id
        ):
            raise ValueError(
                "ConstructionAttachmentVariant.construction_id is only valid for matching construction placeables"
            )
        if self.construction_id is None and self.placeable_kind == "construction":
            object.__setattr__(self, "construction_id", resolved_placeable_id)

    @property
    def placeable_ref(self) -> PlaceableRef:
        placeable_id = self.placeable_id
        if placeable_id is None:
            raise RuntimeError("ConstructionAttachmentVariant.placeable_id was not normalised")
        return PlaceableRef(kind=self.placeable_kind, id=placeable_id)


@dataclass(frozen=True)
class ConstructionAttachmentSet:
    id: str
    param: str
    canvas: GridBounds
    variants: Mapping[str, ConstructionAttachmentVariant] = field(repr=False)
    target_construction_ids: tuple[str, ...] = ()
    target_placeable_refs: tuple[PlaceableRef, ...] = ()
    required: bool = False
    default_variant_id: str | None = None
    label: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        target_placeable_refs = self.target_placeable_refs
        if not target_placeable_refs and self.target_construction_ids:
            target_placeable_refs = tuple(PlaceableRef.construction(target_id) for target_id in self.target_construction_ids)
        if self.default_variant_id is not None and self.default_variant_id not in self.variants:
            raise ValueError(
                f"ConstructionAttachmentSet.default_variant_id {self.default_variant_id!r} "
                f"is not declared in variants"
            )
        if not target_placeable_refs:
            raise ValueError("ConstructionAttachmentSet.target_placeable_refs must not be empty")
        object.__setattr__(self, "target_placeable_refs", tuple(target_placeable_refs))
        construction_ids = tuple(ref.id for ref in target_placeable_refs if ref.kind == "construction")
        if self.target_construction_ids:
            if any(ref.kind != "construction" for ref in target_placeable_refs) or tuple(self.target_construction_ids) != construction_ids:
                raise ValueError(
                    "ConstructionAttachmentSet.target_construction_ids is only valid for matching construction placeables"
                )
        else:
            object.__setattr__(self, "target_construction_ids", construction_ids)
        object.__setattr__(self, "variants", MappingProxyType(dict(self.variants)))

    def variant(self, variant_id: str) -> ConstructionAttachmentVariant | None:
        return self.variants.get(variant_id)

    def to_entity_record(self) -> EntityAttachmentSetRecord:
        return EntityAttachmentSetRecord(
            id=self.id,
            param=self.param,
            canvas=self.canvas,
            variant_ids=tuple(self.variants.keys()),
            required=self.required,
            default_variant_id=self.default_variant_id,
            label=self.label,
            notes=self.notes,
        )


@dataclass(frozen=True)
class EntityAttachmentSetRecord:
    id: str
    param: str
    canvas: GridBounds
    variant_ids: tuple[str, ...]
    required: bool = False
    default_variant_id: str | None = None
    label: str | None = None
    notes: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "param": self.param,
            "required": self.required,
            "default_variant_id": self.default_variant_id,
            "label": self.label,
            "notes": self.notes,
            "canvas": self.canvas.to_payload(),
            "variant_ids": list(self.variant_ids),
        }


@dataclass(frozen=True)
class EntityFootprintSpec:
    mode: Literal["fixed", "parametric_run", "parametric_frame"]
    width: int
    height: int
    axis: Literal["x", "y"] | None = None
    length_param: str | None = None
    minimum_length: int | None = None
    width_param: str | None = None
    height_param: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "width": self.width,
            "height": self.height,
            "axis": self.axis,
            "length_param": self.length_param,
            "minimum_length": self.minimum_length,
            "width_param": self.width_param,
            "height_param": self.height_param,
        }


@dataclass(frozen=True)
class EntityTemplateRecord:
    id: str
    collection_id: str
    kind: EntityTemplateKind
    placement_anchor: Literal["top_left"]
    compose_roles: tuple[str, ...]
    affordances: tuple[str, ...]
    state_groups: tuple[str, ...]
    animation_groups: tuple[str, ...]
    footprint: EntityFootprintSpec
    placeable_kind: PlaceableKind = "construction"
    placeable_id: str | None = None
    construction_id: str | None = None
    attachment_sets: tuple[EntityAttachmentSetRecord, ...] = ()

    def __post_init__(self) -> None:
        resolved_placeable_id = self.placeable_id
        if resolved_placeable_id is None and self.placeable_kind == "construction":
            resolved_placeable_id = self.construction_id
        if resolved_placeable_id is None:
            raise ValueError("EntityTemplateRecord.placeable_id is required for non-construction placeables")
        if resolved_placeable_id == "":
            raise ValueError("EntityTemplateRecord.placeable_id must not be empty")
        object.__setattr__(self, "placeable_id", resolved_placeable_id)
        if self.construction_id is not None and (
            self.placeable_kind != "construction" or self.construction_id != resolved_placeable_id
        ):
            raise ValueError(
                "EntityTemplateRecord.construction_id is only valid for matching construction placeables"
            )

    @property
    def placeable_ref(self) -> PlaceableRef:
        placeable_id = self.placeable_id
        if placeable_id is None:
            raise RuntimeError("EntityTemplateRecord.placeable_id was not normalised")
        return PlaceableRef(kind=self.placeable_kind, id=placeable_id)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "placeable_kind": self.placeable_kind,
            "placeable_id": self.placeable_id,
            "collection_id": self.collection_id,
            "kind": self.kind,
            "placement_anchor": self.placement_anchor,
            "compose_roles": list(self.compose_roles),
            "affordances": list(self.affordances),
            "state_groups": list(self.state_groups),
            "animation_groups": list(self.animation_groups),
            "footprint": self.footprint.to_payload(),
            "attachment_sets": [attachment_set.to_payload() for attachment_set in self.attachment_sets],
        }
        if self.construction_id is not None:
            payload["construction_id"] = self.construction_id
        return payload


@dataclass(frozen=True)
class TileFamilyVariant:
    id: str
    sheet_path: Path | None
    transparent_mode: str
    palette_family: str | None = None
    colorway: str | None = None
    background_mode: str | None = None
    notes: str | None = None
    grid_columns: int | None = None
    grid_rows: int | None = None
    atlas_path: Path | None = None
    atlas_columns: int | None = None
    atlas_rows: int | None = None

    def __post_init__(self) -> None:
        if (self.grid_columns is None) != (self.grid_rows is None):
            raise ValueError("TileFamilyVariant grid_columns and grid_rows must be provided together")
        if self.grid_columns is not None and self.grid_columns <= 0:
            raise ValueError("TileFamilyVariant.grid_columns must be positive")
        if self.grid_rows is not None and self.grid_rows <= 0:
            raise ValueError("TileFamilyVariant.grid_rows must be positive")
        atlas_values = (self.atlas_path, self.atlas_columns, self.atlas_rows)
        if any(value is not None for value in atlas_values) and not all(value is not None for value in atlas_values):
            raise ValueError("TileFamilyVariant atlas_path, atlas_columns, and atlas_rows must be provided together")
        if self.atlas_path is not None and (self.atlas_path.is_absolute() or ".." in self.atlas_path.parts):
            raise ValueError("TileFamilyVariant.atlas_path must be relative within the runtime family")
        if self.atlas_columns is not None and self.atlas_columns <= 0:
            raise ValueError("TileFamilyVariant.atlas_columns must be positive")
        if self.atlas_rows is not None and self.atlas_rows <= 0:
            raise ValueError("TileFamilyVariant.atlas_rows must be positive")


def require_variant_sheet_path(variant: TileFamilyVariant, *, context: str) -> Path:
    if variant.sheet_path is None:
        raise ValueError(
            f"{context} requires source sheet pixels for variant {variant.id!r}, "
            "but runtime-asset variants do not carry sheet_path"
        )
    return variant.sheet_path


@dataclass(frozen=True)
class TileFamilyHeader:
    root: Path
    family_id: str
    title: str | None
    tile_width: int
    tile_height: int
    render_step_width: int | None
    render_step_height: int | None
    siblings_share_semantics: bool | None
    notes: tuple[str, ...] | None
    default_variant_id: str
    runtime_flippable: bool
    cell_content_inset: CellContentInset = field(default_factory=CellContentInset)

    def __post_init__(self) -> None:
        # Holds both the inset and the tile dimensions, so every header-construction
        # path (legacy load and the staged bridge) validates the family inset here.
        self.cell_content_inset.validate_against(
            tile_width=self.tile_width,
            tile_height=self.tile_height,
            context=f"family {self.family_id} cell_content_inset",
        )


def _empty_tile_library_module_context() -> dict[str, ModuleContextValue]:
    return {}


@dataclass(frozen=True)
class TileLibraryPromotedMetadata:
    source_pack_id: str | None = None
    source_tileset_id: str | None = None
    source_tilesheet_id: str | None = None
    module_context: Mapping[str, ModuleContextValue] = field(
        default_factory=_empty_tile_library_module_context,
        repr=False,
    )
    render_traits: RenderTraits = field(default_factory=RenderTraits)
    documented_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_context", MappingProxyType(dict(self.module_context)))
        object.__setattr__(self, "documented_hints", tuple(self.documented_hints))


EMPTY_TILE_LIBRARY_PROMOTED_METADATA = TileLibraryPromotedMetadata()


def _empty_composite_tiles() -> Mapping[str, CompositeTileRecord]:
    return {}


def _empty_tile_clusters() -> Mapping[str, TileClusterRecord]:
    return {}


def _empty_variant_assets() -> Mapping[str, str]:
    return {}


def _empty_variant_atlas_cells() -> Mapping[str, SheetCell]:
    return {}


@dataclass(frozen=True)
class SheetCell:
    col: int
    row: int

    @property
    def ref(self) -> str:
        return format_sheet_cell_ref(self.col, self.row)


@dataclass(frozen=True)
class TileClusterRecord:
    id: str
    scope: str
    members: tuple[str, ...] = ()
    kind_guess: str | None = None
    evidence: tuple[str, ...] = ()
    source_label: str | None = None
    source_notes: str | None = None


@dataclass(frozen=True)
class TileGenesis:
    """Canonical runtime-owned provenance for one tile (ADR 0005).

    Replaces the loose combination of `sheet_col` / `sheet_row` / `source_group`
    / `cluster_ids` that used to be scattered across the tile record. `kind`
    is ``"sheet"`` for sheet-backed tiles and ``"synthetic"`` for derived /
    authored tiles, which must explain their derivation rather than merely
    lacking a sheet cell.
    """

    kind: str
    sheet_col: int | None = None
    sheet_row: int | None = None
    source_group: str | None = None
    cluster_ids: tuple[str, ...] = ()
    derivation: str | None = None
    parent_construction_ids: tuple[str, ...] = ()
    parent_tile_ids: tuple[str, ...] = ()
    authored_notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cluster_ids", tuple(self.cluster_ids))
        object.__setattr__(self, "parent_construction_ids", tuple(self.parent_construction_ids))
        object.__setattr__(self, "parent_tile_ids", tuple(self.parent_tile_ids))


@dataclass(frozen=True)
class TileRecord:
    id: str
    family_id: str
    layer: str
    category: str
    transparent: bool
    genesis: TileGenesis
    tags: tuple[str, ...] = ()
    exact_duplicate_of: str | None = None
    image_override: str | None = None
    variant_assets: Mapping[str, str] = field(default_factory=_empty_variant_assets, repr=False)
    variant_atlas_cells: Mapping[str, SheetCell] = field(default_factory=_empty_variant_atlas_cells, repr=False)
    aliases: tuple[str, ...] = ()
    walkable: bool | None = None
    blocking: bool | None = None
    scenes: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    noise: str | None = None
    contrast: str | None = None
    temperature: str | None = None
    usage: str | None = None
    style: str | None = None
    overlay: str | None = None
    footprint: str | None = None
    orientation: str | None = None
    facing: str | None = None
    pose: str | None = None
    compose_group: str | None = None
    compose_role: str | None = None
    state_group: str | None = None
    state_role: str | None = None
    animation_group: str | None = None
    animation_frame: int | None = None
    animation_frame_count: int | None = None
    connects_on: tuple[str, ...] = ()
    seam_profiles: dict[str, tuple[bool, ...]] | None = None
    cell_content_inset: CellContentInset | None = None
    requires_exposed_on: tuple[str, ...] = ()
    affordances: tuple[str, ...] = ()
    alt_uses: tuple[str, ...] = ()
    meaning: str | None = None
    meaning_confidence: str | None = None
    source_notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_assets", MappingProxyType(dict(self.variant_assets)))
        object.__setattr__(self, "variant_atlas_cells", MappingProxyType(dict(self.variant_atlas_cells)))


RUNTIME_AUTHORED_TILE_FIELDS = frozenset(
    {
        "affordances",
        "alt_uses",
        "blocking",
        "requires_exposed_on",
        "walkable",
    }
)


@dataclass(frozen=True)
class LegacyTileSemanticRecord:
    """Marked, opt-in legacy metadata preserved from the physical tiles.json layer.

    This record intentionally does not feed the clean content-keyed semantic or
    runtime-authored fields. Consumers must ask for the legacy layer explicitly.
    """

    tile_id: str
    origin: str
    schema_version: int
    facts: Mapping[str, LegacySemanticFactValue] = field(repr=False)

    @property
    def id(self) -> str:
        return self.tile_id

    def __post_init__(self) -> None:
        if self.tile_id == "":
            raise ValueError("LegacyTileSemanticRecord.tile_id must not be empty")
        if self.origin == "":
            raise ValueError("LegacyTileSemanticRecord.origin must not be empty")
        if self.schema_version <= 0:
            raise ValueError("LegacyTileSemanticRecord.schema_version must be positive")
        facts: dict[str, LegacySemanticFactValue] = {}
        for field_name, value in cast(Mapping[object, object], self.facts).items():
            if not isinstance(field_name, str) or field_name == "":
                raise ValueError("LegacyTileSemanticRecord facts keys must be non-empty strings")
            if value is None or isinstance(value, str):
                facts[field_name] = value
                continue
            if not isinstance(value, tuple):
                raise ValueError(f"LegacyTileSemanticRecord fact {field_name!r} must be null, a string, or strings")
            values: list[str] = []
            for index, item in enumerate(cast(tuple[object, ...], value)):
                if not isinstance(item, str):
                    raise ValueError(f"LegacyTileSemanticRecord fact {field_name!r}[{index}] must be a string")
                values.append(item)
            facts[field_name] = tuple(values)
        object.__setattr__(self, "facts", MappingProxyType(facts))


def _empty_legacy_semantics() -> Mapping[str, LegacyTileSemanticRecord]:
    return {}


@dataclass(frozen=True)
class CompositeTileCell:
    tile: TileRecord
    x: int
    y: int
    role: str | None = None

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("CompositeTileCell coordinates must be non-negative")


@dataclass(frozen=True)
class CompositeTileRecord:
    id: str
    family_id: str
    collection_id: str
    cells: tuple[tuple[CompositeTileCell | None, ...], ...]
    tags: tuple[str, ...] = ()
    expose_as_entity: bool = True
    placement_anchor: Literal["top_left"] = "top_left"
    kind: Literal["composite_tile"] = "composite_tile"

    def __post_init__(self) -> None:
        if self.id == "":
            raise ValueError("CompositeTileRecord.id must not be empty")
        if self.family_id == "":
            raise ValueError("CompositeTileRecord.family_id must not be empty")
        if self.collection_id == "":
            raise ValueError("CompositeTileRecord.collection_id must not be empty")
        if not self.cells:
            raise ValueError("CompositeTileRecord.cells must be a non-empty rectangular grid")
        width = len(self.cells[0])
        if width == 0:
            raise ValueError("CompositeTileRecord.cells must be a non-empty rectangular grid")
        found_cell = False
        for y, row in enumerate(self.cells):
            if len(row) != width:
                raise ValueError("CompositeTileRecord.cells must be a rectangular grid")
            for x, cell in enumerate(row):
                if cell is None:
                    continue
                found_cell = True
                if cell.x != x or cell.y != y:
                    raise ValueError("CompositeTileRecord cell coordinate must match grid position")
                if cell.tile.family_id != self.family_id:
                    raise ValueError("CompositeTileRecord cells must belong to the same family")
        if not found_cell:
            raise ValueError("CompositeTileRecord.cells must contain at least one tile")
        object.__setattr__(self, "tags", tuple(self.tags))

    @property
    def width(self) -> int:
        return len(self.cells[0])

    @property
    def height(self) -> int:
        return len(self.cells)

    def lowered_cells(self) -> tuple[CompositeTileCell, ...]:
        return tuple(cell for row in self.cells for cell in row if cell is not None)

    def cell_at(self, x: int, y: int) -> CompositeTileCell | None:
        if x < 0 or y < 0 or y >= self.height or x >= self.width:
            return None
        return self.cells[y][x]


TileAsset: TypeAlias = Union[TileRecord, CompositeTileRecord]
Placeable: TypeAlias = Union[TileRecord, CompositeTileRecord, Construction]


@dataclass(frozen=True)
class ResolvedFamilyTile:
    family_id: str
    variant_id: str
    tile_id: str
    sheet_col: int | None
    sheet_row: int | None
    image_override_path: Path | None = None

    @property
    def variant_ref(self) -> str:
        if self.image_override_path is not None or self.sheet_col is None or self.sheet_row is None:
            return self.tile_id
        return f"{self.family_id}@{self.variant_id}:{self.sheet_col},{self.sheet_row}"

    @property
    def physical_ref(self) -> str:
        if self.image_override_path is not None or self.sheet_col is None or self.sheet_row is None:
            return self.tile_id
        return f"{self.family_id}:{self.sheet_col},{self.sheet_row}"


@dataclass(frozen=True)
class LoweredTileCell:
    tile: TileRecord
    x: int
    y: int
    role: str | None = None


@dataclass(frozen=True)
class SeamSegment:
    side: Side
    offset: int
    mask: tuple[bool, ...]
    local_x: int
    local_y: int
    tile_id: str | None = None

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"SeamSegment.side is invalid: {self.side!r}")
        if self.offset < 0:
            raise ValueError("SeamSegment.offset must be non-negative")
        if self.local_x < 0 or self.local_y < 0:
            raise ValueError("SeamSegment local coordinates must be non-negative")
        if not self.mask:
            raise ValueError("SeamSegment.mask must not be empty")
        object.__setattr__(self, "mask", tuple(self.mask))


@dataclass(frozen=True)
class ConnectionSurface:
    segments_by_side: Mapping[Side, tuple[SeamSegment, ...]]

    def __post_init__(self) -> None:
        segments_by_side: dict[Side, tuple[SeamSegment, ...]] = {}
        for side in SIDES:
            segments = tuple(self.segments_by_side.get(side, ()))
            last_key: tuple[int, int, int] | None = None
            for index, segment in enumerate(segments):
                if segment.side != side:
                    raise ValueError(f"ConnectionSurface segment for side {side!r} has side {segment.side!r}")
                key = (segment.offset, segment.local_y, segment.local_x)
                if index > 0 and last_key is not None and key < last_key:
                    raise ValueError(f"ConnectionSurface segments for side {side!r} must be sorted")
                if key == last_key:
                    raise ValueError(f"ConnectionSurface segments for side {side!r} must not duplicate a local edge")
                last_key = key
            segments_by_side[side] = segments
        object.__setattr__(self, "segments_by_side", MappingProxyType(segments_by_side))

    def segments(self, side: Side) -> tuple[SeamSegment, ...]:
        return self.segments_by_side[side]


class RuntimeConstructionCatalog(Protocol):
    def lookup_construction(self, construction_id: str) -> Construction | None:
        ...

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        ...

    def lookup_placeable(self, placeable_ref: PlaceableRef) -> Placeable | None:
        ...

    def entity_template_for_placeable(self, placeable_ref: PlaceableRef) -> EntityTemplateRecord | None:
        ...

    def lower_placeable_to_tile_cells(self, placeable_ref: PlaceableRef) -> tuple[LoweredTileCell, ...] | None:
        ...

    def attachment_sets_for_placeable(self, placeable_ref: PlaceableRef) -> tuple[ConstructionAttachmentSet, ...]:
        ...

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        ...

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        ...

    def runtime_tileset_id_for_placeable(
        self,
        placeable_ref: PlaceableRef,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        ...


def attachment_sets_by_target(
    attachment_sets: Mapping[str, ConstructionAttachmentSet],
) -> Mapping[PlaceableRef, tuple[ConstructionAttachmentSet, ...]]:
    indexed: dict[PlaceableRef, list[ConstructionAttachmentSet]] = defaultdict(list)
    for attachment_set in attachment_sets.values():
        for target_ref in attachment_set.target_placeable_refs:
            indexed[target_ref].append(attachment_set)
    return MappingProxyType({target_ref: tuple(values) for target_ref, values in indexed.items()})


def entity_template_for_construction(
    constructions: Mapping[str, Construction],
    construction_id: str,
    *,
    attachment_sets: Iterable[ConstructionAttachmentSet] = (),
) -> EntityTemplateRecord | None:
    construction = constructions.get(construction_id)
    if construction is None or not construction.expose_as_entity:
        return None
    return entity_template_from_construction(construction, attachment_sets=attachment_sets)


def _sorted_unique(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def lower_tile_asset_to_cells(placeable: TileRecord | CompositeTileRecord) -> tuple[LoweredTileCell, ...]:
    if isinstance(placeable, TileRecord):
        return (LoweredTileCell(tile=placeable, x=0, y=0, role=placeable.compose_role),)
    return tuple(
        LoweredTileCell(
            tile=cell.tile,
            x=cell.x,
            y=cell.y,
            role=cell.role if cell.role is not None else cell.tile.compose_role,
        )
        for cell in placeable.lowered_cells()
    )


def fixed_placeable_bounds(placeable: Placeable, *, context: str) -> GridBounds:
    if isinstance(placeable, TileRecord):
        return GridBounds(x=0, y=0, width=1, height=1)
    if isinstance(placeable, CompositeTileRecord):
        return GridBounds(x=0, y=0, width=placeable.width, height=placeable.height)
    if isinstance(placeable, ParametricRunConstruction):
        raise ValueError(f"{context} must reference a fixed placeable, not parametric_run {placeable.id!r}")
    if isinstance(placeable, ParametricFrameConstruction):
        raise ValueError(f"{context} must reference a fixed placeable, not parametric_frame {placeable.id!r}")
    width = len(placeable.cells[0]) if placeable.cells else 0
    height = len(placeable.cells)
    return GridBounds(x=0, y=0, width=width, height=height)


def _fixed_footprint_for_tile_asset(placeable: TileRecord | CompositeTileRecord) -> EntityFootprintSpec:
    bounds = fixed_placeable_bounds(placeable, context=f"placeable {placeable.id!r}")
    width, height = bounds.width, bounds.height
    return EntityFootprintSpec(mode="fixed", width=width, height=height)


def entity_template_from_placeable(
    placeable: TileRecord | CompositeTileRecord,
    *,
    attachment_sets: Iterable[ConstructionAttachmentSet] = (),
) -> EntityTemplateRecord | None:
    if isinstance(placeable, CompositeTileRecord) and not placeable.expose_as_entity:
        return None
    lowered_cells = lower_tile_asset_to_cells(placeable)
    tiles = tuple(cell.tile for cell in lowered_cells)
    if isinstance(placeable, TileRecord):
        placeable_kind: PlaceableKind = "tile"
        collection_id = placeable.category
        template_kind: EntityTemplateKind = "tile"
    else:
        placeable_kind = "composite_tile"
        collection_id = placeable.collection_id
        template_kind = "composite_tile"
    return EntityTemplateRecord(
        id=placeable.id,
        collection_id=collection_id,
        kind=template_kind,
        placement_anchor="top_left",
        compose_roles=_sorted_unique(cell.role for cell in lowered_cells),
        affordances=_sorted_unique(affordance for tile in tiles for affordance in tile.affordances),
        state_groups=_sorted_unique(tile.state_group for tile in tiles),
        animation_groups=_sorted_unique(tile.animation_group for tile in tiles),
        footprint=_fixed_footprint_for_tile_asset(placeable),
        placeable_kind=placeable_kind,
        placeable_id=placeable.id,
        attachment_sets=tuple(attachment_set.to_entity_record() for attachment_set in attachment_sets),
    )


def _tile_seam_segment(tile: TileRecord, side: Side, *, offset: int, local_x: int, local_y: int) -> SeamSegment:
    if tile.seam_profiles is None or side not in tile.seam_profiles:
        raise ValueError(f"tile {tile.id!r} seam profile missing side {side!r}")
    return SeamSegment(
        side=side,
        offset=offset,
        mask=tile.seam_profiles[side],
        local_x=local_x,
        local_y=local_y,
        tile_id=tile.id,
    )


def _connection_surface_for_tile(tile: TileRecord) -> ConnectionSurface:
    return ConnectionSurface(
        {
            "north": (_tile_seam_segment(tile, "north", offset=0, local_x=0, local_y=0),),
            "south": (_tile_seam_segment(tile, "south", offset=0, local_x=0, local_y=0),),
            "east": (_tile_seam_segment(tile, "east", offset=0, local_x=0, local_y=0),),
            "west": (_tile_seam_segment(tile, "west", offset=0, local_x=0, local_y=0),),
        }
    )


def _connection_surface_for_composite_tile(composite: CompositeTileRecord) -> ConnectionSurface:
    segments: dict[Side, list[SeamSegment]] = {side: [] for side in SIDES}
    for cell in composite.lowered_cells():
        x, y = cell.x, cell.y
        if composite.cell_at(x, y - 1) is None:
            segments["north"].append(_tile_seam_segment(cell.tile, "north", offset=x, local_x=x, local_y=y))
        if composite.cell_at(x, y + 1) is None:
            segments["south"].append(_tile_seam_segment(cell.tile, "south", offset=x, local_x=x, local_y=y))
        if composite.cell_at(x - 1, y) is None:
            segments["west"].append(_tile_seam_segment(cell.tile, "west", offset=y, local_x=x, local_y=y))
        if composite.cell_at(x + 1, y) is None:
            segments["east"].append(_tile_seam_segment(cell.tile, "east", offset=y, local_x=x, local_y=y))
    return ConnectionSurface(
        {
            side: tuple(sorted(side_segments, key=lambda segment: (segment.offset, segment.local_y, segment.local_x)))
            for side, side_segments in segments.items()
        }
    )


def connection_surface_for_placeable(placeable: TileRecord | CompositeTileRecord) -> ConnectionSurface:
    if isinstance(placeable, TileRecord):
        return _connection_surface_for_tile(placeable)
    return _connection_surface_for_composite_tile(placeable)


def _rebind_tile(tile: TileRecord, tiles: Mapping[str, TileRecord]) -> TileRecord:
    return tiles[tile.id]


def index_tiles_by_sheet_cell(
    tiles: Mapping[str, TileRecord],
    *,
    context: str,
) -> dict[tuple[int, int], TileRecord]:
    indexed: dict[tuple[int, int], TileRecord] = {}
    for tile in tiles.values():
        if tile.genesis.sheet_col is None or tile.genesis.sheet_row is None:
            continue
        key = (tile.genesis.sheet_col, tile.genesis.sheet_row)
        existing = indexed.get(key)
        if existing is not None:
            raise ValueError(f"{context} has duplicate sheet cell {key!r}: {existing.id!r} and {tile.id!r}")
        indexed[key] = tile
    return indexed


def _rebind_fixed_construction_tiles(
    construction: FixedConstruction,
    tiles: Mapping[str, TileRecord],
) -> FixedConstruction:
    return replace(
        construction,
        cells=tuple(
            tuple(None if cell is None else _rebind_tile(cell, tiles) for cell in row)
            for row in construction.cells
        ),
    )


def _rebind_parametric_run_tiles(
    construction: ParametricRunConstruction,
    tiles: Mapping[str, TileRecord],
) -> ParametricRunConstruction:
    return replace(
        construction,
        start_tile=_rebind_tile(construction.start_tile, tiles),
        repeat_tile=_rebind_tile(construction.repeat_tile, tiles),
        end_tile=_rebind_tile(construction.end_tile, tiles),
    )


def _rebind_frame_slot_tiles(slot: FrameSlot, tiles: Mapping[str, TileRecord]) -> FrameSlot:
    return replace(slot, tile=_rebind_tile(slot.tile, tiles))


def _rebind_frame_corner_tiles(corner: FrameCornerSlot, tiles: Mapping[str, TileRecord]) -> FrameCornerSlot:
    return replace(
        corner,
        cells=tuple(
            tuple(None if cell is None else _rebind_tile(cell, tiles) for cell in row)
            for row in corner.cells
        ),
    )


def _rebind_parametric_frame_tiles(
    construction: ParametricFrameConstruction,
    tiles: Mapping[str, TileRecord],
) -> ParametricFrameConstruction:
    return replace(
        construction,
        corners={role: _rebind_frame_corner_tiles(corner, tiles) for role, corner in construction.corners.items()},
        edges={role: _rebind_frame_slot_tiles(edge, tiles) for role, edge in construction.edges.items()},
        fill=None if construction.fill is None else _rebind_frame_slot_tiles(construction.fill, tiles),
    )


def _rebind_construction_tiles(construction: Construction, tiles: Mapping[str, TileRecord]) -> Construction:
    if isinstance(construction, FixedConstruction):
        return _rebind_fixed_construction_tiles(construction, tiles)
    if isinstance(construction, ParametricRunConstruction):
        return _rebind_parametric_run_tiles(construction, tiles)
    return _rebind_parametric_frame_tiles(construction, tiles)


def _rebind_composite_tile_tiles(
    composite: CompositeTileRecord,
    tiles: Mapping[str, TileRecord],
) -> CompositeTileRecord:
    return replace(
        composite,
        cells=tuple(
            tuple(
                None if cell is None else replace(cell, tile=_rebind_tile(cell.tile, tiles))
                for cell in row
            )
            for row in composite.cells
        ),
    )


@dataclass(frozen=True, slots=True)
class TileLibraryUnit(RuntimeConstructionCatalog):
    family_id: str
    tile_width: int
    tile_height: int
    render_step_width: int | None
    render_step_height: int | None
    default_variant_id: str
    runtime_flippable: bool
    promoted_metadata: TileLibraryPromotedMetadata = field(repr=False)
    root: Path = field(repr=False)
    variants: Mapping[str, TileFamilyVariant] = field(repr=False)
    tiles: Mapping[str, TileRecord] = field(repr=False)
    aliases: Mapping[str, str] = field(repr=False)
    tiles_by_sheet_cell_index: Mapping[tuple[int, int], TileRecord] = field(repr=False)
    constructions: Mapping[str, Construction] = field(repr=False)
    attachment_sets: Mapping[str, ConstructionAttachmentSet] = field(repr=False)
    attachment_sets_by_target: Mapping[PlaceableRef, tuple[ConstructionAttachmentSet, ...]] = field(repr=False)
    composite_tiles: Mapping[str, CompositeTileRecord] = field(default_factory=_empty_composite_tiles, repr=False)
    clusters: Mapping[str, TileClusterRecord] = field(default_factory=_empty_tile_clusters, repr=False)
    legacy_semantics: Mapping[str, LegacyTileSemanticRecord] = field(default_factory=_empty_legacy_semantics, repr=False)

    def __post_init__(self) -> None:
        for attachment_set in self.attachment_sets.values():
            self._validate_attachment_set(attachment_set)

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(self.variants.keys())

    def variant(self, variant_id: str | None = None) -> TileFamilyVariant:
        resolved_variant_id = variant_id or self.default_variant_id
        return self.variants[resolved_variant_id]

    def runtime_tileset_id(self, variant_id: str | None = None) -> str:
        resolved_variant_id = variant_id or self.default_variant_id
        return f"{self.family_id}@{resolved_variant_id}"

    def tile_record(self, tile_id: str) -> TileRecord | None:
        return self.tiles.get(tile_id)

    def legacy_semantics_for(self, tile_id: str) -> LegacyTileSemanticRecord | None:
        return self.legacy_semantics.get(tile_id)

    def genesis_for(self, tile_id: str) -> TileGenesis | None:
        """One-hop tile-id -> genesis lookup (ADR 0005)."""
        tile = self.tiles.get(tile_id)
        return None if tile is None else tile.genesis

    def genesis_for_alias(self, alias: str) -> TileGenesis | None:
        """One-hop alias -> tile id -> genesis lookup (ADR 0005)."""
        tile_id = self.aliases.get(alias)
        return None if tile_id is None else self.genesis_for(tile_id)

    def tile_at_sheet_cell(self, *, sheet_col: int, sheet_row: int) -> TileRecord | None:
        return self.tiles_by_sheet_cell_index.get((sheet_col, sheet_row))

    def lookup_construction(self, construction_id: str) -> Construction | None:
        return self.constructions.get(construction_id)

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        return entity_template_for_construction(
            self.constructions,
            construction_id,
            attachment_sets=self.attachment_sets_for_construction(construction_id),
        )

    def lookup_placeable(self, placeable_ref: PlaceableRef) -> Placeable | None:
        if placeable_ref.kind == "tile":
            return self.tile_record(placeable_ref.id)
        if placeable_ref.kind == "composite_tile":
            return self.composite_tiles.get(placeable_ref.id)
        return self.lookup_construction(placeable_ref.id)

    def entity_template_for_placeable(self, placeable_ref: PlaceableRef) -> EntityTemplateRecord | None:
        placeable = self.lookup_placeable(placeable_ref)
        if placeable is None:
            return None
        if isinstance(placeable, (TileRecord, CompositeTileRecord)):
            return entity_template_from_placeable(
                placeable,
                attachment_sets=self.attachment_sets_for_placeable(placeable_ref),
            )
        return self.entity_template(placeable_ref.id)

    def lower_placeable_to_tile_cells(self, placeable_ref: PlaceableRef) -> tuple[LoweredTileCell, ...] | None:
        placeable = self.lookup_placeable(placeable_ref)
        if isinstance(placeable, (TileRecord, CompositeTileRecord)):
            return lower_tile_asset_to_cells(placeable)
        return None

    def attachment_sets_for_placeable(self, placeable_ref: PlaceableRef) -> tuple[ConstructionAttachmentSet, ...]:
        return self.attachment_sets_by_target.get(placeable_ref, ())

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.attachment_sets_for_placeable(PlaceableRef.construction(construction_id))

    def _validate_attachment_set(self, attachment_set: ConstructionAttachmentSet) -> None:
        for target_ref in attachment_set.target_placeable_refs:
            target = self.lookup_placeable(target_ref)
            if target is None:
                raise ValueError(
                    f"attachment set {attachment_set.id!r} references unknown target placeable "
                    f"{target_ref.kind}:{target_ref.id!r}"
                )
            target_bounds = fixed_placeable_bounds(
                target,
                context=f"attachment set {attachment_set.id!r} target {target_ref.kind}:{target_ref.id!r}",
            )
            if not bounds_inside(target_bounds, attachment_set.canvas):
                raise ValueError(
                    f"attachment set {attachment_set.id!r} canvas {attachment_set.canvas} must stay inside target "
                    f"placeable {target_ref.kind}:{target_ref.id!r} bounds {target_bounds}"
                )
        for variant in attachment_set.variants.values():
            fill = self.lookup_placeable(variant.placeable_ref)
            if fill is None:
                raise ValueError(
                    f"attachment set {attachment_set.id!r} variant {variant.id!r} references unknown placeable "
                    f"{variant.placeable_ref.kind}:{variant.placeable_ref.id!r}"
                )
            fill_bounds = fixed_placeable_bounds(
                fill,
                context=(
                    f"attachment set {attachment_set.id!r} variant {variant.id!r} "
                    f"{variant.placeable_ref.kind}:{variant.placeable_ref.id!r}"
                ),
            )
            if fill_bounds.width > attachment_set.canvas.width or fill_bounds.height > attachment_set.canvas.height:
                raise ValueError(
                    f"attachment set {attachment_set.id!r} variant {variant.id!r} placeable "
                    f"{variant.placeable_ref.kind}:{variant.placeable_ref.id!r} size "
                    f"{fill_bounds.width}x{fill_bounds.height} exceeds canvas "
                    f"{attachment_set.canvas.width}x{attachment_set.canvas.height}"
                )

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        if construction_id not in self.constructions:
            return None
        self._validate_variant_for_ref(variant_id, context=f"construction {construction_id!r}")
        return self.runtime_tileset_id(variant_id)

    def runtime_tileset_id_for_placeable(
        self,
        placeable_ref: PlaceableRef,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        if self.lookup_placeable(placeable_ref) is None:
            return None
        self._validate_variant_for_ref(
            variant_id,
            context=f"placeable {placeable_ref.kind}:{placeable_ref.id!r}",
        )
        return self.runtime_tileset_id(variant_id)

    def _validate_variant_for_ref(self, variant_id: str | None, *, context: str) -> None:
        try:
            _ = self.variant(variant_id)
        except KeyError as exc:
            resolved_variant_id = variant_id or self.default_variant_id
            raise ValueError(f"Unknown variant {resolved_variant_id!r} for {context}") from exc

    def entity_templates(self) -> list[EntityTemplateRecord]:
        templates: list[EntityTemplateRecord] = []
        for construction in self.constructions.values():
            template = self.entity_template(construction.id)
            if template is not None:
                templates.append(template)
        for composite in self.composite_tiles.values():
            composite_ref = PlaceableRef(kind="composite_tile", id=composite.id)
            template = entity_template_from_placeable(
                composite,
                attachment_sets=self.attachment_sets_for_placeable(composite_ref),
            )
            if template is not None:
                templates.append(template)
        return templates

    def resolve_ref(self, ref: str, *, variant_id: str | None = None) -> ResolvedFamilyTile | None:
        return _resolve_family_ref(
            family_id=self.family_id,
            root=self.root,
            default_variant_id=self.default_variant_id,
            variants=self.variants,
            tiles=self.tiles,
            aliases=self.aliases,
            tiles_by_sheet_cell=self.tiles_by_sheet_cell_index,
            ref=ref,
            variant_id=variant_id,
        )

    def with_tiles(self, tiles: Mapping[str, TileRecord]) -> TileLibraryUnit:
        return replace(
            self,
            tiles=dict(tiles),
            tiles_by_sheet_cell_index=index_tiles_by_sheet_cell(tiles, context=f"tile library {self.family_id!r}"),
            constructions={
                construction_id: _rebind_construction_tiles(construction, tiles)
                for construction_id, construction in self.constructions.items()
            },
            composite_tiles={
                composite_id: _rebind_composite_tile_tiles(composite, tiles)
                for composite_id, composite in self.composite_tiles.items()
            },
        )


@dataclass(frozen=True, slots=True)
class LoadedTileLibraryUnit:
    unit: TileLibraryUnit
    selected_variant_id: str

    @property
    def family_id(self) -> str:
        return self.unit.family_id

    @property
    def selected_tileset_id(self) -> str:
        return self.unit.runtime_tileset_id(self.selected_variant_id)

    @property
    def effective_render_step_width(self) -> int:
        return self.unit.render_step_width if self.unit.render_step_width is not None else self.unit.tile_width

    @property
    def effective_render_step_height(self) -> int:
        return self.unit.render_step_height if self.unit.render_step_height is not None else self.unit.tile_height

    def resolve_ref(self, ref: str) -> ResolvedFamilyTile | None:
        return self.unit.resolve_ref(ref, variant_id=self.selected_variant_id)


@dataclass(frozen=True, slots=True)
class TileLibraryRegistry(RuntimeConstructionCatalog):
    loaded_units_by_id: Mapping[str, LoadedTileLibraryUnit] = field(repr=False)
    construction_entries_by_id: Mapping[str, tuple[str, Construction]] = field(repr=False)
    composite_tile_entries_by_id: Mapping[str, tuple[str, CompositeTileRecord]] = field(repr=False)
    alias_unit_ids: Mapping[str, str] = field(repr=False)
    tile_unit_ids: Mapping[str, str] = field(repr=False)
    tile_width: int
    tile_height: int
    render_step_width: int
    render_step_height: int

    @classmethod
    def from_units(cls, units: Iterable[TileLibraryUnit]) -> TileLibraryRegistry:
        return cls.from_loaded_units(
            LoadedTileLibraryUnit(unit=unit, selected_variant_id=unit.default_variant_id)
            for unit in units
        )

    @classmethod
    def from_loaded_units(cls, loaded_units: Iterable[LoadedTileLibraryUnit]) -> TileLibraryRegistry:
        loaded_units_by_id: dict[str, LoadedTileLibraryUnit] = {}
        construction_entries_by_id: dict[str, tuple[str, Construction]] = {}
        composite_tile_entries_by_id: dict[str, tuple[str, CompositeTileRecord]] = {}
        alias_unit_ids: dict[str, str] = {}
        tile_unit_ids: dict[str, str] = {}
        common_tile_width: int | None = None
        common_tile_height: int | None = None
        common_render_step_width: int | None = None
        common_render_step_height: int | None = None
        for loaded_unit in loaded_units:
            unit = loaded_unit.unit
            existing_unit = loaded_units_by_id.get(unit.family_id)
            if existing_unit is not None:
                raise ValueError(f"Duplicate tile library unit id {unit.family_id!r}")
            loaded_units_by_id[unit.family_id] = loaded_unit
            if common_tile_width is None:
                common_tile_width = unit.tile_width
                common_tile_height = unit.tile_height
                common_render_step_width = loaded_unit.effective_render_step_width
                common_render_step_height = loaded_unit.effective_render_step_height
            else:
                if unit.tile_width != common_tile_width:
                    raise ValueError("All loaded tile families must share the same tile_width")
                if unit.tile_height != common_tile_height:
                    raise ValueError("All loaded tile families must share the same tile_height")
                if loaded_unit.effective_render_step_width != common_render_step_width:
                    raise ValueError("All loaded tile families must share the same render_step_width")
                if loaded_unit.effective_render_step_height != common_render_step_height:
                    raise ValueError("All loaded tile families must share the same render_step_height")
            for tile_id in unit.tiles:
                existing_tile_owner = tile_unit_ids.get(tile_id)
                if existing_tile_owner is not None:
                    raise ValueError(
                        f"Duplicate tile id across tile library units: {tile_id!r} "
                        f"owned by {existing_tile_owner!r} and {unit.family_id!r}"
                    )
                existing_alias_owner = alias_unit_ids.get(tile_id)
                if existing_alias_owner is not None and existing_alias_owner != unit.family_id:
                    raise ValueError(
                        f"Cross-unit ref collision between tile id and alias: {tile_id!r} "
                        f"owned by tile family {unit.family_id!r} and alias family {existing_alias_owner!r}"
                    )
                tile_unit_ids[tile_id] = unit.family_id
            for construction_id, construction in unit.constructions.items():
                existing_construction = construction_entries_by_id.get(construction_id)
                if existing_construction is not None:
                    raise ValueError(
                        f"Duplicate construction id across tile library units: {construction_id!r} "
                        f"owned by {existing_construction[0]!r} and {unit.family_id!r}"
                    )
                construction_entries_by_id[construction_id] = (unit.family_id, construction)
            for composite_id, composite in unit.composite_tiles.items():
                existing_composite = composite_tile_entries_by_id.get(composite_id)
                if existing_composite is not None:
                    raise ValueError(
                        f"Duplicate composite tile id across tile library units: {composite_id!r} "
                        f"owned by {existing_composite[0]!r} and {unit.family_id!r}"
                    )
                composite_tile_entries_by_id[composite_id] = (unit.family_id, composite)
            for alias in unit.aliases:
                existing_alias_owner = alias_unit_ids.get(alias)
                if existing_alias_owner is not None:
                    raise ValueError(
                        f"Duplicate alias across tile library units: {alias!r} "
                        f"owned by {existing_alias_owner!r} and {unit.family_id!r}"
                    )
                existing_tile_owner = tile_unit_ids.get(alias)
                if existing_tile_owner is not None and existing_tile_owner != unit.family_id:
                    raise ValueError(
                        f"Cross-unit ref collision between tile id and alias: {alias!r} "
                        f"owned by tile family {existing_tile_owner!r} and alias family {unit.family_id!r}"
                    )
                alias_unit_ids[alias] = unit.family_id
        if (
            common_tile_width is None
            or common_tile_height is None
            or common_render_step_width is None
            or common_render_step_height is None
        ):
            raise ValueError("Tile library registry requires at least one loaded unit")
        return cls(
            loaded_units_by_id=MappingProxyType(dict(loaded_units_by_id)),
            construction_entries_by_id=MappingProxyType(dict(construction_entries_by_id)),
            composite_tile_entries_by_id=MappingProxyType(dict(composite_tile_entries_by_id)),
            alias_unit_ids=MappingProxyType(dict(alias_unit_ids)),
            tile_unit_ids=MappingProxyType(dict(tile_unit_ids)),
            tile_width=common_tile_width,
            tile_height=common_tile_height,
            render_step_width=common_render_step_width,
            render_step_height=common_render_step_height,
        )

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(self.loaded_units_by_id.keys())

    def loaded_unit(self, unit_id: str) -> LoadedTileLibraryUnit | None:
        return self.loaded_units_by_id.get(unit_id)

    def unit(self, unit_id: str) -> TileLibraryUnit | None:
        loaded_unit = self.loaded_unit(unit_id)
        if loaded_unit is None:
            return None
        return loaded_unit.unit

    def unit_for_construction(self, construction_id: str) -> TileLibraryUnit | None:
        entry = self.construction_entries_by_id.get(construction_id)
        if entry is None:
            return None
        unit_id, _construction = entry
        return self.loaded_units_by_id[unit_id].unit

    def unit_for_composite_tile(self, composite_id: str) -> TileLibraryUnit | None:
        entry = self.composite_tile_entries_by_id.get(composite_id)
        if entry is None:
            return None
        unit_id, _composite = entry
        return self.loaded_units_by_id[unit_id].unit

    def _owner_for(self, placeable_ref: PlaceableRef) -> TileLibraryUnit | None:
        if placeable_ref.kind == "tile":
            return self.tile_owner(placeable_ref.id)
        if placeable_ref.kind == "composite_tile":
            return self.unit_for_composite_tile(placeable_ref.id)
        return self.unit_for_construction(placeable_ref.id)

    def alias_owner(self, alias: str) -> TileLibraryUnit | None:
        unit_id = self.alias_unit_ids.get(alias)
        if unit_id is None:
            return None
        return self.loaded_units_by_id[unit_id].unit

    def tile_owner(self, tile_id: str) -> TileLibraryUnit | None:
        unit_id = self.tile_unit_ids.get(tile_id)
        if unit_id is None:
            return None
        return self.loaded_units_by_id[unit_id].unit

    def genesis_for(self, tile_id: str) -> TileGenesis | None:
        """One-hop tile-id -> genesis across loaded units (ADR 0005)."""
        owner = self.tile_owner(tile_id)
        return None if owner is None else owner.genesis_for(tile_id)

    def genesis_for_alias(self, alias: str) -> TileGenesis | None:
        """One-hop alias -> tile id -> genesis across loaded units (ADR 0005)."""
        owner = self.alias_owner(alias)
        return None if owner is None else owner.genesis_for_alias(alias)

    def unit_for_ref(self, ref: str) -> TileLibraryUnit | None:
        loaded_unit = self.loaded_unit_for_ref(ref)
        if loaded_unit is None:
            return None
        return loaded_unit.unit

    def loaded_unit_for_ref(self, ref: str) -> LoadedTileLibraryUnit | None:
        variant_match = VARIANT_TILE_RE.match(ref)
        if variant_match is not None:
            return self.loaded_unit(variant_match.group("family"))
        physical_match = PHYSICAL_TILE_RE.match(ref)
        if physical_match is not None:
            return self.loaded_unit(physical_match.group("family"))
        tile_owner = self.tile_owner(ref)
        if tile_owner is not None:
            return self.loaded_unit(tile_owner.family_id)
        alias_owner = self.alias_owner(ref)
        if alias_owner is None:
            return None
        return self.loaded_unit(alias_owner.family_id)

    def resolve_ref(
        self,
        ref: str,
        *,
        default_unit_id: str | None = None,
    ) -> ResolvedFamilyTile | None:
        loaded_unit = self.loaded_unit_for_ref(ref)
        if loaded_unit is not None:
            return loaded_unit.resolve_ref(ref)
        if default_unit_id is None:
            return None
        default_loaded_unit = self.loaded_unit(default_unit_id)
        if default_loaded_unit is None:
            return None
        return default_loaded_unit.resolve_ref(ref)

    def lookup_construction(self, construction_id: str) -> Construction | None:
        entry = self.construction_entries_by_id.get(construction_id)
        if entry is None:
            return None
        return entry[1]

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return None
        return unit.entity_template(construction_id)

    def lookup_placeable(self, placeable_ref: PlaceableRef) -> Placeable | None:
        owner = self._owner_for(placeable_ref)
        return None if owner is None else owner.lookup_placeable(placeable_ref)

    def entity_template_for_placeable(self, placeable_ref: PlaceableRef) -> EntityTemplateRecord | None:
        owner = self._owner_for(placeable_ref)
        return None if owner is None else owner.entity_template_for_placeable(placeable_ref)

    def lower_placeable_to_tile_cells(self, placeable_ref: PlaceableRef) -> tuple[LoweredTileCell, ...] | None:
        owner = self._owner_for(placeable_ref)
        return None if owner is None else owner.lower_placeable_to_tile_cells(placeable_ref)

    def attachment_sets_for_placeable(self, placeable_ref: PlaceableRef) -> tuple[ConstructionAttachmentSet, ...]:
        unit = self._owner_for(placeable_ref)
        if unit is None:
            return ()
        return unit.attachment_sets_for_placeable(placeable_ref)

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.attachment_sets_for_placeable(PlaceableRef.construction(construction_id))

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return None
        return unit.runtime_tileset_id_for_construction(construction_id, variant_id=variant_id)

    def runtime_tileset_id_for_placeable(
        self,
        placeable_ref: PlaceableRef,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        unit = self._owner_for(placeable_ref)
        return None if unit is None else unit.runtime_tileset_id_for_placeable(placeable_ref, variant_id=variant_id)


def resolve_tile_image_override_path(*, root: Path, image_override: str, variant_id: str) -> Path:
    return resolve_path(root, image_override.format(variant_id=variant_id))


def _resolved_family_tile(
    *,
    family_id: str,
    root: Path,
    tile: TileRecord,
    variant_id: str,
) -> ResolvedFamilyTile:
    return ResolvedFamilyTile(
        family_id=family_id,
        variant_id=variant_id,
        tile_id=tile.id,
        sheet_col=tile.genesis.sheet_col,
        sheet_row=tile.genesis.sheet_row,
        image_override_path=(
            resolve_tile_image_override_path(
                root=root,
                image_override=tile.image_override,
                variant_id=variant_id,
            )
            if tile.image_override is not None
            else None
        ),
    )


def _resolve_family_ref(
    *,
    family_id: str,
    root: Path,
    default_variant_id: str,
    variants: Mapping[str, TileFamilyVariant],
    tiles: Mapping[str, TileRecord],
    aliases: Mapping[str, str],
    tiles_by_sheet_cell: Mapping[tuple[int, int], TileRecord],
    ref: str,
    variant_id: str | None = None,
) -> ResolvedFamilyTile | None:
    resolved_variant_id = variant_id or default_variant_id

    variant_match = VARIANT_TILE_RE.match(ref)
    if variant_match:
        if variant_match.group("family") != family_id:
            return None
        explicit_variant_id = variant_match.group("variant")
        if explicit_variant_id not in variants:
            raise ValueError(f"Unknown variant ref: {ref}")
        tile = tiles_by_sheet_cell.get((int(variant_match.group("col")), int(variant_match.group("row"))))
        if tile is None:
            return None
        return _resolved_family_tile(
            family_id=family_id,
            root=root,
            tile=tile,
            variant_id=explicit_variant_id,
        )

    physical_match = PHYSICAL_TILE_RE.match(ref)
    if physical_match:
        if physical_match.group("family") != family_id:
            return None
        tile = tiles_by_sheet_cell.get((int(physical_match.group("col")), int(physical_match.group("row"))))
        if tile is None:
            return None
        return _resolved_family_tile(
            family_id=family_id,
            root=root,
            tile=tile,
            variant_id=resolved_variant_id,
        )

    tile = tiles.get(ref)
    if tile is None:
        alias_target = aliases.get(ref)
        if alias_target is None:
            return None
        tile = tiles.get(alias_target)
        if tile is None:
            return None
    return _resolved_family_tile(
        family_id=family_id,
        root=root,
        tile=tile,
        variant_id=resolved_variant_id,
    )


def format_sheet_cell_ref(col: int, row: int) -> str:
    return f"sheet:{col},{row}"


def _construction_tiles(construction: Construction) -> tuple[TileRecord, ...]:
    if isinstance(construction, ParametricRunConstruction):
        return (
            construction.start_tile,
            construction.repeat_tile,
            construction.end_tile,
        )
    if isinstance(construction, ParametricFrameConstruction):
        tiles: list[TileRecord] = []
        for corner in construction.corners.values():
            tiles.extend(corner.tiles())
        tiles.extend(slot.tile for slot in construction.edges.values())
        if construction.fill is not None:
            tiles.append(construction.fill.tile)
        return tuple(tiles)
    return tuple(
        cell
        for row in construction.cells
        for cell in row
        if cell is not None
    )


def _construction_footprint_spec(construction: Construction) -> EntityFootprintSpec:
    if isinstance(construction, ParametricRunConstruction):
        if construction.axis == "x":
            width, height = 2, 1
        else:
            width, height = 1, 2
        return EntityFootprintSpec(
            mode="parametric_run",
            width=width,
            height=height,
            axis=construction.axis,
            length_param=construction.length_param,
            minimum_length=2,
        )
    if isinstance(construction, ParametricFrameConstruction):
        # Both axes are variable; width/height carry the minimum bounding box
        # (the 2-D analogue of parametric_run's minimum-length box).
        return EntityFootprintSpec(
            mode="parametric_frame",
            width=construction.min_width,
            height=construction.min_height,
            width_param=construction.width_param,
            height_param=construction.height_param,
        )
    width = len(construction.cells[0]) if construction.cells else 0
    height = len(construction.cells)
    return EntityFootprintSpec(
        mode="fixed",
        width=width,
        height=height,
    )


def entity_template_from_construction(
    construction: Construction,
    *,
    attachment_sets: Iterable[ConstructionAttachmentSet] = (),
) -> EntityTemplateRecord:
    tiles = _construction_tiles(construction)

    return EntityTemplateRecord(
        id=construction.id,
        collection_id=construction.collection_id,
        kind=construction.kind,
        placement_anchor="top_left",
        compose_roles=_sorted_unique(tile.compose_role for tile in tiles),
        affordances=_sorted_unique(affordance for tile in tiles for affordance in tile.affordances),
        state_groups=_sorted_unique(tile.state_group for tile in tiles),
        animation_groups=_sorted_unique(tile.animation_group for tile in tiles),
        footprint=_construction_footprint_spec(construction),
        placeable_kind="construction",
        placeable_id=construction.id,
        construction_id=construction.id,
        attachment_sets=tuple(attachment_set.to_entity_record() for attachment_set in attachment_sets),
    )
