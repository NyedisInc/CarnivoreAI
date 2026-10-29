
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Tuple

import structlog

from src.core.session_token_usage.cache import HEAD_BYTES, IncrementalCache, stat_signature
from src.core.session_token_usage.persist_spec import PersistSpec, decode_instant, encode_instant
from src.core.transcript_contract import (
    LineScan,
    attachment_body,
    decode_object,
    queue_operation,
    tool_result_blocks,
    user_message,
)
from src.core.transcript_contract.claude_blocks import TextBlock, ToolResultBlock, UnknownBlock

logger = structlog.get_logger(__name__)

MAX_COLD_PARENT_BYTES: int = 256 * 1024 * 1024

ASYNC_LAUNCHED: str = "async_launched"

_NOTIFICATION_RE = re.compile(
    r"<task-notification>(.*?)</task-notification>", re.S
)
_TASK_ID_RE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>")
_STATUS_RE = re.compile(r"<status>\s*([^<\s]+)\s*</status>")

_NOTIFICATION_MARK = b"<task-notification>"
_RESULT_MARK = b'"tool_result"'
_AGENT_MARK = b'"agentId"'


@dataclass(frozen=True)
class RecordedEnd:

    at: datetime
    status: Optional[str]


@dataclass
class CompletionIndex:

    by_agent_id: Dict[str, RecordedEnd] = field(default_factory=dict)
    by_tool_use: Dict[str, RecordedEnd] = field(default_factory=dict)

    def copy(self) -> "CompletionIndex":
        return CompletionIndex(dict(self.by_agent_id), dict(self.by_tool_use))

    def end_for(self, agent_id: str, tool_use_id: Optional[str]) -> Optional[RecordedEnd]:
        ends = [self.by_agent_id.get(agent_id)]
        if tool_use_id:
            ends.append(self.by_tool_use.get(tool_use_id))
        present = [end for end in ends if end is not None]
        if not present:
            return None
        return max(present, key=lambda end: end.at)


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _block_text(block: Any) -> str:
    if isinstance(block, TextBlock):
        return block.text if isinstance(block.text, str) else ""
    if isinstance(block, UnknownBlock) and isinstance(block.raw, dict):
        text = block.raw.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _notification_text(record: Dict[str, Any]) -> Optional[str]:
    kind = record.get("type")
    if kind == "queue-operation":
        queued = queue_operation(record)
        if queued.operation == "enqueue" and isinstance(queued.content, str):
            return queued.content
        return None
    if kind == "attachment":
        body = attachment_body(record)
        queued_command = body.queued_command if body is not None and body.type == "queued_command" else None
        prompt = queued_command.prompt if queued_command is not None else None
        return prompt if isinstance(prompt, str) else None
    if kind == "user":
        origin = record.get("origin")
        if not (isinstance(origin, dict) and origin.get("kind") == "task-notification"):
            return None
        message = user_message(record)
        content = message.content if message is not None else None
        if isinstance(content, str):
            return content
        if isinstance(content, tuple):
            return "".join(_block_text(block) for block in content)
    return None


def _notifications(text: str) -> Iterator[Tuple[str, Optional[str]]]:
    for block in _NOTIFICATION_RE.findall(text):
        status = _STATUS_RE.search(block)
        for task_id in _TASK_ID_RE.findall(block):
            yield task_id, (status.group(1) if status else None)


def _sync_results(record: Dict[str, Any]) -> Iterator[Tuple[str, Optional[str], Optional[str]]]:
    if record.get("type") != "user":
        return
    result = record.get("toolUseResult")
    if not isinstance(result, dict) or "agentId" not in result:
        return
    status = result.get("status")
    if status == ASYNC_LAUNCHED or result.get("isAsync") is True:
        return
    agent_id = result.get("agentId")
    for block in tool_result_blocks(record):
        tool_use_id = block.tool_use_id
        if isinstance(tool_use_id, str) and tool_use_id:
            yield tool_use_id, status if isinstance(status, str) else None, agent_id


ASYNC_LAUNCH_TEXT: str = "Async agent launched"


def _result_text(block: ToolResultBlock) -> str:
    content = block.content
    if isinstance(content, str):
        return content
    if isinstance(content, tuple):
        return "".join(_block_text(part) for part in content)
    return ""


def _bare_results(record: Dict[str, Any]) -> List[str]:
    if record.get("type") != "user" or "toolUseResult" in record:
        return []
    return [
        block.tool_use_id for block in tool_result_blocks(record)
        if isinstance(block.tool_use_id, str) and block.tool_use_id
        and not _result_text(block).lstrip().startswith(ASYNC_LAUNCH_TEXT)
    ]


def _keep_newest(target: Dict[str, RecordedEnd], key: str, end: RecordedEnd) -> None:
    current = target.get(key)
    if current is None or end.at >= current.at:
        target[key] = end


