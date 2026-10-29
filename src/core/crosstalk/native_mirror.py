
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, Optional

import structlog

from src.core.crosstalk import directory
from src.core.mcp.protocol import BatchView
from src.core.session_token_usage.cache import HEAD_BYTES, IncrementalCache, StatSignature, stat_signature
from src.core.session_token_usage.persist_spec import PersistSpec
from src.core.session_transcript_presence import conversation_presence

logger = structlog.get_logger(__name__)
_positions: dict[str, int] = {}
_pending: dict[str, dict[str, tuple[str, str, int, int]]] = {}
_unresolved: dict[str, dict[str, tuple[str, str, str, str]]] = {}
_lock = asyncio.Lock()
_refs: dict[str, dict[str, "LineRef"]] = {}
_uncommitted: set[str] = set()
_committed: dict[str, tuple[int, frozenset[str]]] = {}
LineRef = tuple[int, int, int, int]


@dataclass(frozen=True)
class MirrorCursor:

    pending: tuple[tuple[str, str, str, int, int], ...] = ()
    undelivered: tuple[LineRef, ...] = ()


class _Snapshot(NamedTuple):

    size: int
    mtime_ns: int
    head: bytes
    offset: int
    signature: StatSignature
    pending: tuple[tuple[str, str, str, int, int], ...]


def encode_cursor(cursor: MirrorCursor) -> dict[str, Any]:
    return {"p": [list(call) for call in cursor.pending], "u": [list(ref) for ref in cursor.undelivered]}


