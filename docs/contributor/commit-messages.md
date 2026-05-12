# Commit Messages

How commit history stays readable in this repo.

## Process

Before drafting a commit message:

1. Read `git diff` and `git diff --stat`.
2. If the commit ships a version, read `VERSION`, the matching `docs/CHANGELOG.md` row, and the top-line Summary in `docs/changelog/vX.Y.Z.md`.
3. Check recent `git log --oneline` so the local subject-line style stays coherent.

## Subject Line

Versioned template:

`<Summary> (vX.Y.Z)`

Non-versioned template:

`<prefix> <specific subject>`

Allowed non-versioned prefixes:

- `docs:`
- `test:`
- `chore:`

Rules:

- keep the subject short and specific
- use imperative mood
- do not end the subject with a period
- versioned commits are prefix-free
- versioned subjects reuse the canonical Summary text from `docs/changelog/vX.Y.Z.md` verbatim

## Body

The body explains *why*, not just *what*.

- Omit the body for trivial commits.
- Otherwise use either 2-6 short bullets or 2-4 sentences of prose.
- Name specific identifiers when they add meaning.
- Do not pad the body with file inventories the diff already shows.

## Examples

Good:

```text
Ship the Minimal 8 harness as the repo's first versioned baseline (v0.1.0)
docs: adopt changelog package and commit-message standards
test: cover scene_rules catalogue validation
```

Avoid:

```text
Update docs
Refactor code
feat: v0.1.0
```

## Related

- [changelog-standard.md](changelog-standard.md) — release-history standard
