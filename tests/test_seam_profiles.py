"""Tests for seam-profile derivation core (ADR 0007; design D1/D2/D4).

The core turns a tile's *occupancy grid* (already background-normalised: True =
painted, False = empty/transparent) into a per-side contact mask — the 1px
contact line read in the orientation that lets facing sides compare directly:

  - east / west  read top -> bottom
  - north / south read left -> right

So tile A's ``east`` mask aligns index-for-index with neighbour B's ``west``
mask; A's ``south`` with B's ``north``. The image I/O and background
normalisation that *produce* the occupancy grid live in the ingest layer, not
here, so this core is pure and synthetic-grid testable.
"""

import unittest

from seam_profiles import SIDES, contact_mask, derive_side_masks


class ContactMaskTests(unittest.TestCase):
    def setUp(self):
        # 2 rows x 3 cols
        self.grid = [
            [True, False, False],
            [False, False, True],
        ]

    def test_north_is_top_row_left_to_right(self):
        self.assertEqual(contact_mask(self.grid, "north"), (True, False, False))

    def test_south_is_bottom_row_left_to_right(self):
        self.assertEqual(contact_mask(self.grid, "south"), (False, False, True))

    def test_west_is_left_column_top_to_bottom(self):
        self.assertEqual(contact_mask(self.grid, "west"), (True, False))

    def test_east_is_right_column_top_to_bottom(self):
        self.assertEqual(contact_mask(self.grid, "east"), (False, True))

    def test_unknown_side_raises(self):
        with self.assertRaises(ValueError):
            contact_mask(self.grid, "diagonal")


class FacingAlignmentTests(unittest.TestCase):
    """The orientation contract: facing sides of abutting tiles line up by index."""

    def test_east_of_a_aligns_with_west_of_b(self):
        a = [[False, True], [True, True]]   # east column top->bottom = (True, True)
        b = [[True, False], [True, False]]  # west column top->bottom = (True, True)
        self.assertEqual(contact_mask(a, "east"), contact_mask(b, "west"))

    def test_south_of_a_aligns_with_north_of_b(self):
        a = [[False, False], [True, False]]  # south row = (True, False)
        b = [[True, False], [False, True]]   # north row = (True, False)
        self.assertEqual(contact_mask(a, "south"), contact_mask(b, "north"))


class DeriveSideMasksTests(unittest.TestCase):
    def test_returns_all_four_sides(self):
        masks = derive_side_masks([[True, False], [False, True]])
        self.assertEqual(set(masks), set(SIDES))

    def test_fully_empty_grid_yields_null_masks(self):
        masks = derive_side_masks([[False, False], [False, False]])
        self.assertTrue(all(not any(m) for m in masks.values()))

    def test_single_cell_grid(self):
        masks = derive_side_masks([[True]])
        self.assertEqual(masks, {"north": (True,), "south": (True,), "east": (True,), "west": (True,)})

    def test_empty_grid_raises(self):
        with self.assertRaises(ValueError):
            derive_side_masks([])

    def test_ragged_grid_raises(self):
        with self.assertRaises(ValueError):
            derive_side_masks([[True, False], [True]])


if __name__ == "__main__":
    unittest.main()
