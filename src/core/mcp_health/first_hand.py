
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from src.core.mcp_health.fold import (
    SOURCE_SERVER, STATE_DROPPED, CarnivoreLink, McpDrop, McpHealth, server_key,
)

CARNIVORE_SERVER: str = "carnivore"
LINK_CONNECTED: str = "connected"
LINK_DROPPED: str = "dropped"
LINK_UNKNOWN: str = "unknown"

GRACE: timedelta = timedelta(seconds=30)
MAX_SESSIONS: int = 4096
INITIALIZE_METHOD: str = "initialize"

PROCESS_BOOT_AT: datetime = datetime.now(timezone.utc)


@dataclass(frozen=True)
class McpSeen:

    initialized_at: Optional[datetime] = None
    requested_at: Optional[datetime] = None

    @property
    def latest(self) -> Optional[datetime]:
        stamps = [t for t in (self.initialized_at, self.requested_at) if t is not None]
        return max(stamps) if stamps else None


class McpLinkTable:

    def __init__(self) -> None:
        self._seen: Dict[str, McpSeen] = {}
        self._lock = threading.Lock()

    def record(self, tmux_name: str, method: str, at: Optional[datetime] = None) -> None:
        if not tmux_name or not isinstance(method, str):
            return
        when = at or datetime.now(timezone.utc)
        with self._lock:
            old = self._seen.pop(tmux_name, McpSeen())
            self._seen[tmux_name] = McpSeen(
                initialized_at=when if method == INITIALIZE_METHOD else old.initialized_at, requested_at=when,
            )
            if len(self._seen) > MAX_SESSIONS:
                for stale in list(self._seen)[: MAX_SESSIONS // 2]:
                    del self._seen[stale]

    def seen(self, tmux_name: Optional[str]) -> Optional[McpSeen]:
        if not tmux_name:
            return None
        with self._lock:
            return self._seen.get(tmux_name)

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()


LINKS = McpLinkTable()


def carnivore_state(
    seen: Optional[McpSeen], *, started_at: Optional[datetime], now: datetime, expects_server: bool,
    boot_at: Optional[datetime] = None, grace: timedelta = GRACE,
) -> str:
    latest = seen.latest if seen is not None else None
    if latest is not None and (started_at is None or latest >= started_at):
        return LINK_CONNECTED
    if not expects_server or started_at is None:
        return LINK_UNKNOWN
    reference = max(boot_at or PROCESS_BOOT_AT, started_at)
    return LINK_DROPPED if now - reference > grace else LINK_UNKNOWN


def apply_carnivore_link(
    folded: Optional[McpHealth], state: str, seen: Optional[McpSeen]
) -> Optional[McpHealth]:
    key = server_key(CARNIVORE_SERVER)
    others = tuple(d for d in (folded.dropped if folded else ()) if server_key(d.name) != key)
    link = CarnivoreLink(
        state=state,
        initialized_at=seen.initialized_at if seen else None,
        last_request_at=seen.requested_at if seen else None,
    )
    if state == LINK_DROPPED:
        others += (McpDrop(CARNIVORE_SERVER, STATE_DROPPED, None, True, SOURCE_SERVER),)
    if folded is None and state == LINK_UNKNOWN:
        return None
    return McpHealth(dropped=others, carnivore=link)
