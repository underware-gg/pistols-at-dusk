#!/usr/bin/env python3
"""Shared metadata value objects for source-pack and runtime tile records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderTraits:
    occupancy_style: str | None = None
    gutter_policy: str | None = None
    background_treatment: str | None = None
    alignment_origin: str | None = None
    occlusion_mode: str | None = None

    def merged(self, overrides: RenderTraits) -> RenderTraits:
        return RenderTraits(
            occupancy_style=overrides.occupancy_style or self.occupancy_style,
            gutter_policy=overrides.gutter_policy or self.gutter_policy,
            background_treatment=overrides.background_treatment or self.background_treatment,
            alignment_origin=overrides.alignment_origin or self.alignment_origin,
            occlusion_mode=overrides.occlusion_mode or self.occlusion_mode,
        )


@dataclass(frozen=True)
class ModuleContextValue:
    axis_id: str
    value_id: str
    label: str | None = None
    notes: str | None = None
