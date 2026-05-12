# Contributing

This is the contributor layer's public-facing landing page. Full contributor documentation lives at [docs/contributor/README.md](docs/contributor/README.md).

## Baseline

- The repo conforms to the **Agent-Ready Documentation Standard v1.0** ([adoption notes](docs/contributor/documentation-standard.md), [standard source](https://github.com/Rob-Morris/obsidian-brain/blob/main/docs/standards/agent-ready-documentation.md)).
- The contributor layer is the home of working rules, repo structure, and change discipline. Read it before contributing — `AGENTS.md` is bootstrap-only.
- Update docs alongside the code change that affects them. Behavioural changes that are not reflected in docs regress the project's maturity level.
- Markdown links and path references should be repo-relative. Do not commit absolute filesystem paths such as `/Users/...`.
- Repo versioning uses pre-1.0 [semver](https://semver.org/). `VERSION` at the repo root is the source of truth; shipped release history lives in [docs/CHANGELOG.md](docs/CHANGELOG.md) and [docs/changelog/vX.Y.Z.md](docs/changelog/v0.1.0.md).
- Architectural decisions land as decision records under [docs/architecture/decisions/](docs/architecture/decisions). Records are immutable once landed; supersede them rather than rewriting.

## Quick links

- Full contributor index: [docs/contributor/README.md](docs/contributor/README.md).
- Repo structure & ownership rules: [docs/contributor/repo-structure.md](docs/contributor/repo-structure.md).
- Working rules (code design, review workflow, verification, commits): [docs/contributor/working-rules.md](docs/contributor/working-rules.md).
- Changelog standard: [docs/contributor/changelog-standard.md](docs/contributor/changelog-standard.md).
- Commit message standard: [docs/contributor/commit-messages.md](docs/contributor/commit-messages.md).
- Documentation standard adoption: [docs/contributor/documentation-standard.md](docs/contributor/documentation-standard.md).

## Verification

- Install the pinned Python runtime with `asdf` (`.tool-versions` pins `python 3.12.13`).
- Create the repo-local virtual environment with `asdf exec python -m venv .venv`.
- Install Python dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`.
- Install the repo-local Node tooling with `pnpm install`.
- For typed engine changes, run `bash scripts/check_pyright.sh` before committing.
- `pnpm typecheck` runs the same repo-local typecheck entrypoint.
- Run `bash scripts/check_coverage.sh` or `pnpm test:coverage` for a repo-local Python coverage report.
- To wire the repo into a local pre-commit check, run `git config core.hooksPath tools/git-hooks`.

## Bootstrap

Agents start at [AGENTS.md](AGENTS.md); humans coming via this file should follow the quick links above into the contributor layer.
