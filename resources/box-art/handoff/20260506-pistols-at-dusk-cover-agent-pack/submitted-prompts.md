# Submitted Prompt History

This is a record of the successive prompts I submitted in this thread.

This file is archival context only. It is not the current brief, and it should not override `agent-brief.md`.

Important caveat:

- the local Codex image cache preserved the output PNGs
- it did not preserve the raw prompt text in a clean recoverable form
- Prompt 1 below is now the exact text supplied by the user after the fact
- Prompts 2-5 remain reconstructed from the conversation and generation sequence
- those later prompts should be treated as faithful reconstructions rather than byte-for-byte source metadata

## Output Files

These were the five generated outputs I could identify in the local cache:

1. `~/.codex/generated_images/019dfb89-9c62-7120-9798-3cf31388c28f/ig_08b34acda1f4ecc00169facd581bb0819180636ed6f120851d.png`
2. `~/.codex/generated_images/019dfb89-9c62-7120-9798-3cf31388c28f/ig_08b34acda1f4ecc00169fad03f79a881918a5846a4ff5d6bbb.png`
3. `~/.codex/generated_images/019dfb89-9c62-7120-9798-3cf31388c28f/ig_08b34acda1f4ecc00169fad432b9b081918df81d9e0c864ad0.png`
4. `~/.codex/generated_images/019dfb89-9c62-7120-9798-3cf31388c28f/ig_08b34acda1f4ecc00169fad7335d688191bfc1920eb6ee9a6c.png`
5. `~/.codex/generated_images/019dfb89-9c62-7120-9798-3cf31388c28f/ig_08b34acda1f4ecc00169fada70bee081919986ebd297ea2e2e.png`

## Prompt 1

Intent:

- first concept-art pass
- no title or publisher branding yet
- leaning on the Ultima-style confrontation plus Pistols painted style

Exact prompt:

```text
Portrait fantasy concept artwork for a game called Pistols at Dusk. Compose it explicitly like a classic 1980s fantasy box cover in the spirit of the Ultima V reference: dramatic heroic confrontation in the foreground, looming dark figures or architecture behind, painterly hand-drawn cover-art finish, rich shadows, strong silhouette storytelling, high drama, not a modern poster layout.

Scene: Act III underworld lantern descent. A lone duelist protagonist stands in the foreground on a stone threshold above black water and abyssal channels, turning side-on in a tense defensive stance, holding an antiquated flintlock pistol. Opposite him, confronting him directly, is a demonic bartender figure: tall, subtly recognisable as the same bartender from the tavern, with hints of waistcoat or tavern-keeper silhouette, a knowing human face partially surviving inside the demon, but now transformed into a grave, hellish underworld presence. He is also holding an antiquated flintlock pistol. Make the bartender-demon feel intelligent, intimate, and personally menacing rather than generic monster.

Visual hints for the bartender-demon: infernal host, horn-like shadow shapes, ember eyes, smoke, a sly almost-familiar expression, one hand like a tavern host offering doom, subtle echoes of bottles, cups, or tavern ritual in the costume language. Do not use neon purple outlines or UI effects. The character behind the demon in the reference is irrelevant and should not appear.

Environment: an underworld temple or ritual descent space inspired by the top-down mockup reference but translated into a painted cover-art scene: carved stone, funereal pillars, black water, lantern glow, deep voids, ritual geometry, infernal dusk atmosphere. Small hints of the Fool & Flintlock world surviving in the architecture are welcome.

Style direction: combine classic Ultima box-art fantasy illustration with the hand-painted Pistols promotional art style. Dark, moody, painterly, slightly grimy low-fantasy textures. Colour palette centred on lantern amber, old gold, plum-black, midnight violet, black-teal, dried blood reds. The only real warmth should come from lantern or pistol-metal highlights and the duelist’s clothing accents.

Composition: foreground duel tension, strong triangular cover-art composition, the duelist readable and human, the bartender-demon taller and more ominous, looming behind or across from him. Make it feel like a legendary confrontation at the threshold of the underworld. No text, no logo, no border, no UI.
```

## Prompt 2

Intent:

- second pass after the user asked for a V2
- keep the successful confrontation energy
- add title, crossed-pistols branding, and Underware mark

Reconstructed prompt:

```text
Create a V2 of the Pistols at Dusk cover art. Keep the overall confrontation between the duelist and the demonic bartender, but refine the figure and move the pistol into the duelist's right hand. Make the style closer to the painted Pistols-at-Dawn references rather than generic dark fantasy. Add the title "Pistols at Dusk" at the top in a Chomsky-like blackletter style. Include the crossed-pistols logo from the supplied reference and place a subtle Underware logo on the cover. Use the Ultima V cover as the compositional inspiration and combine it with the Pistols painted references.
```

## Prompt 3

Intent:

- another pass after reviewing the failures
- keep what had worked from pass one and the title from pass two
- lantern in left hand, pistol in right hand

Reconstructed prompt:

```text
Create a V3 painted cover-art version for Pistols at Dusk. Keep the dramatic confrontation, the strong title treatment from the second pass, and the successful menace of the bartender-demon from the first pass. The duelist stands in the foreground with a lantern hanging low in his left hand and a flintlock pistol in his right hand. The bartender-demon remains recognisably the bartender from the supplied in-game art, but transformed into a looming supernatural host. Place the Underware mark subtly in the bottom-right. Aim for a cleaner classic fantasy cover read.
```

## Prompt 4

Intent:

- explicit fresh-start attempt
- rely on source references conceptually rather than the generated chain

Reconstructed prompt:

```text
Fresh-start V4 cover artwork for Pistols at Dusk. Use only the source references conceptually: the Ultima V cover for composition, the bartender demon art for menace, the bartender tavern art for identity, the Pistols painted art for style, the crossed-pistols emblem for secondary branding, and the Underware logo for a subtle publisher mark. Show one human duelist in the foreground, lantern in the left hand, flintlock pistol in the right hand, confronting the bartender transformed into a demonic host in the underworld. Include the title at the top and keep the Underware mark small in the bottom-right.
```

## Prompt 5

Intent:

- one-pass complete cover generation from sources only
- after the user explicitly asked for a genuinely fresh generation and asked me not to keep dragging along the broken generation chain

Reconstructed prompt:

```text
Paint a completely fresh retro-fantasy game box cover for Pistols at Dusk, using only the supplied source references conceptually and not any prior generated images. Create a classic heroic confrontation in the underworld: a human duelist in the foreground, left hand holding a lantern low and right hand aiming an antiquated flintlock pistol, facing the bartender transformed into a demonic host who is still recognisably the bartender from the supplied tavern reference. Blend classic staged box-cover composition with the warmer hand-painted Pistols art style. Include the title "Pistols at Dusk" at the top, a small crossed-pistols emblem, and a subtle Underware logo in the bottom-right.
```

## What Went Wrong

The recurring failure pattern across the outputs was not a small variation problem. The generator appeared to stay attached to a prior internal pose/layout solution across the thread.

That is why the new `agent-brief.md` insists on:

- source-only generation
- no use of the previous outputs as references
- a clean restart workflow
