
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from src.core.mcp import common
from src.core.mcp.common import ToolError

LIVE = "live"
STORED = "stored"
PINNED = "pinned"
CLOSED = "closed"
_REACHES = (LIVE, STORED, PINNED, CLOSED)

COMPANION_TOOLS = frozenset({"session_read_output", "session_send_keys"})

KIND_LIVE = "live"
KIND_ASLEEP = "asleep"
KIND_ORPHAN_PIN = "orphan_pin"
KIND_CLOSED = "closed"


@dataclass(frozen=True)
class SessionTarget:

    kind: str
    info: Any = None
    row: Optional[dict] = None
    session_uuid: Optional[str] = None
    tmux_name: Optional[str] = None

    @property
    def live(self) -> bool:
        return self.kind == KIND_LIVE

    @property
    def shown(self) -> str:
        if self.info is not None:
            return self.info.tmux_session or self.info.session.id
        return self.tmux_name or self.session_uuid or ""


def _target_text(args: Any) -> str:
    target = args.get("target") if isinstance(args, dict) else args
    if not isinstance(target, str) or not target.strip():
        raise ToolError("target is required: a session id, adopted:<name> or tmux name")
    return target.strip()


def asleep_summary(row: dict) -> dict:
    uuid = str(row["session_uuid"])
    label = (row.get("title") or "").strip() or (row.get("claude_title") or "").strip() or None
    return {
        "id": uuid, "session_uuid": uuid, "tmux_session": row.get("tmux_name"), "label": label,
        "agent_type": row.get("agent_type"), "project": row.get("project_name"), "working_dir": row.get("working_dir"),
        "activity_status": "asleep", "unread": None, "asleep": True,
    }


def closed_summary(row: dict) -> dict:
    return {**asleep_summary(row), "activity_status": "closed", "asleep": False, "closed": True,
            "lifecycle_source": row.get("lifecycle_source")}


@dataclass
class TargetResolver:

    manager: Any
    _infos: Optional[list] = field(default=None, repr=False)
    _asleep: Optional[list] = field(default=None, repr=False)
    _closed: Optional[list] = field(default=None, repr=False)

    async def infos(self) -> list:
        if self._infos is None:
            self._infos = await common._all_infos(self.manager)
        return self._infos

    async def asleep_rows(self) -> list:
        if self._asleep is None:
            from src.core.crosstalk import directory

            self._asleep = await asyncio.to_thread(directory._asleep_rows)
        return self._asleep

    async def closed_rows(self) -> list:
        if self._closed is None:
            from src.core.crosstalk import directory

            self._closed = await asyncio.to_thread(directory._closed_rows)
        return self._closed

    async def closed_row(self, target: str) -> Optional[dict]:
        return next((r for r in await self.closed_rows() if str(r["session_uuid"]) == target), None)

    async def asleep_row(self, target: str, *, uuid_only: bool = False) -> Optional[dict]:
        rows = await self.asleep_rows()
        hits = [r for r in rows if str(r["session_uuid"]) == target]
        if not hits and not uuid_only:
            hits = [r for r in rows if r.get("tmux_name") == target]
        if len(hits) > 1:
            raise ToolError(f"{len(hits)} asleep sessions are named {target!r}: use a session_uuid")
        return hits[0] if hits else None

    async def resolve(self, args: Any, *, reach: str = LIVE, tool: str = "") -> SessionTarget:
        if reach not in _REACHES:
            raise ValueError(f"unknown reach {reach!r}")
        target = _target_text(args)
        try:
            return SessionTarget(kind=KIND_LIVE, info=common._resolve(await self.infos(), {"target": target}))
        except ToolError as live_miss:
            companion = await self._companion_info(target)
            if companion is not None:
                if tool in COMPANION_TOOLS:
                    return SessionTarget(kind=KIND_LIVE, info=companion)
                raise ToolError(f"{target!r} is a companion shell: only {', '.join(sorted(COMPANION_TOOLS))} reach it") from None
            row = await self.asleep_row(target)
            if row is not None:
                if reach == LIVE:
                    raise ToolError(f"{target!r} is asleep (session_uuid {row['session_uuid']}): "
                                    f"{tool or 'this tool'} needs a live session; wake it with session_wake first") from None
                return SessionTarget(kind=KIND_ASLEEP, row=row, session_uuid=str(row["session_uuid"]),
                                     tmux_name=row.get("tmux_name"))
            if reach == CLOSED:
                closed = await self.closed_row(target)
                if closed is not None:
                    return SessionTarget(kind=KIND_CLOSED, row=closed, session_uuid=str(closed["session_uuid"]),
                                         tmux_name=closed.get("tmux_name"))
            if reach == PINNED:
                orphan = await self._orphan_pin(target)
                if orphan is not None:
                    return orphan
            if reach == LIVE:
                raise live_miss
            raise ToolError(f"no live or asleep session matches target {target!r}"
                            + (" and no drawer pin carries it" if reach == PINNED else
                               " and no closed session with that session_uuid has a conversation to resume" if reach == CLOSED else "")) from None

    async def _companion_info(self, target: str) -> Any:
        from src.core.mcp.protocol import BatchView

        return await self.manager.companion_info(target) if isinstance(self.manager, BatchView) else None

    async def _orphan_pin(self, target: str) -> Optional[SessionTarget]:
        from src.core.mcp import pin_tools
        from src.core.mcp.write_tools import _request

        pinned = await pin_tools.pinned_session_uuids(_request(self.manager))
        if not pinned:
            return None
        names = await asyncio.to_thread(pin_tools._names_of, pinned)
        if target in pinned:
            return SessionTarget(kind=KIND_ORPHAN_PIN, session_uuid=target, tmux_name=names.get(target))
        hits = [u for u in pinned if names.get(u) == target]
        if len(hits) > 1:
            raise ToolError(f"{len(hits)} pins carry the name {target!r}: use the session_uuid from session_pins_list")
        return SessionTarget(kind=KIND_ORPHAN_PIN, session_uuid=hits[0], tmux_name=target) if hits else None

    async def uuid_of(self, target: SessionTarget) -> str:
        if target.session_uuid:
            return target.session_uuid
        row_id = getattr(target.info, "session_row_id", None)
        uuid = None if row_id is None else await asyncio.to_thread(_session_uuid_of_row, row_id)
        if uuid is None:
            raise ToolError("no stored row for that session")
        return uuid


def _session_uuid_of_row(row_id: int) -> Optional[str]:
    from src.core.mcp.write_tools import _session_uuid_of_row as read

    return read(row_id)


async def resolve_target(manager: Any, args: Any, *, reach: str = LIVE, tool: str = "") -> SessionTarget:
    return await TargetResolver(manager).resolve(args, reach=reach, tool=tool)


async def live_info(manager: Any, args: Any, tool: str = "") -> Any:
    return (await resolve_target(manager, args, reach=LIVE, tool=tool)).info
