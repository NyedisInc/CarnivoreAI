
from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

import structlog

from src.core.conversation_writers import MeasureError, read_process_table
from src.core.mcp_health import host_methods
from src.core.mcp_health.agent_process import find_agent
from src.core.mcp_health.fold import McpDrop, McpHealth, STATE_DROPPED, STATE_FAILED, STATE_NEEDS_AUTH as DROP_NEEDS_AUTH, SOURCE_SERVER, SOURCE_TRANSCRIPT
from src.core.mcp_health.monitor import McpMonitor
from src.core.mcp_health.servers import (
    SOURCE_CLIENT_LOG, SOURCE_FIRST_HAND, SOURCE_PROBE, SOURCE_PROCESS, STATE_CONNECTED, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN,
    TRANSPORT_HTTP, TRANSPORT_PROXY, TRANSPORT_SSE, TRANSPORT_STDIO, TRANSPORT_UNKNOWN, ServerHealth,
)
from src.core.mcp_health.targets import monitor_target
from src.core.session_status_seed_records import parse_timestamp
from src.cplugs.sdk import ports
from src.cplugs.sdk.listing import listing_wake
from src.cplugs.sdk.mcp_health import PORT_NAME, attention_watcher, tmux_socket

logger = structlog.get_logger()

PLUGIN_ID = "mcphealth"
EVENT_FAMILY = "mcp.health"
_SERVER_STATES = frozenset({STATE_CONNECTED, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN})
_DROP_STATES = frozenset({STATE_DROPPED, STATE_FAILED, DROP_NEEDS_AUTH})
_TRANSPORTS = frozenset({TRANSPORT_STDIO, TRANSPORT_HTTP, TRANSPORT_SSE, TRANSPORT_PROXY, TRANSPORT_UNKNOWN})
_SOURCES = frozenset({SOURCE_CLIENT_LOG, SOURCE_FIRST_HAND, SOURCE_PROBE, SOURCE_PROCESS, SOURCE_TRANSCRIPT, SOURCE_SERVER})
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def _text(value: Any, limit: int = 80) -> str:
    return value[:limit] if isinstance(value, str) else ""


def health_from_document(document: Optional[Mapping[str, Any]], session_id: str) -> Optional[McpHealth]:
    data = document.get("data") if isinstance(document, Mapping) else None
    sessions = data.get("sessions") if isinstance(data, Mapping) else None
    entry = sessions.get(session_id) if isinstance(sessions, Mapping) else None
    if not isinstance(entry, Mapping):
        return None
    servers: List[ServerHealth] = []
    for raw in entry.get("servers") or ():
        if isinstance(raw, Mapping) and _text(raw.get("name")):
            reason = raw.get("reason")
            servers.append(ServerHealth(
                name=_text(raw.get("name")), transport=raw.get("transport") if raw.get("transport") in _TRANSPORTS else TRANSPORT_UNKNOWN,
                state=raw.get("state") if raw.get("state") in _SERVER_STATES else STATE_UNKNOWN,
                reason=reason if isinstance(reason, str) and _CODE.match(reason) else "",
                source=raw.get("source") if raw.get("source") in _SOURCES else SOURCE_TRANSCRIPT,
                detail=_text(raw.get("detail"), 120) or None, at=parse_timestamp(raw.get("at")), exact=raw.get("exact") is not False))
    drops = tuple(McpDrop(name=_text(d.get("name")), state=d["state"], at=parse_timestamp(d.get("at")), exact=d.get("exact") is not False,
                          source=d.get("source") if d.get("source") in _SOURCES else SOURCE_TRANSCRIPT)
                  for d in (entry.get("dropped") or ()) if isinstance(d, Mapping) and _text(d.get("name")) and d.get("state") in _DROP_STATES)
    return McpHealth(dropped=drops, servers=tuple(servers))


