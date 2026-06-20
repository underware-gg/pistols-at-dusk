# Architecture Decisions

Architectural decisions are first-class documentation. Taken together, the records on this page are the project's **architectural history** — an append-only sequence of moments preserving the reasoning, forces, and alternatives in play when each decision landed.

Per the [Agent-Ready Documentation Standard v1.0](../../contributor/documentation-standard.md), this router lists every decision record and carries the conventions that govern them.

## Conventions

**Format.** Each record uses the Nygard ADR shape with three required sections: **Context**, **Decision**, **Consequences**. Records may carry additional fields (status, alternatives considered, stakeholders).

**Numbering.** Sequential, four-digit prefix on the filename (`NNNN-slug.md`) and matching heading. Numbers are permanent and never reused — a superseded record keeps its number.

**Status.** Each record carries one of: `accepted`, `superseded`, `extended`. New records open as `accepted`.

**Immutability.** A landed record's body (context, decision, consequences, alternatives, etc.) is **frozen**. It is never rewritten as the project evolves. The only field that updates after the record lands is its navigational header — `Status:`, `Superseded by:`, `Extended by:`.

**Supersede / extend.** When a later decision changes direction, write a **new** record. The new record names the prior record it supersedes (replaces) or extends (builds on). The prior record's status updates and gains a `Superseded by:` / `Extended by:` pointer; its body is untouched. Supersede chains form the historical spine — agents and humans trace them backwards to recover context.

**Co-location vs central.** Cross-cutting decisions live in this directory. Subsystem-local decisions may also live alongside the subsystem they govern (`docs/architecture/<subsystem>/NNNN-...`); each must still be linked from the index below so this router stays the single discovery surface.

**Distinction from living architecture.** Decision records explain *why* the project is the way it is at a moment in time. Living architecture / functional documents describe *what* the project is *today*. If an artefact should be rewritten when behaviour changes, it is a living doc; if it should be preserved and succeeded by a new record, it is a decision record.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-physical-address-is-canonical.md) | Physical Address Is Canonical Identity | accepted |
| [0002](0002-family-manifests-replace-python-catalogs.md) | Family Manifests Replace Python Semantic Catalogs | accepted |
| [0003](0003-scene-entities-are-first-class-runtime-objects.md) | Scene Entities Are First-Class Runtime Objects | accepted |
| [0004](0004-runtime-registry-loads-multiple-compatibility-units.md) | Runtime Registry Loads Multiple Compatibility Units | accepted |
| [0005](0005-runtime-tile-genesis-and-provenance.md) | Runtime Tile Genesis and Provenance | accepted |
| [0006](0006-defer-cross-kit-interchangeability-to-seam-profiles.md) | Defer Cross-Kit Interchangeability to Machine-Verifiable Seam Profiles | superseded |
| [0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md) | Adopt the Three-Axis Tile-Compatibility Model and Build Machine-Verifiable Seam Profiles | extended |
| [0008](0008-locate-seam-contact-line-at-content-box-edge.md) | Locate the Seam Contact Line at the Content-Box Edge via a Declared Cell-Content Inset | extended |
| [0009](0009-composition-asset-model.md) | Composition Asset Model: Tiles (incl. Metatiles), Constructions, Scenes, and Variations | accepted |
| [0010](0010-runtime-flippability-and-role-aware-frame-seams.md) | Runtime Flippability and Role-Aware Frame Seam Verification | accepted |
| [0011](0011-runtime-ingest-family-module-split.md) | Runtime/Ingest Family Module Split | accepted |
| [0012](0012-runtime-owns-pixels-atomic-assets-synthetic-sheets.md) | Runtime Owns Its Pixels: Atomic Content-Addressed Tile Assets and Synthetic Runtime Sheets | accepted |
