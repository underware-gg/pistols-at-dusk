# Pistols at Dusk

[![Version](https://img.shields.io/badge/version-0.1.4-blue)](VERSION) ![Status](https://img.shields.io/badge/status-prototype-orange) ![Python](https://img.shields.io/badge/python-%E2%89%A53.12-3776AB?logo=python&logoColor=white)

Pistols at Dusk game repository, currently centered on tileset and layout tooling: Minimal 8 sprite-family ingestion, semantic tile catalogs, and grid-based scene-composition experiments.

> **WARNING**
> This is a development repository. Expect breaking changes, active refactoring, and non-backward-compatible updates to tooling, data formats, layouts, and contributor-facing conventions while the repo is still pre-1.0.

## Current Harness Features

The Minimal 8 harness currently covers:

- family bootstrap from grid-aligned source sheets into a structured tile-family package
- semantic tile catalogs with aliases, clusters, constructions, and source-layout ingestion metadata
- grid-based layout rendering with layered ops, metatiles, transformed refs, underpaint, and reusable box styles
- scene-template expansion for authored room grammar, including data-driven templates and deterministic slot population via scene rulesets
- inspection and export tooling for family catalogs, scene-runtime snapshots, review packs, and public tile-pack outputs

Documentation starts at [docs/README.md](docs/README.md). Agents start at [AGENTS.md](AGENTS.md). Contributors start at [CONTRIBUTING.md](CONTRIBUTING.md).
Release history lives at [docs/CHANGELOG.md](docs/CHANGELOG.md).

The repo conforms to the [Agent-Ready Documentation Standard v1.0](https://github.com/Rob-Morris/obsidian-brain/blob/main/docs/standards/agent-ready-documentation.md).

## Bootstrap

- Install the pinned Python runtime with `asdf` (`.tool-versions` currently pins `python 3.12.13`).
- Create the repo-local virtual environment with `asdf exec python -m venv .venv`.
- Install Python dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`.
- Install the repo-local Node tooling with `pnpm install`.
- Run `pnpm typecheck` for the repo-local `pyright` entrypoint.
- Run `pnpm test:coverage` for the repo-local Python coverage report.

## Layers

- User docs: [docs/user/README.md](docs/user/README.md)
- Functional docs: [docs/functional/README.md](docs/functional/README.md)
- Architecture docs: [docs/architecture/README.md](docs/architecture/README.md)
- Contributor docs: [docs/contributor/README.md](docs/contributor/README.md)
- Standards: [docs/standards/README.md](docs/standards/README.md) — versioning, changelog, commit-message, and canary standards
