from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, Union, cast

from typing_extensions import TypeAlias

from tile_library import PlaceableKind, PlaceableRef
from _manifest_utils import require_exactly_one


TileRefToken: TypeAlias = Union[str, int, None, dict[str, object], list["TileRefToken"]]


DEFAULT_SCENE_RULES_DIRNAME = "scene-rules"


@dataclass(frozen=True)
class SceneRuleStampCandidate:
    candidate_id: str
    weight: float
    ref: TileRefToken
    layer: str | None = None


@dataclass(frozen=True)
class SceneRuleEntityCandidate:
    candidate_id: str
    weight: float
    construction_id: str | None = None
    layer: str | None = None
    params: dict[str, object] | None = None
    placeable_kind: PlaceableKind = "construction"
    placeable_id: str | None = None

    def __post_init__(self) -> None:
        resolved_placeable_id = self.placeable_id
        if resolved_placeable_id is None and self.construction_id is not None:
            resolved_placeable_id = self.construction_id
        if resolved_placeable_id is None:
            raise ValueError("SceneRuleEntityCandidate.placeable_id is required when construction_id is absent")
        if self.construction_id is not None and (
            self.placeable_kind != "construction" or self.construction_id != resolved_placeable_id
        ):
            raise ValueError(
                "SceneRuleEntityCandidate.construction_id is only valid for matching construction placeables"
            )
        object.__setattr__(self, "placeable_id", resolved_placeable_id)

    @property
    def placeable_ref(self) -> PlaceableRef:
        placeable_id = self.placeable_id
        if placeable_id is None:
            raise RuntimeError("SceneRuleEntityCandidate.placeable_id was not normalised")
        return PlaceableRef(kind=self.placeable_kind, id=placeable_id)


@dataclass(frozen=True)
class SceneRuleSceneCandidate:
    candidate_id: str
    weight: float
    scene_id: str
    args: dict[str, object] | None = None


SceneRuleCandidate: TypeAlias = Union[
    SceneRuleStampCandidate,
    SceneRuleEntityCandidate,
    SceneRuleSceneCandidate,
]


@dataclass(frozen=True)
class SceneRulesetSpec:
    ruleset_id: str
    description: str
    catalogues: dict[str, tuple[SceneRuleCandidate, ...]]

    def require_catalogue(self, catalogue_id: str) -> tuple[SceneRuleCandidate, ...]:
        try:
            return self.catalogues[catalogue_id]
        except KeyError as exc:
            available = ", ".join(sorted(self.catalogues)) or "<none>"
            raise ValueError(
                f"Unknown scene ruleset catalogue: {catalogue_id!r}. "
                f"Available catalogues in {self.ruleset_id!r}: {available}"
            ) from exc


@dataclass(frozen=True)
class SceneRulesetLibrary:
    root: Path
    specs: dict[str, SceneRulesetSpec]

    def require(self, ruleset_id: str) -> SceneRulesetSpec:
        try:
            return self.specs[ruleset_id]
        except KeyError as exc:
            available = ", ".join(sorted(self.specs)) or "<none>"
            raise ValueError(
                f"Unknown scene ruleset: {ruleset_id!r}. Available rulesets: {available}"
            ) from exc


class SceneRuleStampCandidateConfig(TypedDict, total=False):
    id: str
    kind: str
    weight: int | float
    ref: TileRefToken
    layer: str


class SceneRuleEntityCandidateConfig(TypedDict, total=False):
    id: str
    kind: str
    weight: int | float
    construction: str
    layer: str
    params: dict[str, object]


class SceneRuleSceneCandidateConfig(TypedDict, total=False):
    id: str
    kind: str
    weight: int | float
    scene: str
    args: dict[str, object]


SceneRuleCandidateConfig: TypeAlias = Union[
    SceneRuleStampCandidateConfig,
    SceneRuleEntityCandidateConfig,
    SceneRuleSceneCandidateConfig,
]


class SceneRulesetSpecConfig(TypedDict, total=False):
    ruleset_id: str
    description: str
    catalogues: dict[str, list[SceneRuleCandidateConfig]]


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def _require_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    return cast(list[object], value)


