
from __future__ import annotations

from typing import Final

GLOBAL: Final = "global"
FIELD: Final = "field"
MENU: Final = "menu"
TERMINAL_SCREEN: Final = "terminal-screen"
TERMINAL_PANE: Final = "terminal-pane"
OVERLAY_PREFIX: Final = "overlay:"
MENU_PREFIX: Final = "menu:"

EVERYWHERE: Final = frozenset({"electron-menu", "os-global"})

PAIRS: Final = (frozenset({TERMINAL_SCREEN, TERMINAL_PANE}),)


def is_menu(scope: str) -> bool:
    return scope == MENU or scope.startswith(MENU_PREFIX)


def scopes_overlap(a: str, b: str, has_cmd: bool = False) -> bool:
    if a == b or a in EVERYWHERE or b in EVERYWHERE:
        return True
    if GLOBAL in (a, b):
        other = b if a == GLOBAL else a
        return has_cmd if is_menu(other) else True
    if (a == FIELD and b.startswith(OVERLAY_PREFIX)) or (b == FIELD and a.startswith(OVERLAY_PREFIX)):
        return True
    return frozenset({a, b}) in PAIRS
