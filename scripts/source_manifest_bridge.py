#!/usr/bin/env python3
"""One-way adapter from source manifests into the current family-backed runtime path."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from compatibility_family import CompatibilityFamilyPaths
from legacy_semantic_bootstrap import content_hashes_by_tile_id
from semantic_catalogue_ingest import ResolvedSemanticTile
from semantic_catalogue_promotion import SemanticPromotionError, promote_semantic_catalogue
from source_manifests import (
    RenderVariantTilesheetManifest,
    TilePackManifest,
    load_tile_pack_manifest,
)
from tile_library import (
    CellContentInset,
    LegacyTileSemanticRecord,
    NON_CONTENT_LEGACY_TILE_FIELDS,
    TILE_RECORD_FIELD_DEFAULTS,
    TileFamilyHeader,
    TileFamilyVariant,
    TileLibraryUnit,
    TileLibraryPromotedMetadata,
    TileRecord,
)
from source_layout_model import (
    SourceLayoutIngestion,
)
# TODO(IRS Phase 2/3): decouple layout_core from ingest; the bridge still
# imports and reads source_layout / ingestion.json for source-pack families.
from tile_family_ingest import (
    load_source_layout_from_path,
)
from tile_family_runtime import (
    DEFAULT_TRANSPARENT_MODE,
    TileFamily,
    load_family_catalog_sources,
    load_family_header_and_variants,
)


def _bridge_variants(
    variants: Mapping[str, RenderVariantTilesheetManifest],
) -> dict[str, TileFamilyVariant]:
    return {
        variant_id: TileFamilyVariant(
            id=variant_id,
            sheet_path=variant.sheet_path,
            transparent_mode=(
                DEFAULT_TRANSPARENT_MODE
                if variant.transparent_mode is None
                else variant.transparent_mode
            ),
            palette_family=variant.palette_family,
            colorway=variant.colorway,
            background_mode=variant.background_mode,
            notes=variant.notes,
        )
        for variant_id, variant in variants.items()
    }


def _mismatch_message(
    *,
    staged_label: str,
    staged: object,
    legacy_label: str,
    legacy: object,
) -> str | None:
    if staged != legacy:
        return f"Staged {staged_label} {staged!r} does not match {legacy_label} {legacy!r}"
    return None


def _normalised_notes(notes: tuple[str, ...] | None) -> tuple[str, ...]:
    return notes or ()


@dataclass(frozen=True)
class BridgedFamilyInputs:
    header: TileFamilyHeader
    promoted_metadata: TileLibraryPromotedMetadata
    variants: dict[str, TileFamilyVariant]
    compatibility_paths: CompatibilityFamilyPaths
    source_layout: SourceLayoutIngestion | None


@dataclass(frozen=True)
class BridgedSemanticInputs:
    resolved: tuple[ResolvedSemanticTile, ...]
    legacy_semantics: tuple[LegacyTileSemanticRecord, ...]
    variant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved", tuple(self.resolved))
        object.__setattr__(self, "legacy_semantics", tuple(self.legacy_semantics))
        object.__setattr__(self, "variant_ids", tuple(self.variant_ids))
        if not self.variant_ids:
            raise ValueError("Bridged semantic inputs must name the content-hash variant set")


def _build_bridged_family_inputs(
    *,
    pack: TilePackManifest,
    tileset_id: str,
    tilesheet_id: str,
) -> BridgedFamilyInputs:
    tileset = pack.tileset(tileset_id)
    logical_tilesheet = tileset.logical_tilesheet(tilesheet_id)
    compatibility = logical_tilesheet.require_compatibility_family()
    compatibility_root = compatibility.paths.root
    bridged_variants = _bridge_variants(logical_tilesheet.render_variants)
    _assert_corruption_bearing_compatibility(
        pack=pack,
        logical_tilesheet_id=logical_tilesheet.id,
        compatibility_root=compatibility_root,
        bridged_variants=bridged_variants,
    )

    bridged_notes = logical_tilesheet.notes or ()

    source_layout = None
    if logical_tilesheet.source_layout_path is not None:
        source_layout = load_source_layout_from_path(logical_tilesheet.source_layout_path)
        if source_layout.sheet_bounds != logical_tilesheet.bounds:
            raise ValueError(
                f"Logical tilesheet {logical_tilesheet.id!r} bounds {logical_tilesheet.bounds} do not match "
                f"source_layout sheet bounds {source_layout.sheet_bounds}"
            )

    return BridgedFamilyInputs(
        header=TileFamilyHeader(
            root=compatibility_root,
            family_id=compatibility.family_id,
            title=logical_tilesheet.title,
            tile_width=pack.grid.tile_width,
            tile_height=pack.grid.tile_height,
            render_step_width=compatibility.render_step_width,
            render_step_height=compatibility.render_step_height,
            siblings_share_semantics=compatibility.siblings_share_semantics,
            notes=bridged_notes,
            default_variant_id=logical_tilesheet.default_variant_id,
            cell_content_inset=compatibility.cell_content_inset or CellContentInset(),
            runtime_flippable=False if compatibility.runtime_flippable is None else compatibility.runtime_flippable,
        ),
        promoted_metadata=TileLibraryPromotedMetadata(
            source_pack_id=pack.id,
            source_tileset_id=tileset.id,
            source_tilesheet_id=logical_tilesheet.id,
            module_context=dict(tileset.module_context),
            render_traits=logical_tilesheet.render_traits,
            # Until source-side manifests grow a narrower promotion selector,
            # runtime hints intentionally mirror the notes that survive onto
            # the bridged family itself.
            documented_hints=bridged_notes,
        ),
        variants=bridged_variants,
        compatibility_paths=compatibility.paths,
        source_layout=source_layout,
    )


def compare_staged_and_legacy_compatibility_family(
    pack: TilePackManifest,
    *,
    tileset_id: str,
    tilesheet_id: str,
) -> tuple[str, ...]:
    """Return staged-vs-legacy compatibility mismatches for migration diagnostics.

    Normal source-pack loading does not call this helper. It exists only for
    operator migration checks while the legacy compatibility family is retired.
    """

    tileset = pack.tileset(tileset_id)
    logical_tilesheet = tileset.logical_tilesheet(tilesheet_id)
    compatibility = logical_tilesheet.require_compatibility_family()
    legacy_header, legacy_variants, _ = load_family_header_and_variants(compatibility.paths.root)
    bridged_variants = _bridge_variants(logical_tilesheet.render_variants)

    mismatches: list[str] = []
    for message in (
        _mismatch_message(
            staged_label="compatibility family_id",
            staged=compatibility.family_id,
            legacy_label="compatibility family manifest family_id",
            legacy=legacy_header.family_id,
        ),
        _mismatch_message(
            staged_label="pack grid",
            staged=f"{pack.grid.tile_width}x{pack.grid.tile_height}",
            legacy_label="compatibility family grid",
            legacy=f"{legacy_header.tile_width}x{legacy_header.tile_height}",
        ),
        _mismatch_message(
            staged_label="default_variant_id",
            staged=logical_tilesheet.default_variant_id,
            legacy_label="compatibility family default_variant_id",
            legacy=legacy_header.default_variant_id,
        ),
        _mismatch_message(
            staged_label="logical tilesheet title",
            staged=logical_tilesheet.title,
            legacy_label="compatibility family title",
        legacy=legacy_header.title,
    ),
    _mismatch_message(
        staged_label="logical tilesheet notes",
        staged=_normalised_notes(logical_tilesheet.notes),
        legacy_label="compatibility family notes",
        legacy=_normalised_notes(legacy_header.notes),
        ),
        _mismatch_message(
            staged_label="render_step_width",
            staged=compatibility.render_step_width,
            legacy_label="compatibility family render_step_width",
            legacy=legacy_header.render_step_width,
        ),
        _mismatch_message(
            staged_label="render_step_height",
            staged=compatibility.render_step_height,
            legacy_label="compatibility family render_step_height",
            legacy=legacy_header.render_step_height,
        ),
        _mismatch_message(
            staged_label="siblings_share_semantics",
            staged=compatibility.siblings_share_semantics,
            legacy_label="compatibility family siblings_share_semantics",
            legacy=legacy_header.siblings_share_semantics,
        ),
    ):
        if message is not None:
            mismatches.append(message)
    if bridged_variants != legacy_variants:
        mismatches.append(
            f"Staged render variants for logical tilesheet {logical_tilesheet.id!r} do not match compatibility "
            f"family variants in {compatibility.paths.root / 'family.json'}"
        )
    return tuple(mismatches)


def bridge_logical_tilesheet_to_family(
    pack: TilePackManifest,
    *,
    tileset_id: str,
    tilesheet_id: str,
) -> TileFamily:
    inputs = _build_bridged_family_inputs(
        pack=pack,
        tileset_id=tileset_id,
        tilesheet_id=tilesheet_id,
    )
    return TileFamily.from_catalog_sources(
        header=inputs.header,
        variants=inputs.variants,
        catalog=load_family_catalog_sources(inputs.compatibility_paths),
        source_layout=inputs.source_layout,
        promoted_metadata=inputs.promoted_metadata,
    )


def _variant_pixel_signature(
    variants: Mapping[str, TileFamilyVariant],
) -> dict[str, tuple[Path | None, str, str | None]]:
    return {
        variant_id: (variant.sheet_path, variant.transparent_mode, variant.background_mode)
        for variant_id, variant in variants.items()
    }


def _assert_corruption_bearing_compatibility(
    *,
    pack: TilePackManifest,
    logical_tilesheet_id: str,
    compatibility_root: Path,
    bridged_variants: Mapping[str, TileFamilyVariant],
) -> None:
    legacy_header, legacy_variants, _ = load_family_header_and_variants(compatibility_root)
    if message := _mismatch_message(
        staged_label="pack grid",
        staged=f"{pack.grid.tile_width}x{pack.grid.tile_height}",
        legacy_label="compatibility family grid",
        legacy=f"{legacy_header.tile_width}x{legacy_header.tile_height}",
    ):
        raise ValueError(message)
    if _variant_pixel_signature(bridged_variants) != _variant_pixel_signature(legacy_variants):
        raise ValueError(
            f"Staged render variants for logical tilesheet {logical_tilesheet_id!r} do not match compatibility "
            "family pixel-driving variants"
        )


def bridge_logical_tilesheet_to_runtime_unit(
    pack: TilePackManifest,
    *,
    tileset_id: str,
    tilesheet_id: str,
    semantic_inputs: BridgedSemanticInputs,
) -> TileLibraryUnit:
    base_family = bridge_logical_tilesheet_to_family(
        pack,
        tileset_id=tileset_id,
        tilesheet_id=tilesheet_id,
    )
    content_hash_by_tile_id = content_hashes_by_tile_id(
        base_family,
        variant_ids=semantic_inputs.variant_ids,
    )
    structural_unit = _structural_base_unit(base_family.runtime_unit)
    try:
        return promote_semantic_catalogue(
            structural_unit,
            resolved=semantic_inputs.resolved,
            content_hash_by_tile_id=content_hash_by_tile_id,
            legacy_semantics=semantic_inputs.legacy_semantics,
        )
    except SemanticPromotionError as exc:
        if exc.kind == "missing_resolved_record":
            raise ValueError(
                "Bridged semantic promotion failed because the resolved catalogue does not cover "
                f"tile {exc.tile_id!r} content hash {exc.content_hash!r} computed from variant set "
                f"{semantic_inputs.variant_ids!r}"
            ) from exc
        raise


def _structural_base_unit(unit: TileLibraryUnit) -> TileLibraryUnit:
    updates = {field: TILE_RECORD_FIELD_DEFAULTS[field] for field in NON_CONTENT_LEGACY_TILE_FIELDS}
    runtime_tiles: dict[str, TileRecord] = {}
    for tile_id, tile in unit.tiles.items():
        runtime_tiles[tile_id] = replace(tile, **updates)
    return unit.with_tiles(runtime_tiles)


def load_bridged_tile_family(
    pack_path: Path,
    *,
    tileset_id: str,
    tilesheet_id: str,
) -> TileFamily:
    return bridge_logical_tilesheet_to_family(
        load_tile_pack_manifest(pack_path),
        tileset_id=tileset_id,
        tilesheet_id=tilesheet_id,
    )


def load_bridged_tile_library_unit(
    pack_path: Path,
    *,
    tileset_id: str,
    tilesheet_id: str,
    semantic_inputs: BridgedSemanticInputs,
) -> TileLibraryUnit:
    """Load a promoted bridged unit for producer-side runtime asset materialisation.

    Transitional contract: required non-content fields (`category`, `layer`) are
    still provisional compatibility-catalogue carry-forward on this intermediate
    unit. The production runtime-asset producer must seed them from the durable
    legacy layer before serialising the runtime asset (ADR 0014).
    """

    return bridge_logical_tilesheet_to_runtime_unit(
        load_tile_pack_manifest(pack_path),
        tileset_id=tileset_id,
        tilesheet_id=tilesheet_id,
        semantic_inputs=semantic_inputs,
    )
