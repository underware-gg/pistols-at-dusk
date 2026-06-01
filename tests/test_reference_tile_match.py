from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import json
import argparse
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import reference_grid
import reference_tile_match


class ReferenceTileMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.background = (36, 25, 42, 255)

    def _tile(self, pixels: list[tuple[int, int, tuple[int, int, int, int]]]) -> Image.Image:
        image = Image.new("RGBA", (8, 8), self.background)
        for x, y, colour in pixels:
            image.putpixel((x, y), colour)
        return image

    def _render_reference(self, tile: Image.Image) -> Image.Image:
        return reference_grid.resize_nearest(tile, (32, 32))

    def _render_reference_row(self, tiles: list[Image.Image]) -> Image.Image:
        width = 32 * len(tiles)
        canvas = Image.new("RGBA", (width, 32), self.background)
        for index, tile in enumerate(tiles):
            canvas.alpha_composite(self._render_reference(tile), (32 * index, 0))
        return canvas

    def _source_tile(
        self,
        sheet_col: int,
        sheet_row: int,
        tile_id: str | None,
        aliases: tuple[str, ...],
        image: Image.Image,
        *,
        source_id: str = "test.source",
        family_id: str = "test.family",
        variant_id: str = "base",
        colorway: str | None = None,
    ) -> reference_tile_match.SourceTile:
        return reference_tile_match.SourceTile(
            sheet_col=sheet_col,
            sheet_row=sheet_row,
            tile_id=tile_id,
            aliases=aliases,
            image=image,
            source_id=source_id,
            family_id=family_id,
            variant_id=variant_id,
            colorway=colorway,
        )

    def _loaded_source(
        self,
        *,
        source_id: str = "test.source",
        family_path: Path = ROOT,
        family_id: str = "test.family",
        variant_id: str = "base",
        colorway: str | None = None,
        palette_family: str | None = None,
        background_mode: str | None = None,
        available_variants: tuple[reference_tile_match.MatchReportSourceVariant, ...] = (),
        reference_boxes: tuple[tuple[int, int, int, int], ...] = (),
    ) -> reference_tile_match.LoadedSourceSpec:
        return reference_tile_match.LoadedSourceSpec(
            source_id=source_id,
            family_path=family_path,
            family_id=family_id,
            variant_id=variant_id,
            colorway=colorway,
            palette_family=palette_family,
            background_mode=background_mode,
            available_variants=available_variants,
            reference_boxes=reference_boxes,
        )

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _make_colourway_family_dir(self, root: Path) -> Path:
        family_dir = root / "family"
        family_dir.mkdir()

        def write_sheet(name: str, foreground: tuple[int, int, int, int]) -> None:
            image = Image.new("RGBA", (8, 8), (10, 10, 10, 255))
            for x, y in ((0, 7), (1, 7), (0, 6)):
                image.putpixel((x, y), foreground)
            image.save(family_dir / name)

        write_sheet("colored.png", (0, 255, 255, 255))
        write_sheet("green.png", (0, 255, 0, 255))
        write_sheet("orange.png", (255, 180, 0, 255))

        self._write_json(
            family_dir / "family.json",
            {
                "family_id": "test.family",
                "grid": {"tile_width": 8, "tile_height": 8},
                "default_variant_id": "2bit_colored_bg",
                "variants": [
                    {
                        "variant_id": "2bit_colored_bg",
                        "sheet": "colored.png",
                        "transparent": "none",
                        "palette_family": "minimal8-2bit",
                        "colorway": "colored",
                        "background_mode": "colored_bg",
                    },
                    {
                        "variant_id": "2bit_colored_bg_green",
                        "sheet": "green.png",
                        "transparent": "none",
                        "palette_family": "minimal8-2bit",
                        "colorway": "green",
                        "background_mode": "colored_bg",
                    },
                    {
                        "variant_id": "2bit_colored_bg_orange",
                        "sheet": "orange.png",
                        "transparent": "none",
                        "palette_family": "minimal8-2bit",
                        "colorway": "orange",
                        "background_mode": "colored_bg",
                    },
                ],
                "ingestion_spec": "ingestion.json",
            },
        )
        self._write_json(
            family_dir / "ingestion.json",
            {
                "sheet_bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                "regions": [
                    {
                        "id": "sheet.region",
                        "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                        "label": "All sheet content",
                    }
                ],
                "clusters": [
                    {
                        "id": "sheet.region.cluster_01",
                        "source_region_id": "sheet.region",
                        "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                        "label": "Only cluster",
                    }
                ],
                "ignore_regions": [],
                "collections": [],
            },
        )
        self._write_json(
            family_dir / "clusters.json",
            [
                {
                    "id": "cluster.valid",
                    "scope": "family",
                    "members": ["test.family:all:0,0"],
                }
            ],
        )
        self._write_json(
            family_dir / "tiles.json",
            [
                {
                    "id": "test.family:all:0,0",
                    "sheet_col": 0,
                    "sheet_row": 0,
                    "layer": "map",
                    "category": "tile",
                    "transparent": False,
                    "cluster_ids": ["cluster.valid"],
                    "tags": [],
                    "source_group": "test.group",
                    "meaning": "Test tile.",
                    "meaning_confidence": "confirmed",
                }
            ],
        )
        self._write_json(family_dir / "aliases.json", {"sample.alias": "test.family:all:0,0"})
        return family_dir

    def test_match_reference_tiles_reports_exact_duplicates(self) -> None:
        tile = self._tile(
            [
                (0, 7, (255, 0, 0, 255)),
                (1, 7, (255, 0, 0, 255)),
                (0, 6, (255, 0, 0, 255)),
            ]
        )
        source_tiles = [
            self._source_tile(1, 2, "tile.a", ("alias.a",), tile, source_id="source.a"),
            self._source_tile(3, 4, "tile.b", ("alias.b",), tile.copy(), source_id="source.b"),
        ]
        loaded_sources = [
            self._loaded_source(source_id="source.a"),
            self._loaded_source(source_id="source.b"),
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(tile),
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(cells[0]["status"], "exact")
        self.assertEqual(
            {(item["sheet_col"], item["sheet_row"]) for item in cells[0]["exact_matches"]},
            {(1, 2), (3, 4)},
        )

    def test_match_reference_tiles_reports_copy_pasteable_variant_refs(self) -> None:
        tile = self._tile(
            [
                (0, 7, (255, 0, 0, 255)),
                (1, 7, (255, 0, 0, 255)),
                (0, 6, (255, 0, 0, 255)),
            ]
        )
        source_tiles = [
            self._source_tile(
                1,
                2,
                "test.family:cluster:1,2",
                ("alias.a",),
                tile,
                family_id="test.family",
                variant_id="green_bg",
                colorway="green",
            )
        ]
        loaded_sources = [
            self._loaded_source(
                family_id="test.family",
                variant_id="green_bg",
                colorway="green",
            )
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(tile),
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        exact = cells[0]["exact_matches"][0]
        self.assertEqual(exact["colorway"], "green")
        self.assertEqual(exact["physical_ref"], "test.family:1,2")
        self.assertEqual(exact["variant_ref"], "test.family@green_bg:1,2")
        self.assertEqual(
            exact["semantic_variant_ref"],
            "test.family@green_bg:test.family:cluster:1,2",
        )

    def test_match_reference_tiles_respects_non_integer_content_box(self) -> None:
        tile = self._tile(
            [
                (0, 7, (255, 0, 0, 255)),
                (1, 7, (255, 0, 0, 255)),
                (0, 6, (255, 0, 0, 255)),
            ]
        )
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]
        reference_tile = reference_grid.resize_nearest(tile, (39, 39))

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_tile,
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(
                origin_x=0,
                origin_y=0,
                cell_size=39,
                content_box=(0, 1, 7, 8),
            ),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(cells[0]["status"], "exact")

    def test_match_reference_tiles_uses_structural_candidates_when_exact_match_fails(self) -> None:
        reference_tile = self._tile(
            [
                (0, 7, (255, 0, 0, 255)),
                (1, 7, (255, 0, 0, 255)),
                (0, 6, (255, 0, 0, 255)),
            ]
        )
        source_tile = self._tile(
            [
                (0, 7, (0, 255, 0, 255)),
                (1, 7, (0, 255, 0, 255)),
                (0, 6, (0, 255, 0, 255)),
            ]
        )
        source_tiles = [self._source_tile(5, 6, "tile.c", (), source_tile)]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.8,
        )

        self.assertEqual(summary["high_confidence_cells"], 1)
        self.assertEqual(cells[0]["status"], "high_confidence")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "tile.c")
        self.assertLess(cells[0]["candidates"][0]["pixel_match_ratio"], 1.0)
        self.assertEqual(cells[0]["candidates"][0]["mask_match_ratio"], 1.0)
        self.assertEqual(cells[0]["candidates"][0]["mask_iou"], 1.0)
        self.assertEqual(cells[0]["candidates"][0]["chamfer_similarity"], 1.0)
        self.assertEqual(cells[0]["candidates"][0]["projection_similarity"], 1.0)

    def test_match_reference_tiles_prefers_shape_when_reference_has_resampling_bleed(self) -> None:
        reference_tile = self._tile(
            [
                (0, 7, (255, 120, 64, 255)),
                (1, 7, (255, 120, 64, 255)),
                (0, 6, (255, 120, 64, 255)),
                # Slight off-background bleed that should not outweigh the real footprint.
                (1, 6, (44, 31, 47, 255)),
                (2, 7, (43, 29, 45, 255)),
            ]
        )
        matching_tile = self._tile(
            [
                (0, 7, (0, 255, 0, 255)),
                (1, 7, (0, 255, 0, 255)),
                (0, 6, (0, 255, 0, 255)),
            ]
        )
        wrong_shape = self._tile(
            [
                (1, 7, (0, 0, 255, 255)),
                (2, 7, (0, 0, 255, 255)),
                (2, 6, (0, 0, 255, 255)),
            ]
        )
        source_tiles = [
            self._source_tile(2, 3, "tile.match", (), matching_tile, source_id="match.source"),
            self._source_tile(4, 5, "tile.wrong", (), wrong_shape, source_id="wrong.source"),
        ]
        loaded_sources = [
            self._loaded_source(source_id="match.source"),
            self._loaded_source(source_id="wrong.source"),
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.7,
        )

        self.assertEqual(summary["high_confidence_cells"], 1)
        self.assertEqual(cells[0]["status"], "high_confidence")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "tile.match")
        self.assertGreater(
            cells[0]["candidates"][0]["chamfer_similarity"],
            cells[0]["candidates"][1]["chamfer_similarity"],
        )
        self.assertGreater(
            cells[0]["candidates"][0]["projection_similarity"],
            cells[0]["candidates"][1]["projection_similarity"],
        )

    def test_match_reference_tiles_adapts_source_masks_when_reference_bg_differs_from_source_bg(self) -> None:
        reference_background = (33, 8, 32, 255)
        source_background = self.background

        reference_tile = Image.new("RGBA", (8, 8), reference_background)
        reference_tile.putpixel((0, 7), (255, 120, 64, 255))
        reference_tile.putpixel((1, 7), (255, 120, 64, 255))
        reference_tile.putpixel((0, 6), (255, 120, 64, 255))

        matching_tile = Image.new("RGBA", (8, 8), source_background)
        matching_tile.putpixel((0, 7), (0, 255, 0, 255))
        matching_tile.putpixel((1, 7), (0, 255, 0, 255))
        matching_tile.putpixel((0, 6), (0, 255, 0, 255))

        dense_tile = Image.new("RGBA", (8, 8), source_background)
        for x in range(4):
            for y in range(4, 8):
                dense_tile.putpixel((x, y), (0, 0, 255, 255))

        source_tiles = [
            self._source_tile(1, 1, "dense.tile", (), dense_tile),
            self._source_tile(2, 2, "matching.tile", (), matching_tile),
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=reference_background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.7,
        )

        self.assertEqual(summary["high_confidence_cells"], 1)
        self.assertEqual(cells[0]["status"], "high_confidence")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "matching.tile")
        self.assertLess(
            cells[0]["candidates"][1]["mask_iou"],
            cells[0]["candidates"][0]["mask_iou"],
        )

    def test_match_reference_tiles_marks_weak_candidates_as_best_guess(self) -> None:
        reference_tile = self._tile([(0, 7, (255, 0, 0, 255)), (0, 6, (255, 0, 0, 255))])
        source_tile = self._tile([(7, 0, (0, 255, 0, 255)), (7, 1, (0, 255, 0, 255))])
        source_tiles = [self._source_tile(7, 8, "tile.d", (), source_tile)]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.9,
        )

        self.assertEqual(summary["best_guess_cells"], 1)
        self.assertEqual(cells[0]["status"], "best_guess")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "tile.d")

    def test_match_reference_tiles_filters_candidates_by_source_reference_boxes(self) -> None:
        left_tile = self._tile([(0, 7, (255, 0, 0, 255)), (1, 7, (255, 0, 0, 255))])
        right_tile = self._tile([(7, 7, (0, 255, 0, 255)), (6, 7, (0, 255, 0, 255))])
        source_tiles = [
            self._source_tile(1, 1, "left.tile", (), left_tile, source_id="left", family_id="left", variant_id="v1"),
            self._source_tile(2, 2, "right.tile", (), right_tile, source_id="right", family_id="right", variant_id="v1"),
        ]
        loaded_sources = [
            self._loaded_source(source_id="left", family_id="left", variant_id="v1", reference_boxes=((0, 0, 32, 32),)),
            self._loaded_source(source_id="right", family_id="right", variant_id="v1", reference_boxes=((32, 0, 64, 32),)),
        ]
        reference_image = self._render_reference_row([left_tile, right_tile])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            cols=2,
            rows=1,
            span_box=(0, 0, 64, 32),
        )

        self.assertEqual(summary["exact_match_cells"], 2)
        self.assertEqual(cells[0]["exact_matches"][0]["source_id"], "left")
        self.assertEqual(cells[1]["exact_matches"][0]["source_id"], "right")

    def test_match_reference_tiles_prefers_boxed_sources_over_global_sources_inside_owned_zone(self) -> None:
        portrait_tile = self._tile([(0, 7, (255, 0, 0, 255)), (1, 7, (255, 0, 0, 255))])
        global_tile = self._tile([(7, 7, (0, 255, 0, 255)), (6, 7, (0, 255, 0, 255))])
        source_tiles = [
            self._source_tile(1, 1, "global.tile", (), global_tile, source_id="base", family_id="base", variant_id="v1"),
            self._source_tile(2, 2, "portrait.tile", (), portrait_tile, source_id="characters", family_id="characters", variant_id="v1"),
        ]
        loaded_sources = [
            self._loaded_source(source_id="base", family_id="base", variant_id="v1"),
            self._loaded_source(
                source_id="characters",
                family_id="characters",
                variant_id="v1",
                reference_boxes=((0, 0, 32, 32),),
            ),
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(portrait_tile),
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(cells[0]["exact_matches"][0]["source_id"], "characters")

    def test_match_reference_tiles_uses_global_sources_outside_boxed_regions(self) -> None:
        portrait_tile = self._tile([(0, 7, (255, 0, 0, 255)), (1, 7, (255, 0, 0, 255))])
        global_tile = self._tile([(7, 7, (0, 255, 0, 255)), (6, 7, (0, 255, 0, 255))])
        source_tiles = [
            self._source_tile(1, 1, "global.tile", (), global_tile, source_id="base", family_id="base", variant_id="v1"),
            self._source_tile(2, 2, "portrait.tile", (), portrait_tile, source_id="characters", family_id="characters", variant_id="v1"),
        ]
        loaded_sources = [
            self._loaded_source(source_id="base", family_id="base", variant_id="v1"),
            self._loaded_source(
                source_id="characters",
                family_id="characters",
                variant_id="v1",
                reference_boxes=((0, 0, 32, 32),),
            ),
        ]
        reference_image = self._render_reference_row([portrait_tile, global_tile])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            cols=2,
            rows=1,
            span_box=(0, 0, 64, 32),
        )

        self.assertEqual(summary["exact_match_cells"], 2)
        self.assertEqual(cells[0]["exact_matches"][0]["source_id"], "characters")
        self.assertEqual(cells[1]["exact_matches"][0]["source_id"], "base")

    def test_match_reference_tiles_marks_cells_outside_boxed_regions_as_unresolved_without_global_sources(self) -> None:
        portrait_tile = self._tile([(0, 7, (255, 0, 0, 255)), (1, 7, (255, 0, 0, 255))])
        source_tiles = [
            self._source_tile(
                2,
                2,
                "portrait.tile",
                (),
                portrait_tile,
                source_id="characters",
                family_id="characters",
                variant_id="v1",
            )
        ]
        loaded_sources = [
            self._loaded_source(
                source_id="characters",
                family_id="characters",
                variant_id="v1",
                reference_boxes=((0, 0, 32, 32),),
            )
        ]
        reference_image = self._render_reference_row([portrait_tile, portrait_tile])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=loaded_sources,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            cols=2,
            rows=1,
            span_box=(0, 0, 64, 32),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(summary["unresolved_cells"], 1)
        self.assertEqual(cells[0]["exact_matches"][0]["source_id"], "characters")
        self.assertEqual(cells[1]["status"], "unresolved")

    def test_candidate_matches_for_tile_prefers_trimmed_logical_match_on_temple_reference(self) -> None:
        config_path = ROOT / "prototypes/minimal8-harness/reference-transforms/reference-polychrome-temple-courtyard.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        image_path = (config_path.parent / cast(str, config["image"])).resolve()
        family_path = (config_path.parent / cast(str, config["family_path"])).resolve()
        grid = cast(dict[str, object], config["grid"])
        content_box = cast(tuple[int, int, int, int], tuple(cast(list[int], grid["content_box"])))
        span_box = cast(tuple[int, int, int, int], tuple(cast(list[int], grid["span_box"])))
        relevant_boxes = tuple(
            cast(tuple[int, int, int, int], tuple(box))
            for box in cast(list[list[int]], config["relevant_boxes"])
        )
        excluded_boxes = tuple(
            cast(tuple[int, int, int, int], tuple(box))
            for box in cast(list[list[int]], config["excluded_boxes"])
        )

        image = Image.open(image_path).convert("RGBA")
        background = cast(tuple[int, int, int, int], image.getpixel((0, 0)))
        prepared = reference_grid.prepare_reference_grid(
            image,
            transform=reference_grid.GridTransform(
                origin_x=0.0,
                origin_y=0.0,
                cell_size=8.0,
                tile_size=cast(int, grid["tile_size"]),
                content_box=content_box,
            ),
            cols=cast(int, grid["cols"]),
            rows=cast(int, grid["rows"]),
            span_box=span_box,
            relevant_boxes=relevant_boxes,
            excluded_boxes=excluded_boxes,
            exclude_partial_edge_cells=False,
            background=background,
        )
        normalized_cell_size = reference_grid.resolve_normalized_cell_size(
            config.get("normalize_cell_size"),
            prepared.extraction,
        )
        assert normalized_cell_size is not None
        prepared = reference_grid.normalize_prepared_reference_grid(prepared, target_cell_size=normalized_cell_size)
        cell = reference_grid.build_cell_crops(prepared.crop, prepared.extraction)[9][12]  # C13R10

        _, _, _, source_tiles = reference_tile_match.load_source_tiles(family_path, cast(str, config["variant_id"]))
        active_source_tiles = reference_tile_match.render_source_tiles(source_tiles, cell_size=normalized_cell_size)
        candidates = reference_tile_match.candidate_matches_for_tile(
            cell,
            active_source_tiles,
            background,
            max_candidates=5,
            logical_tile_size=8,
        )

        self.assertEqual(candidates[0][0].tile_id, "minimal8:terrain:2,2")
        self.assertEqual(candidates[0][1].mask_iou, 0.0)
        self.assertGreater(candidates[0][1].effective_mask_iou, candidates[0][1].mask_iou)
        self.assertTrue(candidates[0][1].mask_iou_rescue_applied)
        self.assertEqual(candidates[0][1].trimmed_logical_iou, 1.0)
        self.assertGreater(candidates[0][1].score, candidates[1][1].score)

    def test_load_source_tiles_filters_to_authored_source_layout_surface(self) -> None:
        family_path = ROOT / "prototypes/minimal8-harness/tile-families/minimal8"
        _, _, _, source_tiles = reference_tile_match.load_source_tiles(family_path, "2bit_colored_bg")

        coords = {(tile.sheet_col, tile.sheet_row) for tile in source_tiles}
        self.assertNotIn((0, 0), coords)
        self.assertIn((21, 4), coords)

    def test_load_source_tiles_can_filter_to_named_source_regions(self) -> None:
        family_path = ROOT / "prototypes/minimal8-harness/tile-families/minimal8"
        _, _, _, source_tiles = reference_tile_match.load_source_tiles(
            family_path,
            "2bit_colored_bg",
            source_region_ids=("ui.column_4",),
        )

        coords = {(tile.sheet_col, tile.sheet_row) for tile in source_tiles}
        self.assertIn((55, 4), coords)
        self.assertNotIn((21, 4), coords)

    def test_load_source_tiles_rejects_unknown_source_region_ids(self) -> None:
        family_path = ROOT / "prototypes/minimal8-harness/tile-families/minimal8"

        with self.assertRaisesRegex(ValueError, "Unknown source-region ids"):
            reference_tile_match.load_source_tiles(
                family_path,
                "2bit_colored_bg",
                source_region_ids=("unknown.region",),
            )

    def test_match_reference_tiles_marks_missing_guess_as_unresolved(self) -> None:
        reference_tile = self._tile([(0, 7, (255, 0, 0, 255)), (0, 6, (255, 0, 0, 255))])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=[],
            loaded_sources=(),
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["unresolved_cells"], 1)
        self.assertEqual(cells[0]["status"], "unresolved")
        self.assertEqual(cells[0]["candidates"], [])

    def test_match_reference_tiles_marks_blank_cells_as_blank(self) -> None:
        blank_reference = Image.new("RGBA", (32, 32), self.background)

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=blank_reference,
            source_tiles=[],
            loaded_sources=(),
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["blank_cells"], 1)
        self.assertEqual(summary["unresolved_cells"], 0)
        self.assertEqual(cells[0]["status"], "blank")
        self.assertEqual(cells[0]["review"].get("status"), "unreviewed")

    def test_match_reference_tiles_marks_excluded_cells(self) -> None:
        tile = self._tile([(0, 7, (255, 0, 0, 255))])
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(tile),
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            excluded_boxes=((0, 0, 32, 32),),
        )

        self.assertEqual(summary["exact_match_cells"], 0)
        self.assertEqual(cells[0]["status"], "excluded")

    def test_match_reference_tiles_can_drop_partial_edge_cells(self) -> None:
        tile = self._tile([(0, 7, (255, 0, 0, 255))])
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]
        reference_image = Image.new("RGBA", (47, 32), self.background)
        reference_image.alpha_composite(self._render_reference(tile), (0, 0))

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            rows=1,
            exclude_partial_edge_cells=True,
        )

        self.assertEqual(summary["columns"], 1)
        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(len(cells), 1)

    def test_match_reference_tiles_supports_normalized_render_scale(self) -> None:
        tile = self._tile([(0, 7, (255, 0, 0, 255)), (1, 7, (255, 0, 0, 255))])
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]
        reference_image = reference_grid.resize_nearest(tile, (24, 24))

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=24),
            cols=1,
            rows=1,
            span_box=(0, 0, 24, 24),
            normalize_cell_size=24,
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(cells[0]["status"], "exact")

    def test_match_reference_tiles_trims_to_relevant_boxes_and_skips_gaps(self) -> None:
        tile = self._tile([(0, 7, (255, 0, 0, 255))])
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]
        reference_image = self._render_reference_row([tile, tile, tile])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            cols=3,
            rows=1,
            relevant_boxes=((0, 0, 32, 32), (64, 0, 96, 32)),
        )

        self.assertEqual(summary["columns"], 3)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["exact_match_cells"], 2)
        self.assertEqual([cell["status"] for cell in cells], ["exact", "excluded", "exact"])

    def test_match_reference_tiles_supports_exact_span_partitioning(self) -> None:
        tile = self._tile([(0, 7, (255, 0, 0, 255))])
        source_tiles = [self._source_tile(1, 2, "tile.a", ("alias.a",), tile)]
        reference_image = self._render_reference_row([tile, tile, tile])

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=reference_image,
            source_tiles=source_tiles,
            loaded_sources=[self._loaded_source()],
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            cols=3,
            rows=1,
            span_box=(0, 0, 96, 32),
        )

        self.assertEqual(summary["columns"], 3)
        self.assertEqual(summary["exact_match_cells"], 3)
        self.assertEqual([cell["status"] for cell in cells], ["exact", "exact", "exact"])

    def test_resolve_match_run_settings_loads_reference_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            family_path = root / "family"
            image_path.write_bytes(b"png")
            family_path.mkdir()
            config_path = root / "solve.json"
            config_path.write_text(
                json.dumps(
                    {
                        "image": "reference.png",
                        "family_path": "family",
                        "variant_id": "2bit_colored_bg",
                        "grid": {
                            "tile_size": 8,
                            "cols": 39,
                            "rows": 26,
                        "span_box": [0, 22, 1248, 854],
                        "content_box": [0, 1, 7, 8],
                    },
                        "relevant_boxes": [[0, 22, 1248, 854]],
                        "excluded_boxes": [[0, 0, 1248, 22]],
                        "exclude_partial_edge_cells": True,
                        "normalize_cell_size": "auto",
                        "candidate_threshold": 0.9,
                        "reviews": {
                            "C5R6": {
                                "status": "confirmed",
                                "selection": {
                                    "kind": "tile",
                                    "tile_id": "minimal8:terrain:11,8",
                                    "variant_id": "2bit_colored_bg_green",
                                },
                                "note": "Reviewed against the 1-bit reference; best match comes from the 2-bit variant.",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = reference_tile_match.resolve_match_run_settings(
                argparse.Namespace(
                    config=config_path,
                    image=None,
                    family_path=None,
                    variant_id=None,
                    origin_x=None,
                    origin_y=None,
                    cell_size=None,
                    span_box=None,
                    tile_size=8,
                    cols=None,
                    rows=None,
                    normalize_cell_size=None,
                    relevant_box=None,
                    content_box=None,
                    exclude_box=None,
                    exclude_partial_edge_cells=False,
                    max_candidates=3,
                    candidate_threshold=None,
                    output=None,
                )
            )

            self.assertEqual(settings.image_path, image_path)
            self.assertEqual(
                settings.source_specs,
                (reference_tile_match.MatchSourceSpec(family_path=family_path, variant_id="2bit_colored_bg"),),
            )
            self.assertEqual(settings.transform.origin_y, 22.0)
            self.assertEqual(settings.columns, 39)
            self.assertEqual(settings.rows, 26)
            self.assertEqual(settings.span_box, (0, 22, 1248, 854))
            self.assertEqual(settings.transform.content_box, (0, 1, 7, 8))
            self.assertEqual(settings.relevant_boxes, ((0, 22, 1248, 854),))
            self.assertEqual(settings.excluded_boxes, ((0, 0, 1248, 22),))
            self.assertTrue(settings.exclude_partial_edge_cells)
            self.assertEqual(settings.normalize_cell_size, "auto")
            self.assertEqual(settings.max_candidates, 3)
            self.assertEqual(settings.candidate_threshold, 0.9)
            self.assertEqual(
                settings.review_overrides["C5R6"],
                {
                    "status": "confirmed",
                    "selection": {
                        "kind": "tile",
                        "tile_id": "minimal8:terrain:11,8",
                        "variant_id": "2bit_colored_bg_green",
                    },
                    "note": "Reviewed against the 1-bit reference; best match comes from the 2-bit variant.",
                },
            )

    def test_resolve_match_run_settings_supports_multiple_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            base_family_path = root / "family-base"
            characters_family_path = root / "family-characters"
            image_path.write_bytes(b"png")
            base_family_path.mkdir()
            characters_family_path.mkdir()
            config_path = root / "solve.json"
            config_path.write_text(
                json.dumps(
                    {
                        "image": "reference.png",
                        "sources": [
                            {
                                "source_id": "minimal8.base",
                                "family_path": "family-base",
                                "variant_id": "2bit_colored_bg",
                            },
                            {
                                "source_id": "minimal8.characters",
                                "family_path": "family-characters",
                                "variant_id": "2bit_colored",
                                "reference_boxes": [[1024, 544, 1280, 1472]],
                            },
                        ],
                        "grid": {
                            "tile_size": 8,
                            "cols": 85,
                            "rows": 60,
                            "span_box": [0, 0, 2720, 1920],
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = reference_tile_match.resolve_match_run_settings(
                argparse.Namespace(
                    config=config_path,
                    image=None,
                    family_path=None,
                    variant_id=None,
                    origin_x=None,
                    origin_y=None,
                    cell_size=None,
                    span_box=None,
                    tile_size=8,
                    cols=None,
                    rows=None,
                    normalize_cell_size=None,
                    relevant_box=None,
                    content_box=None,
                    exclude_box=None,
                    exclude_partial_edge_cells=False,
                    max_candidates=3,
                    candidate_threshold=None,
                    output=None,
                )
            )

            self.assertEqual(
                settings.source_specs,
                (
                    reference_tile_match.MatchSourceSpec(
                        family_path=base_family_path,
                        variant_id="2bit_colored_bg",
                        source_id="minimal8.base",
                    ),
                    reference_tile_match.MatchSourceSpec(
                        family_path=characters_family_path,
                        variant_id="2bit_colored",
                        source_id="minimal8.characters",
                        reference_boxes=((1024, 544, 1280, 1472),),
                    ),
                ),
            )

    def test_build_match_report_recommends_sibling_colourway_for_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family_path = self._make_colourway_family_dir(root)
            image_path = root / "reference.png"
            reference_tile = self._tile(
                [
                    (0, 7, (0, 255, 0, 255)),
                    (1, 7, (0, 255, 0, 255)),
                    (0, 6, (0, 255, 0, 255)),
                ]
            )
            self._render_reference(reference_tile).save(image_path)

            report = reference_tile_match.build_match_report(
                image_path=image_path,
                source_specs=(
                    reference_tile_match.MatchSourceSpec(
                        family_path=family_path,
                        variant_id="2bit_colored_bg",
                    ),
                ),
                transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
                cols=1,
                rows=1,
                span_box=(0, 0, 32, 32),
            )

            candidate = report["cells"][0]["candidates"][0]
            self.assertEqual(candidate["variant_id"], "2bit_colored_bg")
            self.assertIn("recommended_variant_id", candidate)
            self.assertIn("recommended_colorway", candidate)
            self.assertIn("recommended_variant_ref", candidate)
            self.assertIn("recommended_semantic_variant_ref", candidate)
            self.assertIn("recommended_color_score", candidate)
            recommended_variant_id = candidate.get("recommended_variant_id")
            recommended_colorway = candidate.get("recommended_colorway")
            recommended_variant_ref = candidate.get("recommended_variant_ref")
            recommended_semantic_variant_ref = candidate.get("recommended_semantic_variant_ref")
            recommended_color_score = candidate.get("recommended_color_score")
            self.assertEqual(recommended_variant_id, "2bit_colored_bg_green")
            self.assertEqual(recommended_colorway, "green")
            self.assertEqual(recommended_variant_ref, "test.family@2bit_colored_bg_green:0,0")
            self.assertEqual(
                recommended_semantic_variant_ref,
                "test.family@2bit_colored_bg_green:test.family:all:0,0",
            )
            assert recommended_color_score is not None
            self.assertGreater(recommended_color_score, 0.95)
            self.assertEqual(report["sources"][0]["palette_family"], "minimal8-2bit")
            self.assertEqual(report["sources"][0]["background_mode"], "colored_bg")
            self.assertEqual(
                [variant["variant_id"] for variant in report["sources"][0]["available_variants"]],
                ["2bit_colored_bg", "2bit_colored_bg_green", "2bit_colored_bg_orange"],
            )

    def test_apply_review_overrides_marks_confirmed_tile_and_candidate_rank(self) -> None:
        cells: list[reference_tile_match.ReferenceCellMatch] = [
            {
                "col": 4,
                "row": 5,
                "status": "best_guess",
                "exact_matches": [],
                "candidates": [
                    {
                        "source_id": "minimal8.base",
                        "family_id": "minimal8",
                        "variant_id": "2bit_colored_bg",
                        "colorway": "colored",
                        "sheet_col": 30,
                        "sheet_row": 31,
                        "tile_id": "minimal8:terrain:11,8",
                        "aliases": [],
                        "physical_ref": "minimal8:30,31",
                        "variant_ref": "minimal8@2bit_colored_bg:30,31",
                        "semantic_variant_ref": "minimal8@2bit_colored_bg:minimal8:terrain:11,8",
                        "score": 0.882,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 1.0,
                        "mask_iou": 1.0,
                        "effective_mask_iou": 1.0,
                        "trimmed_logical_iou": 1.0,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 1.0,
                        "projection_similarity": 1.0,
                    }
                ],
                "review": {"status": "unreviewed"},
            }
        ]

        reviewed = reference_tile_match.apply_review_overrides(
            cells,
            {
                "C5R6": {
                    "status": "confirmed",
                    "selection": {
                        "kind": "tile",
                        "tile_id": "minimal8:terrain:11,8",
                    },
                    "note": "Reviewed against the 1-bit reference; best match comes from the 2-bit variant.",
                }
            },
        )

        self.assertEqual(reviewed[0]["review"].get("status"), "confirmed")
        self.assertEqual(
            reviewed[0]["review"].get("selection"),
            {"kind": "tile", "tile_id": "minimal8:terrain:11,8"},
        )
        self.assertEqual(reviewed[0]["review"].get("selected_candidate_rank"), 1)

    def test_apply_review_overrides_supports_variant_qualified_tile_selection(self) -> None:
        cells: list[reference_tile_match.ReferenceCellMatch] = [
            {
                "col": 4,
                "row": 5,
                "status": "best_guess",
                "exact_matches": [],
                "candidates": [
                    {
                        "source_id": "minimal8.base",
                        "family_id": "minimal8",
                        "variant_id": "2bit_colored_bg",
                        "colorway": "colored",
                        "sheet_col": 30,
                        "sheet_row": 31,
                        "tile_id": "minimal8:terrain:11,8",
                        "aliases": [],
                        "physical_ref": "minimal8:30,31",
                        "variant_ref": "minimal8@2bit_colored_bg:30,31",
                        "semantic_variant_ref": "minimal8@2bit_colored_bg:minimal8:terrain:11,8",
                        "score": 0.882,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 1.0,
                        "mask_iou": 1.0,
                        "effective_mask_iou": 1.0,
                        "trimmed_logical_iou": 1.0,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 1.0,
                        "projection_similarity": 1.0,
                    },
                    {
                        "source_id": "minimal8.base",
                        "family_id": "minimal8",
                        "variant_id": "2bit_colored_bg_green",
                        "colorway": "green",
                        "sheet_col": 30,
                        "sheet_row": 31,
                        "tile_id": "minimal8:terrain:11,8",
                        "aliases": [],
                        "physical_ref": "minimal8:30,31",
                        "variant_ref": "minimal8@2bit_colored_bg_green:30,31",
                        "semantic_variant_ref": "minimal8@2bit_colored_bg_green:minimal8:terrain:11,8",
                        "score": 0.88,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 1.0,
                        "mask_iou": 1.0,
                        "effective_mask_iou": 1.0,
                        "trimmed_logical_iou": 1.0,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 1.0,
                        "projection_similarity": 1.0,
                    },
                ],
                "review": {"status": "unreviewed"},
            }
        ]

        reviewed = reference_tile_match.apply_review_overrides(
            cells,
            {
                "C5R6": {
                    "status": "confirmed",
                    "selection": {
                        "kind": "tile",
                        "tile_id": "minimal8:terrain:11,8",
                        "variant_id": "2bit_colored_bg_green",
                    },
                }
            },
        )

        self.assertEqual(
            reviewed[0]["review"].get("selection"),
            {
                "kind": "tile",
                "tile_id": "minimal8:terrain:11,8",
                "variant_id": "2bit_colored_bg_green",
            },
        )
        self.assertEqual(reviewed[0]["review"].get("selected_candidate_rank"), 2)

    def test_apply_review_overrides_supports_confirmed_blank_cells(self) -> None:
        cells: list[reference_tile_match.ReferenceCellMatch] = [
            {
                "col": 6,
                "row": 2,
                "status": "blank",
                "exact_matches": [],
                "candidates": [],
                "review": {"status": "unreviewed"},
            }
        ]

        reviewed = reference_tile_match.apply_review_overrides(
            cells,
            {
                "C7R3": {
                    "status": "confirmed",
                    "selection": {"kind": "blank"},
                    "note": "Visually confirmed blank reference cell.",
                }
            },
        )

        self.assertEqual(reviewed[0]["review"].get("status"), "confirmed")
        self.assertEqual(reviewed[0]["review"].get("selection"), {"kind": "blank"})
        self.assertNotIn("selected_candidate_rank", reviewed[0]["review"])

    def test_apply_review_overrides_supports_confirmed_source_cells(self) -> None:
        cells: list[reference_tile_match.ReferenceCellMatch] = [
            {
                "col": 12,
                "row": 9,
                "status": "best_guess",
                "exact_matches": [],
                "candidates": [
                    {
                        "source_id": "minimal8.characters",
                        "family_id": "minimal8.characters",
                        "variant_id": "2bit_colored",
                        "colorway": "colored",
                        "sheet_col": 23,
                        "sheet_row": 5,
                        "tile_id": None,
                        "aliases": [],
                        "physical_ref": "minimal8.characters:23,5",
                        "variant_ref": "minimal8.characters@2bit_colored:23,5",
                        "semantic_variant_ref": None,
                        "score": 0.8123,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 0.75,
                        "mask_iou": 0.5,
                        "effective_mask_iou": 0.5,
                        "trimmed_logical_iou": 0.5,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 0.9,
                        "projection_similarity": 0.9,
                    }
                ],
                "review": {"status": "unreviewed"},
            }
        ]

        reviewed = reference_tile_match.apply_review_overrides(
            cells,
            {
                "C13R10": {
                    "status": "confirmed",
                    "selection": {
                        "kind": "source_cell",
                        "source_id": "minimal8.characters",
                        "sheet_col": 23,
                        "sheet_row": 5,
                    },
                    "note": "Visually confirmed against the character sheet.",
                }
            },
        )

        self.assertEqual(reviewed[0]["review"].get("status"), "confirmed")
        self.assertEqual(
            reviewed[0]["review"].get("selection"),
            {
                "kind": "source_cell",
                "source_id": "minimal8.characters",
                "sheet_col": 23,
                "sheet_row": 5,
            },
        )
        self.assertEqual(reviewed[0]["review"].get("selected_candidate_rank"), 1)

    def test_apply_review_overrides_supports_variant_qualified_source_cells(self) -> None:
        cells: list[reference_tile_match.ReferenceCellMatch] = [
            {
                "col": 12,
                "row": 9,
                "status": "best_guess",
                "exact_matches": [],
                "candidates": [
                    {
                        "source_id": "minimal8.characters",
                        "family_id": "minimal8.characters",
                        "variant_id": "2bit_colored",
                        "colorway": "colored",
                        "sheet_col": 23,
                        "sheet_row": 5,
                        "tile_id": None,
                        "aliases": [],
                        "physical_ref": "minimal8.characters:23,5",
                        "variant_ref": "minimal8.characters@2bit_colored:23,5",
                        "semantic_variant_ref": None,
                        "score": 0.8123,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 0.75,
                        "mask_iou": 0.5,
                        "effective_mask_iou": 0.5,
                        "trimmed_logical_iou": 0.5,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 0.9,
                        "projection_similarity": 0.9,
                    },
                    {
                        "source_id": "minimal8.characters",
                        "family_id": "minimal8.characters",
                        "variant_id": "2bit_colored_green",
                        "colorway": "green",
                        "sheet_col": 23,
                        "sheet_row": 5,
                        "tile_id": None,
                        "aliases": [],
                        "physical_ref": "minimal8.characters:23,5",
                        "variant_ref": "minimal8.characters@2bit_colored_green:23,5",
                        "semantic_variant_ref": None,
                        "score": 0.8122,
                        "pixel_match_ratio": 0.5,
                        "mask_match_ratio": 0.75,
                        "mask_iou": 0.5,
                        "effective_mask_iou": 0.5,
                        "trimmed_logical_iou": 0.5,
                        "mask_iou_rescue_applied": False,
                        "fill_similarity": 1.0,
                        "edge_match_ratio": 1.0,
                        "chamfer_similarity": 0.9,
                        "projection_similarity": 0.9,
                    },
                ],
                "review": {"status": "unreviewed"},
            }
        ]

        reviewed = reference_tile_match.apply_review_overrides(
            cells,
            {
                "C13R10": {
                    "status": "confirmed",
                    "selection": {
                        "kind": "source_cell",
                        "source_id": "minimal8.characters",
                        "sheet_col": 23,
                        "sheet_row": 5,
                        "variant_id": "2bit_colored_green",
                    },
                }
            },
        )

        self.assertEqual(
            reviewed[0]["review"].get("selection"),
            {
                "kind": "source_cell",
                "source_id": "minimal8.characters",
                "sheet_col": 23,
                "sheet_row": 5,
                "variant_id": "2bit_colored_green",
            },
        )
        self.assertEqual(reviewed[0]["review"].get("selected_candidate_rank"), 2)


if __name__ == "__main__":
    unittest.main()
