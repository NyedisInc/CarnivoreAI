
from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.attention.transcript_records import (
    is_interrupt,
    is_local_command,
    is_real_user_prompt,
    record_text,
)
from src.core.bookmarks.errors import TranscriptUnavailable

logger = structlog.get_logger()

MAX_TRANSCRIPT_BYTES: int = 2 * 1024 * 1024 * 1024
MAX_TRANSCRIPT_LABEL: str = f"{MAX_TRANSCRIPT_BYTES // (1024 * 1024 * 1024)} GB"
SNIPPET_CHARS: int = 200
CHAIN_TYPES = frozenset({"user", "assistant", "attachment", "system", "progress"})
SKIPPED_IN_COPY = "progress"
CARRIED_TYPES = frozenset({"content-replacement", "relocated", "memory-mode", "atis-latch"})
CACHE_SIZE: int = 4
PEER_ORIGIN = "peer"


@dataclass(frozen=True)
class Node:

    uuid: str
    parent: Optional[str]
    logical_parent: Optional[str]
    kind: str
    offset: int
    length: int
    msg_id: Optional[str] = None
    tool_uses: Tuple[str, ...] = ()
    tool_results: Tuple[str, ...] = ()
    prompt: bool = False
    stop: bool = False
    turn_start: bool = False
    snippet: str = ""
    timestamp: str = ""


@dataclass
class TranscriptIndex:

    path: Path
    size: int
    source_session_id: Optional[str] = None
    nodes: Dict[str, Node] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    children: Dict[str, List[str]] = field(default_factory=dict)
    carried: List[Tuple[str, int, int]] = field(default_factory=list)
    suppressed: bool = False
    skipped_lines: int = 0

    def leaf(self) -> Optional[str]:
        return self.order[-1] if self.order else None

    def active_path(self) -> List[Node]:
        out: List[Node] = []
        seen = set()
        cursor = self.leaf()
        while cursor and cursor in self.nodes and cursor not in seen:
            seen.add(cursor)
            node = self.nodes[cursor]
            out.append(node)
            cursor = node.parent or node.logical_parent
        out.reverse()
        return out


def is_turn_prompt(record: dict) -> bool:
    if not is_real_user_prompt(record) or is_interrupt(record) or is_local_command(record):
        return False
    if record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    return bool(record_text(record).strip())


def peer_turn_text(record: dict) -> Optional[str]:
    origin = record.get("origin")
    if record.get("type") != "user" or not isinstance(origin, dict) or origin.get("kind") != PEER_ORIGIN:
        return None
    if record.get("isSidechain") is True or record.get("toolUseResult") is not None:
        return None
    body = origin.get("body")
    text = body if isinstance(body, str) and body.strip() else record_text(record)
    return text if text.strip() else None


def _tool_ids(record: dict) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return (), ()
    uses = tuple(b["id"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("id"), str))
    results = tuple(b["tool_use_id"] for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str))
    return uses, results


def node_from_record(record: dict, offset: int, length: int) -> Optional[Node]:
    kind = record.get("type")
    uuid = record.get("uuid")
    if kind not in CHAIN_TYPES or not isinstance(uuid, str) or record.get("isSidechain") is True:
        return None
    prompt = kind == "user" and is_turn_prompt(record)
    opener = record_text(record) if prompt else peer_turn_text(record)
    uses, results = _tool_ids(record)
    message = record.get("message")
    return Node(
        uuid=uuid,
        parent=record.get("parentUuid") if isinstance(record.get("parentUuid"), str) else None,
        logical_parent=record.get("logicalParentUuid") if isinstance(record.get("logicalParentUuid"), str) else None,
        kind=kind,
        offset=offset,
        length=length,
        msg_id=message.get("id") if isinstance(message, dict) and isinstance(message.get("id"), str) else None,
        tool_uses=uses,
        tool_results=results,
        prompt=prompt,
        stop=prompt or (kind == "user" and is_local_command(record)),
        turn_start=opener is not None,
        snippet=" ".join(opener.split())[:SNIPPET_CHARS] if opener is not None else "",
        timestamp=str(record.get("timestamp") or ""),
    )


def build_index(path: Path) -> TranscriptIndex:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TranscriptUnavailable(f"the transcript could not be read: {exc.strerror or exc}") from exc
    if size > MAX_TRANSCRIPT_BYTES:
        raise TranscriptUnavailable(f"the transcript is over the {MAX_TRANSCRIPT_LABEL} bookmark limit")
    index = TranscriptIndex(path=path, size=size)
    offset = 0
    try:
        with path.open("rb") as stream:
            for raw in stream:
                start, offset = offset, offset + len(raw)
                if offset > size:
                    break
                _index_line(index, raw, start)
    except OSError as exc:
        raise TranscriptUnavailable(f"the transcript could not be read: {exc.strerror or exc}") from exc
    if index.skipped_lines:
        logger.info("bookmark_index_skipped_lines", path=str(path), skipped=index.skipped_lines)
    return index


def _index_line(index: TranscriptIndex, raw: bytes, start: int) -> None:
    if not raw.strip():
        return
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        index.skipped_lines += 1
        return
    if not isinstance(record, dict):
        index.skipped_lines += 1
        return
    kind = record.get("type")
    if kind in CARRIED_TYPES:
        index.carried.append((kind, start, len(raw)))
        return
    if kind == "history-suppression":
        index.suppressed = True
        return
    node = node_from_record(record, start, len(raw))
    if node is None:
        return
    if index.source_session_id is None and isinstance(record.get("sessionId"), str):
        index.source_session_id = record["sessionId"]
    index.nodes[node.uuid] = node
    index.order.append(node.uuid)
    if node.parent:
        index.children.setdefault(node.parent, []).append(node.uuid)


_cache: "OrderedDict[str, Tuple[int, int, TranscriptIndex]]" = OrderedDict()
_cache_lock = threading.Lock()


def cached_index(path: Path) -> TranscriptIndex:
    try:
        st = os.stat(path)
    except OSError as exc:
        raise TranscriptUnavailable(f"the transcript could not be read: {exc.strerror or exc}") from exc
    key = str(path)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            _cache.move_to_end(key)
            return hit[2]
    index = build_index(path)
    with _cache_lock:
        _cache[key] = (st.st_size, st.st_mtime_ns, index)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return index


def turns(index: TranscriptIndex) -> List[Node]:
    return [node for node in reversed(index.active_path()) if node.prompt]


def marked_turn(index: TranscriptIndex, node: Node) -> Optional[Node]:
    seen = set()
    cursor: Optional[Node] = node
    while cursor is not None and cursor.uuid not in seen:
        if cursor.turn_start:
            return cursor
        seen.add(cursor.uuid)
        parent = cursor.parent or cursor.logical_parent
        cursor = index.nodes.get(parent) if parent else None
    return None


def latest_turn(index: TranscriptIndex) -> Optional[Node]:
    found = turns(index)
    return found[0] if found else None
