from __future__ import annotations

import sys
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import reference_grid


class ReferenceGridTests(unittest.TestCase):
    def test_compute_extraction_floors_to_full_cells(self) -> None:
        extraction = reference_grid.compute_extraction(
            (100, 83),
            reference_grid.GridTransform(origin_x=4, origin_y=3, cell_size=16),
        )

        self.assertEqual(extraction.columns, 6)
        self.assertEqual(extraction.rows, 5)
        self.assertEqual(extraction.crop_box, (4, 3, 100, 83))

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

    def test_render_gutter_overlay_preserves_bottom_left_shape(self) -> None:
        background = (36, 25, 42, 255)
        tile = Image.new("RGBA", (8, 8), background)
        for x in range(7):
            tile.putpixel((x, 7), (255, 0, 0, 255))
        for y in range(8):
            tile.putpixel((0, y), (255, 0, 0, 255))
        crop = reference_grid.resize_nearest(tile, (32, 32))
        extraction = reference_grid.GridExtraction(
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            columns=1,
            rows=1,
            crop_box=(0, 0, 32, 32),
        )

        overlay = reference_grid.render_gutter_overlay(crop, extraction, background)

        # The content starts after the outer margin; bottom-left art should stay intact.
        self.assertEqual(overlay.getpixel((36, 24 + 31)), (255, 0, 0, 255))
        self.assertNotEqual(overlay.getpixel((36 + 31, 24)), background)


if __name__ == "__main__":
    unittest.main()
