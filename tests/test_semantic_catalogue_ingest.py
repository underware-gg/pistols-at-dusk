from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from semantic_catalogue_ingest import (
    AuthoredSemanticPatch,
    DetectedSemanticTile,
    ResolvedSemanticTile,
    content_hash_for_image,
    resolve_semantic_catalogue,
    semantic_catalogue_from_json,
    semantic_catalogue_to_json,
)


def _image(colour: tuple[int, int, int, int]) -> Image.Image:
    return Image.new("RGBA", (2, 2), colour)


class SemanticCatalogueIngestTests(unittest.TestCase):
    def test_content_hash_uses_real_canonical_rgba_pixels(self) -> None:
        red_rgba = _image((255, 0, 0, 255))
        red_rgb = Image.new("RGB", (2, 2), (255, 0, 0))
        blue_rgba = _image((0, 0, 255, 255))

        red_hash = content_hash_for_image(red_rgba)

        self.assertTrue(red_hash.startswith("content-sha256:"))
        self.assertEqual(red_hash, content_hash_for_image(red_rgb))
        self.assertNotEqual(red_hash, content_hash_for_image(blue_rgba))

    def test_identical_pixels_share_one_content_hash_identity(self) -> None:
        first = content_hash_for_image(_image((12, 34, 56, 255)))
        second = content_hash_for_image(_image((12, 34, 56, 255)))

        self.assertEqual(first, second)

    def test_resolver_applies_authored_patch_over_detected_base(self) -> None:
        content_hash = content_hash_for_image(_image((1, 2, 3, 255)))
        detected = (
            DetectedSemanticTile(
                content_hash=content_hash,
                facts={
                    "semantics": ("stool",),
                    "temperature": "warm",
                    "style": "wood",
                },
            ),
        )
        patch = (
            AuthoredSemanticPatch(
                content_hash=content_hash,
                facts={
                    "semantics": ("bed",),
                },
            ),
        )

        resolved = resolve_semantic_catalogue(detected, patch)

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].facts["semantics"], ("bed",))
        self.assertEqual(resolved[0].facts["temperature"], "warm")
        self.assertEqual(resolved[0].facts["style"], "wood")
        self.assertEqual(resolved[0].authored_fields, ("semantics",))

    def test_resolved_catalogue_serialization_is_deterministic(self) -> None:
        red = content_hash_for_image(_image((255, 0, 0, 255)))
        blue = content_hash_for_image(_image((0, 0, 255, 255)))
        first = resolve_semantic_catalogue(
            (
                DetectedSemanticTile(content_hash=blue, facts={"temperature": "cool"}),
                DetectedSemanticTile(content_hash=red, facts={"temperature": "warm"}),
            ),
            (
                AuthoredSemanticPatch(content_hash=red, facts={"contrast": "high"}),
                AuthoredSemanticPatch(content_hash=blue, facts={"contrast": "low"}),
            ),
        )
        second = resolve_semantic_catalogue(
            (
                DetectedSemanticTile(content_hash=red, facts={"temperature": "warm"}),
                DetectedSemanticTile(content_hash=blue, facts={"temperature": "cool"}),
            ),
            (
                AuthoredSemanticPatch(content_hash=blue, facts={"contrast": "low"}),
                AuthoredSemanticPatch(content_hash=red, facts={"contrast": "high"}),
            ),
        )

        first_json = semantic_catalogue_to_json(first)
        second_json = semantic_catalogue_to_json(second)

        self.assertEqual(first_json, second_json)
        self.assertEqual(semantic_catalogue_from_json(first_json), semantic_catalogue_from_json(second_json))

    def test_patch_for_unknown_content_hash_raises(self) -> None:
        known = content_hash_for_image(_image((1, 1, 1, 255)))
        unknown = content_hash_for_image(_image((2, 2, 2, 255)))

        with self.assertRaisesRegex(ValueError, "unknown content hashes"):
            resolve_semantic_catalogue(
                (DetectedSemanticTile(content_hash=known, facts={"temperature": "warm"}),),
                (AuthoredSemanticPatch(content_hash=unknown, facts={"temperature": "cool"}),),
            )

    def test_malformed_content_hash_raises_on_construct_and_load(self) -> None:
        with self.assertRaisesRegex(ValueError, "content-sha256"):
            DetectedSemanticTile(content_hash="sha256:" + "0" * 64, facts={"temperature": "warm"})

        payload: dict[str, object] = {
            "schema_version": 1,
            "tiles": [
                {
                    "content_hash": "content-sha256:" + "z" * 64,
                    "facts": {"temperature": "warm"},
                    "authored_fields": [],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "content-sha256"):
            semantic_catalogue_from_json(json.dumps(payload))

    def test_duplicate_detected_content_hash_raises(self) -> None:
        content_hash = content_hash_for_image(_image((3, 3, 3, 255)))

        with self.assertRaisesRegex(ValueError, "Duplicate detected semantic record"):
            resolve_semantic_catalogue(
                (
                    DetectedSemanticTile(content_hash=content_hash, facts={"temperature": "warm"}),
                    DetectedSemanticTile(content_hash=content_hash, facts={"temperature": "cool"}),
                )
            )

    def test_duplicate_authored_patch_content_hash_raises(self) -> None:
        content_hash = content_hash_for_image(_image((8, 8, 8, 255)))

        with self.assertRaisesRegex(ValueError, "Duplicate authored semantic patch"):
            resolve_semantic_catalogue(
                (DetectedSemanticTile(content_hash=content_hash, facts={"temperature": "warm"}),),
                (
                    AuthoredSemanticPatch(content_hash=content_hash, facts={"temperature": "cool"}),
                    AuthoredSemanticPatch(content_hash=content_hash, facts={"temperature": "neutral"}),
                ),
            )

    def test_unsupported_semantic_field_raises(self) -> None:
        content_hash = content_hash_for_image(_image((4, 4, 4, 255)))

        with self.assertRaisesRegex(ValueError, "unsupported semantic field"):
            DetectedSemanticTile(content_hash=content_hash, facts={"unknown": "value"})

    def test_catalogue_payload_round_trips_sequence_fields(self) -> None:
        content_hash = content_hash_for_image(_image((5, 5, 5, 255)))
        resolved = (
            ResolvedSemanticTile(
                content_hash=content_hash,
                facts={"semantics": ("door", "wood"), "style": None},
                authored_fields=("semantics",),
            ),
        )

        payload = json.loads(semantic_catalogue_to_json(resolved))
        self.assertEqual(payload["tiles"][0]["facts"]["semantics"], ["door", "wood"])

        loaded = semantic_catalogue_from_json(semantic_catalogue_to_json(resolved))
        self.assertEqual(loaded, resolved)

    def test_resolved_catalogue_deduplicates_authored_fields(self) -> None:
        content_hash = content_hash_for_image(_image((9, 9, 9, 255)))

        resolved = ResolvedSemanticTile(
            content_hash=content_hash,
            facts={"semantics": ("door",), "temperature": "warm"},
            authored_fields=("temperature", "semantics", "temperature"),
        )

        self.assertEqual(resolved.authored_fields, ("semantics", "temperature"))

    def test_resolved_catalogue_rejects_duplicate_content_hashes(self) -> None:
        content_hash = content_hash_for_image(_image((6, 6, 6, 255)))
        payload: dict[str, object] = {
            "schema_version": 1,
            "tiles": [
                {"content_hash": content_hash, "facts": {"temperature": "warm"}, "authored_fields": []},
                {"content_hash": content_hash, "facts": {"temperature": "cool"}, "authored_fields": []},
            ],
        }

        with self.assertRaisesRegex(ValueError, "Duplicate resolved semantic record"):
            semantic_catalogue_from_json(json.dumps(payload))

    def test_resolved_catalogue_rejects_authored_field_absent_from_facts(self) -> None:
        content_hash = content_hash_for_image(_image((7, 7, 7, 255)))

        with self.assertRaisesRegex(ValueError, "authored fields absent from facts"):
            ResolvedSemanticTile(
                content_hash=content_hash,
                facts={"semantics": ("door",)},
                authored_fields=("temperature",),
            )


if __name__ == "__main__":
    unittest.main()
