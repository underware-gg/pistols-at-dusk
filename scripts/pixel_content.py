"""Canonical pixel byte helpers shared by ingest-side producers."""

from __future__ import annotations

from PIL import Image


CANONICAL_RGBA_FORMAT_HEADER = b"rgba8\n"


def canonical_rgba_bytes(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    return CANONICAL_RGBA_FORMAT_HEADER + f"{rgba.width}x{rgba.height}\n".encode("ascii") + rgba.tobytes()
