"""Composable seam matching (ADR 0007; design decisions D6/D7/D8).

A *seam mask* is the occupancy of one tile-side's 1px contact line — a sequence
of bools, painted (``True``) vs empty (``False``). Two sides "fit" when a matcher
agrees they line up. Matchers are pure scored functions; a thin policy decides
which are enabled and how their scores combine into a verdict, so matching can be
reconfigured and hill-climb-tuned without touching matcher code.

Masks are pre-oriented by the caller: index ``i`` of one side faces index ``i``
of the side it abuts. The matchers here are purely positional.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

Mask = Sequence[bool]
Matcher = Callable[[Mask, Mask], float]


def _check_pair(a: Mask, b: Mask) -> None:
    if len(a) != len(b):
        raise ValueError(f"seam masks differ in length: {len(a)} vs {len(b)}")
    if len(a) == 0:
        raise ValueError("seam masks must be non-empty")


def equality_score(a: Mask, b: Mask) -> float:
    """Fraction of positions where the masks agree (butt-join fit).

    ``1.0`` when identical (including ``null == null`` — two empty/finished edges
    abut with no break); ``0.0`` when fully opposite.
    """
    _check_pair(a, b)
    agree = sum(1 for x, y in zip(a, b) if bool(x) == bool(y))
    return agree / len(a)


def complement_score(a: Mask, b: Mask) -> float:
    """Fraction of positions where the masks are opposite (interlocking fit).

    ``1.0`` when each painted pixel faces an empty one (tab/slot); ``0.0`` when
    identical. ``null`` vs ``null`` scores ``0.0`` — nothing interlocks.
    """
    _check_pair(a, b)
    opposite = sum(1 for x, y in zip(a, b) if bool(x) != bool(y))
    return opposite / len(a)


MATCHERS: dict[str, Matcher] = {
    "equality": equality_score,
    "complement": complement_score,
}


@dataclass(frozen=True)
class MatchPolicy:
    """Decides fit from one or more enabled matchers.

    The verdict is the ``max`` score over enabled matchers compared to
    ``threshold`` — a side pair fits if *any* enabled matcher accepts it (a clean
    butt-join *or* a clean interlock). ``threshold`` defaults to exact (``1.0``);
    relax it for tuning. Disable a matcher by omitting it from ``enabled``.
    """

    enabled: tuple[str, ...] = ("equality", "complement")
    threshold: float = 1.0

    def __post_init__(self) -> None:
        if not self.enabled:
            raise ValueError("MatchPolicy requires at least one enabled matcher")
        unknown = [name for name in self.enabled if name not in MATCHERS]
        if unknown:
            raise ValueError(f"unknown matcher(s): {unknown!r}; known: {sorted(MATCHERS)}")

    def scores(self, a: Mask, b: Mask) -> dict[str, float]:
        """Per-matcher score for the pair, for inspection and tuning."""
        return {name: MATCHERS[name](a, b) for name in self.enabled}

    def combined(self, a: Mask, b: Mask) -> float:
        """The single fit score: the best (max) over enabled matchers."""
        return max(self.scores(a, b).values())

    def fits(self, a: Mask, b: Mask) -> bool:
        """Whether the pair fits under this policy's threshold."""
        return self.combined(a, b) >= self.threshold
