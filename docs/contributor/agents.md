# Contributing — Agent Instructions

Instructions for agents contributing to this repo. Read [CONTRIBUTING.md](../../CONTRIBUTING.md) first for the baseline contributor rules, then use this file for agent-specific workflow help only: what to update, how to maintain the doc index chain, and how to keep verification work local and disposable.

## When To Update Which Layer

| Change type | Update |
|---|---|
| Task-oriented contributor or end-user workflows (ingest a family, inspect a variant, export a review pack, choose a colorway) | `docs/user/README.md` and the relevant guide under `docs/user/`; `README.md` only if the landing-page summary changed |
| Family-package format, addressing forms, project consumption model, review-pack workflow, runtime contracts | `docs/functional/README.md` and the relevant doc under `docs/functional/`, plus `tests/` when the contract is asserted there |
| System boundaries, ingestion/render layering, runtime shape, decision records, retained source-sheet notes | `docs/architecture/README.md`, `docs/architecture/decisions/`, and the relevant architecture docs |
| Repo structure, working rules, code design principles, canonical sources of truth, asset-meaning vs source-context, review workflow | `docs/contributor/repo-structure.md`, `docs/contributor/working-rules.md` |
| Verification expectations, hook usage, canary workflow, release tooling commands | `docs/contributor/process.md`, `docs/contributor/release-workflow.md`, `.canaries/pre-commit.md`, `tools/git-hooks/pre-commit`, `tools/git-hooks/commit-msg`, `scripts/release_workflow.py` |
| Versioning, changelog, commit-message, or canary policy | `docs/standards/versioning.md`, `docs/standards/changelog.md`, `docs/standards/commit-messages.md`, `docs/standards/canary.md`, `docs/standards/README.md`; cross-check `docs/CHANGELOG.md` and `.canaries/pre-commit.md` |
| Documentation routing or doc-layer structure | `docs/README.md`, the affected layer `README.md` files, and `docs/contributor/documentation-standard.md` |
| Latest version ship | `VERSION`, `docs/changelog/vX.Y.Z.md`, `docs/CHANGELOG.md`, the README version badge — all in one commit; see [release-workflow.md](release-workflow.md) |
| Stable release promotion | `docs/changelog/releases/vX.Y.Z-<slug>.md`, the matching `Release: <title>` row in `docs/CHANGELOG.md`; see [release-workflow.md](release-workflow.md) |
| Bootstrap shape (entry points, layer routing, safety rules) | `AGENTS.md`, `CONTRIBUTING.md`, `docs/README.md`, and this file |

## Index Maintenance

When adding, moving, renaming, or deleting docs:

1. Update the nearest layer `README.md`
2. Update `docs/README.md` if the doc is a root-level surface, standard, or cross-layer exception
3. Do not leave orphaned docs discoverable only by filesystem crawl

## Local Verification Practice

Apply the safety rules from [AGENTS.md](../../AGENTS.md) conservatively.

Unless the user explicitly asks otherwise:

- keep verification work local and disposable
- prefer temporary local fixtures and disposable output directories over shared state
- do not widen a local verification task into a remote action, credentialed step, or shared environment touch
- treat generated output, scratch areas, and `.canary--pre-commit` as transient; do not commit them
