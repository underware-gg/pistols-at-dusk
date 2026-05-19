#!/usr/bin/env python3
"""One-way adapter from source manifests into the current family-backed runtime path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TypeVar

from compatibility_family import CompatibilityFamilyPaths
from source_manifests import RenderVariantTilesheetManifest, TilePackManifest, load_tile_pack_manifest
from tile_families import (
    DEFAULT_TRANSPARENT_MODE,
    SourceLayoutIngestion,
    TileFamily,
    TileFamilyHeader,
    TileFamilyVariant,
    load_family_catalog_sources,
    load_family_header_and_variants,
    load_source_layout_from_path,
)

ComparableT = TypeVar("ComparableT")


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


def _require_match(
    *,
    staged_label: str,
    staged: ComparableT,
    legacy_label: str,
    legacy: ComparableT,
    formatter: Callable[[ComparableT], str] = repr,
) -> None:
    if staged != legacy:
        raise ValueError(
            f"Staged {staged_label} {formatter(staged)} does not match {legacy_label} {formatter(legacy)}"
        )


def _resolve_bridged_notes(
    *,
    logical_tilesheet_notes: tuple[str, ...] | None,
    legacy_notes: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if logical_tilesheet_notes is None:
        return legacy_notes or ()
    if legacy_notes is None:
        return logical_tilesheet_notes
    if logical_tilesheet_notes == legacy_notes:
        return logical_tilesheet_notes
    # An explicitly-authored empty list is a real "clear inherited notes" choice,
    # not the same thing as "notes omitted, fall back to legacy."
    if not logical_tilesheet_notes or not legacy_notes:
        return logical_tilesheet_notes
    raise ValueError(
        "Staged logical tilesheet notes do not match compatibility family notes"
    )


def _resolve_optional_override(
    *,
    staged_label: str,
    staged: ComparableT | None,
    legacy_label: str,
    legacy: ComparableT | None,
) -> ComparableT | None:
    if staged is None:
        return legacy
    if legacy is None:
        return staged
    if staged != legacy:
        raise ValueError(
            f"Staged {staged_label} {staged!r} does not match {legacy_label} {legacy!r}"
        )
    return staged


@dataclass(frozen=True)
class BridgedFamilyInputs:
    header: TileFamilyHeader
    variants: dict[str, TileFamilyVariant]
    compatibility_paths: CompatibilityFamilyPaths
    source_layout: SourceLayoutIngestion | None


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
    legacy_header, legacy_variants, _ = load_family_header_and_variants(compatibility_root)
    bridged_variants = _bridge_variants(logical_tilesheet.render_variants)

    _require_match(
        staged_label="compatibility family_id",
        staged=compatibility.family_id,
        legacy_label="compatibility family manifest family_id",
        legacy=legacy_header.family_id,
    )
    _require_match(
        staged_label="pack grid",
        staged=f"{pack.grid.tile_width}x{pack.grid.tile_height}",
        legacy_label="compatibility family grid",
        legacy=f"{legacy_header.tile_width}x{legacy_header.tile_height}",
        formatter=str,
    )
    _require_match(
        staged_label="default_variant_id",
        staged=logical_tilesheet.default_variant_id,
        legacy_label="compatibility family default_variant_id",
        legacy=legacy_header.default_variant_id,
    )
    if bridged_variants != legacy_variants:
        raise ValueError(
            f"Staged render variants for logical tilesheet {logical_tilesheet.id!r} do not match compatibility family "
            f"variants in {compatibility_root / 'family.json'}"
        )

    bridged_title = _resolve_optional_override(
        staged_label="logical tilesheet title",
        staged=logical_tilesheet.title,
        legacy_label="compatibility family title",
        legacy=legacy_header.title,
    )
    bridged_notes = _resolve_bridged_notes(
        logical_tilesheet_notes=logical_tilesheet.notes,
        legacy_notes=legacy_header.notes,
    )
    bridged_render_step_width = _resolve_optional_override(
        staged_label="render_step_width",
        staged=compatibility.render_step_width,
        legacy_label="compatibility family render_step_width",
        legacy=legacy_header.render_step_width,
    )
    bridged_render_step_height = _resolve_optional_override(
        staged_label="render_step_height",
        staged=compatibility.render_step_height,
        legacy_label="compatibility family render_step_height",
        legacy=legacy_header.render_step_height,
    )
    bridged_siblings_share_semantics = _resolve_optional_override(
        staged_label="siblings_share_semantics",
        staged=compatibility.siblings_share_semantics,
        legacy_label="compatibility family siblings_share_semantics",
        legacy=legacy_header.siblings_share_semantics,
    )

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
            title=bridged_title,
            tile_width=pack.grid.tile_width,
            tile_height=pack.grid.tile_height,
            render_step_width=bridged_render_step_width,
            render_step_height=bridged_render_step_height,
            siblings_share_semantics=bridged_siblings_share_semantics,
            notes=bridged_notes,
            default_variant_id=logical_tilesheet.default_variant_id,
        ),
        variants=bridged_variants,
        compatibility_paths=compatibility.paths,
        source_layout=source_layout,
    )


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
    )


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
