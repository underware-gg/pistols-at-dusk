---
version: 0.1.0
name: Pistols at Dusk
description: |
  Visual design tokens for Pistols at Dusk — a tile-based 1-bit/2-bit roguelike.
  Colours are locked to the Minimal 8 v2.1 palette imported under
  resources/Super Assets 3000/Minimal 8/. Typography, layout, and components
  are early drafts and will harden as the first slice ships.

colors:
  # Source palette — Minimal 8 v2.1 (40 colours, 4 luminance rows × 10 hues).
  # Names below are project-semantic; the hex codes are taken verbatim from
  # resources/Super Assets 3000/Minimal 8/palette.png.

  # Row 1 — lightest / pastel
  coral:               '#FF9072'
  cream:               '#F6C37C'
  paleYellow:          '#FDFF75'
  paleGreen:           '#D0F98B'
  paleCyan:            '#9BFCF8'
  paleBlue:            '#7EBFFF'
  paleViolet:          '#CE90FF'
  mint:                '#C4F0C2'
  softTeal:            '#8AD4BA'
  plumBlack:           '#24192A'

  # Row 2 — mid-bright / saturated mids
  emberVermilion:      '#DC6250'
  burntOrange:         '#F28C3A'
  gold:                '#FFD731'
  leafGreen:           '#82CE63'
  turquoise:           '#5DE9DA'
  skyBlue:             '#5A8BDE'
  lightPurple:         '#8559D4'
  midTeal:             '#5AB9A8'
  slateTeal:           '#5B9D98'
  paleSkin:            '#FFD4A3'

  # Row 3 — mid-dark / deep saturated
  brickRed:            '#A83737'
  pumpkin:             '#D74922'
  lanternAmber:        '#EDA41E'
  forestGreen:         '#32A458'
  tealCyan:            '#43B2B2'
  deepBlue:            '#384AB3'
  deepViolet:          '#473087'
  darkTeal:            '#1E606E'
  slate:               '#225153'
  nearBlack:           '#1C1B21'

  # Row 4 — darkest / near-black
  bloodRed:            '#3A1313'
  burntUmber:          '#3E150A'
  darkMustard:         '#4B3306'
  bottleGreen:         '#10331B'
  deepTeal:            '#123030'
  midnightBlue:        '#101532'
  midnightViolet:      '#1C1335'
  blackGrey:           '#1D2628'
  blackTeal:           '#102728'
  pureBlack:           '#000000'

  # Semantic aliases (token references — resolve to hex via lookup).
  # These are the names the rest of the project should refer to;
  # the row-named colours above are the literal palette.

  brand.primary:       '{colors.lanternAmber}'    # Flintlock-and-lantern signature warmth
  brand.shadow:        '{colors.plumBlack}'       # The "dusk" itself
  brand.honour:        '{colors.gold}'            # Code-aligned acts; rare
  brand.danger:        '{colors.emberVermilion}'  # UI death/danger; AA-safe on dark surfaces

  surface.primary:     '{colors.plumBlack}'
  surface.secondary:   '{colors.blackGrey}'
  surface.underworld:  '{colors.midnightViolet}'
  surface.void:        '{colors.blackTeal}'

  text.body:           '{colors.cream}'           # 10.4:1 on plumBlack — AAA
  text.heading:        '{colors.gold}'            # 12.0:1 — AAA
  text.disabled:       '{colors.slateTeal}'       #  5.4:1 — AA
  text.danger:         '{colors.emberVermilion}'  #  4.7:1 — AA (pair with skull glyph)
  text.honour:         '{colors.lanternAmber}'    #  8.0:1 — AAA

  border.default:      '{colors.slateTeal}'
  border.emphasis:     '{colors.lanternAmber}'

  archetype.honourable: '{colors.gold}'
  archetype.trickster:  '{colors.cream}'
  archetype.villainous: '{colors.deepViolet}'     # Atmospheric only — fails UI text contrast

  health.high:         '{colors.forestGreen}'
  health.mid:          '{colors.lanternAmber}'
  health.low:          '{colors.emberVermilion}'

  point.full:          '{colors.cream}'
  point.spent:         '{colors.blackGrey}'

  # Atmospheric only — DO NOT use as UI text/icon colours.
  atmosphere.bloodPool:   '{colors.bloodRed}'
  atmosphere.bloodSplat:  '{colors.brickRed}'
  atmosphere.villainous:  '{colors.deepViolet}'

typography:
  # Provisional. Final font choices deferred — needs a pixel font that
  # composes with 8x8 tiles. Candidates: Pixel Operator, Press Start 2P,
  # Determination Mono, or a custom 1-bit face matched to the tileset.
  body:
    family: 'TBD-pixel-mono'
    size: 8px
    weight: regular
    lineHeight: 12px
    letterSpacing: 0px
  heading:
    family: 'TBD-pixel-mono'
    size: 16px
    weight: bold
    lineHeight: 20px
    letterSpacing: 0px
  caption:
    family: 'TBD-pixel-mono'
    size: 8px
    weight: regular
    lineHeight: 10px
  narrator:
    family: 'TBD-pixel-serif'   # the Narrator gets a different face — slightly bookish
    size: 8px
    weight: regular
    lineHeight: 12px

