
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog

from src.core.theme_paths import user_themes_dir

logger = structlog.get_logger()


class ThemeAccents:

    def __init__(self) -> None:
        self.cache: dict[str, Optional[str]] = {}

    @staticmethod
    def themes_dir() -> Path:
        return (
            Path(__file__).resolve().parent.parent.parent.parent
            / "client"
            / "css"
            / "themes"
        )

    def accent_for_theme(self, theme_id: Optional[str]) -> Optional[str]:
        if not theme_id or theme_id in (".", "..") or "/" in theme_id or "\\" in theme_id:
            return None
        if theme_id in self.cache:
            return self.cache[theme_id]

        accent: Optional[str] = None
        found = False
        for root in (self.themes_dir(), user_themes_dir()):
            manifest_path = root / theme_id / "theme.json"
            try:
                with manifest_path.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except FileNotFoundError:
                continue
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.debug(
                    "toast_theme_accent_read_failed",
                    theme_id=theme_id,
                    path=str(manifest_path),
                    error=str(exc),
                )
                found = True
                break
            found = True
            css_vars = raw.get("cssVars") if isinstance(raw, dict) else None
            if isinstance(css_vars, dict):
                val = css_vars.get("--color-accent")
                if isinstance(val, str) and val.strip():
                    accent = val.strip()
            break

        if found:
            self.cache[theme_id] = accent
        return accent
