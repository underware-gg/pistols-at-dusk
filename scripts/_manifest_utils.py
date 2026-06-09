from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, cast


@dataclass(frozen=True)
class GridBounds:
    x: int
    y: int
    width: int
    height: int


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
