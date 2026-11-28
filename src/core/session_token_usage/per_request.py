
from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.session_token_usage import claude_reader
from src.core.session_token_usage.reader import SessionSubject
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.stat_gate.dir_names import entry_names
from src.models.per_request_usage import RequestUsageRow, SessionRequestUsage

logger = structlog.get_logger(__name__)

MAX_FILES = 16384
MAX_ROWS_PER_FILE = 20000
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000
_HEAD_BYTES = 256
_PREFIX = "agent-"
_JSONL = ".jsonl"


@dataclass
class _FileState:

    head: bytes = b""
    offset: int = 0
    stat_sig: Optional[Tuple[int, int, int]] = None
    rows: List[RequestUsageRow] = field(default_factory=list)
    row_epochs: List[float] = field(default_factory=list)
    max_epoch: float = 0.0
    seen: Set[str] = field(default_factory=set)


_lock = threading.Lock()
_states: "OrderedDict[str, _FileState]" = OrderedDict()


def clear() -> None:
    with _lock:
        _states.clear()


def _count(usage: Dict[str, Any], key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _row(record: Dict[str, Any], agent_id: str, workflow: Optional[str]) -> Optional[Tuple[str, RequestUsageRow]]:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    request_id = record.get("requestId") if isinstance(record.get("requestId"), str) else None
    message_id = message.get("id") if isinstance(message.get("id"), str) else None
    key = request_id or message_id
    if key is None:
        return None
    model = message.get("model")
    stamp = record.get("timestamp")
    return key, RequestUsageRow(
        request_id=request_id, message_id=message_id, agent_id=agent_id, workflow=workflow,
        model=model if isinstance(model, str) else None,
        input_tokens=_count(usage, "input_tokens"), output_tokens=_count(usage, "output_tokens"),
        cache_creation_tokens=_count(usage, "cache_creation_input_tokens"),
        cache_read_tokens=_count(usage, "cache_read_input_tokens"),
        timestamp=stamp if isinstance(stamp, str) else None,
    )


_MTIME_SKEW_SECONDS = 300.0


def _advance(
    path: Path,
    state: _FileState,
    agent_id: str,
    workflow: Optional[str],
    *,
    min_mtime: Optional[float] = None,
) -> bool:
    try:
        st = os.stat(path)
        sig = (st.st_ino, st.st_size, st.st_mtime_ns)
        if state.stat_sig == sig:
            return True
        if min_mtime is not None and state.stat_sig is None and st.st_mtime < min_mtime:
            return True
        with open(path, "rb") as handle:
            fst = os.fstat(handle.fileno())
            size = fst.st_size
            sig = (fst.st_ino, size, fst.st_mtime_ns)
            head = handle.read(_HEAD_BYTES)
            if state.offset and (size < state.offset or not head.startswith(state.head)):
                state.offset, state.rows, state.row_epochs, state.max_epoch, state.seen = 0, [], [], 0.0, set()
            if not state.offset:
                state.head = head
            handle.seek(state.offset)
            while True:
                line = handle.readline()
                if not line or not line.endswith(b"\n"):
                    break
                state.offset += len(line)
                if b'"usage"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                found = _row(record, agent_id, workflow) if isinstance(record, dict) else None
                if found is None or found[0] in state.seen:
                    continue
                state.seen.add(found[0])
                ep = _epoch(found[1].timestamp)
                state.rows.append(found[1])
                state.row_epochs.append(ep)
                if ep > state.max_epoch:
                    state.max_epoch = ep
            if len(state.rows) > MAX_ROWS_PER_FILE:
                trim = len(state.rows) - MAX_ROWS_PER_FILE
                del state.rows[:trim]
                del state.row_epochs[:trim]
                state.max_epoch = max(state.row_epochs, default=0.0)
            state.stat_sig = sig
    except OSError as exc:
        logger.debug("per_request_usage_file_unreadable", error=str(exc))
        return False
    return True


def _files(transcript: Path) -> List[Tuple[Path, str, Optional[str]]]:
    found: List[Tuple[Path, str, Optional[str]]] = [(transcript, "", None)]
    base = transcript.with_suffix("") / "subagents"
    folders: List[Tuple[Path, Optional[str]]] = [(base, None)]
    try:
        folders += [(base / "workflows" / n, n) for n in entry_names(base / "workflows") if n.startswith("wf_")]
    except OSError:
        pass
    for folder, workflow in folders:
        try:
            names = entry_names(folder)
        except OSError:
            continue
        found += [(folder / n, n[len(_PREFIX):-len(_JSONL)], workflow)
                  for n in names if n.startswith(_PREFIX) and n.endswith(_JSONL)]
    return found


def _epoch(stamp: Optional[str]) -> float:
    if not stamp:
        return 0.0
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return 0.0


def read_conversation_requests(
    transcript: Path, *, since: Optional[str] = None, limit: int = DEFAULT_LIMIT
) -> Tuple[List[RequestUsageRow], int, bool]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be 1 to {MAX_LIMIT}")
    floor = datetime.fromisoformat(since).timestamp() if since else None
    min_mtime = (floor - _MTIME_SKEW_SECONDS) if floor is not None else None
    matched: List[Tuple[float, RequestUsageRow]] = []
    seen: Set[str] = set()
    for path, agent_id, workflow in _files(transcript):
        key = os.fspath(path)
        with _lock:
            state = _states.pop(key, None) or _FileState()
        try:
            _advance(path, state, agent_id, workflow, min_mtime=min_mtime)
            if floor is not None and state.max_epoch <= floor:
                snapshot: List[Tuple[float, RequestUsageRow]] = []
            else:
                snapshot = list(zip(state.row_epochs, state.rows))
        finally:
            with _lock:
                _states[key] = state
                while len(_states) > MAX_FILES:
                    _states.popitem(last=False)
        for ep, row in snapshot:
            if floor is not None and ep <= floor:
                continue
            dedup = row.request_id or row.message_id or ""
            if dedup in seen:
                continue
            seen.add(dedup)
            matched.append((ep, row))
    matched.sort(key=lambda pair: pair[0])
    rows = [row for _, row in matched]
    return rows[:limit], len(rows), len(rows) > limit


def read_session_requests(
    subject: SessionSubject, *, since: Optional[str] = None, limit: int = DEFAULT_LIMIT,
    projects_dir: Optional[Path] = None,
) -> SessionRequestUsage:
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    family = subject.agent_family
    if family is not None and family != DEFAULT_FAMILY:
        return SessionRequestUsage(state="not_applicable", family=family, as_of=stamp,
                                   detail="this agent family reports usage per session only")
    base = dict(family=DEFAULT_FAMILY, conversation_uuid=subject.conversation_uuid, as_of=stamp)
    if not subject.conversation_uuid:
        return SessionRequestUsage(state="absent", detail="this session has no conversation yet", **base)
    location = claude_reader.locate_transcript(subject.conversation_uuid, working_dir=subject.working_dir,
                                               projects_dir=projects_dir)
    if location.outcome == CONVERSATION_ABSENT:
        return SessionRequestUsage(state="absent", detail="no transcript exists for this conversation yet", **base)
    if location.outcome != CONVERSATION_PRESENT or location.path is None:
        return SessionRequestUsage(state="unchecked", detail="the transcript corpus could not be read", **base)
    rows, total, truncated = read_conversation_requests(location.path, since=since, limit=limit)
    return SessionRequestUsage(state="ok", requests=rows, total=total, truncated=truncated,
                               next_since=rows[-1].timestamp if truncated and rows else None, **base)
