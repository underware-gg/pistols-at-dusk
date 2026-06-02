# 0006 - Defer Cross-Kit Interchangeability to Machine-Verifiable Seam Profiles

- Status: superseded
- Superseded by: [0007](0007-adopt-three-axis-tile-compatibility-and-build-seam-profiles.md)

## Context

The border-kit system (`parametric_frame`, see [construction-system.md](../construction-system.md)) is complete: kits declare corner / edge / fill slots, and a corner slot may borrow another kit's tile by tile-id reference. One planned-but-unbuilt increment remained — **compatibility-group formalisation**: declaring which kits' corners and edges are interchangeable so a kit "knows which connectors and corners it can use" (the motivating case being the gold simple 2×2 corners pairing with either ornate 3×3 body).

Scoping that increment against the actual data and code surfaced three facts:

1. **No runtime consumer.** The `entity` scene op places exactly one construction by id. Nothing at runtime mixes slot-classes — corners from kit A with edges from kit B. A cross-kit compatibility-group declaration plus a placement-time override API would be an extension point with no caller.

2. **The one real grounding case is already expressible.** The gold simple corners pairing with an ornate body is already authored via tile-id corner refs (a corner borrowing another kit's tile by id). No new mechanism is required for it.

3. **`connects_on` cannot verify interchangeability.** The construction-validation adjacency rule uses `connects_on`, a per-side direction flag (open / closed). It proves a side is *meant* to connect, but not that two facing sides actually *fit* (matching seam shape). It is also empty on all 56 frame tiles. A `connects_on`-backed compatibility validator would require populating connection data across every kit and still could not verify that two open sides line up.

A related correction: the grounding case had been sketched as a flat, symmetric group `{gold.gap, gold.smooth, gold.simple}` with corners and edges all interchangeable. The ingest review evidence contradicts this. Interchangeability here is an **asymmetric shared-corner hub** — the simple corners pair with *either* ornate body, but the two ornate bodies are each coherent kits and must not mix connectors with each other. A flat group would encode a falsehood.

## Decision

**Defer cross-kit interchangeability / compatibility-group formalisation.** Do not build a declarative compatibility-group mechanism or a `connects_on`-backed interchangeability validator now.

When a real consumer appears — a second tileset with genuinely interchangeable frames, or the planned `parametric_bar` / selector generalisation — build interchangeability on **machine-verifiable seam profiles** rather than hand-declared groups. A seam profile is a derived per-side key, computed from the tile art at ingest, where two sides connect iff their facing profiles match (or complement). Interchangeability then becomes a *derived, verified* property — "kit A's corner is interchangeable with kit B's edge iff their shared seam keys match" — instead of a trusted hand declaration. That model would **supersede the `connects_on` direction-flag adjacency rule** (which becomes a strictly weaker special case of it).

The durable design for that future work is held in the project brain vault ("Machine-Verifiable Seam Profiles", status `proposed`); it is not yet accepted for build.

## Consequences

- **No change to `scripts/` or `constructions.json`.** The `connects_on` adjacency validation, the `parametric_frame` renderer, and the tile-id corner-ref mechanism all stay as-is. The border-kit system is otherwise complete and is not blocked by this deferral.
- The "Cross-kit constructions" entry in `construction-system.md` is now a **decided deferral**, not an undecided open question.
- Any future hand-declared compatibility data must model the asymmetric shared-corner hub, not a flat clique — but the preferred path is to derive interchangeability from seam profiles rather than declare it.
- When seam profiles are built, expect a **follow-on ADR that supersedes the `connects_on` adjacency model** described in `construction-system.md`. This record would then gain a `Superseded by:` pointer.
