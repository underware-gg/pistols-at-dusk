from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, cast


def as_int(value: object, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


@dataclass(frozen=True)
class GridBounds:
    x: int
    y: int
    width: int
    height: int

    def to_payload(self) -> dict[str, object]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_payload(cls, raw: object, *, context: str) -> GridBounds:
        mapping = require_mapping(raw, context=context)
        x = as_int(mapping.get("x"), context=f"{context}.x")
        y = as_int(mapping.get("y"), context=f"{context}.y")
        width = as_int(mapping.get("width"), context=f"{context}.width")
        height = as_int(mapping.get("height"), context=f"{context}.height")
        if x < 0 or y < 0:
            raise ValueError(f"{context} origin must be non-negative")
        if width <= 0 or height <= 0:
            raise ValueError(f"{context} width and height must be positive")

        return cls(
            x=x,
            y=y,
            width=width,
            height=height,
        )


def load_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    # Treat any local manifest file read or parse failure as a validation error at
    # the ingest boundary so callers see a uniform contract from the loaders.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load JSON file {path}: {exc}") from exc


def require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def require_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    return cast(list[object], value)


def check_required_keys(
    mapping: dict[str, object],
    required: tuple[str, ...],
    *,
    context: str,
) -> None:
    missing = [key for key in required if key not in mapping]
    if missing:
        raise ValueError(f"{context} is missing required keys: {', '.join(missing)}")


def require_exactly_one(mapping: Mapping[str, object], first: str, second: str, *, context: str) -> None:
    if (first in mapping) == (second in mapping):
        raise ValueError(f"{context} must declare exactly one of {first} or {second}")


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path).resolve()


def bounds_inside(outer: GridBounds, inner: GridBounds) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )
