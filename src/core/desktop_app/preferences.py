
from __future__ import annotations

import re

DEFAULT_BANNERS: bool = False
DEFAULT_HIDE_COMMAND: bool = False
DEFAULT_NOTIFY_ASKS_ONLY: bool = False
DEFAULT_HOTKEY: str = "Ctrl+Option+Cmd+C"
DEFAULT_OPTION_IS_META: bool = False
DEFAULT_MENU_BAR_ICON: bool = True
DEFAULT_TERMINAL_APP: str = "terminal"

TERMINAL_APPS: tuple[str, ...] = ("ghostty", "iterm2", "terminal", "kitty", "wezterm", "custom")

_MODIFIERS = frozenset({"ctrl", "control", "alt", "option", "shift", "cmd", "command", "super", "meta", "cmdorctrl", "commandorcontrol"})
_KEY_RE = re.compile(r"^(?:[A-Za-z0-9]|F(?:[1-9]|1[0-9]|2[0-4])|Space|Tab|Enter|Return|Escape|Esc|Backspace|Delete|Insert|Home|End|PageUp|PageDown|Up|Down|Left|Right|Plus|[`\-=\[\]\;',./])$")
_MODIFIER_CANON = {"control": "ctrl", "option": "alt", "command": "cmd", "super": "cmd", "meta": "cmd", "cmdorctrl": "cmd", "commandorcontrol": "cmd"}
_SYSTEM_CHORDS = frozenset({
    frozenset({"cmd", "shift", "q"}), frozenset({"cmd", "ctrl", "q"}), frozenset({"cmd", "alt", "escape"}), frozenset({"cmd", "alt", "esc"}),
    frozenset({"cmd", "shift", "3"}), frozenset({"cmd", "shift", "4"}), frozenset({"cmd", "shift", "5"}), frozenset({"cmd", "alt", "d"}),
})
MAX_HOTKEY_CHARS: int = 64
MAX_CUSTOM_CHARS: int = 500


def is_desktop_field(name: str) -> bool:
    return name.startswith("desktop_") or name == "mac_option_is_meta"


def validate_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def validate_hotkey(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_HOTKEY_CHARS:
        raise ValueError("desktop_hotkey must be an accelerator such as Ctrl+Option+Cmd+C, or empty for off")
    if value == "":
        return value
    parts = value.split("+")
    key = parts[-1]
    mods = [p.lower() for p in parts[:-1]]
    if (
        not mods or len(mods) > 4 or len(set(mods)) != len(mods) or any(m not in _MODIFIERS for m in mods)
        or mods == ["shift"] or not _KEY_RE.match(key)
    ):
        raise ValueError("desktop_hotkey must be one to four modifiers and one key, such as Ctrl+Option+Cmd+C")
    return value if is_safe_global_chord(mods, key) else _refuse_chord()


def is_safe_global_chord(mods: list[str], key: str) -> bool:
    canon = {_MODIFIER_CANON.get(m, m) for m in mods}
    lowered = key.lower()
    if len(canon) < 2 and not re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", lowered):
        return False
    return frozenset(canon | {lowered}) not in _SYSTEM_CHORDS


def _refuse_chord() -> str:
    raise ValueError("desktop_hotkey needs at least two modifiers (a function key may have one) and must not be a macOS shortcut")


def validate_terminal_app(value: object) -> str:
    if not isinstance(value, str) or value not in TERMINAL_APPS:
        raise ValueError("desktop_terminal_app must be one of " + ", ".join(TERMINAL_APPS))
    return value


def validate_terminal_custom(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_CUSTOM_CHARS:
        raise ValueError(f"desktop_terminal_custom must be 1 to {MAX_CUSTOM_CHARS} characters")
    if any(not ch.isprintable() for ch in value):
        raise ValueError("desktop_terminal_custom must not contain control characters")
    return value
