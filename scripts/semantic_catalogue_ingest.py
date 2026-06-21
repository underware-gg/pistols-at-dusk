"""Ingest-side semantic catalogue resolver.

This module owns the within-ingest non-clobber rule: detected base facts are
resolved with sparse authored patches, and authored facts win. It deliberately
does not model runtime-authored metadata preservation; promotion across the
runtime boundary owns that later concern.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol, TypeAlias, TypeVar, cast

from PIL import Image

from _manifest_utils import require_list, require_mapping
from pixel_content import canonical_rgba_bytes


CONTENT_HASH_ALGORITHM = "sha256"
CONTENT_HASH_PREFIX = f"content-{CONTENT_HASH_ALGORITHM}:"
CONTENT_HASH_DIGEST_LENGTH = 64
SEMANTIC_CATALOGUE_SCHEMA_VERSION = 1

_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")

_SEQUENCE_FACT_FIELDS = frozenset(
    {
        "tags",
        "semantics",
        "motifs",
    }
)

INGEST_SEMANTIC_FIELDS = frozenset(
    {
        "category",
        "contrast",
        "facing",
        "footprint",
        "layer",
        "meaning",
        "meaning_confidence",
        "motifs",
        "noise",
        "orientation",
        "overlay",
        "pose",
        "semantics",
        "source_notes",
        "style",
        "tags",
        "temperature",
        "usage",
    }
)

SemanticFactValue: TypeAlias = str | tuple[str, ...] | None
SemanticFacts: TypeAlias = Mapping[str, SemanticFactValue]


class HasContentHash(Protocol):
    @property
    def content_hash(self) -> str: ...


_HashIndexed = TypeVar("_HashIndexed", bound=HasContentHash)


def content_hash_for_image(image: Image.Image) -> str:
    digest = canonical_image_digest(image)
    return f"{CONTENT_HASH_PREFIX}{digest}"


def content_hash_for_variant_images(images_by_variant_id: Mapping[str, Image.Image]) -> str:
    if not images_by_variant_id:
        raise ValueError("content_hash_for_variant_images requires at least one variant image")
    digest = hashlib.sha256()
    digest.update(b"rgba8-variant-set\n")
    for variant_id in sorted(images_by_variant_id):
        variant_id_bytes = variant_id.encode("utf-8")
        image_digest = canonical_image_digest(images_by_variant_id[variant_id])
        digest.update(f"{len(variant_id_bytes)}:".encode("ascii"))
        digest.update(variant_id_bytes)
        digest.update(b":")
        digest.update(image_digest.encode("ascii"))
        digest.update(b"\n")
    return f"{CONTENT_HASH_PREFIX}{digest.hexdigest()}"


def canonical_image_digest(image: Image.Image) -> str:
    return hashlib.sha256(canonical_rgba_bytes(image)).hexdigest()


def _validate_content_hash(content_hash: str, *, context: str) -> None:
    if (
        not content_hash.startswith(CONTENT_HASH_PREFIX)
        or len(content_hash) != len(CONTENT_HASH_PREFIX) + CONTENT_HASH_DIGEST_LENGTH
    ):
        raise ValueError(f"{context} must be a {CONTENT_HASH_PREFIX}<64 hex chars> content hash")
    digest = content_hash[len(CONTENT_HASH_PREFIX) :]
    if any(char not in _LOWER_HEX_DIGITS for char in digest):
        raise ValueError(f"{context} must be a {CONTENT_HASH_PREFIX}<64 hex chars> content hash")


def _normalise_fact_value(field: str, value: SemanticFactValue, *, context: str) -> SemanticFactValue:
    if field in _SEQUENCE_FACT_FIELDS:
        if not isinstance(value, tuple):
            raise ValueError(f"{context}.{field} must be a tuple of strings")
        values = cast(tuple[object, ...], value)
        if any(not isinstance(item, str) for item in values):
            raise ValueError(f"{context}.{field} must be a tuple of strings")
        return cast(tuple[str, ...], values)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{context}.{field} must be a string or null")
    return value


def _normalise_facts(facts: SemanticFacts, *, context: str) -> Mapping[str, SemanticFactValue]:
    normalised: dict[str, SemanticFactValue] = {}
    for field, value in facts.items():
        if field not in INGEST_SEMANTIC_FIELDS:
            raise ValueError(f"{context} declares unsupported semantic field {field!r}")
        normalised[field] = _normalise_fact_value(field, value, context=context)
    return MappingProxyType(normalised)


@dataclass(frozen=True)
class DetectedSemanticTile:
    content_hash: str
    facts: SemanticFacts

    def __post_init__(self) -> None:
        _validate_content_hash(self.content_hash, context="DetectedSemanticTile.content_hash")
        object.__setattr__(self, "facts", _normalise_facts(self.facts, context=f"detected {self.content_hash}"))


@dataclass(frozen=True)
class AuthoredSemanticPatch:
    content_hash: str
    facts: SemanticFacts

    def __post_init__(self) -> None:
        _validate_content_hash(self.content_hash, context="AuthoredSemanticPatch.content_hash")
        object.__setattr__(self, "facts", _normalise_facts(self.facts, context=f"authored patch {self.content_hash}"))


@dataclass(frozen=True)
class ResolvedSemanticTile:
    content_hash: str
    facts: SemanticFacts
    authored_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_content_hash(self.content_hash, context="ResolvedSemanticTile.content_hash")
        object.__setattr__(self, "facts", _normalise_facts(self.facts, context=f"resolved {self.content_hash}"))
        authored_fields = tuple(sorted(set(self.authored_fields)))
        unknown_fields = sorted(set(authored_fields) - set(self.facts))
        if unknown_fields:
            raise ValueError(
                f"Resolved semantic record {self.content_hash!r} lists authored fields absent from facts: "
                f"{', '.join(unknown_fields)}"
            )
        object.__setattr__(self, "authored_fields", authored_fields)

    def to_payload(self) -> dict[str, object]:
        return {
            "content_hash": self.content_hash,
            "facts": _facts_payload(self.facts),
            "authored_fields": list(self.authored_fields),
        }


def _facts_payload(facts: SemanticFacts) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in sorted(facts):
        value = facts[field]
        payload[field] = list(value) if isinstance(value, tuple) else value
    return payload


def index_by_content_hash(
    items: tuple[_HashIndexed, ...],
    *,
    kind: str,
) -> dict[str, _HashIndexed]:
    by_hash: dict[str, _HashIndexed] = {}
    for item in items:
        content_hash = item.content_hash
        if content_hash in by_hash:
            raise ValueError(f"Duplicate {kind} for content hash {content_hash!r}")
        by_hash[content_hash] = item
    return by_hash


def resolve_semantic_catalogue(
    detected_base: tuple[DetectedSemanticTile, ...],
    authored_patches: tuple[AuthoredSemanticPatch, ...] = (),
) -> tuple[ResolvedSemanticTile, ...]:
    detected_by_hash = index_by_content_hash(
        detected_base,
        kind="detected semantic record",
    )
    patches_by_hash = index_by_content_hash(
        authored_patches,
        kind="authored semantic patch",
    )
    unknown_patches = sorted(set(patches_by_hash) - set(detected_by_hash))
    if unknown_patches:
        raise ValueError(f"Authored semantic patch references unknown content hashes: {', '.join(unknown_patches)}")

    resolved: list[ResolvedSemanticTile] = []
    for content_hash in sorted(detected_by_hash):
        base = detected_by_hash[content_hash]
        patch = patches_by_hash.get(content_hash)
        merged = dict(base.facts)
        authored_fields: tuple[str, ...] = ()
        if patch is not None:
            merged.update(patch.facts)
            authored_fields = tuple(patch.facts)
        resolved.append(
            ResolvedSemanticTile(
                content_hash=content_hash,
                facts=merged,
                authored_fields=authored_fields,
            )
        )
    return tuple(resolved)


def semantic_catalogue_payload(records: tuple[ResolvedSemanticTile, ...]) -> dict[str, object]:
    return {
        "schema_version": SEMANTIC_CATALOGUE_SCHEMA_VERSION,
        "tiles": [record.to_payload() for record in sorted(records, key=lambda item: item.content_hash)],
    }


def semantic_catalogue_to_json(records: tuple[ResolvedSemanticTile, ...]) -> str:
    return semantic_payload_to_json(semantic_catalogue_payload(records))


def authored_patch_payload(patches: Iterable[AuthoredSemanticPatch]) -> dict[str, object]:
    return {
        "schema_version": SEMANTIC_CATALOGUE_SCHEMA_VERSION,
        "patches": [
            {
                "content_hash": patch.content_hash,
                "facts": _facts_payload(patch.facts),
            }
            for patch in sorted(patches, key=lambda item: item.content_hash)
        ],
    }


def authored_patch_to_json(patches: tuple[AuthoredSemanticPatch, ...]) -> str:
    return semantic_payload_to_json(authored_patch_payload(patches))


def detected_base_payload(records: Iterable[DetectedSemanticTile]) -> dict[str, object]:
    return {
        "schema_version": SEMANTIC_CATALOGUE_SCHEMA_VERSION,
        "tiles": [
            {
                "content_hash": record.content_hash,
                "facts": _facts_payload(record.facts),
            }
            for record in sorted(records, key=lambda item: item.content_hash)
        ],
    }


def detected_base_to_json(records: tuple[DetectedSemanticTile, ...]) -> str:
    return semantic_payload_to_json(detected_base_payload(records))


def semantic_payload_to_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def semantic_catalogue_from_payload(payload: object, *, context: str = "semantic catalogue") -> tuple[ResolvedSemanticTile, ...]:
    mapping = require_mapping(payload, context=context)
    if mapping.get("schema_version") != SEMANTIC_CATALOGUE_SCHEMA_VERSION:
        raise ValueError(f"{context} schema_version must be {SEMANTIC_CATALOGUE_SCHEMA_VERSION}")
    tile_payloads = require_list(mapping.get("tiles"), context=f"{context}.tiles")
    records: list[ResolvedSemanticTile] = []
    for index, raw_tile in enumerate(tile_payloads):
        tile_context = f"{context}.tiles[{index}]"
        tile_mapping = require_mapping(raw_tile, context=tile_context)
        content_hash = tile_mapping.get("content_hash")
        if not isinstance(content_hash, str):
            raise ValueError(f"{tile_context}.content_hash must be a string")
        facts = _facts_from_payload(tile_mapping.get("facts"), context=f"{tile_context}.facts")
        authored_fields = _authored_fields_from_payload(
            tile_mapping.get("authored_fields", []),
            context=f"{tile_context}.authored_fields",
        )
        records.append(ResolvedSemanticTile(content_hash=content_hash, facts=facts, authored_fields=authored_fields))
    return tuple(
        index_by_content_hash(
            tuple(records),
            kind="resolved semantic record",
        ).values()
    )


def semantic_catalogue_from_json(payload: str) -> tuple[ResolvedSemanticTile, ...]:
    return semantic_catalogue_from_payload(json.loads(payload))


def _facts_from_payload(raw: object, *, context: str) -> dict[str, SemanticFactValue]:
    mapping = require_mapping(raw, context=context)
    facts: dict[str, SemanticFactValue] = {}
    for field, value in mapping.items():
        if field in _SEQUENCE_FACT_FIELDS:
            facts[field] = tuple(_string_list_from_payload(value, context=f"{context}.{field}"))
        else:
            facts[field] = cast(str | None, value)
    return facts


def _authored_fields_from_payload(raw: object, *, context: str) -> tuple[str, ...]:
    return tuple(_string_list_from_payload(raw, context=context))


def _string_list_from_payload(raw: object, *, context: str) -> list[str]:
    values = require_list(raw, context=context)
    if any(not isinstance(item, str) for item in values):
        raise ValueError(f"{context} must be an array of strings")
    return cast(list[str], values)
