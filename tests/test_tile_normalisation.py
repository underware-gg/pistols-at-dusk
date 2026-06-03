"""Tests for the shared transparency-normalisation primitive (ADR 0007 precondition).

Background normalisation must run before a tile's silhouette is rendered or its
seam profile derived, so the runtime renderer and seam derivation share this
module. The rule: ``top_left`` keys the sheet's top-left pixel to transparency;
``none`` keys nothing.
"""

import unittest

from PIL import Image

from tile_normalisation import apply_transparent_key, transparent_key_for_sheet


class TransparentKeyForSheetTests(unittest.TestCase):
    def test_top_left_returns_top_left_pixel(self):
        sheet = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        sheet.putpixel((0, 0), (200, 100, 50, 255))
        self.assertEqual(transparent_key_for_sheet(sheet, "top_left"), (200, 100, 50, 255))

    def test_none_returns_none(self):
        sheet = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        self.assertIsNone(transparent_key_for_sheet(sheet, "none"))

    def test_unsupported_mode_raises(self):
        sheet = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        with self.assertRaises(ValueError):
            transparent_key_for_sheet(sheet, "checkerboard")


class ApplyTransparentKeyTests(unittest.TestCase):
    def test_matching_pixels_become_fully_transparent(self):
        image = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        key = (50, 60, 70, 255)
        image.putpixel((0, 0), key)
        image.putpixel((1, 0), (90, 90, 90, 255))
        apply_transparent_key(image, key)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (90, 90, 90, 255))


if __name__ == "__main__":
    unittest.main()
