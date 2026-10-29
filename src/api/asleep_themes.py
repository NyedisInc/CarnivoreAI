
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from src.core.session_theme_resolution import resolve_theme
from src.core.sessions import theme_dotfile


def read_dotfile_themes(rows: Iterable[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    dirs = {row.get("working_dir") for row in rows if row.get("working_dir")}
    return {wd: theme_dotfile.read_project_theme_cached(wd) for wd in dirs}


class PrefetchedThemes:

    def __init__(self, store: Any, dotfile_themes: Dict[str, Optional[str]]) -> None:
        self._store = store
        self._dotfile_themes = dotfile_themes

    def resolve_project_theme(self, working_dir: Any, tmux_name: Optional[str] = None) -> Optional[str]:
        if working_dir not in self._dotfile_themes:
            return self._store.resolve_project_theme(working_dir, tmux_name)
        pinned = self._store.get_pin(tmux_name) if tmux_name else None
        return resolve_theme(pinned=pinned, project_default=self._dotfile_themes[working_dir]).theme_id
