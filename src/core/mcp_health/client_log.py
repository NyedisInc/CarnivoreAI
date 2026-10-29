
from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.mcp_health.fold import server_key
from src.core.mcp_health.servers import (
    REASON_CLOSED, REASON_CONNECT_FAILED, REASON_CONNECTED, REASON_GAVE_UP, REASON_NEEDS_AUTH, REASON_NOT_IMPLEMENTED, REASON_RECONNECTING,
    STATE_CONNECTED, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN, TRANSPORT_HTTP, TRANSPORT_PROXY, TRANSPORT_SSE,
    TRANSPORT_STDIO, TRANSPORT_UNKNOWN,
)
from src.core.session_status_seed_records import parse_timestamp

log = structlog.get_logger()

LOG_DIR_PREFIX: str = "mcp-logs-"
LOG_SUFFIX: str = ".jsonl"
ATTRIBUTION_AFTER: timedelta = timedelta(seconds=20)
ATTRIBUTION_BEFORE: timedelta = timedelta(seconds=2)
RECONNECT_SETTLE: timedelta = timedelta(seconds=60)
FIRST_READ_BYTES: int = 8 * 1024 * 1024
MAX_READ_BYTES: int = 8 * 1024 * 1024
MAX_FILES: int = 2048

KIND_CONNECTED = "connected"
KIND_FAILED = "failed"
KIND_GAVE_UP = "gave_up"
KIND_NOT_IMPLEMENTED = "not_implemented"
KIND_CLOSED = "closed"
KIND_NEEDS_AUTH = "needs_auth"
KIND_RECONNECTING = "reconnecting"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_FAILED_CODE = re.compile(r"Connection failed(?: after \d+ms)? \(([A-Z][A-Z0-9_]{1,40})\)")
_NOT_IMPLEMENTED = re.compile(r"Connection failed(?: after [^()]*)? \((?:404|501)\)")
_TRANSPORT = re.compile(r"\(transport: ([a-z-]+)\)")
_STAMP = "%Y-%m-%dT%H-%M-%S-%fZ"

_RULES: Tuple[Tuple[str, str], ...] = (
    ("Max reconnection attempts", KIND_GAVE_UP),
    ("Successfully connected", KIND_CONNECTED),
    ("reconnection successful", KIND_CONNECTED),
    ("Connection established with capabilities", KIND_CONNECTED),
    ("In-process Chrome MCP server started", KIND_CONNECTED),
    ("Unauthorized", KIND_NEEDS_AUTH),
    ("needs-auth", KIND_NEEDS_AUTH),
    ("Connection failed (", KIND_FAILED),
    ("attempting automatic reconnection", KIND_RECONNECTING),
    ("Scheduling reconnection attempt", KIND_RECONNECTING),
    ("connection dropped after", KIND_RECONNECTING),
    ("server may be down", KIND_RECONNECTING),
    ("server may have crashed", KIND_RECONNECTING),
    ("Closing transport (", KIND_RECONNECTING),
    ("MCP session expired", KIND_RECONNECTING),
    ("connection closed after", KIND_CLOSED),
    ("Cleared connection cache", KIND_CLOSED),
    ("MCP server process exited", KIND_CLOSED),
    ("Connection abandoned", KIND_CLOSED),
)
_TOOL_OK = "completed successfully"
_NEEDLES: Tuple[bytes, ...] = tuple({n.encode() for n, _ in _RULES} | {_TOOL_OK.encode()})


def default_root() -> str:
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "claude-cli-nodejs")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "claude-cli-nodejs")


def cwd_slug(cwd: str) -> str:
    return _NON_ALNUM.sub("-", cwd)


def log_dir_name(server: str) -> str:
    return LOG_DIR_PREFIX + _NAME_UNSAFE.sub("-", server)


def classify_line(line: bytes) -> Optional[Tuple[str, Optional[datetime], Optional[str], Optional[str]]]:
    if not any(n in line for n in _NEEDLES):
        return None
    try:
        record = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    text = record.get("debug") if isinstance(record.get("debug"), str) else record.get("error")
    if not isinstance(text, str):
        return None
    text = text.split("\n", 1)[0]
    at = parse_timestamp(record.get("timestamp"))
    if text.startswith("Tool ") or text.startswith("Calling MCP tool"):
        return (KIND_CONNECTED, at, None, None) if _TOOL_OK in text else None
    for needle, kind in _RULES:
        if needle in text:
            detail = None
            hint = None
            if kind == KIND_FAILED:
                code = _FAILED_CODE.search(text)
                detail = code.group(1) if code else None
                if detail and "AUTH" in detail:
                    kind = KIND_NEEDS_AUTH
                elif _NOT_IMPLEMENTED.search(text):
                    kind = KIND_NOT_IMPLEMENTED
            found = _TRANSPORT.search(text)
            if found:
                hint = found.group(1)
            return kind, at, detail, hint
    return None


def transport_from_hint(hint: Optional[str]) -> str:
    return {"stdio": TRANSPORT_STDIO, "http": TRANSPORT_HTTP, "sse": TRANSPORT_SSE,
            "claudeai-proxy": TRANSPORT_PROXY}.get(hint or "", TRANSPORT_UNKNOWN)


@dataclass
class _FileState:

    inode: int = 0
    offset: int = 0
    tail: bytes = b""
    kind: Optional[str] = None
    at: Optional[datetime] = None
    detail: Optional[str] = None
    last_failure: Optional[str] = None
    transport: Optional[str] = None
    skip_fragment: bool = False


@dataclass(frozen=True)
class LinkState:

    dir_name: str
    transport: str
    state: str
    reason: str
    detail: Optional[str] = None
    at: Optional[datetime] = None

    @property
    def key(self) -> str:
        return server_key(self.dir_name)


