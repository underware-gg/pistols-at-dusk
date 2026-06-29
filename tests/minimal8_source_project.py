from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from produce_minimal8_source_project import write_minimal8_source_pack_project


ROOT = Path(__file__).resolve().parents[1]


def source_minimal8_project_path(
    test_case: unittest.TestCase,
    project_name: str = "project.minimal8.json",
) -> Path:
    temp_dir = tempfile.TemporaryDirectory()
    test_case.addCleanup(temp_dir.cleanup)
    return write_minimal8_source_pack_project(
        ROOT / "prototypes" / "minimal8-harness" / project_name,
        Path(temp_dir.name) / f"source-{project_name}",
    )
