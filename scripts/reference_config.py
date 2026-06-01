from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, cast

from _manifest_utils import require_mapping
from reference_grid_types import ContentBox, GuideLineMode, NormalizeCellSizeSetting, Rect


def load_reference_config(config_path: Path | None) -> tuple[dict[str, object], Path | None]:
    if config_path is None:
        return {}, None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return require_mapping(payload, context="config"), config_path.parent


def _resolve_relative_path(raw: str, config_dir: Path | None) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute() or config_dir is None:
        return path
    return config_dir / path


def read_path(
    cli_value: Path | None,
    config: Mapping[str, object],
    key: str,
    *,
    config_dir: Path | None,
) -> Path | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} must be a string path")
    return _resolve_relative_path(raw, config_dir)


def read_string(cli_value: str | None, config: Mapping[str, object], key: str) -> str | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} must be a string")
    return raw


def read_string_list(
    cli_value: list[str] | None,
    config: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    if cli_value is not None:
        return tuple(cli_value)
    raw = config.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list of strings")
    values: list[str] = []
    for index, item in enumerate(cast(list[object], raw)):
        if not isinstance(item, str):
            raise ValueError(f"{key}[{index}] must be a string")
        values.append(item)
    return tuple(values)


def read_guide_line_mode(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
) -> GuideLineMode:
    raw = cli_value if cli_value is not None else config.get(key, "separated")
    if raw not in {"separated", "overlay"}:
        raise ValueError(f"{key} must be 'separated' or 'overlay'")
    return cast(GuideLineMode, raw)


def read_int(cli_value: int | None, config: Mapping[str, object], key: str) -> int | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    return raw


def read_float(cli_value: float | None, config: Mapping[str, object], key: str) -> float | None:
    if cli_value is not None:
        return cli_value
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(raw)


def parse_rect(raw: str) -> Rect:
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("rectangle must be left,top,right,bottom")
    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        raise ValueError("rectangle bounds must satisfy left < right and top < bottom")
    return (left, top, right, bottom)


def read_rect(cli_value: str | None, config: Mapping[str, object], key: str) -> Rect | None:
    if cli_value is not None:
        return parse_rect(cli_value)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a rectangle list")
    parts = cast(list[object], raw)
    return parse_rect(",".join(str(part) for part in parts))


def read_normalize_cell_size(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
) -> NormalizeCellSizeSetting:
    raw: object | None = cli_value if cli_value is not None else config.get(key)
    if raw is None:
        return None
    if raw == "auto":
        return "auto"
    if isinstance(raw, int):
        if raw <= 0:
            raise ValueError(f"{key} must be positive")
        return raw
    if isinstance(raw, str):
        value = int(raw)
        if value <= 0:
            raise ValueError(f"{key} must be positive")
        return value
    raise ValueError(f"{key} must be a positive integer or 'auto'")


def read_rectangles(cli_value: list[str] | None, config: Mapping[str, object], key: str) -> tuple[Rect, ...]:
    if cli_value is not None:
        return tuple(parse_rect(raw) for raw in cli_value)
    raw = config.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list of rectangles")
    rectangles: list[Rect] = []
    items = cast(list[object], raw)
    for index, item in enumerate(items):
        if not isinstance(item, list):
            raise ValueError(f"{key}[{index}] must be a list")
        parts = cast(list[object], item)
        rectangles.append(parse_rect(",".join(str(part) for part in parts)))
    return tuple(rectangles)


def parse_content_box(raw: str | None, tile_size: int) -> ContentBox | None:
    if raw is None:
        return None
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("content_box must be left,top,right,bottom")
    left, top, right, bottom = parts
    if not (0 <= left < right <= tile_size):
        raise ValueError("content_box horizontal bounds must satisfy 0 <= left < right <= tile_size")
    if not (0 <= top < bottom <= tile_size):
        raise ValueError("content_box vertical bounds must satisfy 0 <= top < bottom <= tile_size")
    return (left, top, right, bottom)


def read_content_box(
    cli_value: str | None,
    config: Mapping[str, object],
    key: str,
    *,
    tile_size: int,
) -> ContentBox | None:
    if cli_value is not None:
        return parse_content_box(cli_value, tile_size)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    parts = cast(list[object], raw)
    return parse_content_box(",".join(str(part) for part in parts), tile_size)


def parse_zoom_cell(raw: str | None) -> tuple[int, int] | None:
    if raw is None:
        return None
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 2:
        raise ValueError("zoom_cell must be col,row")
    col, row = parts
    if col < 0 or row < 0:
        raise ValueError("zoom_cell coordinates must be non-negative")
    return (col, row)


def read_zoom_cell(cli_value: str | None, config: Mapping[str, object], key: str) -> tuple[int, int] | None:
    if cli_value is not None:
        return parse_zoom_cell(cli_value)
    raw = config.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    parts = cast(list[object], raw)
    return parse_zoom_cell(",".join(str(part) for part in parts))


def read_bool(cli_value: bool, config: Mapping[str, object], key: str, *, default: bool = False) -> bool:
    raw = config.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean")
    return raw or cli_value
