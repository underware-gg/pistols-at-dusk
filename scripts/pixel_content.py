"""Canonical pixel byte helpers shared by runtime and ingest producers."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image


CANONICAL_RGBA_FORMAT_HEADER = b"rgba8\n"


def canonical_rgba_bytes(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    return CANONICAL_RGBA_FORMAT_HEADER + f"{rgba.width}x{rgba.height}\n".encode("ascii") + rgba.tobytes()


def canonical_image_digest(image: Image.Image) -> str:
    return hashlib.sha256(canonical_rgba_bytes(image)).hexdigest()


def deterministic_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()
