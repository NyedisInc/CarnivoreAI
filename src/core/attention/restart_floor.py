
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, Optional


class RestartFloors:

    def __init__(self) -> None:
        self._floors: Dict[str, datetime] = {}

    def stamp(self, session_id: str, now: datetime) -> None:
        self._floors[session_id] = now

    def floor_for(self, session_id: Optional[str]) -> Optional[datetime]:
        if not session_id:
            return None
        return self._floors.get(session_id)

    def abandon(self, session_id: str) -> None:
        self._floors.pop(session_id, None)


@dataclass
class RestartWindow:

    replaced: bool = False


@contextmanager
def restart_bracket(
    watcher: Any, backend: Any, session_id: Optional[str]
) -> Iterator[RestartWindow]:
    backend._attention_generation = getattr(backend, "_attention_generation", 0) + 1
    backend._attention_restarting = True
    if watcher is not None and session_id:
        watcher.invalidate_session(session_id)
    window = RestartWindow()
    try:
        yield window
    finally:
        backend._attention_restarting = False
        if watcher is not None and session_id and not window.replaced:
            watcher.abandon_process_floor(session_id)
