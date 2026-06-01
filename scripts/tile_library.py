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
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Protocol, Union

from typing_extensions import TypeAlias

from _manifest_utils import GridBounds, resolve_path
from tile_metadata import ModuleContextValue, RenderTraits


PHYSICAL_TILE_RE = re.compile(r"^(?P<family>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$")
VARIANT_TILE_RE = re.compile(
    r"^(?P<family>[a-z0-9_.-]+)@(?P<variant>[a-z0-9_.-]+):(?P<col>\d+),(?P<row>\d+)$"
)
@dataclass(frozen=True)
class MetatileConstruction:
    id: str
    collection_id: str
    cells: tuple[tuple[TileRecord | None, ...], ...]
    expose_as_entity: bool = True
    kind: Literal["metatile"] = "metatile"


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


Construction: TypeAlias = Union[
    MetatileConstruction,
    ParametricRunConstruction,
    ParametricFrameConstruction,
]


@dataclass(frozen=True)
class ConstructionAttachmentVariant:
    id: str
    construction_id: str
    label: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ConstructionAttachmentSet:
    id: str
    param: str
    target_construction_ids: tuple[str, ...]
    canvas: GridBounds
    variants: Mapping[str, ConstructionAttachmentVariant] = field(repr=False)
    required: bool = False
    default_variant_id: str | None = None
    label: str | None = None
    notes: str | None = None

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
            "canvas": {
                "x": self.canvas.x,
                "y": self.canvas.y,
                "width": self.canvas.width,
                "height": self.canvas.height,
            },
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
    construction_id: str
    collection_id: str
    kind: Literal["metatile", "parametric_run", "parametric_frame"]
    placement_anchor: Literal["top_left"]
    compose_roles: tuple[str, ...]
    affordances: tuple[str, ...]
    state_groups: tuple[str, ...]
    animation_groups: tuple[str, ...]
    footprint: EntityFootprintSpec
    attachment_sets: tuple[EntityAttachmentSetRecord, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "construction_id": self.construction_id,
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


@dataclass(frozen=True)
class TileFamilyVariant:
    id: str
    sheet_path: Path
    transparent_mode: str
    palette_family: str | None = None
    colorway: str | None = None
    background_mode: str | None = None
    notes: str | None = None


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
class TileRecord:
    id: str
    family_id: str
    layer: str
    category: str
    transparent: bool
    tags: tuple[str, ...]
    sheet_col: int | None = None
    sheet_row: int | None = None
    exact_duplicate_of: str | None = None
    image_override: str | None = None
    aliases: tuple[str, ...] = ()
    walkable: bool | None = None
    blocking: bool | None = None
    scenes: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    cluster_ids: tuple[str, ...] = ()
    source_group: str | None = None
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
    requires_exposed_on: tuple[str, ...] = ()
    affordances: tuple[str, ...] = ()
    alt_uses: tuple[str, ...] = ()
    meaning: str | None = None
    meaning_confidence: str | None = None
    source_notes: str | None = None


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


class RuntimeConstructionCatalog(Protocol):
    def lookup_construction(self, construction_id: str) -> Construction | None:
        ...

    def entity_template(self, construction_id: str) -> EntityTemplateRecord | None:
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


def attachment_sets_by_target(
    attachment_sets: Mapping[str, ConstructionAttachmentSet],
) -> Mapping[str, tuple[ConstructionAttachmentSet, ...]]:
    indexed: dict[str, list[ConstructionAttachmentSet]] = defaultdict(list)
    for attachment_set in attachment_sets.values():
        for target_id in attachment_set.target_construction_ids:
            indexed[target_id].append(attachment_set)
    return MappingProxyType({target_id: tuple(values) for target_id, values in indexed.items()})


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


@dataclass(frozen=True, slots=True)
class TileLibraryUnit(RuntimeConstructionCatalog):
    family_id: str
    tile_width: int
    tile_height: int
    render_step_width: int | None
    render_step_height: int | None
    default_variant_id: str
    promoted_metadata: TileLibraryPromotedMetadata = field(repr=False)
    root: Path = field(repr=False)
    variants: Mapping[str, TileFamilyVariant] = field(repr=False)
    tiles: Mapping[str, TileRecord] = field(repr=False)
    aliases: Mapping[str, str] = field(repr=False)
    tiles_by_sheet_cell_index: Mapping[tuple[int, int], TileRecord] = field(repr=False)
    constructions: Mapping[str, Construction] = field(repr=False)
    attachment_sets: Mapping[str, ConstructionAttachmentSet] = field(repr=False)
    attachment_sets_by_target: Mapping[str, tuple[ConstructionAttachmentSet, ...]] = field(repr=False)

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

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        return self.attachment_sets_by_target.get(construction_id, ())

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        if construction_id not in self.constructions:
            return None
        self.variant(variant_id)
        return self.runtime_tileset_id(variant_id)

    def entity_templates(self) -> list[EntityTemplateRecord]:
        templates: list[EntityTemplateRecord] = []
        for construction in self.constructions.values():
            template = self.entity_template(construction.id)
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

    def attachment_sets_for_construction(self, construction_id: str) -> tuple[ConstructionAttachmentSet, ...]:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return ()
        return unit.attachment_sets_for_construction(construction_id)

    def runtime_tileset_id_for_construction(
        self,
        construction_id: str,
        *,
        variant_id: str | None = None,
    ) -> str | None:
        unit = self.unit_for_construction(construction_id)
        if unit is None:
            return None
        unit.variant(variant_id)
        return unit.runtime_tileset_id(variant_id)


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
        sheet_col=tile.sheet_col,
        sheet_row=tile.sheet_row,
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

    def _sorted_unique(values: Iterable[str | None]) -> tuple[str, ...]:
        return tuple(sorted({value for value in values if value}))

    return EntityTemplateRecord(
        id=construction.id,
        construction_id=construction.id,
        collection_id=construction.collection_id,
        kind=construction.kind,
        placement_anchor="top_left",
        compose_roles=_sorted_unique(tile.compose_role for tile in tiles),
        affordances=_sorted_unique(affordance for tile in tiles for affordance in tile.affordances),
        state_groups=_sorted_unique(tile.state_group for tile in tiles),
        animation_groups=_sorted_unique(tile.animation_group for tile in tiles),
        footprint=_construction_footprint_spec(construction),
        attachment_sets=tuple(attachment_set.to_entity_record() for attachment_set in attachment_sets),
    )


