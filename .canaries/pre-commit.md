# Canary: Pre-Commit

Follow before every commit.

## Tasks

[1] **Typecheck passes** Run `bash scripts/check_pyright.sh`.

[2] **Coverage check** If engine code under `scripts/` or `tests/` changed: run `bash scripts/check_coverage.sh` and inspect the result.

[3] **Docs updated** Update the affected documentation layers. Start from `docs/README.md` for the layer map. The "When To Update Which Layer" table in `docs/contributor/agents.md` maps change types to files when you're unsure which layer owns a given fact:
  [3a] **User layer** — start at `docs/user/README.md`. If task-oriented contributor or end-user workflows changed: update the current user docs.
  [3b] **Functional layer** — start at `docs/functional/README.md`. If runtime contracts, family-package format, addressing forms, project consumption model, or review-pack workflow changed: update the current functional docs.
  [3c] **Architecture layer** — start at `docs/architecture/README.md`. If system boundaries, ownership, ingestion/render layering, runtime shape, or documentation structure changed: update the relevant architecture docs (including decision records under `docs/architecture/decisions/`).
  [3d] **Contributor layer** — start at `docs/contributor/README.md`. If process, repo structure, verification, contributor workflow, or canary/hook expectations changed: update the relevant contributor docs.
  [3e] **Standards layer** — start at `docs/standards/README.md`. If versioning, changelog, commit-message, or canary policy changed: update the relevant standards docs.
  [3f] **Index maintenance** — if docs were added, moved, renamed, or deleted: update `docs/README.md` and the affected layer `README.md` files.

[4] **Shared facts cross-checked** If you changed a shared fact, grep for stale references:
  [4a] **Repo-wide identifiers** Check identifiers such as canonical paths, family/region IDs, scene template names, and config keys.
  [4b] **Version and release references** Check `VERSION`, `README.md`, `docs/CHANGELOG.md`, `docs/changelog/`, and standards docs when versioning or release policy changed. If the distributed hooks are enabled, `tools/git-hooks/pre-commit` rejects commits when the `README.md` version badge drifts from `VERSION`.

[5] **Release hygiene** Follow `docs/standards/versioning.md`, `docs/standards/changelog.md`, and `docs/contributor/release-workflow.md`:
  [5a] **Latest version** — if you are creating a new latest version commit (on `main`, or on a branch building a clean latest-line sequence for later integration): the full bundle lands in a single commit. Bump `VERSION`, create `docs/changelog/vX.Y.Z.md`, update `docs/CHANGELOG.md`, update the README badge, and run `python scripts/release_workflow.py version-check` *before* `git commit` — the `commit-msg` hook checks all four artefacts together, not just `VERSION`.
  [5b] **Stable release** — if you are promoting an existing latest version to stable: keep the same version, maintain the release file under `docs/changelog/releases/`, keep the matching `Release: <title>` row in `docs/CHANGELOG.md`, and run `python scripts/release_workflow.py release`.

[6] **Commit message drafted per standard** Follow `docs/standards/commit-messages.md`, including the latest-line versioned subject (allowed on `main` or on a branch), `WIP:` as the off-`main` escape hatch when work is not yet a latest-line candidate, and the `release:` subject for stable promotion commits (`main`-only).

## Log

After following the tasks above, ALWAYS write a log file named `.canary--pre-commit` to the repo root.
Write one log line per task ID. The hook requires full task coverage with valid formatting; keep the receipt to one line per task to avoid ambiguity. Optionally indent sub-items for readability.

Log format: `[id] Short name: status, comment`

The `[id]` brackets are literal. Comment is optional for `done`, required for `skip`.

### done

`done` means you performed the action. Only write `done` if you actually did the thing. You may optionally add detail after `done`.

### skip

`skip, {reason}` means you did not perform the action. The reason must describe what you evaluated and why the step did not apply.

### Example

```text
[1] Typecheck passes: done
[2] Coverage check: skip, no changes under scripts/ or tests/
[3] Docs updated: done
  [3a] User layer: skip, no user-facing workflow changes
  [3b] Functional layer: skip, no runtime contract changes
  [3c] Architecture layer: skip, no boundary or routing changes
  [3d] Contributor layer: done
  [3e] Standards layer: skip, no standards changes
  [3f] Index maintenance: skip, no docs added/moved/renamed/deleted
[4] Shared facts cross-checked: done
  [4a] Repo-wide identifiers: skip, no canonical identifier changes
  [4b] Version and release references: done
[5] Release hygiene: skip, support-only change with no version bump
  [5a] Latest version: skip, no versioned work in this pass
  [5b] Stable release: skip, no stable promotion work in this pass
[6] Commit message drafted per standard: done
```