def _is_offset(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def decode_cursor(value: Any) -> MirrorCursor:
    if not isinstance(value, dict) or set(value) != {"p", "u"} or not all(isinstance(value[k], list) for k in "pu"):
        raise ValueError("mirror cursor payload has the wrong fields")
    calls = []
    for row in value["p"]:
        tool_id, to, body, start, length = row
        if not (isinstance(tool_id, str) and isinstance(to, str) and isinstance(body, str)
                and _is_offset(start) and _is_offset(length)):
            raise TypeError("mirror cursor call fields have the wrong types")
        calls.append((tool_id, to, body, start, length))
    refs = []
    for row in value["u"]:
        start, length, call_start, call_length = row
        if not all(_is_offset(item) for item in row) or length == 0:
            raise TypeError("mirror cursor reference fields must be offsets")
        refs.append((start, length, call_start, call_length))
    return MirrorCursor(tuple(calls), tuple(refs))


MIRROR_CURSOR_SPEC = PersistSpec(
    name="crosstalk.native_mirror", manual_version=2,
    sources=("src.core.crosstalk.native_mirror", "src.core.session_token_usage.cache",
             "src.core.session_token_usage.persist_spec"),
    encode=encode_cursor, decode=decode_cursor,
)
_MIRROR_CURSORS = IncrementalCache(max_entries=1024, persist=MIRROR_CURSOR_SPEC)
_WRAPPER = re.compile(r'^<cross-session-message\b[^>]*\bfrom-name="([^"<>]+)"[^>]*>\n(.*)\n</cross-session-message>$', re.DOTALL)


def _read_head(path: Path) -> Optional[bytes]:
    try:
        with path.open("rb") as stream:
            return stream.read(HEAD_BYTES)
    except OSError:
        return None


def _scan_line(line: bytes, start: int, pending: dict[str, tuple[str, str, int, int]],
               found: list[tuple[str, str, str, str]], refs: dict[str, LineRef]) -> None:
    try:
        row = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(row, dict):
        return
    origin = row.get("origin")
    if row.get("type") == "user" and isinstance(origin, dict) and origin.get("kind") == "peer":
        native_id = origin.get("msg_id")
        body = origin.get("body")
        name = origin.get("name")
        content = (row.get("message") or {}).get("content")
        wrapper = _WRAPPER.fullmatch(content) if isinstance(content, str) else None
        if wrapper:
            if not isinstance(name, str):
                name = wrapper.group(1)
            if not isinstance(body, str):
                body = wrapper.group(2)
        if isinstance(native_id, str) and isinstance(body, str) and isinstance(name, str):
            if not body.startswith("crosstalk from @"):
                found.append(("claude:" + native_id, "inbound", name, body))
                refs["claude:" + native_id] = (start, len(line), 0, 0)
    if row.get("type") == "assistant":
        blocks = (row.get("message") or {}).get("content")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "SendMessage":
                    continue
                args = block.get("input") or {}
                tool_id = block.get("id")
                to, body = args.get("to"), args.get("message")
                if isinstance(tool_id, str) and isinstance(to, str) and isinstance(body, str):
                    pending[tool_id] = (to, body, start, len(line))
    if row.get("type") == "user":
        result = row.get("toolUseResult")
        blocks = (row.get("message") or {}).get("content")
        ids = [block.get("tool_use_id") for block in blocks if isinstance(block, dict) and block.get("type") == "tool_result"] if isinstance(blocks, list) else []
        if isinstance(result, dict):
            for tool_id in ids:
                call = pending.pop(tool_id, None)
                if call and result.get("success") is True:
                    key = "claude:" + str(result.get("msg_id") or tool_id)
                    found.append((key, "outbound", call[0], call[1]))
                    refs[key] = (start, len(line), call[2], call[3])


def _read_ref_line(stream: Any, start: int, length: int) -> Optional[bytes]:
    """One complete line at a byte range, or None when the file no longer holds it there."""
    stream.seek(start)
    line = stream.read(length)
    return line if len(line) == length and line.endswith(b"\n") else None


def _rebuild_backlog(path: Path, undelivered: tuple[LineRef, ...]) -> Optional[list[tuple[str, str, str, str]]]:
    key = str(path)
    found: list[tuple[str, str, str, str]] = []
    refs: dict[str, LineRef] = {}
    try:
        with path.open("rb") as stream:
            for start, length, call_start, call_length in undelivered:
                calls: dict[str, tuple[str, str, int, int]] = {}
                if call_length:
                    call_line = _read_ref_line(stream, call_start, call_length)
                    if call_line is None:
                        return None
                    _scan_line(call_line, call_start, calls, [], {})
                line = _read_ref_line(stream, start, length)
                before = len(found)
                if line is None:
                    return None
                _scan_line(line, start, calls, found, refs)
                if len(found) != before + 1:
                    return None
    except OSError:
        return None
    _refs[key] = refs
    return found


def _hydrate(key: str, path: Path, stat: os.stat_result) -> list[tuple[str, str, str, str]]:
    head = _read_head(path)
    if head is None:
        return []
    resume = _MIRROR_CURSORS.resume_point(key, size=stat.st_size, mtime_ns=stat.st_mtime_ns, head=head)
    if resume is None:
        return []
    cursor = resume[1]
    backlog = _rebuild_backlog(path, cursor.undelivered) if cursor.undelivered else []
    if backlog is None:
        _MIRROR_CURSORS.forget(key)
        return []
    _positions[key] = resume[0]
    _pending[key] = {tool_id: (to, body, start, length) for tool_id, to, body, start, length in cursor.pending}
    if backlog:
        _uncommitted.add(key)
    _committed[key] = (resume[0], frozenset(event[0] for event in backlog))
    return backlog


def _events(path: Path) -> tuple[list[tuple[str, str, str, str]], Optional[_Snapshot]]:
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return [], None
    size = stat.st_size
    found: list[tuple[str, str, str, str]] = []
    if key not in _positions:
        found = _hydrate(key, path, stat)
    offset = _positions.get(key, 0)
    if offset > size:
        offset = 0
        _pending.pop(key, None)
        _refs.pop(key, None)
    if offset == size and key not in _uncommitted:
        return found, None
    pending = _pending.setdefault(key, {})
    refs = _refs.setdefault(key, {})
    head = b""
    try:
        with path.open("rb") as stream:
            head = stream.read(HEAD_BYTES)
            stream.seek(offset)
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line or not line.endswith(b"\n"):
                    stream.seek(start)
                    break
                _scan_line(line, start, pending, found, refs)
            _positions[key] = stream.tell()
    except OSError as exc:
        logger.warning("crosstalk_mirror_read_failed", error_type=type(exc).__name__)
        return found, None
    calls = tuple((tool_id, to, body, start, length) for tool_id, (to, body, start, length) in pending.items())
    return found, _Snapshot(max(size, _positions[key]), stat.st_mtime_ns, head, _positions[key],
                            stat_signature(stat), calls)


def _commit_cursor(key: str, snapshot: _Snapshot, undelivered: set[str]) -> None:
    refs = {native: ref for native, ref in _refs.get(key, {}).items() if native in undelivered}
    _refs[key] = refs
    state = (snapshot.offset, frozenset(refs))
    if refs:
        _uncommitted.add(key)
    else:
        _uncommitted.discard(key)
    if _committed.get(key) == state:
        return
    _committed[key] = state
    cursor = MirrorCursor(snapshot.pending, tuple(sorted(refs.values())))
    _MIRROR_CURSORS.remember(key, size=snapshot.size, mtime_ns=snapshot.mtime_ns, head=snapshot.head,
                             offset=snapshot.offset, totals=cursor, signature=snapshot.signature)


async def mirror(app: Any, info: Any) -> None:
    if (info.agent_family or info.agent_type) != "claude" or not info.claude_session_uuid:
        return
    presence = await asyncio.to_thread(conversation_presence, info.claude_session_uuid,
                                       working_dir=info.session.working_dir)
    if presence.path is None:
        return
    async with _lock:
        events, snapshot = await asyncio.to_thread(_events, presence.path)
    backlog = _unresolved.setdefault(info.session.id, {})
    for event in events:
        backlog[event[0]] = event
    if backlog:
        await _deliver(app, info, backlog)
    if snapshot is not None:
        _commit_cursor(str(presence.path), snapshot, set(backlog))


async def _deliver(app: Any, info: Any, backlog: dict[str, tuple[str, str, str, str]]) -> None:
    from src.core.crosstalk import store

    cards = await directory.list_cards(BatchView(app.state.session_manager, app), include_remote=False)
    local = next((card for card in cards if card["id"] == info.session.id), None)
    if local is None:
        return
    for native_key, direction, peer_name, body in list(backlog.values()):
        matches = await directory.resolve_handle_async(peer_name, cards)
        if matches.ambiguous or len(matches.matches) != 1:
            continue
        peer = matches.matches[0]
        sender, receiver = (peer, local) if direction == "inbound" else (local, peer)
        try:
            await asyncio.to_thread(store.mirror_native, native_key=native_key,
                                    sender_id=sender["id"], receiver_id=receiver["id"],
                                    sender_uuid=sender["session_uuid"], receiver_uuid=receiver["session_uuid"],
                                    sender_name=sender["name"], text=body,
                                    sender_provider="claude", sender_model=sender.get("model"),
                                    receiver_name=receiver["name"], receiver_provider=receiver.get("provider"),
                                    receiver_model=receiver.get("model"))
            backlog.pop(native_key, None)
        except (OSError, ValueError) as exc:
            logger.warning("crosstalk_mirror_store_failed", error_type=type(exc).__name__)
