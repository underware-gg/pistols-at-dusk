# Release Workflow

How latest experimental versions and stable releases work in this repo.

## Three States

- **Dev** — branch-local work on non-`main` branches. Non-support engine or tooling work uses `WIP:` when it is not yet a latest-line candidate, or a versioned `<Summary> (vX.Y.Z)` subject when building a clean sequence of latest-line commits prior to integrating onto `main`.
- **Latest** — versioned, release-ready experimental states on `main`.
- **Stable** — a later `release:` promotion of an existing version on `main`.

Only stable releases get Git tags.

## Rebundle On An Integration Branch

When several granular branch commits need to be reshaped into a cleaner latest-line sequence, do that work on a dedicated integration branch rather than rewriting the active dev branch in place. The shared pre-`main` integration branch in this repo is `integration/main`.

Keep the granular dev branch during the active packaging cycle. Once its work has been absorbed into `integration/main`, either recreate the dev branch from the integration tip or reset it to that tip. Before any reset, preserve the old branch tip as a dated backup branch using the source branch path under `backup/`, for example:

```text
backup/dev/rob/20260516
```

This keeps the detailed local history recoverable while making the rebundled integration branch the shared truth for the next cycle.

## Ship A New Latest Version On `main`

When a non-support change is ready to become the new latest experimental state, the **whole bundle lands in a single commit**. All four artefacts must be coherent in that commit; the `commit-msg` hook rejects the commit if any one of them drifts.

1. bump `VERSION`
2. create `docs/changelog/vX.Y.Z.md`
3. add the matching version row to `docs/CHANGELOG.md`
4. update the README version badge to `vX.Y.Z`
5. run `python scripts/release_workflow.py version-check`
6. commit with the canonical Summary subject:

```text
<Summary> (vX.Y.Z)
```

This commit is the new latest experimental line. It is not yet tagged stable.

## Prepare A Stable Release

When a latest version has passed the extra quality gate and is ready for stable promotion:

1. stay on `main`
2. scaffold the release artefacts:

```bash
python scripts/release_workflow.py release-prepare --title "Release Title" --slug release-title
```

3. fill in the generated release file under `docs/changelog/releases/`
4. keep the matching `Release: <title>` row in `docs/CHANGELOG.md`

`release-prepare` is structural only. It does not invent the release title, release notes, or commit narrative.

## Finalize The Stable Release

Once the release artefacts are authored and the latest version is ready to promote:

```bash
python scripts/release_workflow.py release
```

This command:

- runs the version checks again
- validates the stable release artefacts
- creates the stable-promotion commit:

```text
release: promote vX.Y.Z to stable
```

- creates the Git tag:

```text
vX.Y.Z
```

`release` does not push anything. Publication is explicit:

```bash
git push origin main
git push origin vX.Y.Z
```

## Notes

- there is one stable release file per version
- version files under `docs/changelog/` record latest experimental shipped states
- release files under `docs/changelog/releases/` record the later stable promotion of that same version
- if you need to validate the version bundle without creating a release, use `python scripts/release_workflow.py version-check`
- `release` expects no unrelated tracked changes; the only release artefact changes should be the stable release row in `docs/CHANGELOG.md` and the matching release file
- a stable release is fully published only once the tagged commit has been pushed

## Related

- [Versioning](../standards/versioning.md) — when a change should bump the version
- [Changelog](../standards/changelog.md) — how shipped versions and stable releases are recorded
- [Commit Messages](../standards/commit-messages.md) — subject-line rules for versioned, release, support, and WIP commits
- [Contributor Process](process.md) — hooks, verification, and canary
