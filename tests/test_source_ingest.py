from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import source_ingest
from minimal8_source_project import source_minimal8_project_path


class SourceIngestCliTests(unittest.TestCase):
    def test_main_inspect_source_cell_reports_region_cluster_and_mapped_tile(self) -> None:
        project_path = source_minimal8_project_path(self)
        stdout = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "source_ingest.py",
                "inspect-source-cell",
                str(project_path),
                "--tileset",
                "minimal8@2bit_colored_bg",
                "--sheet-col",
                "21",
                "--sheet-row",
                "4",
            ],
        ), redirect_stdout(stdout):
            source_ingest.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["sheet_cell"], {"col": 21, "row": 4, "label_col": 22, "label_row": 5})
        self.assertEqual(payload["source_layout"]["region"]["id"], "tileset.column_2")
        self.assertEqual(
            [cluster["id"] for cluster in payload["source_layout"]["clusters"]],
            ["tileset.column_2.cluster_01"],
        )
        self.assertEqual(payload["tile"]["id"], "minimal8:terrain:2,2")
        self.assertEqual(payload["tile"]["canonical_tile_id"], "minimal8:terrain:2,2")
        self.assertEqual(payload["tile"]["aliases"], ["underworld.glyph.c"])

    def test_main_inspect_source_cell_defaults_to_source_operator_project(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "source_ingest.py",
                "inspect-source-cell",
                "--tileset",
                "minimal8@2bit_colored_bg",
                "--sheet-col",
                "21",
                "--sheet-row",
                "4",
            ],
        ), redirect_stdout(stdout):
            source_ingest.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["tile"]["id"], "minimal8:terrain:2,2")

    def test_main_inspect_source_cell_distinguishes_region_membership_from_tile_mapping(self) -> None:
        project_path = source_minimal8_project_path(self)
        stdout = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "source_ingest.py",
                "inspect-source-cell",
                str(project_path),
                "--tileset",
                "minimal8@2bit_colored_bg",
                "--sheet-col",
                "21",
                "--sheet-row",
                "24",
            ],
        ), redirect_stdout(stdout):
            source_ingest.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["source_layout"]["region"]["id"], "tileset.column_2")
        self.assertEqual(
            [cluster["id"] for cluster in payload["source_layout"]["clusters"]],
            ["tileset.column_2.cluster_04"],
        )
        self.assertIsNone(payload["tile"])

    def test_main_validate_family_ingest_reports_complete_minimal8_family(self) -> None:
        project_path = source_minimal8_project_path(self)
        stdout = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "source_ingest.py",
                "validate-family-ingest",
                str(project_path),
                "--tileset",
                "minimal8@1bit_colored_bg",
            ],
        ), redirect_stdout(stdout):
            source_ingest.main()

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["tile_count"], 1408)

    def test_main_inspect_family_exports_characters_source_layout(self) -> None:
        project_path = source_minimal8_project_path(self, "project.minimal8.characters.json")
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "family-inspection"

            with patch.object(
                sys,
                "argv",
                [
                    "source_ingest.py",
                    "inspect-family",
                    str(project_path),
                    "--tileset",
                    "minimal8.characters@2bit_colored",
                    "--output-dir",
                    str(output_dir),
                ],
            ), redirect_stdout(stdout):
                source_ingest.main()

            reported_path = Path(stdout.getvalue().strip()).resolve()
            self.assertEqual(reported_path, output_dir.resolve())
            self.assertTrue((reported_path / "catalog.json").exists())
            self.assertTrue((reported_path / "sheet_grid.png").exists())
            self.assertTrue((reported_path / "source_layout.json").exists())
            self.assertTrue((reported_path / "source_layout.guide.png").exists())


if __name__ == "__main__":
    unittest.main()
