
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.timeline.model import FAMILY_CLAUDE

_DURABLE_KEY = re.compile(r"\A(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\Z")


@dataclass(frozen=True)
class LiveRef:

    session_id: str
    tmux_session: Optional[str]
    session_row_id: Optional[int]
    host_key: str
    activity_status: Optional[str]
    status_source: Optional[str]
    unread: Optional[bool]
    startup_gate: Optional[Any]

    @staticmethod
    def from_info(info: Any) -> "LiveRef":
        status = info.activity_status
        return LiveRef(info.session.id, info.tmux_session, info.session_row_id, info.host_key, getattr(status, "value", status),
                       info.status_source, info.unread, info.startup_gate)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "LiveRef":
        session = row.get("session") or {}
        return LiveRef(session.get("id", ""), row.get("tmux_session"), row.get("session_row_id"), row.get("host_key", LOCAL_HOST_KEY),
                       row.get("activity_status"), row.get("status_source"), row.get("unread"), row.get("startup_gate"))

    def lights(self) -> Dict[str, Any]:
        return {"status": self.activity_status, "status_source": self.status_source, "unread": self.unread,
                "startup_gate": self.startup_gate}


Listing = Callable[[], Awaitable[List[LiveRef]]]


@dataclass(frozen=True)
class Resolved:

    row: Any
    info: Optional[LiveRef] = None

    @property
    def row_family(self) -> str:
        from src.core.bookmarks import rows  # noqa: PLC0415

        return rows.family_of(self.row.agent_type)

    @property
    def conv(self) -> Optional[str]:
        return self.row.claude_session_uuid


def require_claude(row: Any) -> None:
    from src.core.bookmarks import rows  # noqa: PLC0415
    from src.core.bookmarks.errors import NotClaudeSession  # noqa: PLC0415

    family = rows.family_of(row.agent_type)
    if family != FAMILY_CLAUDE:
        raise NotClaudeSession(f"the timeline reads claude code sessions only; this one runs {family}")


async def manager_listing(manager: Any) -> List[LiveRef]:
    return [LiveRef.from_info(info) for info in await manager.list_session_infos()]


def _local(row: Any) -> Any:
    from src.core.bookmarks.errors import SessionNotFound  # noqa: PLC0415

    if getattr(row, "host_key", LOCAL_HOST_KEY) != LOCAL_HOST_KEY:
        raise SessionNotFound("no session with that id")
    return row


async def resolve(manager: Any, key: str, listing: Optional[Listing] = None) -> Resolved:
    from src.core.bookmarks import rows  # noqa: PLC0415
    from src.core.bookmarks.errors import SessionNotFound  # noqa: PLC0415

    key = key.strip()
    if not key:
        raise SessionNotFound("no session with that id")
    live = [ref for ref in await (listing() if listing else manager_listing(manager)) if ref.host_key == LOCAL_HOST_KEY]
    if _DURABLE_KEY.match(key):
        row = _local(await asyncio.to_thread(rows.read_row, key))
        return Resolved(row, next((ref for ref in live if ref.session_row_id == row.id), None))
    for ref in live:
        if ref.session_id == key or ref.tmux_session == key:
            if ref.session_row_id is None:
                raise SessionNotFound("that session has no stored row yet")
            return Resolved(_local(await asyncio.to_thread(rows.read_row, str(ref.session_row_id))), ref)
    return Resolved(_local(await asyncio.to_thread(rows.read_row, key)), None)


def pushed_listing(publisher: Any, manager: Any) -> Listing:
    async def rows() -> List[LiveRef]:
        entry = ((await publisher.snapshot()).get("collections") or {}).get("list") or {}
        if entry.get("ok") is False:
            return await manager_listing(manager)
        return [LiveRef.from_row(row) for row in entry.get("rows", [])]

    return rows