def _require_string(value: object, *, context: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    if not allow_empty and value == "":
        raise ValueError(f"{context} must not be empty")
    return value


def _require_weight(value: object, *, context: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{context} must be a number")
    weight = float(value)
    if weight <= 0:
        raise ValueError(f"{context} must be greater than 0")
    return weight


def _is_tile_ref_token(value: object) -> bool:
    if value is None or isinstance(value, (str, int)):
        return True
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return all(isinstance(key, str) for key in mapping.keys())
    if isinstance(value, list):
        items = cast(list[object], value)
        return all(_is_tile_ref_token(item) for item in items)
    return False


def _load_scene_rule_candidate(
    raw_candidate: object,
    *,
    context: str,
    seen_candidate_ids: set[str],
) -> SceneRuleCandidate:
    candidate = _require_mapping(raw_candidate, context=context)
    candidate_kind = _require_string(candidate.get("kind"), context=f"{context} kind")
    candidate_id = _require_string(candidate.get("id"), context=f"{context} id")
    if candidate_id in seen_candidate_ids:
        raise ValueError(f"Duplicate scene rule candidate id in {context}: {candidate_id!r}")
    seen_candidate_ids.add(candidate_id)
    weight = _require_weight(candidate.get("weight"), context=f"{context} weight")
    if candidate_kind == "stamp":
        if "ref" not in candidate:
            raise ValueError(f"{context} kind 'stamp' is missing required field 'ref'")
        ref = candidate["ref"]
        if not _is_tile_ref_token(ref):
            raise ValueError(f"{context} ref must be a valid tile ref token")
        layer = candidate.get("layer")
        if layer is not None:
            layer = _require_string(layer, context=f"{context} layer")
        return SceneRuleStampCandidate(
            candidate_id=candidate_id,
            weight=weight,
            ref=cast(TileRefToken, ref),
            layer=layer,
        )
    if candidate_kind == "entity":
        require_exactly_one(candidate, "construction", "placeable", context=context)
        if "placeable" in candidate:
            placeable_ref = PlaceableRef.from_mapping(candidate["placeable"], context=f"{context} placeable")
            construction_id: str | None = None
        else:
            construction_id = _require_string(candidate.get("construction"), context=f"{context} construction")
            placeable_ref = PlaceableRef.construction(construction_id)
        layer = candidate.get("layer")
        if layer is not None:
            layer = _require_string(layer, context=f"{context} layer")
        raw_params = candidate.get("params")
        params = None if raw_params is None else _require_mapping(raw_params, context=f"{context} params")
        return SceneRuleEntityCandidate(
            candidate_id=candidate_id,
            weight=weight,
            construction_id=construction_id,
            layer=layer,
            params=None if params is None else dict(params),
            placeable_kind=placeable_ref.kind,
            placeable_id=placeable_ref.id,
        )
    if candidate_kind == "scene":
        scene_id = _require_string(candidate.get("scene"), context=f"{context} scene")
        raw_args = candidate.get("args")
        args = None if raw_args is None else _require_mapping(raw_args, context=f"{context} args")
        return SceneRuleSceneCandidate(
            candidate_id=candidate_id,
            weight=weight,
            scene_id=scene_id,
            args=None if args is None else dict(args),
        )
    raise ValueError(f"{context} has unknown candidate kind {candidate_kind!r}")


def _load_scene_ruleset_spec(path: Path) -> SceneRulesetSpec:
    raw = _require_mapping(load_json(path), context=str(path))
    ruleset_id = _require_string(raw.get("ruleset_id"), context=f"{path} ruleset_id")
    if path.stem != ruleset_id:
        raise ValueError(f"{path} ruleset_id {ruleset_id!r} must match filename stem {path.stem!r}")
    raw_catalogues = _require_mapping(raw.get("catalogues"), context=f"{path} catalogues")
    catalogues: dict[str, tuple[SceneRuleCandidate, ...]] = {}
    for catalogue_id, raw_candidates in raw_catalogues.items():
        candidate_list = _require_list(raw_candidates, context=f"{path} catalogue {catalogue_id!r}")
        if not candidate_list:
            raise ValueError(f"{path} catalogue {catalogue_id!r} must not be empty")
        seen_candidate_ids: set[str] = set()
        catalogues[catalogue_id] = tuple(
            _load_scene_rule_candidate(
                raw_candidate,
                context=f"{path} catalogue {catalogue_id!r} candidate[{index}]",
                seen_candidate_ids=seen_candidate_ids,
            )
            for index, raw_candidate in enumerate(candidate_list)
        )
    return SceneRulesetSpec(
        ruleset_id=ruleset_id,
        description=_require_string(raw.get("description"), context=f"{path} description", allow_empty=True),
        catalogues=catalogues,
    )


def _resolve_path(base: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base / path).resolve()


def load_scene_ruleset_library(base_dir: Path, raw_dir: str | None) -> SceneRulesetLibrary:
    rules_dir = (
        _resolve_path(base_dir, raw_dir)
        if raw_dir is not None
        else (base_dir / DEFAULT_SCENE_RULES_DIRNAME).resolve()
    )
    if not rules_dir.exists():
        if raw_dir is not None:
            raise ValueError(f"Configured scene_rules_dir does not exist: {rules_dir}")
        return SceneRulesetLibrary(root=rules_dir, specs={})
    if not rules_dir.is_dir():
        raise ValueError(f"scene_rules_dir must be a directory: {rules_dir}")

    specs: dict[str, SceneRulesetSpec] = {}
    for path in sorted(rules_dir.glob("*.json")):
        spec = _load_scene_ruleset_spec(path)
        if spec.ruleset_id in specs:
            raise ValueError(f"Duplicate scene ruleset id {spec.ruleset_id!r} in {rules_dir}")
        specs[spec.ruleset_id] = spec
    return SceneRulesetLibrary(root=rules_dir, specs=specs)
