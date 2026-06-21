"""Runtime-owned atomic tile asset addressing helpers."""

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


def atomic_asset_address_from_digest(digest: str) -> str:
    _validate_digest(digest, context="digest")
    return f"{ATOMIC_ASSET_PREFIX}{digest}"


def atomic_asset_relative_path(address: str) -> Path:
    if not address.startswith(ATOMIC_ASSET_PREFIX) or len(address) != len(ATOMIC_ASSET_PREFIX) + ATOMIC_ASSET_DIGEST_LENGTH:
        raise ValueError(f"Unsupported atomic asset address {address!r}")
    digest = address[len(ATOMIC_ASSET_PREFIX) :]
    _validate_digest(digest, context="address digest")
    return Path("assets") / ATOMIC_ASSET_ALGORITHM / digest[:2] / f"{digest}.png"
