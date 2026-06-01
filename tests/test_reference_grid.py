from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import json
import argparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import reference_grid


class ReferenceGridTests(unittest.TestCase):
    def _single_cell_extraction(
        self,
        *,
        cell_size: float,
        content_box: reference_grid.ContentBox | None = None,
    ) -> reference_grid.GridExtraction:
        cell_edge = round(cell_size)
        return reference_grid.GridExtraction(
            transform=reference_grid.GridTransform(
                origin_x=0,
                origin_y=0,
                cell_size=cell_size,
                content_box=content_box,
            ),
            columns=1,
            rows=1,
            crop_box=(0, 0, cell_edge, cell_edge),
            x_edges=(0, cell_edge),
            y_edges=(0, cell_edge),
        )

    def test_compute_extraction_floors_to_full_cells(self) -> None:
        extraction = reference_grid.compute_extraction(
            (100, 83),
            reference_grid.GridTransform(origin_x=4, origin_y=3, cell_size=16),
        )

        self.assertEqual(extraction.columns, 6)
        self.assertEqual(extraction.rows, 5)
        self.assertEqual(extraction.crop_box, (4, 3, 100, 83))
        self.assertEqual(extraction.x_edges, (0, 16, 32, 48, 64, 80, 96))
        self.assertEqual(extraction.y_edges, (0, 16, 32, 48, 64, 80))

    def test_compute_extraction_quantizes_fractional_pitch_to_cumulative_edges(self) -> None:
        extraction = reference_grid.compute_extraction(
            (794, 635),
            reference_grid.GridTransform(origin_x=3, origin_y=108, cell_size=184 / 7),
            cols=30,
            rows=20,
        )

        self.assertEqual(extraction.crop_box, (3, 108, 792, 634))
        self.assertEqual(extraction.x_edges[:6], (0, 26, 53, 79, 105, 131))
        self.assertEqual(extraction.x_edges[-6:], (657, 683, 710, 736, 762, 789))
        self.assertEqual(extraction.y_edges[:6], (0, 26, 53, 79, 105, 131))
        self.assertEqual(extraction.y_edges[-6:], (394, 421, 447, 473, 499, 526))

    def test_compute_extraction_supports_fractional_origin_phase(self) -> None:
        extraction = reference_grid.compute_extraction(
            (794, 635),
            reference_grid.GridTransform(origin_x=0.25, origin_y=106.5, cell_size=26.44),
            cols=30,
            rows=20,
        )

        self.assertEqual(extraction.crop_box, (0, 106, 793, 635))
        self.assertEqual(extraction.x_edges[:6], (0, 27, 53, 80, 106, 132))
        self.assertEqual(extraction.y_edges[:6], (0, 27, 53, 80, 106, 133))

    def test_compute_extraction_partitions_exact_span_without_float_drift(self) -> None:
        extraction = reference_grid.compute_extraction(
            (794, 635),
            reference_grid.GridTransform(origin_x=0, origin_y=106, cell_size=26.45),
            cols=30,
            rows=20,
            span_box=(0, 106, 794, 635),
        )

        self.assertEqual(extraction.crop_box, (0, 106, 794, 635))
        self.assertEqual(extraction.x_edges[:6], (0, 26, 53, 79, 106, 132))
        self.assertEqual(extraction.x_edges[-6:], (662, 688, 715, 741, 768, 794))
        self.assertEqual(extraction.y_edges[:6], (0, 26, 53, 79, 106, 132))
        self.assertEqual(extraction.y_edges[-6:], (397, 423, 450, 476, 503, 529))

    def test_resolve_normalized_cell_size_auto_chooses_nearest_valid_multiple(self) -> None:
        extraction = reference_grid.compute_extraction(
            (794, 635),
            reference_grid.GridTransform(origin_x=0, origin_y=106, cell_size=26.45, tile_size=8),
            cols=30,
            rows=20,
            span_box=(0, 106, 794, 635),
        )

        resolved = reference_grid.resolve_normalized_cell_size("auto", extraction)

        self.assertEqual(resolved, 24)

    def test_normalize_prepared_reference_grid_scales_crop_and_regions(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (79, 53), background)
        prepared = reference_grid.PreparedReferenceGrid(
            crop=crop,
            extraction=reference_grid.GridExtraction(
                transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=26.5, tile_size=8, content_box=(0, 1, 7, 8)),
                columns=3,
                rows=2,
                crop_box=(0, 0, 79, 53),
                x_edges=(0, 26, 53, 79),
                y_edges=(0, 26, 53),
            ),
            relevant_boxes=((0, 0, 79, 53),),
            excluded_boxes=((0, 0, 79, 6),),
            normalized_cell_size=None,
        )

        normalized = reference_grid.normalize_prepared_reference_grid(
            prepared,
            target_cell_size=24,
        )

        self.assertEqual(normalized.crop.size, (72, 48))
        self.assertEqual(normalized.extraction.x_edges, (0, 24, 48, 72))
        self.assertEqual(normalized.extraction.y_edges, (0, 24, 48))
        self.assertEqual(normalized.relevant_boxes, ((0, 0, 72, 48),))
        self.assertEqual(normalized.excluded_boxes, ((0, 0, 72, 5),))
        self.assertEqual(normalized.normalized_cell_size, 24)

    def test_compute_extraction_includes_partial_edge_cells_by_default(self) -> None:
        extraction = reference_grid.compute_extraction(
            (95, 50),
            reference_grid.GridTransform(origin_x=4, origin_y=3, cell_size=16),
            rows=2,
        )

        self.assertEqual(extraction.columns, 6)
        self.assertEqual(extraction.crop_box, (4, 3, 100, 35))
        self.assertEqual(extraction.x_edges, (0, 16, 32, 48, 64, 80, 96))

    def test_trim_extraction_to_full_cells_drops_partial_right_edge(self) -> None:
        extraction = reference_grid.compute_extraction(
            (95, 50),
            reference_grid.GridTransform(origin_x=4, origin_y=3, cell_size=16),
            rows=2,
        )

        trimmed = reference_grid.trim_extraction_to_full_cells(extraction, (95, 50))

        self.assertEqual(trimmed.columns, 5)
        self.assertEqual(trimmed.crop_box, (4, 3, 84, 35))
        self.assertEqual(trimmed.x_edges, (0, 16, 32, 48, 64, 80))

    def test_recover_base_tile_samples_integer_scale_without_drift(self) -> None:
        background = (36, 25, 42, 255)
        tile = Image.new("RGBA", (8, 8), background)
        for x in range(7):
            tile.putpixel((x, 7), (255, 0, 0, 255))
        for y in range(6, -1, -1):
            tile.putpixel((0, y), (255, 0, 0, 255))
        tile.putpixel((3, 4), (0, 255, 0, 255))

        rendered = reference_grid.resize_nearest(tile, (32, 32))
        recovered = reference_grid.recover_base_tile(rendered, tile_size=8)

        self.assertEqual(recovered.tobytes(), tile.tobytes())

    def test_recover_base_tile_respects_non_integer_content_box(self) -> None:
        background = (36, 25, 42, 255)
        tile = Image.new("RGBA", (8, 8), background)
        for x in range(7):
            tile.putpixel((x, 7), (255, 0, 0, 255))
        for y in range(1, 8):
            tile.putpixel((0, y), (255, 0, 0, 255))
        tile.putpixel((3, 4), (0, 255, 0, 255))

        rendered = reference_grid.resize_nearest(tile, (39, 39))
        recovered = reference_grid.recover_base_tile(
            rendered,
            tile_size=8,
            content_box=(0, 1, 7, 8),
            background=background,
        )

        self.assertEqual(recovered.tobytes(), tile.tobytes())

    def test_render_gutter_overlay_preserves_bottom_left_shape(self) -> None:
        background = (36, 25, 42, 255)
        tile = Image.new("RGBA", (8, 8), background)
        for x in range(7):
            tile.putpixel((x, 7), (255, 0, 0, 255))
        for y in range(8):
            tile.putpixel((0, y), (255, 0, 0, 255))
        crop = reference_grid.resize_nearest(tile, (32, 32))
        extraction = self._single_cell_extraction(cell_size=32)
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_gutter_overlay(crop, extraction, background)

        # The content starts after the outer margin; bottom-left art should stay intact.
        self.assertEqual(
            overlay.getpixel((guide_margin + 1, guide_margin + 31)),
            (255, 0, 0, 255),
        )
        self.assertNotEqual(
            overlay.getpixel((guide_margin + 31, guide_margin)),
            background,
        )

    def test_render_exact_boundary_overlay_upscales_content_with_nearest_neighbour(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (8, 8), background)
        crop.putpixel((1, 2), (255, 0, 0, 255))
        extraction = self._single_cell_extraction(cell_size=8)
        guide_margin = reference_grid.guide_margin_for_extraction(extraction, render_scale=4)

        overlay = reference_grid.render_exact_boundary_overlay(
            crop,
            extraction,
            background,
            guide_render_scale=4,
        )

        for x in range(guide_margin + 4, guide_margin + 8):
            for y in range(guide_margin + 8, guide_margin + 12):
                self.assertEqual(overlay.getpixel((x, y)), (255, 0, 0, 255))

    def test_render_gutter_overlay_uses_explicit_content_box_boundaries(self) -> None:
        background = (36, 25, 42, 255)
        tile = Image.new("RGBA", (8, 8), background)
        for x in range(7):
            tile.putpixel((x, 7), (255, 0, 0, 255))
        for y in range(1, 8):
            tile.putpixel((0, y), (255, 0, 0, 255))
        crop = reference_grid.resize_nearest(tile, (39, 39))
        extraction = self._single_cell_extraction(cell_size=39, content_box=(0, 1, 7, 8))
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_gutter_overlay(crop, extraction, background)

        # The first solid art row/column should remain untouched by the explicit guides.
        self.assertEqual(
            overlay.getpixel((guide_margin + 1, guide_margin + 1 + 5)),
            (255, 0, 0, 255),
        )
        self.assertEqual(
            overlay.getpixel((guide_margin + 1 + 33, guide_margin + 1 + 38)),
            (255, 0, 0, 255),
        )

    def test_count_solid_guide_pixels_ignores_excluded_boxes(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), background)
        for x in range(32):
            crop.putpixel((x, 3), (255, 0, 0, 255))
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))

        solid, total = reference_grid.count_solid_guide_pixels(crop, extraction, background)
        self.assertGreater(solid, 0)
        self.assertGreater(total, 0)

        excluded = ((0, 0, 32, 4),)
        solid_excluded, total_excluded = reference_grid.count_solid_guide_pixels(
            crop,
            extraction,
            background,
            excluded_boxes=excluded,
        )
        self.assertEqual(solid_excluded, 0)
        self.assertLess(total_excluded, total)

    def test_trim_extraction_to_relevant_boxes_rebases_crop_and_edges(self) -> None:
        extraction = reference_grid.compute_extraction(
            (50, 40),
            reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=10),
            cols=4,
            rows=3,
        )

        trimmed = reference_grid.trim_extraction_to_relevant_boxes(
            extraction,
            ((12, 12, 28, 28),),
        )

        self.assertEqual(trimmed.columns, 2)
        self.assertEqual(trimmed.rows, 2)
        self.assertEqual(trimmed.crop_box, (10, 10, 30, 30))
        self.assertEqual(trimmed.x_edges, (0, 10, 20))
        self.assertEqual(trimmed.y_edges, (0, 10, 20))

    def test_trim_extraction_to_relevant_boxes_raises_when_region_misses_grid(self) -> None:
        extraction = reference_grid.compute_extraction(
            (32, 32),
            reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=16),
            cols=2,
            rows=2,
        )

        with self.assertRaisesRegex(ValueError, "relevant_box"):
            reference_grid.trim_extraction_to_relevant_boxes(
                extraction,
                ((40, 40, 48, 48),),
            )

    def test_count_solid_guide_pixels_limits_measurement_to_relevant_boxes(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), background)
        for x in range(32):
            crop.putpixel((x, 3), (255, 0, 0, 255))
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))

        solid, total = reference_grid.count_solid_guide_pixels(crop, extraction, background)
        self.assertGreater(solid, 0)
        self.assertGreater(total, 0)

        relevant = ((0, 4, 32, 32),)
        solid_relevant, total_relevant = reference_grid.count_solid_guide_pixels(
            crop,
            extraction,
            background,
            relevant_boxes=relevant,
        )
        self.assertEqual(solid_relevant, 0)
        self.assertLess(total_relevant, total)

    def test_extract_crop_pads_partial_edges_with_background(self) -> None:
        background = (36, 25, 42, 255)
        image = Image.new("RGBA", (95, 32), background)
        image.putpixel((94, 31), (255, 0, 0, 255))
        extraction = reference_grid.compute_extraction(
            image.size,
            reference_grid.GridTransform(origin_x=4, origin_y=0, cell_size=16),
            rows=2,
        )

        crop = reference_grid.extract_crop(image, extraction, background=background)

        self.assertEqual(crop.size, (96, 32))
        self.assertEqual(crop.getpixel((90, 31)), (255, 0, 0, 255))
        self.assertEqual(crop.getpixel((95, 31)), background)

    def test_resolve_background_falls_back_to_opaque_guide_background_for_transparent_image(self) -> None:
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))

        resolved = reference_grid.resolve_background(image, None)

        self.assertEqual(resolved, reference_grid.DEFAULT_GUIDE_BACKGROUND)

    def test_render_gutter_overlay_adds_border_space_on_all_sides(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), background)
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_gutter_overlay(crop, extraction, background)

        self.assertGreater(overlay.width, crop.width + guide_margin)
        self.assertGreater(overlay.height, crop.height + guide_margin)
        right_border_x = guide_margin + crop.width + 1
        bottom_border_y = guide_margin + crop.height + 1
        self.assertNotEqual(overlay.getpixel((right_border_x, guide_margin + 8)), background)
        self.assertNotEqual(overlay.getpixel((guide_margin + 8, bottom_border_y)), background)

    def test_render_gutter_overlay_can_make_only_grid_surface_transparent(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_gutter_overlay(
            crop,
            extraction,
            background,
            transparent_grid_surface=True,
        )

        self.assertEqual(overlay.getpixel((0, 0)), background)
        self.assertEqual(overlay.getpixel((guide_margin + 8, guide_margin + 8)), (0, 0, 0, 0))

    def test_render_gutter_overlay_overlay_mode_can_make_only_grid_surface_transparent(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_gutter_overlay(
            crop,
            extraction,
            background,
            transparent_grid_surface=True,
            guide_line_mode="overlay",
        )

        self.assertEqual(overlay.getpixel((0, 0)), background)
        self.assertEqual(overlay.getpixel((guide_margin + 8, guide_margin + 8)), (0, 0, 0, 0))

    def test_render_exact_boundary_overlay_can_make_only_grid_surface_transparent(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        extraction = self._single_cell_extraction(cell_size=32, content_box=(0, 1, 7, 8))
        guide_margin = reference_grid.guide_margin_for_extraction(extraction)

        overlay = reference_grid.render_exact_boundary_overlay(
            crop,
            extraction,
            background,
            transparent_grid_surface=True,
        )

        self.assertEqual(overlay.getpixel((0, 0)), background)
        self.assertEqual(overlay.getpixel((guide_margin + 8, guide_margin + 8)), (0, 0, 0, 0))

    def test_render_gutter_overlay_keeps_grid_lines_visible_through_excluded_fill(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (64, 32), background)
        extraction = reference_grid.GridExtraction(
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32, content_box=(0, 1, 7, 8)),
            columns=2,
            rows=1,
            crop_box=(0, 0, 64, 32),
            x_edges=(0, 32, 64),
            y_edges=(0, 32),
        )

        overlay = reference_grid.render_gutter_overlay(
            crop,
            extraction,
            background,
            excluded_boxes=((0, 0, 64, 32),),
        )

        guide_margin = reference_grid.guide_margin_for_extraction(extraction)
        separator_x = guide_margin + extraction.x_edges[1] + 1
        self.assertEqual(
            overlay.getpixel((separator_x, guide_margin + 12)),
            (218, 206, 185, 70),
        )

    def test_render_gutter_overlay_draws_excluded_outline_on_grid_boundaries(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (64, 32), background)
        extraction = reference_grid.GridExtraction(
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32, content_box=(0, 1, 7, 8)),
            columns=2,
            rows=1,
            crop_box=(0, 0, 64, 32),
            x_edges=(0, 32, 64),
            y_edges=(0, 32),
        )

        overlay = reference_grid.render_gutter_overlay(
            crop,
            extraction,
            background,
            excluded_boxes=((0, 0, 32, 32),),
        )

        guide_margin = reference_grid.guide_margin_for_extraction(extraction)
        separator_x = guide_margin + extraction.x_edges[1] + 1

        self.assertEqual(
            overlay.getpixel((separator_x, guide_margin + 12)),
            reference_grid.EXCLUDED_OUTLINE_COLOUR,
        )
        self.assertNotEqual(
            overlay.getpixel((separator_x - 1, guide_margin + 12)),
            reference_grid.EXCLUDED_OUTLINE_COLOUR,
        )

    def test_render_gutter_overlay_uses_same_colour_for_border_and_internal_grid(self) -> None:
        background = (36, 25, 42, 255)
        crop = Image.new("RGBA", (64, 32), background)
        extraction = reference_grid.GridExtraction(
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32, content_box=(0, 1, 7, 8)),
            columns=2,
            rows=1,
            crop_box=(0, 0, 64, 32),
            x_edges=(0, 32, 64),
            y_edges=(0, 32),
        )

        overlay = reference_grid.render_gutter_overlay(crop, extraction, background)

        guide_margin = reference_grid.guide_margin_for_extraction(extraction)
        separator_x = guide_margin + extraction.x_edges[1] + 1
        top_border_y = guide_margin

        self.assertEqual(
            overlay.getpixel((separator_x, guide_margin + 12)),
            overlay.getpixel((guide_margin + 12, top_border_y)),
        )

    def test_guide_chrome_scales_with_large_cells(self) -> None:
        small = self._single_cell_extraction(cell_size=32)
        large = self._single_cell_extraction(cell_size=80)

        build_guide_chrome = getattr(reference_grid, "_build_guide_chrome")
        small_chrome = build_guide_chrome(small)
        large_chrome = build_guide_chrome(large)

        self.assertGreater(large_chrome.actual_label_height, small_chrome.actual_label_height)
        self.assertGreater(large_chrome.margin, small_chrome.margin)
        self.assertGreaterEqual(
            large_chrome.label_band,
            large_chrome.actual_label_width + (large_chrome.label_inner_pad * 2),
        )
        self.assertGreaterEqual(
            large_chrome.label_band,
            large_chrome.actual_label_height + (large_chrome.label_inner_pad * 2),
        )

    def test_guide_chrome_scales_down_for_native_eight_pixel_cells(self) -> None:
        tiny = self._single_cell_extraction(cell_size=8)

        build_guide_chrome = getattr(reference_grid, "_build_guide_chrome")
        tiny_chrome = build_guide_chrome(tiny)

        self.assertEqual(tiny_chrome.actual_label_height, 4)
        self.assertLessEqual(tiny_chrome.actual_label_height, round(8 * 0.5))
        self.assertLessEqual(tiny_chrome.label_band, 10)
        self.assertEqual(tiny_chrome.margin, 12)

    def test_default_guide_line_colour_scales_alpha_with_cell_size(self) -> None:
        tiny = self._single_cell_extraction(cell_size=8)
        large = self._single_cell_extraction(cell_size=80)

        resolve_default_guide_line_colour = getattr(reference_grid, "_resolve_default_guide_line_colour")
        tiny_colour = resolve_default_guide_line_colour(tiny)
        large_colour = resolve_default_guide_line_colour(large)

        self.assertLess(tiny_colour[3], large_colour[3])
        self.assertEqual(large_colour[3], reference_grid.GUIDE_LINE_ALPHA_MAX)

    def test_guide_canvas_layout_places_label_bands_symmetrically(self) -> None:
        extraction = self._single_cell_extraction(cell_size=80)
        build_guide_chrome = getattr(reference_grid, "_build_guide_chrome")
        build_guide_canvas_layout = getattr(reference_grid, "_build_guide_canvas_layout")
        chrome = build_guide_chrome(extraction)
        layout = build_guide_canvas_layout(
            content_width=80,
            content_height=80,
            chrome=chrome,
        )

        top_gap = layout.top_margin - layout.top_label_center_y
        bottom_gap = layout.bottom_label_center_y - (layout.top_margin + layout.content_height)
        left_gap = layout.left_margin - layout.left_label_center_x
        right_gap = layout.right_label_center_x - (layout.left_margin + layout.content_width)

        self.assertEqual(top_gap, bottom_gap)
        self.assertEqual(left_gap, right_gap)

    def test_text_origin_for_centered_bbox_accounts_for_bbox_offsets(self) -> None:
        text_origin_for_centered_bbox = getattr(reference_grid, "_text_origin_for_centered_bbox")
        origin = text_origin_for_centered_bbox(
            left=2,
            top=6,
            right=18,
            bottom=26,
            center_x=100,
            center_y=200,
        )

        self.assertEqual(origin, (90, 184))

    def test_resolve_grid_run_settings_loads_relative_config_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            image_path.write_bytes(b"png")
            config_path = root / "solve.json"
            config_path.write_text(
                json.dumps(
                    {
                        "image": "reference.png",
                        "prefix": "overworld_reference",
                        "grid": {
                            "tile_size": 8,
                            "cols": 39,
                            "rows": 26,
                        "span_box": [0, 22, 1248, 854],
                        "content_box": [0, 1, 7, 8],
                    },
                        "relevant_boxes": [[0, 22, 1248, 854]],
                        "excluded_boxes": [[416, 54, 832, 182]],
                        "exclude_partial_edge_cells": True,
                        "normalize_cell_size": "auto",
                        "guide_line_mode": "overlay",
                        "zoom_cell": [19, 13],
                    }
                ),
                encoding="utf-8",
            )

            settings = reference_grid.resolve_grid_run_settings(
                argparse.Namespace(
                    config=config_path,
                    image=None,
                    output_dir=root / "out",
                    prefix=None,
                    origin_x=None,
                    origin_y=None,
                    cell_size=None,
                    span_box=None,
                    tile_size=8,
                    cols=None,
                    rows=None,
                    normalize_cell_size=None,
                    relevant_box=None,
                    exclude_box=None,
                    content_box=None,
                    background=None,
                    exclude_partial_edge_cells=False,
                    guide_line_mode=None,
                    guide_render_scale=None,
                    transparent_grid_surface=False,
                    emit_recovered_tile_sheet=False,
                    zoom_cell=None,
                    recovered_tile_scale=4,
                )
            )

            self.assertEqual(settings.image_path, image_path)
            self.assertEqual(settings.prefix, "overworld_reference")
            self.assertEqual(settings.transform.origin_y, 22.0)
            self.assertEqual(settings.columns, 39)
            self.assertEqual(settings.rows, 26)
            self.assertEqual(settings.span_box, (0, 22, 1248, 854))
            self.assertEqual(settings.transform.content_box, (0, 1, 7, 8))
            self.assertEqual(settings.relevant_boxes, ((0, 22, 1248, 854),))
            self.assertEqual(settings.excluded_boxes, ((416, 54, 832, 182),))
            self.assertTrue(settings.exclude_partial_edge_cells)
            self.assertEqual(settings.normalize_cell_size, "auto")
            self.assertEqual(settings.guide_line_mode, "overlay")
            self.assertEqual(settings.guide_render_scale, 1)
            self.assertFalse(settings.transparent_grid_surface)
            self.assertFalse(settings.emit_recovered_tile_sheet)
            self.assertEqual(settings.zoom_cell, (19, 13))

    def test_resolve_grid_run_settings_loads_transparent_grid_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            image_path.write_bytes(b"png")
            config_path = root / "solve.json"
            config_path.write_text(
                json.dumps(
                    {
                        "image": "reference.png",
                        "prefix": "characters_sheet",
                        "grid": {
                            "tile_size": 8,
                            "cols": 32,
                            "rows": 48,
                            "origin_x": 0,
                            "origin_y": 0,
                            "cell_size": 8,
                            "content_box": [0, 1, 7, 8],
                        },
                        "transparent_grid_surface": True,
                        "guide_render_scale": 4,
                    }
                ),
                encoding="utf-8",
            )

            settings = reference_grid.resolve_grid_run_settings(
                argparse.Namespace(
                    config=config_path,
                    image=None,
                    output_dir=root / "out",
                    prefix=None,
                    origin_x=None,
                    origin_y=None,
                    cell_size=None,
                    span_box=None,
                    tile_size=8,
                    cols=None,
                    rows=None,
                    normalize_cell_size=None,
                    relevant_box=None,
                    exclude_box=None,
                    exclude_partial_edge_cells=False,
                    guide_line_mode=None,
                    guide_render_scale=None,
                    transparent_grid_surface=False,
                    emit_recovered_tile_sheet=False,
                    content_box=None,
                    background=None,
                    zoom_cell=None,
                    recovered_tile_scale=4,
                )
            )

            self.assertEqual(settings.guide_render_scale, 4)
            self.assertTrue(settings.transparent_grid_surface)
            self.assertFalse(settings.emit_recovered_tile_sheet)

    def test_save_outputs_writes_guide_beside_reference_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            image = Image.new("RGBA", (32, 32), (36, 25, 42, 255))
            image.save(image_path)

            outputs = reference_grid.save_outputs(
                argparse.Namespace(
                    config=None,
                    image=image_path,
                    output_dir=root / "out",
                    prefix="reference",
                    origin_x=0,
                    origin_y=0,
                    cell_size=32,
                    span_box=None,
                    tile_size=8,
                    cols=1,
                    rows=1,
                    normalize_cell_size=None,
                    relevant_box=None,
                    exclude_box=None,
                    content_box="0,1,7,8",
                    background=None,
                    exclude_partial_edge_cells=False,
                    guide_line_mode=None,
                    guide_render_scale=None,
                    transparent_grid_surface=False,
                    emit_recovered_tile_sheet=False,
                    zoom_cell=None,
                    recovered_tile_scale=4,
                )
            )

            sibling_guide = image_path.with_name("reference--guide.png")
            self.assertIn(sibling_guide, outputs)
            self.assertTrue(sibling_guide.exists())
            self.assertNotIn(root / "out" / "reference_recovered_tile_sheet.png", outputs)

    def test_save_outputs_uses_opaque_guide_background_for_transparent_reference_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            image.save(image_path)

            outputs = reference_grid.save_outputs(
                argparse.Namespace(
                    config=None,
                    image=image_path,
                    output_dir=root / "out",
                    prefix="reference",
                    origin_x=0,
                    origin_y=0,
                    cell_size=32,
                    span_box=None,
                    tile_size=8,
                    cols=1,
                    rows=1,
                    normalize_cell_size=None,
                    relevant_box=None,
                    exclude_box=None,
                    content_box="0,1,7,8",
                    background=None,
                    exclude_partial_edge_cells=False,
                    guide_line_mode=None,
                    guide_render_scale=None,
                    transparent_grid_surface=False,
                    emit_recovered_tile_sheet=False,
                    zoom_cell=None,
                    recovered_tile_scale=4,
                )
            )

            sibling_guide = image_path.with_name("reference--guide.png")
            self.assertIn(sibling_guide, outputs)
            rendered_guide = Image.open(sibling_guide).convert("RGBA")
            self.assertEqual(rendered_guide.getpixel((0, 0)), reference_grid.DEFAULT_GUIDE_BACKGROUND)

    def test_save_outputs_writes_normalized_body_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            image = Image.new("RGBA", (79, 53), (36, 25, 42, 255))
            image.save(image_path)

            outputs = reference_grid.save_outputs(
                argparse.Namespace(
                    config=None,
                    image=image_path,
                    output_dir=root / "out",
                    prefix="reference",
                    origin_x=0,
                    origin_y=0,
                    cell_size=26.5,
                    span_box="0,0,79,53",
                    tile_size=8,
                    cols=3,
                    rows=2,
                    normalize_cell_size="24",
                    relevant_box=None,
                    exclude_box=None,
                    content_box="0,1,7,8",
                    background=None,
                    exclude_partial_edge_cells=False,
                    guide_line_mode=None,
                    guide_render_scale=None,
                    transparent_grid_surface=False,
                    emit_recovered_tile_sheet=False,
                    zoom_cell=None,
                    recovered_tile_scale=4,
                )
            )

            normalized_body = root / "out" / "reference_normalized_body.png"
            self.assertIn(normalized_body, outputs)
            self.assertTrue(normalized_body.exists())

    def test_save_outputs_emits_recovered_tile_sheet_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "reference.png"
            background = (36, 25, 42, 255)
            image = Image.new("RGBA", (16, 8), background)
            for x in range(8):
                image.putpixel((x, 7), (255, 0, 0, 255))
                image.putpixel((8 + x, 0), (0, 255, 0, 255))
            image.save(image_path)

            args = argparse.Namespace(
                config=None,
                image=image_path,
                output_dir=root / "out",
                prefix="reference",
                origin_x=0,
                origin_y=0,
                cell_size=8,
                span_box=None,
                tile_size=8,
                cols=2,
                rows=1,
                normalize_cell_size=None,
                relevant_box=None,
                exclude_box=None,
                content_box=None,
                background=None,
                exclude_partial_edge_cells=False,
                guide_line_mode=None,
                guide_render_scale=None,
                transparent_grid_surface=False,
                emit_recovered_tile_sheet=True,
                zoom_cell=None,
                recovered_tile_scale=4,
            )

            outputs = reference_grid.save_outputs(args)

            recovered_tile_path = root / "out" / "reference_recovered_tile_sheet.png"
            self.assertIn(recovered_tile_path, outputs)
            recovered_tile_sheet = Image.open(recovered_tile_path).convert("RGBA")

            prepared = reference_grid.prepare_reference_grid(
                image,
                transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=8, tile_size=8),
                cols=2,
                rows=1,
                background=background,
            )
            tile_grid = reference_grid.build_tile_grid(prepared.crop, prepared.extraction, background=background)
            crop_and_extraction = getattr(reference_grid, "_crop_and_extraction_for_recovered_tile_grid")
            contact_crop, contact_extraction = crop_and_extraction(
                tile_grid,
                background=background,
            )
            expected = reference_grid.render_gutter_overlay(
                contact_crop,
                contact_extraction,
                background,
                guide_render_scale=4,
                guide_line_mode="separated",
            )

            self.assertEqual(recovered_tile_sheet.size, expected.size)
            self.assertEqual(recovered_tile_sheet.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
