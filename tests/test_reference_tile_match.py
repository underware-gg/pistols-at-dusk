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

    def test_match_reference_tiles_reports_exact_duplicates(self) -> None:
        tile = self._tile(
            [
                (0, 7, (255, 0, 0, 255)),
                (1, 7, (255, 0, 0, 255)),
                (0, 6, (255, 0, 0, 255)),
            ]
        )
        source_tiles = [
            reference_tile_match.SourceTile(1, 2, "tile.a", ("alias.a",), tile),
            reference_tile_match.SourceTile(3, 4, "tile.b", ("alias.b",), tile.copy()),
        ]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(tile),
            source_tiles=source_tiles,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
        )

        self.assertEqual(summary["exact_match_cells"], 1)
        self.assertEqual(cells[0]["status"], "exact")
        self.assertEqual(
            {(item["sheet_col"], item["sheet_row"]) for item in cells[0]["exact_matches"]},
            {(1, 2), (3, 4)},
        )

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
        source_tiles = [reference_tile_match.SourceTile(5, 6, "tile.c", (), source_tile)]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.8,
        )

        self.assertEqual(summary["candidate_cells"], 1)
        self.assertEqual(cells[0]["status"], "candidate")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "tile.c")
        self.assertLess(cells[0]["candidates"][0]["pixel_match_ratio"], 1.0)
        self.assertEqual(cells[0]["candidates"][0]["mask_match_ratio"], 1.0)

    def test_match_reference_tiles_marks_weak_candidates_as_no_match(self) -> None:
        reference_tile = self._tile([(0, 7, (255, 0, 0, 255)), (0, 6, (255, 0, 0, 255))])
        source_tile = self._tile([(7, 0, (0, 255, 0, 255)), (7, 1, (0, 255, 0, 255))])
        source_tiles = [reference_tile_match.SourceTile(7, 8, "tile.d", (), source_tile)]

        cells, summary = reference_tile_match.match_reference_tiles(
            reference_image=self._render_reference(reference_tile),
            source_tiles=source_tiles,
            background=self.background,
            transform=reference_grid.GridTransform(origin_x=0, origin_y=0, cell_size=32),
            candidate_threshold=0.9,
        )

        self.assertEqual(summary["no_match_cells"], 1)
        self.assertEqual(cells[0]["status"], "no_match")
        self.assertEqual(cells[0]["candidates"][0]["tile_id"], "tile.d")


if __name__ == "__main__":
    unittest.main()
