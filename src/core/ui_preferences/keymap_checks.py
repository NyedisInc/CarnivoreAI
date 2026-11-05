
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.keymap import protected

MAX_OVERRIDDEN_ACTIONS = 600
MAX_CHORDS_PER_ACTION = 4

_TOP_LEVEL = (*protected.FAMILIES, "mouse")

_REASONS = {
    "malformed": "that is not a shortcut the app can read",
    "reserved": "that shortcut belongs to the operating system or the browser",
    "escape": "escape closes the top layer, so no action can take it",
    "tab": "tab moves focus, so no action can take it",
    "needs_cmd": "on a mac, a shortcut that can reach the terminal must include cmd, or the terminal loses that key",
    "needs_ctrl_shift": "off a mac, a shortcut that can reach the terminal must be ctrl with shift, or the terminal loses that key",
    "no_ctrl_alt": "ctrl with alt types characters on many keyboards, so no action can take it",
    "terminal_owned": "the terminal or a text field already uses that shortcut",
    "needs_modifier": "an action inside a text box needs ctrl, alt or cmd, or it would swallow the letters being typed",
}


def _check_keys(family: str, mapping: Any) -> Dict[str, List[str]]:
    if not isinstance(mapping, dict) or len(mapping) > MAX_OVERRIDDEN_ACTIONS:
        raise ValueError(f"keymap.{family} must be an object of at most {MAX_OVERRIDDEN_ACTIONS} actions")
    for action_id, chords in mapping.items():
        if not protected.is_action_id(action_id):
            raise ValueError(f"keymap.{family} names an action id that is not shaped like one")
        if not isinstance(chords, list) or len(chords) > MAX_CHORDS_PER_ACTION or len(set(chords)) != len(chords):
            raise ValueError(f"keymap.{family}: each action takes a list of at most {MAX_CHORDS_PER_ACTION} different shortcuts")
        for chord in chords:
            code = protected.refusal(family, chord, action_id) if isinstance(chord, str) else "malformed"
            if code:
                raise ValueError(f"keymap.{family}: {_REASONS[code]}")
    return mapping


def _check_mouse(mapping: Any) -> Dict[str, List[str]]:
    if not isinstance(mapping, dict) or len(mapping) > MAX_OVERRIDDEN_ACTIONS:
        raise ValueError("keymap.mouse must be an object of actions")
    for action_id, gestures in mapping.items():
        if not protected.is_action_id(action_id):
            raise ValueError("keymap.mouse names an action id that is not shaped like one")
        if not isinstance(gestures, list) or not set(gestures) <= protected.REBINDABLE_GESTURES or len(set(gestures)) != len(gestures):
            raise ValueError("keymap.mouse: only the middle click can be bound")
    return mapping


def check_keymap(value: Any) -> Optional[Dict[str, Dict[str, List[str]]]]:
    if value is None:
        return None
    if not isinstance(value, dict) or not set(value) <= set(_TOP_LEVEL):
        raise ValueError("keymap must be an object with only mac, other and mouse in it")
    for key, mapping in value.items():
        value[key] = _check_mouse(mapping) if key == "mouse" else _check_keys(key, mapping)
    return value
