"""Transparency normalisation — the background-normalisation primitive.

A sheet-backed tile carries its "no content here" convention as a background
colour (the ``top_left`` mode keys the sheet's top-left pixel to full
transparency) rather than as genuine alpha. That normalisation must run *before*
a tile's silhouette is rendered **or** its seam profile is derived: deriving a
seam from un-normalised pixels would read the keyed background as painted and
fabricate a false seam (ADR 0007's one hard precondition).

This rule is shared by the runtime renderer (``layout_core``) and seam
derivation (``tile_families``), so it lives here once. Pure PIL; imports nothing
from our own layers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from PIL import Image

RGBA = tuple[int, int, int, int]


def transparent_key_for_sheet(sheet: Image.Image, transparent_mode: str) -> RGBA | None:
    """The pixel value keyed to full transparency for a sheet under ``transparent_mode``.

    ``top_left`` keys the sheet's top-left pixel; ``none`` keys nothing (the
    sheet already carries genuine alpha).
    """
    if transparent_mode == "top_left":
        return cast(RGBA, sheet.getpixel((0, 0)))
    if transparent_mode == "none":
        return None
    raise ValueError(f"Unsupported transparent mode: {transparent_mode}")


def apply_transparent_key(image: Image.Image, transparent_key: object) -> None:
    """Replace pixels matching ``transparent_key`` in ``image`` with full transparency."""
    # Pillow's get_flattened_data / putdata stubs are weakly typed; route through a
    # cast that pyright can fully resolve so the strict checker stays happy.
    get_data = cast(Callable[[], Sequence[object]], getattr(image, "get_flattened_data"))
    put_data = cast(Callable[[Sequence[RGBA]], None], getattr(image, "putdata"))
    pixels: list[RGBA] = [
        (0, 0, 0, 0) if pixel == transparent_key else cast(RGBA, pixel)
        for pixel in get_data()
    ]
    put_data(pixels)
