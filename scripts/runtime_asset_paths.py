"""Runtime-owned tile asset path helpers."""

from __future__ import annotations

from pathlib import Path


ATOMIC_ASSET_ALGORITHM = "sha256"
ATOMIC_ASSET_PREFIX = f"{ATOMIC_ASSET_ALGORITHM}:"
ATOMIC_ASSET_DIGEST_LENGTH = 64
_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_digest(digest: str, *, context: str) -> None:
    if len(digest) != ATOMIC_ASSET_DIGEST_LENGTH or any(char not in _LOWER_HEX_DIGITS for char in digest):
        raise ValueError(f"Unsupported atomic asset {context} {digest!r}")


def runtime_family_root(base_dir: Path, family_id: str) -> Path:
    return base_dir / family_id


def runtime_atlas_relative_path(variant_id: str) -> Path:
    if "/" in variant_id or "\\" in variant_id or variant_id in {"", ".", ".."}:
        raise ValueError(f"Unsupported runtime atlas variant id {variant_id!r}")
    return Path("sheets") / f"{variant_id}.png"


def atlas_cell_box(col: int, row: int, *, tile_width: int, tile_height: int) -> tuple[int, int, int, int]:
    left = col * tile_width
    top = row * tile_height
    return (left, top, left + tile_width, top + tile_height)


def atomic_asset_address_from_digest(digest: str) -> str:
    _validate_digest(digest, context="digest")
    return f"{ATOMIC_ASSET_PREFIX}{digest}"


def atomic_asset_relative_path(address: str) -> Path:
    if not address.startswith(ATOMIC_ASSET_PREFIX) or len(address) != len(ATOMIC_ASSET_PREFIX) + ATOMIC_ASSET_DIGEST_LENGTH:
        raise ValueError(f"Unsupported atomic asset address {address!r}")
    digest = address[len(ATOMIC_ASSET_PREFIX) :]
    _validate_digest(digest, context="address digest")
    return Path("assets") / ATOMIC_ASSET_ALGORITHM / digest[:2] / f"{digest}.png"
