from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

from PIL import Image

from reference_grid import (
    GridTransform,
    build_tile_grid,
    compute_extraction,
    extract_crop,
)
from tile_families import TileFamily


RGBA = tuple[int, int, int, int]


class TileMatchMetadata(TypedDict):
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: list[str]


class TileMatchCandidate(TypedDict):
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: list[str]
    score: float
    pixel_match_ratio: float
    mask_match_ratio: float
    fill_similarity: float
    edge_match_ratio: float


class ReferenceCellMatch(TypedDict):
    col: int
    row: int
    status: str
    exact_matches: list[TileMatchMetadata]
    candidates: list[TileMatchCandidate]


class MatchSummary(TypedDict):
    columns: int
    rows: int
    background_cells: int
    exact_match_cells: int
    candidate_cells: int
    no_match_cells: int


class MatchReport(TypedDict):
    reference_image: str
    family_path: str
    variant_id: str
    grid: dict[str, int]
    summary: MatchSummary
    cells: list[ReferenceCellMatch]


@dataclass(frozen=True)
class SourceTile:
    sheet_col: int
    sheet_row: int
    tile_id: str | None
    aliases: tuple[str, ...]
    image: Image.Image


@dataclass(frozen=True)
class SimilarityScore:
    score: float
    pixel_match_ratio: float
    mask_match_ratio: float
    fill_similarity: float
    edge_match_ratio: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Match reference-sheet cells against a family variant source sheet once the "
            "render-grid transform is known."
        )
    )
    parser.add_argument("--image", type=Path, required=True, help="Reference image to analyse.")
    parser.add_argument("--family-path", type=Path, required=True, help="Tile family package directory.")
    parser.add_argument("--variant-id", default=None, help="Family variant to match against.")
    parser.add_argument("--origin-x", type=int, required=True, help="Render-space x origin of the tile grid.")
    parser.add_argument("--origin-y", type=int, required=True, help="Render-space y origin of the tile grid.")
    parser.add_argument("--cell-size", type=int, required=True, help="Render-space tile size in pixels.")
    parser.add_argument("--tile-size", type=int, default=8, help="Base tile size to recover. Defaults to 8.")
    parser.add_argument("--cols", type=int, help="Optional column count override.")
    parser.add_argument("--rows", type=int, help="Optional row count override.")
    parser.add_argument("--max-candidates", type=int, default=5, help="How many fallback candidates to keep.")
    parser.add_argument(
        "--candidate-threshold",
        type=float,
        default=0.75,
        help="Minimum similarity score to treat a non-exact cell as a candidate match.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Defaults to stdout only.")
    return parser.parse_args()


