# Documentation

This repo conforms to the [Agent-Ready Documentation Standard v1.0](https://github.com/Rob-Morris/obsidian-brain/blob/main/docs/standards/agent-ready-documentation.md). Adoption notes and current maturity sit in [contributor/documentation-standard.md](contributor/documentation-standard.md).

## Layers

- [User](user/README.md) — task-oriented workflows: ingest a sprite family, inspect a variant, export a review pack, choose a colorway.
- [Functional](functional/README.md) — what the system does: family-package format, addressing forms, project consumption model, review-pack workflow.
- [Architecture](architecture/README.md) — how the system is structured: ingestion/render layering, runtime shape, decision records router, supporting notes.
- [Contributor](contributor/README.md) — how to contribute: process, release workflow, working rules, repo structure, change discipline.
- [Standards](standards/README.md) — imported and shared documentation standards: versioning, changelog, commit messages, canary.

## Convention-based exceptions

These files sit at conventional locations recognised by tooling and humans:

- [README.md](../README.md) — repo landing page; links into this index.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contributor layer's public-facing landing page; links into the contributor layer.
- [AGENTS.md](../AGENTS.md) — agent-facing bootstrap. `CLAUDE.md` is a symlink to it.
- [design.md](../design.md) — design tokens (colours, typography, components); also indexed from the architecture layer.
- [CHANGELOG.md](CHANGELOG.md) — version history index; links to one file per shipped version under `changelog/`.

## Bootstrap

Agents arrive via [AGENTS.md](../AGENTS.md). Humans typically arrive via the repo [README.md](../README.md). Both route here.

## Current focus

The Minimal 8 ingestion subsystem is the project's first substantive surface.
The active source-side entrypoint now lives at
[prototypes/minimal8-harness/tile-packs/minimal8](../prototypes/minimal8-harness/tile-packs/minimal8),
while
[prototypes/minimal8-harness/tile-families/minimal8](../prototypes/minimal8-harness/tile-families/minimal8)
remains the transitional compatibility bundle consumed through the current
family-backed runtime path. Related decisions are in the
[decisions router](architecture/decisions/README.md).
