from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from semantic_catalogue_ingest import ResolvedSemanticTile
from semantic_catalogue_promotion import promote_semantic_catalogue
from tile_library import (
    CompositeTileCell,
    CompositeTileRecord,
    EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
    FixedConstruction,
    TileFamilyVariant,
    TileGenesis,
    TileLibraryUnit,
    TileRecord,
    attachment_sets_by_target,
    index_tiles_by_sheet_cell,
)


_HASH_A = "content-sha256:" + "a" * 64
_HASH_B = "content-sha256:" + "b" * 64
_HASH_C = "content-sha256:" + "c" * 64


def _tile(tile_id: str, *, sheet_col: int, meaning: str = "stool") -> TileRecord:
    return TileRecord(
        id=tile_id,
        family_id="test.family",
        layer="object",
        category="furniture",
        transparent=True,
        tags=("legacy",),
        genesis=TileGenesis(kind="sheet", sheet_col=sheet_col, sheet_row=0),
        variant_assets={"base": "sha256:" + "0" * 64},
        variant_atlas_cells={},
        walkable=False,
        blocking=True,
        requires_exposed_on=("north",),
        affordances=("sit",),
        alt_uses=("prop",),
        semantics=("old-semantic",),
        motifs=("old-motif",),
        meaning=meaning,
        source_notes="legacy source note",
    )


def _unit(
    *tiles: TileRecord,
    constructions: dict[str, FixedConstruction] | None = None,
    composite_tiles: dict[str, CompositeTileRecord] | None = None,
) -> TileLibraryUnit:
    tile_map = {tile.id: tile for tile in tiles}
    return TileLibraryUnit(
        family_id="test.family",
        tile_width=8,
        tile_height=8,
        render_step_width=None,
        render_step_height=None,
        default_variant_id="base",
        runtime_flippable=True,
        promoted_metadata=EMPTY_TILE_LIBRARY_PROMOTED_METADATA,
        root=Path("."),
        variants={"base": TileFamilyVariant(id="base", sheet_path=None, transparent_mode="none")},
        tiles=tile_map,
        aliases={},
        tiles_by_sheet_cell_index=index_tiles_by_sheet_cell(tile_map, context="test unit"),
        constructions=constructions or {},
        attachment_sets={},
        attachment_sets_by_target=attachment_sets_by_target({}),
        composite_tiles=composite_tiles or {},
        clusters={},
    )


