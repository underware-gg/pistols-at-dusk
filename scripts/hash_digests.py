"""Shared digest string validation helpers."""
from __future__ import annotations


SHA256_HEX_DIGEST_LENGTH = 64
SHA256_HEX_DIGITS = frozenset("0123456789abcdef")


def is_sha256_hex(digest: str) -> bool:
    return len(digest) == SHA256_HEX_DIGEST_LENGTH and all(char in SHA256_HEX_DIGITS for char in digest)
