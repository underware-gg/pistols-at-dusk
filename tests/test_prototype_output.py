from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import prototype_output


class PrototypeOutputArchivingTests(unittest.TestCase):
    def test_publish_staged_output_skips_archive_when_output_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "render.png"
            output_path.write_bytes(b"same-bytes")
            staged_path = prototype_output.create_staging_output_path(output_path)
            staged_path.write_bytes(b"same-bytes")

            result_path = prototype_output.publish_staged_output(output_path, staged_path)

            self.assertEqual(result_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertFalse(staged_path.exists())
            self.assertFalse((output_path.parent / "archive").exists())

    def test_publish_staged_output_archives_existing_output_when_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "render.png"
            output_path.write_bytes(b"before")
            staged_path = prototype_output.create_staging_output_path(output_path)
            staged_path.write_bytes(b"after")

            result_path = prototype_output.publish_staged_output(output_path, staged_path)
            archived_path = output_path.parent / "archive" / "render-0001.png"

            self.assertEqual(result_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertFalse(staged_path.exists())
            self.assertTrue(archived_path.exists())
            self.assertEqual(output_path.read_bytes(), b"after")
            self.assertEqual(archived_path.read_bytes(), b"before")

    def test_archive_existing_output_returns_none_when_no_output_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "missing.png"

            archived_path = prototype_output.archive_existing_output(output_path)

            self.assertIsNone(archived_path)
            self.assertFalse((output_path.parent / "archive").exists())
