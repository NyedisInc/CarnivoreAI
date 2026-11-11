
from __future__ import annotations

import asyncio
import contextvars
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from src.core.session_token_usage.per_request import _files as conversation_files

logger = structlog.get_logger(__name__)

TOOL_USE_META_KEY = "claudecode/toolUseId"
CURRENT_TOOL_USE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("argent_current_tool_use_id", default="")
TAIL_BYTES = 512 * 1024
DEFAULT_ATTEMPTS = 6
DEFAULT_DELAY = 0.5

HOW_ID = "tool_use_id"
HOW_INPUT = "name_and_input"
HOW_ROOT = "root_call"
HOW_FALLBACK_NONE = "root_fallback_not_found"
HOW_FALLBACK_AMBIGUOUS = "root_fallback_ambiguous"


@dataclass(frozen=True)
class JoinResult:

    sub_agent_id: str
    how: str
    exact: bool


def tool_use_id_from_meta(params: Any) -> str:
    meta = params.get("_meta") if isinstance(params, dict) else None
    value = meta.get(TOOL_USE_META_KEY) if isinstance(meta, dict) else None
    return value if isinstance(value, str) else ""


def _tail_lines(path: Path) -> List[bytes]:
    try:
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read()
    except OSError as exc:
        logger.debug("argent_join_file_unreadable", error_type=type(exc).__name__)
        return []
    lines = data.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]
    return lines


def _matching_calls(path: Path, tool_use_id: str, tool_name: str, tool_input: Optional[Dict[str, Any]]) -> int:
    needle = (tool_use_id or tool_name).encode()
    seen: Set[str] = set()
    for line in _tail_lines(path):
        if needle not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if tool_use_id:
                hit = block.get("id") == tool_use_id
            else:
                hit = block.get("name") == tool_name and (tool_input is None or block.get("input") == tool_input)
            if hit:
                seen.add(str(block.get("id") or id(block)))
    return len(seen)


def join_once(transcript: Path, *, tool_use_id: str = "", tool_name: str = "", tool_input: Optional[Dict[str, Any]] = None) -> Optional[JoinResult]:
    if not tool_use_id and not tool_name:
        return None
    how = HOW_ID if tool_use_id else HOW_INPUT
    owners: List[str] = []
    total = 0
    for path, agent_id, _workflow in conversation_files(transcript):
        count = _matching_calls(path, tool_use_id, tool_name, tool_input)
        if count:
            owners.append(agent_id)
            total += count
    if not owners:
        return None
    if total > 1 or len(owners) > 1:
        return JoinResult("", HOW_FALLBACK_AMBIGUOUS, False)
    return JoinResult(owners[0], how if owners[0] else HOW_ROOT, True)


async def join(transcript: Optional[Path], *, tool_use_id: str = "", tool_name: str = "", tool_input: Optional[Dict[str, Any]] = None,
               attempts: int = DEFAULT_ATTEMPTS, delay: float = DEFAULT_DELAY) -> JoinResult:
    if transcript is None or not (tool_use_id or tool_name):
        return JoinResult("", HOW_FALLBACK_NONE, False)
    for attempt in range(max(1, attempts)):
        found = await asyncio.to_thread(join_once, transcript, tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input)
        if found is not None:
            return found
        if attempt + 1 < attempts:
            await asyncio.sleep(delay)
    return JoinResult("", HOW_FALLBACK_NONE, False)


async def agent_for_pane_call(manager: Any, session_id: str, tmux_name: str, *, tool_name: str, tool_input: Dict[str, Any]) -> JoinResult:
    from src.core.session_transcript_presence import CONVERSATION_PRESENT
    from src.core.session_token_usage import claude_reader

    try:
        info = await manager.get_session_info(session_id)
        if info is None or (info.agent_family or "claude") != "claude":
            return JoinResult("", HOW_FALLBACK_NONE, False)
        uuid = manager.claude_uuid_for_tmux_name(tmux_name)
        working_dir = info.session.working_dir if info.session is not None else None
        found = await asyncio.to_thread(claude_reader.locate_transcript, uuid, working_dir=working_dir) if uuid else None
    except (OSError, ValueError) as exc:
        logger.warning("argent_join_locate_failed", error_type=type(exc).__name__)
        return JoinResult("", HOW_FALLBACK_NONE, False)
    path = found.path if found is not None and found.outcome == CONVERSATION_PRESENT else None
    return await join(path, tool_use_id=CURRENT_TOOL_USE_ID.get(), tool_name=tool_name, tool_input=tool_input)