def link_from_state(dir_name: str, state: _FileState, now: datetime) -> Optional[LinkState]:
    transport = transport_from_hint(state.transport)
    if state.kind is None:
        return None
    if state.kind == KIND_CONNECTED:
        return LinkState(dir_name, transport, STATE_CONNECTED, REASON_CONNECTED, None, state.at)
    if state.kind == KIND_GAVE_UP:
        return LinkState(dir_name, transport, STATE_DOWN, REASON_GAVE_UP, state.last_failure, state.at)
    if state.kind == KIND_FAILED:
        return LinkState(dir_name, transport, STATE_DOWN, REASON_CONNECT_FAILED, state.detail, state.at)
    if state.kind == KIND_NOT_IMPLEMENTED:
        return LinkState(dir_name, transport, STATE_DOWN, REASON_NOT_IMPLEMENTED, None, state.at)
    if state.kind == KIND_CLOSED:
        return LinkState(dir_name, transport, STATE_DOWN, REASON_CLOSED, None, state.at)
    if state.kind == KIND_NEEDS_AUTH:
        return LinkState(dir_name, transport, STATE_NEEDS_AUTH, REASON_NEEDS_AUTH, state.detail, state.at)
    settled = state.at is not None and now - state.at > RECONNECT_SETTLE
    return LinkState(dir_name, transport, STATE_DOWN if settled else STATE_UNKNOWN, REASON_RECONNECTING,
                     state.last_failure, state.at)


def _apply(state: _FileState, line: bytes) -> None:
    found = classify_line(line)
    if found is None:
        return
    kind, at, detail, hint = found
    if hint:
        state.transport = hint
    if kind == KIND_FAILED and detail:
        state.last_failure = detail
    if kind == KIND_CONNECTED:
        state.last_failure = None
    state.kind, state.at, state.detail = kind, at, detail


def _parse_stamp(name: str) -> Optional[datetime]:
    if not name.endswith(LOG_SUFFIX):
        return None
    try:
        return datetime.strptime(name[: -len(LOG_SUFFIX)], _STAMP).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class ClientLogReader:

    root: str = field(default_factory=default_root)
    _files: Dict[str, _FileState] = field(default_factory=dict)
    _dirs: Dict[str, Tuple[int, List[str]]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _listing(self, path: str) -> List[str]:
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            return []
        hit = self._dirs.get(path)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return []
        if len(self._dirs) > MAX_FILES:
            self._dirs.clear()
        self._dirs[path] = (stamp, names)
        return names

    def _read(self, path: str) -> Optional[_FileState]:
        try:
            info = os.stat(path)
        except OSError:
            return None
        state = self._files.get(path)
        if state is None or state.inode != info.st_ino or info.st_size < state.offset:
            start = max(0, info.st_size - FIRST_READ_BYTES)
            state = _FileState(inode=info.st_ino, offset=start, skip_fragment=start > 0)
            if len(self._files) >= MAX_FILES:
                self._files.clear()
            self._files[path] = state
        if info.st_size == state.offset:
            return state
        try:
            with open(path, "rb") as handle:
                handle.seek(state.offset)
                blob = handle.read(MAX_READ_BYTES)
        except OSError as exc:
            log.debug("mcp_client_log_unreadable", path=path, error=type(exc).__name__)
            return state
        state.offset += len(blob)
        data = state.tail + blob
        lines = data.split(b"\n")
        state.tail = lines.pop()
        if state.skip_fragment and lines:
            lines = lines[1:]
            state.skip_fragment = False
        for line in lines:
            _apply(state, line)
        return state

    def _attributed(self, cwd: Optional[str], started_at: Optional[datetime]) -> Optional[List[Tuple[str, str]]]:
        if not cwd or started_at is None:
            return None
        project = os.path.join(self.root, cwd_slug(cwd))
        dirs = [d for d in self._listing(project) if d.startswith(LOG_DIR_PREFIX)]
        if not dirs:
            return None
        found: List[Tuple[str, str]] = []
        for name in dirs:
            folder = os.path.join(project, name)
            best: Optional[Tuple[timedelta, str]] = None
            for entry in self._listing(folder):
                stamp = _parse_stamp(entry)
                if stamp is None:
                    continue
                delta = stamp - started_at
                if -ATTRIBUTION_BEFORE <= delta <= ATTRIBUTION_AFTER and (best is None or abs(delta) < best[0]):
                    best = (abs(delta), entry)
            if best is not None:
                found.append((name, os.path.join(folder, best[1])))
        return found

    def session_links(self, cwd: Optional[str], started_at: Optional[datetime], now: datetime) -> Optional[Dict[str, LinkState]]:
        with self._lock:
            files = self._attributed(cwd, started_at)
            if files is None:
                return None
            out: Dict[str, LinkState] = {}
            for name, path in files:
                state = self._read(path)
                link = link_from_state(name[len(LOG_DIR_PREFIX):], state, now) if state else None
                if link is not None:
                    out[link.key] = link
            return out

    def session_servers(self, cwd: Optional[str], started_at: Optional[datetime]) -> Optional[FrozenSet[str]]:
        with self._lock:
            files = self._attributed(cwd, started_at)
        if not files:
            return None
        return frozenset(server_key(name[len(LOG_DIR_PREFIX):]) for name, _ in files)

    def reset(self) -> None:
        with self._lock:
            self._files.clear()
            self._dirs.clear()


READER = ClientLogReader()


def with_name(link: LinkState, name: str) -> LinkState:
    return replace(link, dir_name=name)
