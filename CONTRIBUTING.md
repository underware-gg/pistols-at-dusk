# Contributing to Pistols at Dusk

Guide for anyone changing this repo. If you are working as an agent, also read [docs/contributor/agents.md](docs/contributor/agents.md).

## Documentation Entry Point

This repo adopts the [Agent-Ready Documentation Standard v1.0](https://github.com/Rob-Morris/obsidian-brain/blob/main/docs/standards/agent-ready-documentation.md). Adoption notes are in [docs/contributor/documentation-standard.md](docs/contributor/documentation-standard.md).

Start with [docs/README.md](docs/README.md), which routes to the current documentation layers:

- [User](docs/user/README.md) — task-oriented workflows for ingestion, inspection, review packs, and harness usage
- [Functional](docs/functional/README.md) — family-package format, addressing forms, project consumption model, review-pack workflow
- [Architecture](docs/architecture/README.md) — system structure, ingestion/render layering, runtime shape, decision records
- [Contributor](docs/contributor/README.md) — contributor workflow, verification, release process, and agent-specific entry points
- [Standards](docs/standards/README.md) — versioning, changelog, commit-message, and canary standards

## Start Here

- [docs/contributor/process.md](docs/contributor/process.md) — shared contributor workflow, verification, hooks, and canary usage
- [docs/contributor/release-workflow.md](docs/contributor/release-workflow.md) — how dev work becomes latest versions and stable releases
- [docs/contributor/agents.md](docs/contributor/agents.md) — agent-only workflow help and the "When To Update Which Layer" table
- [docs/contributor/README.md](docs/contributor/README.md) — contributor layer router
- [docs/standards/README.md](docs/standards/README.md) — versioning, changelog, commit-message, and canary standards

## Baseline Expectations

- This is a pre-`1.0.0` repo. Expect breaking changes to tooling, data formats, layouts, and contributor-facing conventions. See [docs/standards/versioning.md](docs/standards/versioning.md).
- Repo versioning uses pre-1.0 [semver](https://semver.org/). `VERSION` at the repo root is the source of truth; shipped release history lives in [docs/CHANGELOG.md](docs/CHANGELOG.md) and `docs/changelog/`.
- Keep living docs accurate when behaviour changes. Update the affected layers in the same change. The `.canaries/pre-commit.md` brief lists the layer-by-layer checks.
- Markdown links and path references should be repo-relative. Do not commit absolute filesystem paths such as `/Users/...`.
- Follow the linked contributor and standards docs rather than inventing local variations.
