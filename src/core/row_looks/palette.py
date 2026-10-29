
from __future__ import annotations

from typing import Optional, Tuple

COLORS: Tuple[str, ...] = (
    "orange", "green", "cyan", "yellow", "coral", "violet", "green-bright", "yellow-bright",
)
ICONS: Tuple[str, ...] = (
    "docs", "files", "folder", "code", "terminal", "globe", "link", "bookmark", "star", "bolt", "rocket", "chart",
    "database", "cpu", "lab", "bell", "eye", "pencil", "lock", "info", "question", "spark", "cube", "radar", "activity",
    "gear", "swarm", "bot", "pin", "skull", "crown", "image", "chat", "inbox-tray",
)


class RowLookRefused(ValueError):
    pass


def checked(color: Optional[str], icon: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if color is not None and color not in COLORS:
        raise RowLookRefused(f"unknown color {color!r}; valid colors: {', '.join(COLORS)}")
    if icon is not None and icon not in ICONS:
        raise RowLookRefused(f"unknown icon {icon!r}; valid icons: {', '.join(ICONS)}")
    return color, icon
