# Pistols at Dusk

Contributor bootstrap for agents working in this repo.

- If `AGENTS.local.md` exists at the repo root, ALWAYS read it first for machine-specific instructions.
- ALWAYS read `docs/README.md` (documentation map). Especially before planning, contributing, or editing.
- Before contributing or editing repo docs/code, read `docs/contributor/agents.md`.

## Safety

- Treat asset processing, scene composition, and tile-family ingestion work as local and disposable unless the user explicitly asks otherwise. Do not publish review packs, push prototype output to shared locations, or commit large generated artefacts without explicit authorisation.
- Architectural decisions land as decision records under `docs/architecture/decisions/`. Do not rewrite a landed decision record — supersede it.
- Versioned commits (`<Summary> (vX.Y.Z)`) and stable release promotions (`release: promote vX.Y.Z to stable`) are commit-message subject patterns enforced by `tools/git-hooks/commit-msg`; do not invent new prefix shapes. See [docs/standards/commit-messages.md](docs/standards/commit-messages.md).
