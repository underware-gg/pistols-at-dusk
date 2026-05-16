# Canary

How this repo uses canary briefs to gate subjective contributor work.

A canary brief is a short checklist with bracketed task IDs and a matching transient log file. The brief is the source of truth; the hook checks the receipt, not the work.

## Repo Pattern

This repo uses:

- `.canaries/pre-commit.md` — the pre-commit brief
- `.canary--pre-commit` — the transient log written at the repo root
- [`tools/git-hooks/pre-commit`](../../tools/git-hooks/pre-commit) — the distributed checker
- [`tools/git-hooks/commit-msg`](../../tools/git-hooks/commit-msg) — companion commit-subject checker for branch/release policy

The hook is not active by default. Contributors opt in with:

```bash
git config core.hooksPath tools/git-hooks
```

## When To Use

Use a canary brief when the work has subjective or cross-cutting steps that are easy to forget but hard to test deterministically.

Examples in this repo:

- documentation routing and rehome work
- shared-fact cross-checks (version badge, CHANGELOG row, VERSION coherence)
- versioning and changelog hygiene
- local-only typecheck and coverage verification

If a step can be tested deterministically, prefer the deterministic test and let the canary prove that the test was actually run when it matters.

## Brief Shape

A canary brief has three parts:

1. Context
2. Tasks
3. Log instructions

Task format:

```text
[id] **Short name** condition: instruction
```

Use nested IDs when a task has meaningful sub-checks.

## Log Shape

The log file must contain one line per task:

```text
[id] Short name: done
[id] Short name: skip, reason
```

Rules:

- every task ID in the brief must appear exactly once in the log
- `done` means the action was actually performed
- `skip` requires a real reason based on what was evaluated
- canary logs are transient and gitignored

## Checker Behaviour

The distributed pre-commit hook:

1. checks that the `README.md` version badge matches `VERSION`
2. reads `.canaries/pre-commit.md`
3. extracts all task IDs between `## Tasks` and `## Log`
4. verifies `.canary--pre-commit` exists and covers every task ID with valid formatting
5. deletes the log file after a successful check so stale receipts cannot be reused

## Related

- [Commit Messages](commit-messages.md) — commit drafting rules the pre-commit canary references
- [Versioning](versioning.md) — release-bump rules the pre-commit canary references
- [Changelog](changelog.md) — changelog rules the pre-commit canary references
