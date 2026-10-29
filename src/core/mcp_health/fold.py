
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.core.session_status_seed_records import parse_timestamp

if TYPE_CHECKING:
    from src.core.mcp_health.servers import ServerHealth

STATE_DROPPED: str = "dropped"
STATE_FAILED: str = "failed"
STATE_NEEDS_AUTH: str = "needs_auth"

SOURCE_TRANSCRIPT: str = "transcript"
SOURCE_SERVER: str = "server"

RECONCILE_WINDOW: timedelta = timedelta(seconds=2)

_RECONNECTED_ONE = re.compile(r"^(?:Successfully reconnected to (.+?)|Reconnected to (.+?)\.)$")
_RECONNECTED_ALL = re.compile(r"^Reconnected (\d+) of (\d+) MCP servers?\b")
_LOCAL_STDOUT = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.DOTALL)

MCP_TOOL_PREFIX: str = "mcp__"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class McpDrop:

    name: str
    state: str
    at: Optional[datetime] = None
    exact: bool = False
    source: str = SOURCE_TRANSCRIPT


@dataclass(frozen=True)
class McpEvent:

    at: Optional[datetime]
    exact: bool
    removed: Tuple[str, ...] = ()
    added: Tuple[str, ...] = ()
    failed: Tuple[str, ...] = ()
    needs_auth: Tuple[str, ...] = ()
    reconnect: bool = False
    all_connected: bool = False


@dataclass(frozen=True)
class CarnivoreLink:

    state: str
    initialized_at: Optional[datetime] = None
    last_request_at: Optional[datetime] = None


@dataclass(frozen=True)
class McpHealth:

    dropped: Tuple[McpDrop, ...] = ()
    carnivore: Optional[CarnivoreLink] = None
    servers: Tuple["ServerHealth", ...] = ()


def server_key(name: str) -> str:
    return _NON_ALNUM.sub("_", name.lower()).strip("_")


def window_start(records: Iterable[Any] | Sequence[Any]) -> Optional[datetime]:
    earliest: Optional[datetime] = None
    for record in records or ():
        if not isinstance(record, dict) or record.get("isSidechain") is True:
            continue
        at = parse_timestamp(record.get("timestamp"))
        if at is not None and (earliest is None or at < earliest):
            earliest = at
    return earliest


def _tool_server(tool_name: Any) -> Optional[str]:
    if not isinstance(tool_name, str) or not tool_name.startswith(MCP_TOOL_PREFIX):
        return None
    server = tool_name[len(MCP_TOOL_PREFIX):].split("__", 1)[0]
    return server or None