rounded:
  none: 0px
  # 1-bit pixel art has no rounded corners. All UI is hard-edged.

spacing:
  tile: 8px      # base tile size
  cell: 8px      # one grid cell
  gap: 8px       # default gap between elements
  pad: 4px       # half-cell padding inside boxes
  pad.lg: 8px
  pad.xl: 16px

components:
  dialog:
    backgroundColor: '{colors.surface.primary}'
    textColor:       '{colors.text.body}'
    borderColor:     '{colors.border.default}'
    rounded:         '{rounded.none}'
    padding:         '{spacing.pad.lg}'

  narratorBox:
    backgroundColor: '{colors.surface.primary}'
    textColor:       '{colors.text.body}'
    borderColor:     '{colors.border.emphasis}'
    typography:      '{typography.narrator}'
    rounded:         '{rounded.none}'
    padding:         '{spacing.pad.lg}'

  button.default:
    backgroundColor: '{colors.surface.primary}'
    textColor:       '{colors.text.heading}'
    borderColor:     '{colors.border.emphasis}'
    rounded:         '{rounded.none}'
    padding:         '{spacing.pad}'

  button.danger:
    backgroundColor: '{colors.surface.primary}'
    textColor:       '{colors.text.danger}'
    borderColor:     '{colors.brand.danger}'
    rounded:         '{rounded.none}'
    padding:         '{spacing.pad}'

  healthBar.high:
    backgroundColor: '{colors.health.high}'

  healthBar.mid:
    backgroundColor: '{colors.health.mid}'

  healthBar.low:
    backgroundColor: '{colors.health.low}'

  pointPip.full:
    backgroundColor: '{colors.point.full}'

  pointPip.spent:
    backgroundColor: '{colors.point.spent}'

  archetypeBadge.honourable:
    textColor: '{colors.archetype.honourable}'

  archetypeBadge.trickster:
    textColor: '{colors.archetype.trickster}'

  archetypeBadge.villainous:
    textColor: '{colors.text.danger}'             # UI text uses Vermilion, not Deep Violet
    borderColor: '{colors.archetype.villainous}'  # Atmospheric tint as outline only

  stake.honour:
    textColor: '{colors.text.body}'
    glyph: 'wreath'                               # never colour-only; pair with glyph

  stake.death:
    textColor: '{colors.text.danger}'
    glyph: 'skull'
---

# Pistols at Dusk — Design Tokens

