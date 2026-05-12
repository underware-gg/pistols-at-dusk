# Minimal 8

Vendor asset pack by **algernon3000**, sourced from itch.io.

- Source: https://algernon3000.itch.io/minimal-8
- Tile size: 8x8 (some art uses a 7x7 inner grid)
- Style: 1-bit / 2-bit minimalist retro pixel art
- Intended use: medieval RPGs, roguelikes, turn-based strategy

## Pack contents

The pack ships four sheet variants plus separate character art and source files:

| Path | Notes |
| --- | --- |
| `1bit png/` | 1-bit sheet, transparent background |
| `1bit_colored bg png/` | 1-bit sheet on a coloured background (canonical first-pass evidence sheet for ingestion) |
| `2bit png/` | 2-bit sheet, transparent background |
| `2bit_colored bg png/` | 2-bit sheet on a coloured background |
| `Characters/` | Character sprites with idle animations |
| `*.aseprite` | Aseprite source files for each variant |
| `palette.aseprite`, `palette.png` | Shared palette |
| `changelog.txt` | Upstream changelog |

## License

- Free demo (1-bit only): non-commercial use with attribution.
- Paid version (1-bit + 2-bit): CC BY 4.0 — commercial and non-commercial use with credit.

Refer to the itch.io page for current terms before commercial use.

## Project usage

This repo treats Minimal 8 as the canonical first-target sheet. Family metadata, ingestion specs, and tile semantics live under `prototypes/minimal8-harness/tile-families/minimal8/`, not here. This folder remains a clean copy of the upstream pack.
