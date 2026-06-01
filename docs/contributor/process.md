# Contributor Process

Shared contributor workflow for this repo.

This file is for humans and agents alike. For agent-only workflow help, use [agents.md](agents.md).

## Documentation Discipline

- keep living docs accurate when behavior changes
- update the relevant layer indexes when adding, moving, or deleting docs
- prefer extending existing docs over carrying duplicate explanations across layers

## Verification Expectations

Bootstrap once per machine:

- install the pinned Python runtime with `asdf` (`.tool-versions` pins `python 3.12.13`)
- create the repo-local virtual environment with `asdf exec python -m venv .venv`
- install Python dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`
- install the repo-local Node tooling with `pnpm install` (Node is required only because the `pyright` CLI is distributed via npm; the engine itself is Python)

Local verification:

- `bash scripts/check_pyright.sh` (or `pnpm typecheck`) — typecheck the Python sources
- `bash scripts/check_coverage.sh` (or `pnpm test:coverage`) — Python line and branch coverage report
- `.venv/bin/python -m unittest tests.test_tile_families tests.test_harness tests.test_scene_expansion tests.test_prototype_output` — harness module tests
- `python scripts/release_workflow.py version-check` — validate the current version bundle

## Supply-chain policy

The repo's only npm dependency is `pyright` (used as the type-checker CLI), but the install path is hardened in two layers.

### pnpm policy ([`pnpm-workspace.yaml`](../../pnpm-workspace.yaml))

- `minimumReleaseAge: 10080` — reject packages whose latest publish is younger than 7 days, so a freshly-compromised release is not picked up in the window before it's caught and unpublished
- `blockExoticSubdeps: true` — reject git, file, and link dependencies in the transitive graph; only registry-resolved versions are allowed
- `strictDepBuilds: true` — reject the install if any dependency declares a postinstall script that is not on the per-package allowlist
- `packageManagerStrictVersion: true` — reject the install if the running pnpm version differs from the `packageManager` pin in `package.json`, so an attacker cannot silently downgrade the package manager

The exact pnpm version pin lives in `package.json` (`packageManager: pnpm@10.17.0`). Bump the pin and the local pnpm CLI together; do not run an older or newer pnpm against this repo.

`pyright` is pinned to an exact version (no caret range) in `devDependencies` so the lockfile cannot silently float across patch releases.

If a future dependency needs a postinstall build step, add it to an explicit `allowBuilds` block in `pnpm-workspace.yaml` rather than disabling `strictDepBuilds`.

### npm defence in depth ([`.npmrc`](../../.npmrc))

pnpm is the canonical package manager for this repo. The `.npmrc` exists so that if someone runs `npm install` *by accident*, the install path stays safe — npm does not read `pnpm-workspace.yaml`, so the pnpm policy above does not protect this path:

- `ignore-scripts=true` — block every `preinstall` / `postinstall` / `prepare` script in the graph, neutralising script-based RCE from any compromised package
- `engine-strict=true` — reject install if the running Node does not satisfy `engines` in `package.json` (currently no-op; defensive for when `engines` gains a constraint)
- `audit-level=moderate` — fail `npm audit` at moderate or higher severity
- `fund=false` — suppress funding messages so real warnings remain visible

`package-lock.json` is gitignored so an accidental `npm install` cannot commit a competing lockfile.

If a future dependency genuinely needs a build script with pnpm (via `allowBuilds`), the `.npmrc` `ignore-scripts=true` will block it under pnpm too — flip both gates together, deliberately, for that single workflow.

## Pre-Commit Canary And Hooks

This repo ships opt-in distributed Git hooks:

- brief: [`.canaries/pre-commit.md`](../../.canaries/pre-commit.md)
- pre-commit checker: [`tools/git-hooks/pre-commit`](../../tools/git-hooks/pre-commit)
- commit-message checker: [`tools/git-hooks/commit-msg`](../../tools/git-hooks/commit-msg)
- Git LFS passthrough hooks: `tools/git-hooks/post-checkout`, `post-commit`, `post-merge`, `pre-push`
- standard: [docs/standards/canary.md](../standards/canary.md)

Enable them locally with:

```bash
git config core.hooksPath tools/git-hooks
```

When enabled:

- `tools/git-hooks/pre-commit` runs `scripts/check_pyright.sh`, then rejects commits if the `README.md` version badge does not match `VERSION`, rejects staged `.canary--pre-commit` receipts, then enforces a complete local `.canary--pre-commit` receipt against the brief and deletes the receipt on success
- `tools/git-hooks/commit-msg` strictly enforces `WIP:` vs versioned vs `release:` subject rules by branch, and checks latest-version and stable-release subjects against the changelog files via `scripts/release_workflow.py`
- the Git LFS passthrough hooks keep PNG and other LFS-tracked assets behaving normally when `core.hooksPath` points at `tools/git-hooks`
- write `.canary--pre-commit` at the repo root before committing; leave it unstaged and untracked, and let the hook validate it and delete it on success

## Commit, Versioning, And Changelog

Follow:

- [docs/standards/commit-messages.md](../standards/commit-messages.md)
- [docs/standards/versioning.md](../standards/versioning.md)
- [docs/standards/changelog.md](../standards/changelog.md)
- [docs/CHANGELOG.md](../CHANGELOG.md)
- [release-workflow.md](release-workflow.md)

Repo workflow commands:

- `python scripts/release_workflow.py version-check` — validate the current latest-version bundle
- `python scripts/release_workflow.py release-prepare --title "..." --slug ...` — scaffold the stable release artefacts
- `python scripts/release_workflow.py release` — validate and finalize the stable release locally

## Related

- [Contributing](../../CONTRIBUTING.md) — contributor landing page
- [Agent Instructions](agents.md) — agent-specific workflow help
- [Release Workflow](release-workflow.md) — how dev work becomes latest versions and stable releases