class HostMcpHealth:

    def __init__(self, deliver: Callable[[str, int, Any], Awaitable[bool]], render: Callable[[], Awaitable[Optional[Dict[str, Any]]]]) -> None:
        self._deliver, self._render = deliver, render
        self.monitor: Optional[McpMonitor] = None
        self.app_state: Any = None
        self._targets: Dict[str, Any] = {}
        self._document: Optional[Dict[str, Any]] = None
        self._task: Optional[asyncio.Task] = None
        self._wake_task: Optional[asyncio.Task] = None
        self._wake_again = False
        self._seq = 0


    def start(self) -> None:
        if self.monitor is not None:
            return
        self.monitor = McpMonitor()
        self._task = asyncio.create_task(self.monitor.run(lambda: tmux_socket(self.app_state) or "", self._moved))
        ports.register(PORT_NAME, self)

    async def stop(self) -> None:
        monitor, task, wake = self.monitor, self._task, self._wake_task
        self.monitor = self._task = self._wake_task = None
        self._document, self._targets = None, {}
        if ports.get(PORT_NAME) is self:
            ports.unregister(PORT_NAME)
        for pending in (task, wake):
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
        if monitor is not None:
            monitor.close()


    def _moved(self) -> None:
        if self._wake_task is not None and not self._wake_task.done():
            self._wake_again = True
            return
        self._wake_task = asyncio.create_task(self._send_wake())

    async def _send_wake(self) -> None:
        while True:
            self._wake_again = False
            self._seq += 1
            try:
                await self._deliver(EVENT_FAMILY, self._seq, {"sessions": len(self._targets)})
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("mcp_health_wake_failed", error_type=type(exc).__name__)
                return
            if not self._wake_again:
                return

    async def refresh(self) -> None:
        try:
            document = await self._render()
        except (RuntimeError, ValueError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("mcp_health_render_failed", error_type=type(exc).__name__)
            return
        if document is not None and self.monitor is not None:
            self._document = document
            if self.app_state is not None:
                listing_wake(self.app_state)()


    def stamp(self, app_state: Any, rows: Sequence[Any], now: datetime) -> List[Optional[McpHealth]]:
        self.app_state = app_state
        watcher = attention_watcher(app_state)
        targets = [t for t in (monitor_target(watcher, r, now) for r in rows) if t is not None]
        self._targets = {t.session_id: t for t in targets}
        if self.monitor is not None:
            self.monitor.register(targets)
        return [health_from_document(self._document, str(r.session.id)) for r in rows]

    def health_for(self, app_state: Any, row: Any, now: datetime) -> Optional[McpHealth]:
        return health_from_document(self._document, str(row.session.id))


    def _pick(self, ref: Optional[str]) -> List[Any]:
        return [t for t in self._targets.values() if ref is None or ref in (t.session_id, t.tmux_name)]

    def _measures(self) -> Mapping[str, Any]:
        monitor = self.monitor
        return {} if monitor is None else {sid: m for sid in self._targets if (m := monitor.measure_for(sid)) is not None}

    async def process_snapshot(self) -> Dict[str, Any]:
        try:
            table = await asyncio.to_thread(read_process_table)
        except MeasureError as exc:
            logger.warning("mcp_health_ps_failed", error=str(exc))
            return {"processes": []}
        targets = self._pick(None)
        roots = {}
        for t in targets:
            pid = t.agent_pid if t.agent_pid in table.rows else find_agent(table, t.pane_pid, t.family)
            if pid is not None:
                roots[t.session_id] = pid
        return {"processes": host_methods.process_rows(table, targets, roots)}

    async def mcp_config(self, ref: Optional[str]) -> Dict[str, Any]:
        return {"sessions": host_methods.config_rows(self._pick(ref), self._measures())}

    async def mcp_links(self, ref: Optional[str]) -> Dict[str, Any]:
        return {"sessions": host_methods.link_rows(self._pick(ref), self._measures())}
