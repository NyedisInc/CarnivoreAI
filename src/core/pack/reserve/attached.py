
from __future__ import annotations

import sqlite3
from typing import Any, Callable, List, Optional, Set

from src.core.pack.reserve import session_demote, throttle as throttle_mod


def visible_viewer_names(manager: Any, names: Set[str]) -> Set[str]:
    negotiator = getattr(manager, "_terminal_size_negotiator", None)
    registry = getattr(manager, "_registry", None)
    if negotiator is None or registry is None:
        return set()
    out: Set[str] = set()
    for name in names:
        try:
            if any(negotiator.visible_count(sid) > 0 for sid in registry.registered_ids_for_tmux_name(name)):
                out.add(name)
        except (RuntimeError, AttributeError):
            out.add(name)
    return out


def make_viewing(manager_of: Callable[[], Any]) -> throttle_mod.Viewing:
    def viewing(names: Set[str]) -> Set[str]:
        return (names & session_demote.focused_sessions()) | visible_viewer_names(manager_of(), names)
    return viewing


class BodyPanes:

    def __init__(self, open_db: Callable[[], sqlite3.Connection], *, run: Optional[Callable[[List[str]], Optional[str]]] = None,
                 viewing: Optional[throttle_mod.Viewing] = None) -> None:
        self._open_db, self._run, self._viewing = open_db, run, viewing
        self._held: List[int] = []

    def loose(self) -> List[int]:
        loose, self._held = throttle_mod.agent_panes(self._open_db, run=self._run, viewing=self._viewing)
        return loose

    def attached(self) -> List[int]:
        return list(self._held)
