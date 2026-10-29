
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog

from src.core.theme_paths import user_themes_dir

logger = structlog.get_logger(__name__)

THEMES_DIR = Path(__file__).resolve().parents[2] / "client" / "css" / "themes"
DEFAULT_THEME = "carnivore"

HUE_KEYS = {
    "green": "green", "yellow": "yellow", "light-blue": "brightBlue", "gray": "white",
    "dark-gray": "brightBlack", "red": "red",
}
FALLBACK_XTERM = {
    "background": "#000000", "foreground": "#c0c0c0", "red": "#cc5544", "green": "#44cc66", "yellow": "#ccaa44",
    "white": "#c0c0c0", "brightBlack": "#707070", "brightBlue": "#6699cc",
}


@dataclass(frozen=True)
class Palette:

    theme_id: str
    background: str
    foreground: str
    accent: str
    titlerow: str
    frame: str
    muted: str
    coral: str
    hues: Mapping[str, str]
    truecolor: bool

    def hue(self, name: str) -> str:
        return self.hues[name]

    def css_variables(self) -> dict[str, str]:
        return {"frame": self.frame, "muted": self.muted, "coral": self.coral, "titlerow": self.titlerow}


def supports_truecolor(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get("COLORTERM") or "").lower() in ("truecolor", "24bit")


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def nearest_256(color: str) -> str:
    r, g, b = _rgb(color)
    steps = (0, 95, 135, 175, 215, 255)
    cube = tuple(min(steps, key=lambda s: abs(s - v)) for v in (r, g, b))
    level = round((r + g + b) / 3)
    gray_v = min(range(8, 239, 10), key=lambda s: abs(s - level))
    gray = (gray_v, gray_v, gray_v)
    best = min((cube, gray), key=lambda c: sum((a - b_) ** 2 for a, b_ in zip(c, (r, g, b))))
    return "#%02x%02x%02x" % best


def _hex(value: Any, fallback: str) -> str:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            _rgb(value)
            return value.lower()
        except ValueError:
            pass
    return fallback


def _read_theme(theme_id: str, *roots: Path) -> Optional[dict[str, Any]]:
    if theme_id in ("", ".", "..") or "/" in theme_id or "\\" in theme_id:
        return None
    error = "FileNotFoundError"
    for root in roots:
        try:
            data = json.loads((root / theme_id / "theme.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            error = type(exc).__name__
            continue
        if isinstance(data, dict) and isinstance(data.get("xterm"), dict):
            return data
        error = "NoXtermBlock"
    logger.info("tui_theme_unreadable", theme=theme_id, error=error)
    return None


def load_palette(
    theme_id: Optional[str],
    *,
    truecolor: Optional[bool] = None,
    themes_dir: Path = THEMES_DIR,
    user_dir: Optional[Path] = None,
) -> Palette:
    deep = supports_truecolor() if truecolor is None else truecolor
    roots = (themes_dir, user_themes_dir() if user_dir is None else user_dir)
    data = _read_theme(theme_id, *roots) if theme_id else None
    used = theme_id if data else DEFAULT_THEME
    if data is None:
        data = _read_theme(DEFAULT_THEME, themes_dir)
    xterm = {**FALLBACK_XTERM, **(data["xterm"] if data else {})}
    css = (data or {}).get("cssVars") or {}
    fit = (lambda c: c) if deep else nearest_256
    bg = _hex(xterm.get("background"), FALLBACK_XTERM["background"])
    fg = _hex(xterm.get("foreground"), FALLBACK_XTERM["foreground"])
    return Palette(
        theme_id=used,
        background=fit(bg),
        foreground=fit(fg),
        accent=fit(_hex(css.get("--color-accent"), _hex(xterm.get("cursor"), fg))),
        titlerow=fit(_hex(css.get("--color-header-bg"), bg)),
        frame=fit(_hex(css.get("--color-border"), _hex(xterm.get("brightBlack"), fg))),
        muted=fit(_hex(css.get("--color-fg-muted"), _hex(xterm.get("brightBlack"), fg))),
        coral=fit(_hex(xterm.get("red"), FALLBACK_XTERM["red"])),
        hues={name: fit(_hex(xterm.get(key), fg)) for name, key in HUE_KEYS.items()},
        truecolor=deep,
    )


_active: Optional[Palette] = None


def active() -> Palette:
    global _active
    if _active is None:
        _active = load_palette(DEFAULT_THEME)
    return _active


def set_active(palette: Palette) -> None:
    global _active
    _active = palette
