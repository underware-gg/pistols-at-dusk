from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import cast


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "prototypes/minimal8-harness/scene-templates/party_menu_character_stats.json"
REFERENCE_PATH = (
    ROOT / "prototypes/minimal8-harness/reference-transforms/reference-party-menu-character-stats.json"
)
CELL_RE = re.compile(r"^C(\d+)R(\d+)$")


def _selection_to_ref(selection: dict[str, object]) -> str:
    kind = selection["kind"]
    if kind == "tile":
        tile_id = str(selection["tile_id"])
        variant_id = selection.get("variant_id")
        if variant_id is not None:
            return f"minimal8@{variant_id}:{tile_id}"
        return tile_id
    if kind == "source_cell":
        sheet_col = int(cast("int | str", selection["sheet_col"]))
        sheet_row = int(cast("int | str", selection["sheet_row"]))
        variant_id = selection.get("variant_id")
        if variant_id is not None:
            return f"minimal8@{variant_id}#{sheet_col},{sheet_row}"
        source_id = str(selection["source_id"])
        match = re.fullmatch(r"minimal8@(.+)", source_id)
        if match is not None:
            return f"minimal8@{match.group(1)}#{sheet_col},{sheet_row}"
        return f"minimal8#{sheet_col},{sheet_row}"
    if kind == "blank":
        return "blank"
    raise AssertionError(f"unexpected selection kind {kind!r}")


class PartyMenuReferenceSyncTests(unittest.TestCase):
    def test_tracked_scene_background_matches_reviewed_reference_except_brown_trunk(self) -> None:
        scene = json.loads(SCENE_PATH.read_text())
        reference = json.loads(REFERENCE_PATH.read_text())

        background_cells: dict[str, str] = {}
        for op in scene["ops"]:
            if op.get("kind") != "stamp" or op.get("layer") != "background":
                continue
            cell = f"C{op['x'] + 1}R{op['y'] + 1}"
            background_cells[cell] = op["ref"]

        self.assertEqual(len(background_cells), 81)

        mismatches: list[tuple[str, str, str]] = []
        for cell, scene_ref in sorted(
            background_cells.items(),
            key=lambda item: tuple(
                int(part) for part in cast("re.Match[str]", CELL_RE.fullmatch(item[0])).groups()
            ),
        ):
            review = reference["reviews"].get(cell)
            self.assertIsNotNone(review, msg=f"missing review for {cell}")
            review_ref = _selection_to_ref(review["selection"])
            if cell == "C31R17":
                self.assertEqual(scene_ref, "minimal8:terrain:1,5")
                self.assertEqual(review_ref, "minimal8@2bit_colored_bg_green:minimal8:terrain:1,5")
                self.assertIn("brown", review["note"].lower())
                self.assertIn("green", review["note"].lower())
                continue
            if scene_ref != review_ref:
                mismatches.append((cell, scene_ref, review_ref))

        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