class SemanticCataloguePromotionTests(unittest.TestCase):
    def test_promotion_refreshes_ingest_fields_and_preserves_runtime_authored_fields(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0, meaning="stool"))
        resolved = (
            ResolvedSemanticTile(
                content_hash=_HASH_A,
                facts={
                    "category": "bedding",
                    "layer": "floor",
                    "meaning": "bed",
                    "tags": ("bed", "furniture"),
                    "semantics": ("sleep",),
                },
                authored_fields=("meaning",),
            ),
        )

        promoted = promote_semantic_catalogue(
            unit,
            resolved=resolved,
            content_hash_by_tile_id={"test.tile": _HASH_A},
        )

        promoted_tile = promoted.tiles["test.tile"]
        self.assertEqual(promoted_tile.meaning, "bed")
        self.assertEqual(promoted_tile.tags, ("bed", "furniture"))
        self.assertEqual(promoted_tile.semantics, ("sleep",))
        self.assertEqual(promoted_tile.motifs, ())
        self.assertIsNone(promoted_tile.source_notes)
        self.assertEqual(promoted_tile.category, "bedding")
        self.assertEqual(promoted_tile.layer, "floor")
        self.assertFalse(promoted_tile.walkable)
        self.assertTrue(promoted_tile.blocking)
        self.assertEqual(promoted_tile.requires_exposed_on, ("north",))
        self.assertEqual(promoted_tile.affordances, ("sit",))
        self.assertEqual(promoted_tile.alt_uses, ("prop",))
        self.assertEqual(promoted_tile.variant_assets, unit.tiles["test.tile"].variant_assets)
        self.assertIsNot(promoted.tiles["test.tile"], unit.tiles["test.tile"])

    def test_one_content_record_fans_out_to_multiple_physical_tiles(self) -> None:
        unit = _unit(
            _tile("test.tile.a", sheet_col=0, meaning="stool"),
            _tile("test.tile.b", sheet_col=1, meaning="chair"),
        )
        resolved = (
            ResolvedSemanticTile(
                content_hash=_HASH_A,
                facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("shared",)},
            ),
        )

        promoted = promote_semantic_catalogue(
            unit,
            resolved=resolved,
            content_hash_by_tile_id={
                "test.tile.a": _HASH_A,
                "test.tile.b": _HASH_A,
            },
        )

        self.assertEqual(promoted.tiles["test.tile.a"].meaning, "bed")
        self.assertEqual(promoted.tiles["test.tile.b"].meaning, "bed")
        self.assertEqual(promoted.tiles["test.tile.a"].tags, ("shared",))
        self.assertEqual(promoted.tiles["test.tile.b"].tags, ("shared",))

    def test_missing_required_ingest_field_raises(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0))

        with self.assertRaisesRegex(
            ValueError,
            f"{re.escape(_HASH_A)}.*tile 'test.tile' omits required ingest field 'category'",
        ):
            promote_semantic_catalogue(
                unit,
                resolved=(
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"layer": "object", "meaning": "bed", "tags": ("bed",)},
                    ),
                ),
                content_hash_by_tile_id={"test.tile": _HASH_A},
            )

    def test_with_tiles_rebinds_construction_and_composite_tile_references(self) -> None:
        tile_a = _tile("test.tile.a", sheet_col=0)
        tile_b = _tile("test.tile.b", sheet_col=1)
        fixed = FixedConstruction(
            id="test.fixed",
            collection_id="test.collection",
            cells=((tile_a, tile_b),),
        )
        composite = CompositeTileRecord(
            id="test.composite",
            family_id="test.family",
            collection_id="test.collection",
            cells=((CompositeTileCell(tile=tile_a, x=0, y=0), CompositeTileCell(tile=tile_b, x=1, y=0)),),
        )
        unit = _unit(
            tile_a,
            tile_b,
            constructions={fixed.id: fixed},
            composite_tiles={composite.id: composite},
        )
        resolved = (
            ResolvedSemanticTile(
                content_hash=_HASH_A,
                facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("bed",)},
            ),
            ResolvedSemanticTile(
                content_hash=_HASH_B,
                facts={"category": "furniture", "layer": "object", "meaning": "chair", "tags": ("chair",)},
            ),
        )

        promoted = promote_semantic_catalogue(
            unit,
            resolved=resolved,
            content_hash_by_tile_id={
                tile_a.id: _HASH_A,
                tile_b.id: _HASH_B,
            },
        )

        promoted_fixed = promoted.constructions["test.fixed"]
        self.assertIsInstance(promoted_fixed, FixedConstruction)
        assert isinstance(promoted_fixed, FixedConstruction)
        self.assertIs(promoted_fixed.cells[0][0], promoted.tiles[tile_a.id])
        self.assertIs(promoted_fixed.cells[0][1], promoted.tiles[tile_b.id])
        self.assertIsNot(promoted_fixed.cells[0][0], tile_a)
        promoted_composite = promoted.composite_tiles["test.composite"]
        first_cell = promoted_composite.cells[0][0]
        second_cell = promoted_composite.cells[0][1]
        assert first_cell is not None
        assert second_cell is not None
        self.assertIs(first_cell.tile, promoted.tiles[tile_a.id])
        self.assertIs(second_cell.tile, promoted.tiles[tile_b.id])
        self.assertIsNot(first_cell.tile, tile_a)

    def test_missing_content_hash_for_tile_raises(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0))

        with self.assertRaisesRegex(ValueError, "Missing content hash for tile 'test.tile'"):
            promote_semantic_catalogue(
                unit,
                resolved=(
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("bed",)},
                    ),
                ),
                content_hash_by_tile_id={},
            )

    def test_missing_resolved_record_raises(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0))

        with self.assertRaisesRegex(ValueError, f"test.tile.*{re.escape(_HASH_B)}.*has no resolved semantic record"):
            promote_semantic_catalogue(
                unit,
                resolved=(
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("bed",)},
                    ),
                ),
                content_hash_by_tile_id={"test.tile": _HASH_B},
            )

    def test_unused_resolved_record_raises(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0))

        with self.assertRaisesRegex(ValueError, "unused content hashes"):
            promote_semantic_catalogue(
                unit,
                resolved=(
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("bed",)},
                    ),
                    ResolvedSemanticTile(
                        content_hash=_HASH_C,
                        facts={"category": "furniture", "layer": "object", "meaning": "unused", "tags": ("unused",)},
                    ),
                ),
                content_hash_by_tile_id={"test.tile": _HASH_A},
            )

    def test_duplicate_resolved_record_raises(self) -> None:
        unit = _unit(_tile("test.tile", sheet_col=0))

        with self.assertRaisesRegex(ValueError, "Duplicate resolved semantic record"):
            promote_semantic_catalogue(
                unit,
                resolved=(
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"category": "furniture", "layer": "object", "meaning": "bed", "tags": ("bed",)},
                    ),
                    ResolvedSemanticTile(
                        content_hash=_HASH_A,
                        facts={"category": "furniture", "layer": "object", "meaning": "duplicate", "tags": ("duplicate",)},
                    ),
                ),
                content_hash_by_tile_id={"test.tile": _HASH_A},
            )


if __name__ == "__main__":
    unittest.main()
