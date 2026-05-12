# Character Identification Walkthrough

This note captures first-pass review feedback for the full character block on the Minimal 8 source sheet.

## Shared Behavior

- All character entries use the same four-sprite pattern.
- Top left: tall/right-facing.
- Bottom left: tall/left-facing.
- Top right: short/right-facing.
- Bottom right: short/left-facing.
- The left/right facings presumably support movement direction.
- The shorter pose may represent sitting, ducking, or an alternate animation frame such as part of a walk cycle. That interpretation remains uncertain and should stay documented as tentative.

## Column 1

- `sheet:38,4-39,5` — humanoid with ears, perhaps a catman
- `sheet:38,6-39,7` — humanoid with rectangular head
- `sheet:38,8-39,9` — humanoid with slightly elongated rectangular head
- `sheet:38,10-39,11` — humanoid carrying a bow
- `sheet:38,12-39,13` — cat
- `sheet:38,14-39,15` — some kind of flying winged creature, maybe an insect
- `sheet:38,16-39,17` — small circular hovering creature, perhaps a will-o-wisp
- `sheet:38,18-39,19` — small walking critter

## Column 2

- `sheet:41,4-42,5` — humanoid with staff
- `sheet:41,6-42,7` — a rogue with sword
- `sheet:41,8-42,9` — knight
- `sheet:41,10-42,11` — humanoid with broom
- `sheet:41,12-42,13` — a cute/friendly dog with floppy ears
- `sheet:41,14-42,15` — a jelly or gelatinous blob maybe
- `sheet:41,16-42,17` — maybe a robot with wheels
- `sheet:41,18-42,19` — a critter or ghost

## Column 3

- `sheet:44,4-45,5` — a small humanoid, maybe a child
- `sheet:44,6-45,7` — a traveller with a hat and a staff
- `sheet:44,8-45,9` — a knight
- `sheet:44,10-45,11` — a knight with a club
- `sheet:44,12-45,13` — a bird
- `sheet:44,14-45,15` — a dog
- `sheet:44,16-45,17` — a mushroom
- `sheet:44,18-45,19` — a floating skull

## Column 4

- `sheet:47,4-48,5` — a villager wearing a hat
- `sheet:47,6-48,7` — a villager with a sword
- `sheet:47,8-48,9` — a villager with a fishing pole
- `sheet:47,10-48,11` — a villager
- `sheet:47,12-48,13` — a fish
- `sheet:47,14-48,15` — a goat

## Column 5

- `sheet:50,4-51,5` — a monkey
- `sheet:50,6-51,7` — a wizard in a robe with a staff
- `sheet:50,8-51,9` — a rogue maybe
- `sheet:50,10-51,11` — empty
- `sheet:50,12-51,13` — a snake

## Notes

- This is best-effort, low-pixel first-pass identification and should remain versioned as review feedback until promoted into authored character metadata.
- If this character block is expanded into authored collections later, each character should likely become its own pose/state grouping rather than a fixed multi-tile entity.