def load_source_tiles(family_path: Path, variant_id: str | None) -> tuple[TileFamily, str, list[SourceTile]]:
    family = TileFamily.load(family_path)
    resolved_variant_id = variant_id or family.default_variant_id
    variant = family.variant(resolved_variant_id)
    sheet = Image.open(variant.sheet_path).convert("RGBA")
    tiles: list[SourceTile] = []
    for sheet_row in range(sheet.height // family.tile_height):
        for sheet_col in range(sheet.width // family.tile_width):
            left = sheet_col * family.tile_width
            top = sheet_row * family.tile_height
            tile_image = sheet.crop((left, top, left + family.tile_width, top + family.tile_height))
            tile_record = family.tile_at_sheet_cell(sheet_col=sheet_col, sheet_row=sheet_row)
            tile_id = tile_record.id if tile_record is not None else None
            aliases = tuple(sorted(family.aliases_by_tile.get(tile_id, ()))) if tile_id is not None else ()
            tiles.append(
                SourceTile(
                    sheet_col=sheet_col,
                    sheet_row=sheet_row,
                    tile_id=tile_id,
                    aliases=aliases,
                    image=tile_image,
                )
            )
    return family, resolved_variant_id, tiles


def is_background_tile(image: Image.Image, background: RGBA) -> bool:
    rgba = image.convert("RGBA")
    return all(cast(RGBA, rgba.getpixel((x, y))) == background for y in range(rgba.height) for x in range(rgba.width))


def _edge_signature(image: Image.Image, background: RGBA) -> tuple[bool, bool, bool, bool]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    left = any(cast(RGBA, rgba.getpixel((0, y))) != background for y in range(height))
    right = any(cast(RGBA, rgba.getpixel((width - 1, y))) != background for y in range(height))
    top = any(cast(RGBA, rgba.getpixel((x, 0))) != background for x in range(width))
    bottom = any(cast(RGBA, rgba.getpixel((x, height - 1))) != background for x in range(width))
    return (left, top, right, bottom)


def score_tile_similarity(reference_tile: Image.Image, source_tile: Image.Image, background: RGBA) -> SimilarityScore:
    reference_rgba = reference_tile.convert("RGBA")
    source_rgba = source_tile.convert("RGBA")
    if reference_rgba.size != source_rgba.size:
        raise ValueError("reference and source tiles must share a size")

    total = reference_rgba.width * reference_rgba.height
    reference_pixels = [
        cast(RGBA, reference_rgba.getpixel((x, y)))
        for y in range(reference_rgba.height)
        for x in range(reference_rgba.width)
    ]
    source_pixels = [
        cast(RGBA, source_rgba.getpixel((x, y)))
        for y in range(source_rgba.height)
        for x in range(source_rgba.width)
    ]
    pixel_matches = sum(1 for left, right in zip(reference_pixels, source_pixels) if left == right)
    reference_mask = [px != background for px in reference_pixels]
    source_mask = [px != background for px in source_pixels]
    mask_matches = sum(1 for left, right in zip(reference_mask, source_mask) if left == right)
    reference_fill = sum(1 for value in reference_mask if value)
    source_fill = sum(1 for value in source_mask if value)
    fill_similarity = 1.0 - (abs(reference_fill - source_fill) / total)
    reference_edges = _edge_signature(reference_rgba, background)
    source_edges = _edge_signature(source_rgba, background)
    edge_matches = sum(1 for left, right in zip(reference_edges, source_edges) if left == right)

    pixel_ratio = pixel_matches / total
    mask_ratio = mask_matches / total
    edge_ratio = edge_matches / 4
    score = (0.55 * mask_ratio) + (0.3 * pixel_ratio) + (0.1 * edge_ratio) + (0.05 * fill_similarity)
    return SimilarityScore(
        score=score,
        pixel_match_ratio=pixel_ratio,
        mask_match_ratio=mask_ratio,
        fill_similarity=fill_similarity,
        edge_match_ratio=edge_ratio,
    )


def exact_matches_for_tile(reference_tile: Image.Image, source_tiles: list[SourceTile]) -> list[SourceTile]:
    reference_bytes = reference_tile.convert("RGBA").tobytes()
    return [tile for tile in source_tiles if tile.image.convert("RGBA").tobytes() == reference_bytes]


def candidate_matches_for_tile(
    reference_tile: Image.Image,
    source_tiles: list[SourceTile],
    background: RGBA,
    *,
    max_candidates: int,
) -> list[tuple[SourceTile, SimilarityScore]]:
    ranked = [
        (tile, score_tile_similarity(reference_tile, tile.image, background))
        for tile in source_tiles
        if not is_background_tile(tile.image, background)
    ]
    ranked.sort(
        key=lambda item: (
            item[1].score,
            item[1].pixel_match_ratio,
            item[1].mask_match_ratio,
            item[1].edge_match_ratio,
        ),
        reverse=True,
    )
    return ranked[:max_candidates]


def _match_metadata(tile: SourceTile) -> TileMatchMetadata:
    return {
        "sheet_col": tile.sheet_col,
        "sheet_row": tile.sheet_row,
        "tile_id": tile.tile_id,
        "aliases": list(tile.aliases),
    }


def _candidate_payload(tile: SourceTile, score: SimilarityScore) -> TileMatchCandidate:
    return {
        "sheet_col": tile.sheet_col,
        "sheet_row": tile.sheet_row,
        "tile_id": tile.tile_id,
        "aliases": list(tile.aliases),
        "score": round(score.score, 4),
        "pixel_match_ratio": round(score.pixel_match_ratio, 4),
        "mask_match_ratio": round(score.mask_match_ratio, 4),
        "fill_similarity": round(score.fill_similarity, 4),
        "edge_match_ratio": round(score.edge_match_ratio, 4),
    }


def match_reference_tiles(
    *,
    reference_image: Image.Image,
    source_tiles: list[SourceTile],
    background: RGBA,
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    max_candidates: int = 5,
    candidate_threshold: float = 0.75,
) -> tuple[list[ReferenceCellMatch], MatchSummary]:
    extraction = compute_extraction(reference_image.size, transform, cols=cols, rows=rows)
    crop = extract_crop(reference_image, extraction)
    tile_grid = build_tile_grid(crop, extraction)

    cells: list[ReferenceCellMatch] = []
    background_cells = 0
    exact_cells = 0
    candidate_cells = 0
    no_match_cells = 0

    for row_index, row_tiles in enumerate(tile_grid):
        for col_index, reference_tile in enumerate(row_tiles):
            if is_background_tile(reference_tile, background):
                background_cells += 1
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "background",
                        "exact_matches": [],
                        "candidates": [],
                    }
                )
                continue

            exact = exact_matches_for_tile(reference_tile, source_tiles)
            if exact:
                exact_cells += 1
                cells.append(
                    {
                        "col": col_index,
                        "row": row_index,
                        "status": "exact",
                        "exact_matches": [_match_metadata(tile) for tile in exact],
                        "candidates": [],
                    }
                )
                continue

            candidates = candidate_matches_for_tile(
                reference_tile,
                source_tiles,
                background,
                max_candidates=max_candidates,
            )
            if candidates and candidates[0][1].score >= candidate_threshold:
                candidate_cells += 1
                status = "candidate"
            else:
                no_match_cells += 1
                status = "no_match"

            cells.append(
                {
                    "col": col_index,
                    "row": row_index,
                    "status": status,
                    "exact_matches": [],
                    "candidates": [_candidate_payload(tile, score) for tile, score in candidates],
                }
            )

    summary: MatchSummary = {
        "columns": extraction.columns,
        "rows": extraction.rows,
        "background_cells": background_cells,
        "exact_match_cells": exact_cells,
        "candidate_cells": candidate_cells,
        "no_match_cells": no_match_cells,
    }
    return cells, summary


