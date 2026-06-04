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


def contact_mask(grid: Grid, side: str, inset: int = 0) -> Mask:
    """The 1px contact line for ``side``, oriented per the module contract.

    ``inset`` reads the line that many pixels *in* from ``side``'s edge rather
    than at the literal edge — the content-box edge for art drawn within a
    consistent transparent margin ("gutter"); see ADR 0008. ``inset=0`` is the
    literal cell edge.
    """
    _validate_grid(grid)
    if inset < 0:
        raise ValueError(f"inset must be non-negative, got {inset}")
    height = len(grid)
    width = len(grid[0])
    if side in ("north", "south"):
        if inset >= height:
            raise ValueError(f"inset {inset} exceeds grid height {height} for side {side!r}")
        row = grid[inset] if side == "north" else grid[height - 1 - inset]
        return tuple(bool(cell) for cell in row)
    if side in ("east", "west"):
        if inset >= width:
            raise ValueError(f"inset {inset} exceeds grid width {width} for side {side!r}")
        col = inset if side == "west" else width - 1 - inset
        return tuple(bool(row[col]) for row in grid)
    raise ValueError(f"unknown side {side!r}; expected one of {SIDES}")


def derive_side_masks(
    grid: Grid, *, top: int = 0, right: int = 0, bottom: int = 0, left: int = 0
) -> dict[str, Mask]:
    """Per-side contact masks, each read at its side's content-box edge.

    The per-side insets (``top``/``right``/``bottom``/``left``, default 0 = the
    literal cell edge) absorb a consistent transparent gutter so painted content
    is compared against painted content (ADR 0008).
    """
    _validate_grid(grid)
    return {
        "north": contact_mask(grid, "north", top),
        "south": contact_mask(grid, "south", bottom),
        "east": contact_mask(grid, "east", right),
        "west": contact_mask(grid, "west", left),
    }
