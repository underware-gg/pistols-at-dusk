from __future__ import annotations

from typing import Literal, TypeAlias


ContentBox: TypeAlias = tuple[int, int, int, int]
Rect: TypeAlias = tuple[int, int, int, int]
GuideLineMode: TypeAlias = Literal["separated", "overlay"]
NormalizeCellSizeSetting: TypeAlias = int | Literal["auto"] | None
