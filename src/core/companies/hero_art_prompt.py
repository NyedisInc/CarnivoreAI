
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.message_model_secrets import scan_text

PROMPT_VERSION = 4
NAME_MAX = 40
THEME_MAX = 220
SOURCE_MAX = 600
SUMMARY_FILES = ("README.md", "README", "CLAUDE.md", "package.json", "pyproject.toml")

_LOOK = (
    "Matte industrial render, machined gunmetal and charcoal, one restrained warm amber accent light, fine technical "
    "hairline details, soft volumetric haze. "
)
_FIT = (
    "COMPOSITION: wide cinematic panorama. The subject is compact, centred exactly in the middle of the frame, fully "
    "visible, no taller than 28% of the frame height and about one fifth of its width. The scene extends far to the left and "
    "right as a horizontally stretched atmospheric field with a faint perspective grid and long horizontal light "
    "streaks, near-black at the edges, generous empty space above and below the subject. "
)
_FIT_COMPANY = (
    "COMPOSITION: the emblem is HUGE and fills 70 to 80 percent of the frame height, centred exactly in the middle, "
    "fully visible and never cropped, about half the frame width at most. The ground is a plain, flat, near-black "
    "field with a very faint soft vignette and nothing else: no grid, no light streaks, no horizon, no scene. "
)
_NO_TEXT = (
    "ABSOLUTELY NO text, letters, words, numbers, digits, symbols that look like writing, captions, signage, "
    "watermarks, or logos containing words anywhere in the image. No people, no faces, no hands."
)
_SUBJECT_RULE = (
    "The subject is a concrete object or scene taken from what this project does, never a generic stand-in. Do NOT draw "
    "a safe, vault, padlock, shield, server rack or generic glowing globe unless the subject below says so. "
)
TEMPLATES = {
    "project": (
        "A cinematic, high-end visual for a software project, rendered in the cold, restrained style of a classified "
        "intelligence-agency dossier (the style only, not the subject). " + _SUBJECT_RULE + "One striking physical "
        "centrepiece, the subject: {theme}. " + _LOOK + _FIT + _NO_TEXT
    ),
    "skill": (
        "A cinematic, high-end card illustration for one software skill (a reusable capability of a coding agent). "
        + _SUBJECT_RULE + "One striking physical centrepiece, the subject: {theme}. " + _LOOK + _FIT + _NO_TEXT
    ),
    "company": (
        "A sleek, powerful, impactful logo MARK for a company: a single bold emblem or symbol only, no wordmark, "
        "geometric and iconic, instantly memorable, themed by what the company does: {theme}. Polished metal with "
        "crisp edges and a subtle amber glow. " + _LOOK + _FIT_COMPANY + _NO_TEXT
    ),
}
NAME_THEME = "a concrete object or scene that visually expresses the meaning of the words \"{name}\", depicted, never written"

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_QUOTE = re.compile(r"[\"\\]")


def clean_name(name: str) -> str:
    return " ".join(_QUOTE.sub("", _CONTROL.sub(" ", name)).split())[:NAME_MAX]


def has_secret(text: str) -> bool:
    return bool(scan_text(text))


def build_prompt(kind: str, theme: Optional[str], name: str = "") -> str:
    motif = " ".join((theme or "").split())[:THEME_MAX]
    if not motif or has_secret(motif):
        shown = clean_name(name)
        if not shown or has_secret(shown):
            raise ValueError("no theme and no usable name")
        motif = NAME_THEME.format(name=shown)
    return TEMPLATES[kind].format(theme=motif.rstrip("."))


def _excerpt(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    if path.name == "package.json":
        try:
            raw = str(json.loads(raw).get("description") or "")
        except (ValueError, AttributeError):
            return ""
    text = " ".join(re.sub(r"[#*`>|\[\]()_-]+", " ", raw).split())[:SOURCE_MAX]
    return "" if has_secret(raw) or has_secret(text) else text


_SOURCE_LABEL = {"README.md": "readme", "README": "readme", "CLAUDE.md": "claude_md"}


def read_summary_source(root: Optional[str]) -> Tuple[str, str]:
    if not root:
        return "", ""
    folder = Path(root)
    parts: List[str] = []
    source = ""
    for filename in SUMMARY_FILES:
        text = _excerpt(folder / filename)
        if text:
            parts.append(text)
            source = source or _SOURCE_LABEL.get(filename, "manifest")
        if sum(len(p) for p in parts) >= SOURCE_MAX:
            break
    return " ".join(parts)[:SOURCE_MAX], source


def read_summary(root: Optional[str]) -> str:
    return read_summary_source(root)[0]