def build_match_report(
    *,
    image_path: Path,
    family_path: Path,
    variant_id: str | None,
    transform: GridTransform,
    cols: int | None = None,
    rows: int | None = None,
    max_candidates: int = 5,
    candidate_threshold: float = 0.75,
) -> MatchReport:
    reference_image = Image.open(image_path).convert("RGBA")
    background = cast(RGBA, reference_image.getpixel((0, 0)))
    _, resolved_variant_id, source_tiles = load_source_tiles(family_path, variant_id)
    cells, summary = match_reference_tiles(
        reference_image=reference_image,
        source_tiles=source_tiles,
        background=background,
        transform=transform,
        cols=cols,
        rows=rows,
        max_candidates=max_candidates,
        candidate_threshold=candidate_threshold,
    )
    return {
        "reference_image": str(image_path),
        "family_path": str(family_path),
        "variant_id": resolved_variant_id,
        "grid": {
            "origin_x": transform.origin_x,
            "origin_y": transform.origin_y,
            "cell_size": transform.cell_size,
            "tile_size": transform.tile_size,
        },
        "summary": summary,
        "cells": cells,
    }


def main() -> int:
    args = parse_args()
    report = build_match_report(
        image_path=args.image,
        family_path=args.family_path,
        variant_id=args.variant_id,
        transform=GridTransform(
            origin_x=args.origin_x,
            origin_y=args.origin_y,
            cell_size=args.cell_size,
            tile_size=args.tile_size,
        ),
        cols=args.cols,
        rows=args.rows,
        max_candidates=args.max_candidates,
        candidate_threshold=args.candidate_threshold,
    )
    payload = json.dumps(report, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
