
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.session_theme_resolution import resolve_theme
from src.core.sessions import theme_dotfile, theme_global
from src.core.unique_tmp_path import unique_tmp_path
from src.core.sessions.theme_accents import ThemeAccents

logger = structlog.get_logger()


class ThemeStore:

    def __init__(
        self,
        *,
        pin_path: Callable[[], Path],
        accents: Optional[ThemeAccents] = None,
        global_theme: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._pin_path = pin_path
        self.global_theme_reader = global_theme
        self.pinned_themes: dict[str, str] = {}
        self.accents: ThemeAccents = (
            accents if accents is not None else ThemeAccents()
        )

    @property
    def accent_cache(self) -> dict[str, Optional[str]]:
        return self.accents.cache


    def load(self) -> None:
        path = self._pin_path()
        if not path.exists():
            return
        try:
            with open(path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                logger.warning(
                    "pinned_themes_unexpected_shape",
                    type=type(raw).__name__,
                )
                return
            self.pinned_themes = {
                str(k): v for k, v in raw.items()
                if isinstance(v, str) and v
            }
            logger.info(
                "pinned_themes_loaded", count=len(self.pinned_themes)
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("failed_to_load_pinned_themes", error=str(exc))

    def save(self) -> None:
        path = self._pin_path()
        tmp: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                try:
                    path.with_suffix(path.suffix + ".bak").write_bytes(
                        path.read_bytes()
                    )
                except OSError as exc:
                    logger.warning(
                        "pinned_themes_backup_failed",
                        path=str(path),
                        error=str(exc),
                    )
            tmp = unique_tmp_path(path)
            with tmp.open("w") as f:
                json.dump(self.pinned_themes, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(str(tmp), str(path))
        except (OSError, TypeError, ValueError) as exc:
            logger.error("failed_to_save_pinned_themes", error=str(exc))
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass


    def get_pin(self, tmux_name: Optional[str]) -> Optional[str]:
        if not tmux_name:
            return None
        return self.pinned_themes.get(tmux_name)

    def set_pin(self, tmux_name: Optional[str], theme_id: Optional[str]) -> bool:
        if not tmux_name:
            return False
        if theme_id:
            self.pinned_themes[tmux_name] = theme_id
        else:
            self.pinned_themes.pop(tmux_name, None)
        self.save()
        return True

    def discard_pin(self, tmux_name: Optional[str]) -> None:
        if tmux_name and tmux_name in self.pinned_themes:
            self.pinned_themes.pop(tmux_name, None)
            self.save()

    def discard_theme(self, theme_id: Optional[str]) -> list[str]:
        if not theme_id:
            return []
        hit = sorted(
            name
            for name, pinned in self.pinned_themes.items()
            if pinned == theme_id
        )
        if not hit:
            return []
        logger.info("pinned_themes_dropping_theme", theme=theme_id, names=hit)
        for name in hit:
            self.pinned_themes.pop(name, None)
        self.save()
        return hit

    def rekey_pin(self, old_name: str, new_name: str) -> bool:
        if old_name not in self.pinned_themes:
            return False
        self.pinned_themes[new_name] = self.pinned_themes.pop(old_name)
        self.save()
        return True

    def prune_to_live(self, live_names: set[str]) -> list[str]:
        if not self.pinned_themes:
            return []
        dead = sorted(
            name for name in self.pinned_themes if name not in live_names
        )
        if not dead:
            return []
        logger.info("pinned_themes_pruning_dead", names=dead)
        for name in dead:
            self.pinned_themes.pop(name, None)
        self.save()
        return dead


    project_theme_path = staticmethod(theme_dotfile.project_theme_path)

    def get_project_theme(self, working_dir) -> Optional[str]:
        return theme_dotfile.read_project_theme(working_dir)

    def set_project_theme(self, working_dir, theme_id: Optional[str]) -> None:
        theme_dotfile.write_project_theme(working_dir, theme_id)
    def resolve_project_theme(
        self, working_dir, tmux_name: Optional[str] = None
    ) -> Optional[str]:
        return resolve_theme(
            pinned=self.get_pin(tmux_name) if tmux_name else None,
            project_default=self.get_project_theme(working_dir),
        ).theme_id

    @staticmethod
    def legacy_pin_key(
        tmux_session: Optional[str], session_id: Optional[str]
    ) -> Optional[str]:
        if tmux_session:
            return tmux_session
        sid = session_id or ""
        if sid.startswith("adopted:"):
            return sid[len("adopted:"):] or None
        return sid or None

    def accent_for_theme(self, theme_id: Optional[str]) -> Optional[str]:
        return self.accents.accent_for_theme(theme_id)

    def accent_for(
        self, working_dir, tmux_name: Optional[str]
    ) -> Optional[str]:
        return self.accent_for_theme(
            theme_global.effective_theme(self, working_dir, tmux_name)
        )