def scan_parent_lines(
    handle: BinaryIO, index: CompletionIndex, *, spawner: bool = False
) -> Tuple[CompletionIndex, int]:
    scan = LineScan(handle, (_NOTIFICATION_MARK, _RESULT_MARK))
    for line in scan:
        if scan.hit == _NOTIFICATION_MARK:
            notification, result = True, _RESULT_MARK in line
        else:
            notification, result = False, True
        sync = result and _AGENT_MARK in line
        bare = spawner and result
        if not (notification or sync or bare):
            continue
        record = decode_object(line)
        if record is None:
            continue
        at = parse_timestamp(record.get("timestamp"))
        if at is None:
            continue
        if notification:
            text = _notification_text(record)
            for agent_id, status in _notifications(text or ""):
                _keep_newest(index.by_agent_id, agent_id, RecordedEnd(at, status))
        if sync:
            for tool_use_id, status, agent_id in _sync_results(record):
                end = RecordedEnd(at, status)
                _keep_newest(index.by_tool_use, tool_use_id, end)
                if isinstance(agent_id, str) and agent_id:
                    _keep_newest(index.by_agent_id, agent_id, end)
        if bare:
            for tool_use_id in _bare_results(record):
                _keep_newest(index.by_tool_use, tool_use_id, RecordedEnd(at, None))
    return index, scan.offset


def _encode_ends(ends: Dict[str, RecordedEnd]) -> List[List[Any]]:
    return [[key, encode_instant(end.at), end.status] for key, end in ends.items()]


def _decode_ends(rows: Any) -> Dict[str, RecordedEnd]:
    if not isinstance(rows, list):
        raise TypeError("ends must be a list")
    ends: Dict[str, RecordedEnd] = {}
    for row in rows:
        if not (isinstance(row, list) and len(row) == 3):
            raise ValueError("an end row must hold three values")
        key, at, status = row
        if not isinstance(key, str) or not isinstance(at, str):
            raise TypeError("an end key and instant must be strings")
        if status is not None and not isinstance(status, str):
            raise TypeError("an end status must be a string or null")
        ends[key] = RecordedEnd(decode_instant(at), status)
    return ends


def encode_index(index: CompletionIndex) -> Dict[str, Any]:
    return {"a": _encode_ends(index.by_agent_id), "t": _encode_ends(index.by_tool_use)}


def decode_index(value: Any) -> CompletionIndex:
    if not isinstance(value, dict) or set(value) != {"a", "t"}:
        raise ValueError("index payload must hold exactly a and t")
    return CompletionIndex(_decode_ends(value["a"]), _decode_ends(value["t"]))


INDEX_SOURCES: Tuple[str, ...] = (
    "src.core.subagents.parent_index",
    "src.core.transcript_contract.stream",
    "src.core.transcript_contract.lines",
    "src.core.transcript_contract.parsed",
    "src.core.transcript_contract.fields",
    "src.core.transcript_contract.claude_parse",
    "src.core.transcript_contract.claude_message",
    "src.core.transcript_contract.claude_blocks",
    "src.core.transcript_contract.claude_attachments",
    "src.core.transcript_contract.claude_attachment_kinds",
    "src.core.transcript_contract.claude_meta_records",
    "src.core.session_token_usage.cache",
    "src.core.session_token_usage.persist_spec",
)


def index_spec(name: str) -> PersistSpec:
    return PersistSpec(name=name, manual_version=1, sources=INDEX_SOURCES,
                       encode=encode_index, decode=decode_index)


PARENT_INDEX_CACHE = IncrementalCache(persist=index_spec("subagents.completion_index"))
SPAWNER_INDEX_CACHE = IncrementalCache(persist=index_spec("subagents.spawner_index"))


def read_completion_index(
    path: Path,
    *,
    cache: Optional[IncrementalCache] = None,
    max_cold_bytes: int = MAX_COLD_PARENT_BYTES,
    spawner: bool = False,
) -> Optional[CompletionIndex]:
    default = SPAWNER_INDEX_CACHE if spawner else PARENT_INDEX_CACHE
    store = cache if cache is not None else default
    key = os.path.abspath(str(path))
    try:
        stat = os.stat(key)
        signature = stat_signature(stat)
        unchanged = store.unchanged(key, signature)
        if unchanged is not None:
            return unchanged
        if stat.st_size > max_cold_bytes and not store.knows(key):
            logger.debug("subagent_parent_too_large_cold", size=stat.st_size)
            return None
        with open(key, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            resume = store.resume_point(
                key, size=stat.st_size, mtime_ns=stat.st_mtime_ns, head=head
            )
            if resume is None:
                handle.seek(0)
                index = CompletionIndex()
            else:
                offset, remembered = resume
                handle.seek(offset)
                index = remembered.copy()
            index, offset = scan_parent_lines(handle, index, spawner=spawner)
    except OSError as exc:
        logger.debug("subagent_parent_unreadable", error=str(exc),
                     error_type=type(exc).__name__)
        return None
    store.remember(key, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                   head=head, offset=offset, totals=index, signature=signature)
    return index
