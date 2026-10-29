
from __future__ import annotations

from typing import Dict

STYLE_VERSION = 3

STYLES: Dict[str, str] = {
    "skill": '16-bit SNES-era video game pixel art. Crisp visible pixels, a limited palette of about 24 colours with hand-placed dithering and a dark outline, flat cel shading, composed as an item icon centred on a dark-garden hacker guild hall RPG class card with an ornate pixel-art frame and a parchment-and-stone panel behind it, whose runes and carvings are hex digit shapes, circuit traces and tiny modem indicator lights. Moody night palette with one neon accent colour.',
    "plugin": '16-bit SNES-era video game pixel art. Crisp visible pixels, a limited palette of about 24 colours with hand-placed dithering and a dark outline, flat cel shading, composed as an item icon centred on an RPG class card shown as a rare cyber loot drop, with a rarity-coloured pixel-art frame and floppy disks, a dial-up modem and phone-line cable motifs worked into the ornament. Bright saturated colours.',
    "mod": '16-bit SNES-era video game pixel art. Crisp visible pixels, a limited palette of about 24 colours with hand-placed dithering and a dark outline, flat cel shading, composed as an item icon centred on an RPG class card from a BBS hacker RPG, the card set into a beige 90s CRT monitor bezel with a phosphor glow on the panel behind the item. The item is drawn as a legendary loot item.',
}
DEFAULT_KIND = "skill"
WIDE_FRAME = ("Composed for a wide 16:9 banner: the whole card and everything important sits inside the central 16:9 band, "
              "with nothing important near the top or bottom edge.")
NO_TEXT_TAIL = "No people, no faces, no hands. No text, letters, numbers or lettering anywhere."
AVOID = "Not a safe, vault, padlock, shield, server rack or globe."


def style_for(kind: str) -> str:
    return STYLES.get(kind, STYLES[DEFAULT_KIND])


def build_prompt(kind: str, name: str, about: str) -> str:
    label = kind if kind in STYLES else DEFAULT_KIND
    detail = f": {about.rstrip('.')}" if about else ""
    subject = f'An image of a concrete object or scene that expresses the {label} "{name}"{detail}. {AVOID}'
    return f"{style_for(kind)} {subject} {WIDE_FRAME} {NO_TEXT_TAIL}"