This file is the machine-readable output of the [Pistols at Dusk Colour
Scheme](obsidian://Brain/Designs/project~pistols-at-dusk/Pistols%20at%20Dusk%20Colour%20Scheme.md)
brain design (status `shaping`). The brain artefact is where decisions and
rationale live; this file is what the codebase, art pipeline, and engine
theming consume.

## Overview

Pistols at Dusk is a top-down tile-based 1-bit/2-bit roguelike set in the
[Pistols at Dawn](https://underware.gg/) world. The visual language is
locked to the **Minimal 8 v2.1** palette imported under `resources/Super
Assets 3000/Minimal 8/`. No out-of-palette colours; no rounded corners; no
soft-mode UI.

Three acts (Tavern → Overworld → Underworld) traverse a warm-to-cold arc.
The signature contrast is **lantern against the dark** — Gold and Lantern
Amber on Plum Black, Midnight Violet, and Black-Teal.

## Colors

The 40-colour Minimal 8 palette is exposed as named tokens (Row 1 lightest →
Row 4 darkest). Project semantics layer on top as token references — refer
to those (`brand.primary`, `surface.primary`, `text.body`, etc.), not the
raw row names, in code and components.

### Roles

| Role | Token | Use |
|------|-------|-----|
| Primary brand | `brand.primary` (Lantern Amber) | Lantern motif; rare; carries the project identity |
| Signature dark | `brand.shadow` (Plum Black) | Title backdrop; primary UI surface |
| Honour signal | `brand.honour` (Gold) | Code-aligned acts; UI emphasis |
| Danger signal | `brand.danger` (Ember Vermilion) | UI death stake; pair with skull glyph |
| Underworld dark | `surface.underworld` (Midnight Violet) | Act III dominant background |

### Per-act distributions

The 60-30-10 dominance ratio shifts across acts:

- **Act I (Tavern)** — warm dominant. 60 % `plumBlack` + `burntUmber`, 30 % `cream` + `pumpkin`, 10 % `lanternAmber` + `gold`.
- **Act II (Overworld)** — cool dominant. 60 % `slateTeal` + `darkTeal`, 30 % `forestGreen` + `bottleGreen`, 10 % `lanternAmber` + `brickRed`.
- **Act III (Underworld)** — cold dominant, single warm accent. 60 % `midnightViolet` + `deepViolet`, 30 % `blackTeal` + `pureBlack`, 10 % `lanternAmber` + `bloodRed`.

The bartender is the only entity in the game that uses `gold` and
`deepViolet` together. Protect this — it foreshadows a late-game reveal.

### Accessibility

WCAG 2.1 contrast ratios on `surface.primary` (Plum Black `#24192A`):

| Token | Hex | Ratio | Verdict |
|-------|-----|-------|---------|
| `text.body` (Cream) | `#F6C37C` | 10.4:1 | AAA |
| `text.heading` (Gold) | `#FFD731` | 12.0:1 | AAA |
| `text.honour` (Lantern Amber) | `#EDA41E` | 8.0:1 | AAA |
| `text.disabled` (Slate Teal) | `#5B9D98` | 5.4:1 | AA |
| `text.danger` (Ember Vermilion) | `#DC6250` | 4.7:1 | AA |
| `archetype.villainous` (Deep Violet) | `#473087` | 1.6:1 | **FAIL — atmospheric only** |
| `atmosphere.bloodSplat` (Brick Red) | `#A83737` | 2.6:1 | **FAIL — atmospheric only** |

Atmosphere tokens (`atmosphere.*`, `archetype.villainous`) fail UI contrast
on dark surfaces and must never carry text or icon-meaning weight. They are
for tile fills, banners, and outlines under a higher-contrast foreground.

## Typography

Provisional. Final font choices deferred — pixel font selection blocks on
the first slice. Candidates: a body face that composes with 8×8 tiles
(Pixel Operator, Determination Mono, or a custom 1-bit face), and a faintly
bookish face for the Narrator's voice (a 1-bit serif if one exists; else a
distinct weight of the body face).

The Narrator's face is intentionally different from the body face. Voice
matters; we want the player to feel a different speaker the moment the
Narrator interjects.

## Layout

8×8 pixel tile grid. All UI snaps to the same grid. No half-pixels, no
sub-cell padding. Default gaps and pad units are multiples of `spacing.cell`
(8 px); `spacing.pad` (4 px) is the smallest legal unit and is reserved for
inside-component padding.

Resolution targets are deferred to the platform decision (mobile / browser /
desktop — open in the project hub).

## Components

The HUD's first concrete proposal lives in the YAML `components` block
above. The duel engine's default client is undesigned at the engine
level ([Pistols Duel Engine §11](obsidian://Brain/Designs/project~pistols/Pistols%20Duel%20Engine.md)),
so this `components` block is also the engine's first concrete theming
input. Either Dusk overrides the engine client via these tokens, or the
engine grows a theming API that consumes them.

Component variants (`button.default` / `button.danger`,
`healthBar.high` / `healthBar.mid` / `healthBar.low`,
`archetypeBadge.honourable` / `archetypeBadge.trickster` / `archetypeBadge.villainous`,
`stake.honour` / `stake.death`) are listed as separate entries per the
DESIGN.md spec.

## Do's and Don'ts

**Do**

- Stay inside the 40-colour Minimal 8 palette. Out-of-palette colours
  require a written exception in the brain colour-scheme artefact.
- Refer to semantic tokens (`brand.primary`, `surface.primary`,
  `text.body`) in code, not the raw row colours (`lanternAmber`,
  `plumBlack`, `cream`).
- Pair every status colour with a glyph (skull / wreath / heart /
  broken-shield) and/or a numeric indicator. Never colour alone for
  meaning. ~8 % of male players have a colour-vision deficiency.
- Treat `lanternAmber` and `gold` as precious. They are everywhere as
  small accents and concentrated only where it counts (lantern, honour,
  the bartender's eyes).
- Use `pureBlack` (`#000000`) for outlines and the deepest Act III voids
  only. It is not a default fill.
- Keep one warm accent per dark scene. Mixed warm hues at full saturation
  in the same frame fight the palette's restraint.

**Don't**

- Don't use `brickRed`, `bloodRed`, or `deepViolet` for UI text or icons
  on dark surfaces. They fail WCAG contrast. They are atmospheric.
- Don't use `darkTeal` (`#1E606E`) as a UI surface. Mid-luminance breaks
  accessibility for almost every legal foreground.
- Don't pair `gold` with `deepViolet` anywhere except on the bartender.
  This combination is reserved.
- Don't introduce rounded corners. The 1-bit aesthetic is hard-edged.
- Don't use pure white for text. `cream` (`#F6C37C`) is the lightest
  comfortable foreground.
- Don't rely on red/green pairs for meaning (deuteranopia is the most
  common colour-vision deficiency). Use luminance contrast and glyph
  shape instead.
