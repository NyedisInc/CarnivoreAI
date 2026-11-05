
from __future__ import annotations

import re
from typing import Final, Optional

FAMILIES: Final = ("mac", "other")

MODIFIER_ORDER: Final = ("ctrl", "alt", "shift", "cmd")

NAMED_KEYS: Final = frozenset(
    {"enter", "escape", "tab", "space", "backspace", "delete", "insert", "home", "end", "pageup", "pagedown",
     "arrowup", "arrowdown", "arrowleft", "arrowright", "menu"}
    | {f"f{n}" for n in range(1, 21)}
)

LOCAL_ONLY_PREFIXES: Final = (
    "menu.", "nav.", "catalog.", "feed.", "review.", "automations.", "sidebar.row.", "elite.",
    "palette.next", "palette.prev", "palette.pick", "palette.chip", "file.save", "search.focus", "keybar.", "form.submit",
    "terminal.search.next", "terminal.search.prev", "terminal.search.jump", "terminal.search.close",
)

TEXT_INPUT_PREFIXES: Final = (
    "form.", "palette.next", "palette.prev", "palette.pick", "palette.chip",
    "terminal.search.next", "terminal.search.prev", "terminal.search.jump", "terminal.search.close",
)

TERMINAL_OWNED: Final = {
    "mac": frozenset(
        {"arrowdown", "arrowup", "cmd+c", "cmd+enter", "cmd+f", "cmd+g", "cmd+v", "enter", "escape", "shift+cmd+enter",
         "shift+cmd+g", "shift+enter", "shift+escape"}
    ),
    "other": frozenset(
        {"arrowdown", "arrowup", "ctrl+enter", "ctrl+f", "ctrl+g", "ctrl+shift+c", "ctrl+shift+g", "ctrl+shift+v", "enter",
         "escape", "shift+enter", "shift+escape"}
    ),
}

RESERVED: Final = {
    "mac": frozenset(
        {"cmd+c", "cmd+v", "cmd+x", "cmd+a", "cmd+z", "shift+cmd+z", "cmd+q", "cmd+w", "cmd+h", "cmd+m", "cmd+space", "cmd+tab",
         "cmd+t", "cmd+l", "cmd+d", "shift+cmd+t"}
    ),
    "other": frozenset(
        {"ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+w", "ctrl+t", "ctrl+n", "ctrl+tab", "ctrl+shift+t",
         "ctrl+shift+n", "ctrl+shift+w", "alt+f4", "alt+tab", "ctrl+shift+tab"}
    ),
}

REBINDABLE_GESTURES: Final = frozenset({"middle"})

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ChordError(ValueError):
    pass


def is_action_id(value: object) -> bool:
    return isinstance(value, str) and _ID.match(value) is not None


def split_chord(chord: str) -> tuple[list[str], str]:
    if chord == "+":
        return [], "+"
    if chord.endswith("++"):
        return chord[:-2].split("+") if chord[:-2] else [], "+"
    parts = chord.split("+")
    return parts[:-1], parts[-1]


def parse_chord(chord: object) -> tuple[list[str], str]:
    if not isinstance(chord, str) or not chord or len(chord) > 40:
        raise ChordError("a shortcut must be a short piece of text")
    mods, key = split_chord(chord)
    ranks = [MODIFIER_ORDER.index(m) if m in MODIFIER_ORDER else -1 for m in mods]
    if -1 in ranks or ranks != sorted(set(ranks)):
        raise ChordError("a shortcut writes its modifiers once each, in the order ctrl, alt, shift, cmd")
    one_char = len(key) == 1 and key.isprintable() and key != " " and key == key.lower()
    if not (one_char or key in NAMED_KEYS):
        raise ChordError("a shortcut ends in one key: a character, or a named key such as enter or arrowup")
    if one_char and not key.isalnum() and "shift" in mods:
        raise ChordError("a symbol key already includes shift, so a shortcut leaves shift out")
    return mods, key


def reaches_terminal(action_id: str) -> bool:
    return not action_id.startswith(LOCAL_ONLY_PREFIXES)


def in_text_input(action_id: str) -> bool:
    return action_id.startswith(TEXT_INPUT_PREFIXES)


def refusal(family: str, chord: str, action_id: str) -> Optional[str]:
    try:
        mods, key = parse_chord(chord)
    except ChordError:
        return "malformed"
    if chord in RESERVED[family]:
        return "reserved"
    if key == "escape":
        return "escape"
    if key == "tab":
        return "tab"
    if chord in TERMINAL_OWNED[family]:
        return "terminal_owned"
    if in_text_input(action_id) and not {"ctrl", "alt", "cmd"} & set(mods):
        return "needs_modifier"
    if not reaches_terminal(action_id):
        return None
    if family == "mac":
        return None if "cmd" in mods else "needs_cmd"
    if "ctrl" in mods and "alt" in mods:
        return "no_ctrl_alt"
    return None if "ctrl" in mods and "shift" in mods else "needs_ctrl_shift"
