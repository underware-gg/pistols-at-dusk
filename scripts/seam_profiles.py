"""Seam-profile derivation core (ADR 0007; design D1/D2/D4).

Turns a tile's *occupancy grid* — already background-normalised, ``True`` =
painted, ``False`` = empty/transparent — into a per-side contact mask: the 1px
contact line of each edge (D2/D4, silhouette-only for v1).

Masks are oriented so facing sides of abutting tiles compare index-for-index
(see :data:`SIDES`): east/west are read top -> bottom, north/south left ->
right. A's ``east`` therefore aligns with its neighbour's ``west``.

This module is pure. Loading sheet pixels and applying the transparency /
``render_variant`` background normalisation that *produce* the occupancy grid
belong to the ingest layer, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

Grid = Sequence[Sequence[bool]]
Mask = tuple[bool, ...]

SIDES: tuple[str, ...] = ("north", "south", "east", "west")


def _validate_grid(grid: Grid) -> None:
    if not grid or not grid[0]:
        raise ValueError("occupancy grid must be non-empty")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("occupancy grid must be rectangular")


def contact_mask(grid: Grid, side: str) -> Mask:
    """The 1px contact line for ``side``, oriented per the module contract."""
    _validate_grid(grid)
    if side == "north":
        return tuple(bool(cell) for cell in grid[0])
    if side == "south":
        return tuple(bool(cell) for cell in grid[-1])
    if side == "west":
        return tuple(bool(row[0]) for row in grid)
    if side == "east":
        return tuple(bool(row[-1]) for row in grid)
    raise ValueError(f"unknown side {side!r}; expected one of {SIDES}")


def derive_side_masks(grid: Grid) -> dict[str, Mask]:
    """Per-side contact masks for all four sides of a tile's occupancy grid."""
    _validate_grid(grid)
    return {side: contact_mask(grid, side) for side in SIDES}
