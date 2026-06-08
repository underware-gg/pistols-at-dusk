"""Shared compatibility-family path records used by legacy and staged loaders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompatibilityFamilyPaths:
    root: Path
    tiles_path: Path
    aliases_path: Path
    clusters_path: Path
    constructions_path: Path | None = None
    composite_tiles_path: Path | None = None
    attachments_path: Path | None = None

    @classmethod
    def for_legacy_root(cls, root: Path) -> CompatibilityFamilyPaths:
        constructions_path = root / "constructions.json"
        composite_tiles_path = root / "composite_tiles.json"
        attachments_path = root / "attachments.json"
        return cls(
            root=root,
            tiles_path=root / "tiles.json",
            aliases_path=root / "aliases.json",
            clusters_path=root / "clusters.json",
            constructions_path=constructions_path if constructions_path.exists() else None,
            composite_tiles_path=composite_tiles_path if composite_tiles_path.exists() else None,
            attachments_path=attachments_path if attachments_path.exists() else None,
        )