def _names(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _server_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [n for n in (v.get("name") if isinstance(v, dict) else v for v in value) if isinstance(n, str) and n]


class _Ledger:

    def __init__(self) -> None:
        self.drops: Dict[str, McpDrop] = {}
        self.connected: set[str] = set()
        self.seen = False

    def mark(self, name: str, state: str, at: Optional[datetime], exact: bool) -> None:
        key = server_key(name)
        if not key:
            return
        previous = self.drops.get(key)
        if previous is not None and previous.exact and not exact:
            name, exact = previous.name, True
        self.seen = True
        self.drops[key] = McpDrop(name=name, state=state, at=at, exact=exact)

    def clear(self, name: str) -> None:
        self.seen = True
        self.connected.add(server_key(name))
        self.drops.pop(server_key(name), None)


def _server_names(tools: List[str]) -> Tuple[str, ...]:
    seen: List[str] = []
    for tool in tools:
        server = _tool_server(tool)
        if server is not None and server not in seen:
            seen.append(server)
    return tuple(seen)


def _reconnect_event(record: Dict[str, Any]) -> Optional[McpEvent]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    if not isinstance(content, str):
        return None
    found = _LOCAL_STDOUT.search(content)
    if found is None:
        return None
    line = found.group(1).strip()
    at = parse_timestamp(record.get("timestamp"))
    every = _RECONNECTED_ALL.match(line)
    if every is not None:
        return McpEvent(at=at, exact=True, reconnect=True, all_connected=every.group(1) == every.group(2))
    one = _RECONNECTED_ONE.match(line)
    if one is not None and ", but " not in line:
        return McpEvent(at=at, exact=True, reconnect=True, added=(one.group(1) or one.group(2),))
    return None


def _blocks(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _worked_events(record: Dict[str, Any], open_calls: Dict[str, str]) -> List[McpEvent]:
    healed: List[McpEvent] = []
    at = parse_timestamp(record.get("timestamp"))
    for block in _blocks(record):
        if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
            server = _tool_server(block.get("name"))
            if server is not None:
                open_calls[block["id"]] = server
        elif block.get("type") == "tool_result" and block.get("is_error") is not True:
            call_id = block.get("tool_use_id")
            server = open_calls.pop(call_id, None) if isinstance(call_id, str) else None
            if server is not None:
                healed.append(McpEvent(at=at, exact=False, reconnect=True, added=(server,)))
    return healed


def extract_mcp_events(records: Iterable[Any] | Sequence[Any]) -> Tuple[McpEvent, ...]:
    events: List[McpEvent] = []
    open_calls: Dict[str, str] = {}
    for record in records or ():
        if not isinstance(record, dict) or record.get("isSidechain") is True:
            continue
        if record.get("type") in ("user", "assistant"):
            if record.get("type") == "user":
                healed = _reconnect_event(record)
                if healed is not None:
                    events.append(healed)
            events.extend(_worked_events(record, open_calls))
            continue
        if record.get("type") != "attachment":
            continue
        attachment = record.get("attachment")
        if not isinstance(attachment, dict):
            continue
        kind = attachment.get("type")
        at = parse_timestamp(record.get("timestamp"))
        if kind == "mcp_instructions_delta":
            events.append(McpEvent(
                at=at, exact=True,
                removed=tuple(_names(attachment.get("removedNames"))),
                added=tuple(_names(attachment.get("addedNames"))),
            ))
        elif kind == "deferred_tools_delta":
            events.append(McpEvent(
                at=at, exact=False,
                removed=_server_names(_names(attachment.get("removedNames"))),
                added=_server_names(_names(attachment.get("addedNames")) + _names(attachment.get("readdedNames"))),
                failed=tuple(_server_list(attachment.get("failedMcpServers"))),
                needs_auth=tuple(_server_list(attachment.get("needsAuthMcpServers"))),
            ))
    return tuple(events)


def fold_mcp_health(
    events: Iterable[McpEvent], *, since: Optional[datetime] = None, window_from: Optional[datetime] = None
) -> Optional[McpHealth]:
    ledger = _Ledger()
    events = tuple(events or ())
    resumed = since is not None and (
        (window_from is not None and window_from < since) or any(e.at is not None and e.at < since for e in events)
    )
    first_at: Optional[datetime] = None
    for event in events:
        if event.reconnect:
            if event.all_connected:
                ledger.drops = {k: d for k, d in ledger.drops.items() if d.state == STATE_NEEDS_AUTH}
                ledger.seen = True
            for name in event.added:
                ledger.clear(name)
            continue
        in_history = since is not None and event.at is not None and event.at < since
        if not in_history and resumed and first_at is None and event.at is not None:
            first_at = event.at
        reconciling = (
            first_at is not None and event.at is not None and event.at - first_at <= RECONCILE_WINDOW
        )
        for name in event.removed:
            ledger.connected.add(server_key(name))
            if in_history or reconciling:
                ledger.seen = True
            else:
                ledger.mark(name, STATE_DROPPED, event.at, event.exact)
        for name in event.added:
            ledger.clear(name)
        if in_history:
            continue
        for name in event.failed:
            ledger.mark(name, STATE_FAILED, event.at, True)
        for name in event.needs_auth:
            ledger.mark(name, STATE_NEEDS_AUTH, event.at, True)
    if not ledger.seen:
        return None
    return McpHealth(dropped=tuple(ledger.drops.values()))
