# Documentation Standard

This repo conforms to the **Agent-Ready Documentation Standard v1.0** ([source](https://github.com/Rob-Morris/obsidian-brain/blob/main/docs/standards/agent-ready-documentation.md)).

The standard prescribes how documentation is structured, indexed, and maintained so that human or automated agents can work in the codebase effectively. This page records how that standard applies here — what we adopt, where we sit on the maturity ladder, and what contributors must do to keep the project from regressing.

## Conformance

- **Standard:** Agent-Ready Documentation Standard
- **Version cited:** v1.0
- **Current maturity:** Level 1 — Bootstrapped, advancing toward Level 2 (Documented) on the Minimal 8 ingestion subsystem first.

Per principle P6 (ratcheting improvement), the floor is the level we have reached; changes must not regress it.

## Layer adoption

The four required layers are present and indexed:

| Layer | Layer index | Notes |
|---|---|---|
| User | [docs/user/README.md](../user/README.md) | Task-oriented workflows for the harness CLI and family ingestion |
| Functional | [docs/functional/README.md](../functional/README.md) | Reference shape of the family-package format and addressing |
| Architecture | [docs/architecture/README.md](../architecture/README.md) | Subsystem structure, decisions router, cross-cutting notes |
| Contributor | [docs/contributor/README.md](README.md) | This layer — the home for everyone working in the repo |

No additional project-defined layers at this time.

## Bootstrap

The agent-facing bootstrap is [AGENTS.md](../../AGENTS.md). It names the project, routes to each layer index, and points at convention-based exceptions. In this repo, `AGENTS.md` stays thin and points agents to `AGENTS.local.md` / `CLAUDE.local.md` for tracked machine-specific overrides. The `brain_session` tooling-startup directive lives in that local override file rather than in the main bootstrap; everything else lives in this layer.

`CLAUDE.md` is a symlink to `AGENTS.md` (and `CLAUDE.local.md` → `AGENTS.local.md`). Claude Code agents reading `CLAUDE.md` get the canonical bootstrap content with no drift risk.

## Convention-based exceptions

| File | Role | Treatment |
|---|---|---|
| [README.md](../../README.md) | Repo landing page (referential) | Project blurb + link into `docs/README.md`. |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | Contributor layer's public-facing landing page (prescriptive) | Baseline contributor content + link into `docs/contributor/README.md`. |
| [design.md](../../design.md) | Project-specific design-tokens artefact (referential) | Indexed from the architecture layer; sits at root for tooling consumption. |
| `AGENTS.local.md` / `CLAUDE.local.md` | Local-only overrides (referential) | Tracked, intentionally thin; may carry machine-specific startup directives such as `brain_session`, but project-wide guidance has migrated into this layer. |

## Release History Package

Versioned release history lives in:

- `VERSION` — current repo version
- [docs/CHANGELOG.md](../CHANGELOG.md) — newest-first index of shipped versions
- `docs/changelog/vX.Y.Z.md` — one file per shipped version

Contributor-facing rules for this package live in
[docs/standards/changelog.md](../standards/changelog.md),
[docs/standards/commit-messages.md](../standards/commit-messages.md),
and [docs/standards/versioning.md](../standards/versioning.md).
The release flow is documented in [release-workflow.md](release-workflow.md).

## Decision records

- Router: [docs/architecture/decisions/README.md](../architecture/decisions/README.md).
- Format: Context / Decision / Consequences (Nygard ADR), with sequential numbering (`NNNN-slug.md`).
- Records are immutable once landed. Direction changes write a new record that supersedes or extends the old one — the old record is not edited beyond pointer metadata.

## Three-way reconstruction (target)

Code, docs, and tests should each be reconstructable from the other two. Today, partial reconstruction is supported on the Minimal 8 ingestion stack; full reconstruction is the Level 3 target and not yet met repo-wide.

## Contributor obligations

When you make a change:

1. **Update docs alongside code.** If the change alters behaviour described in any layer, update that layer's content in the same change.
2. **Land architectural decisions as decision records.** Anything that future contributors would need to know *why* about — a new record under `docs/architecture/decisions/`. Do not edit prior records to reflect the new direction; supersede them.
3. **Index every new artefact.** A new file in a layer is reachable from that layer's index; otherwise it is invisible to agents.
4. **Do not regress maturity.** If you remove substantive content, replace it; if you remove an indexed artefact, update its index.
5. **Keep the bootstrap thin.** Workflow prescriptions and repo guidance go in the contributor layer, not in `AGENTS.md` / `CLAUDE.md`.

## Out-of-repo context

The project keeps additional design and planning context in a private Obsidian vault. Per the standard, private knowledge bases are not linked from public-facing bootstraps. Agents with vault access reach it through tooling (the `brain` MCP), not through documentation links.
