
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.attention.transcript_contract import check_window
from src.core.attention.transcript_records import _is_real_user_prompt
from src.core.attention.turn_counts import (
    KIND_MONITOR,
    KIND_SHELL,
    async_launch,
    content_blocks,
    stopped_task_id,
)
from src.core.session_token_usage.cache import HEAD_BYTES, IncrementalCache, stat_signature
from src.core.session_token_usage.persist_spec import PersistSpec, decode_instant, encode_instant
from src.core.subagents.files import read_line_facts, read_meta_facts
from src.core.subagents.parent_index import (
    MAX_COLD_PARENT_BYTES,
    INDEX_SOURCES,
    CompletionIndex,
    index_spec,
    parse_timestamp,
    read_completion_index,
)
from src.core.subagents.reader import CLOCK_SKEW, subagents_dir_for
from src.core.timers.redact import summary as _redact_summary
from src.core.transcript_contract import LineScan, decode_object

logger = structlog.get_logger(__name__)

_OUTPUT_PATH_RE = re.compile(r"Output is being written to: (\S+?\.output)")

_AGENT_FILE_RE = re.compile(r"^agent-([0-9a-f]+)\.jsonl$")

_LAUNCH_MARKS: Tuple[bytes, ...] = (b'"backgroundTaskId"', b'"persistent"', b'"task_type"')
_PROMPT_MARK = b'"type":"user"'
_PROMPT_REJECTS: Tuple[bytes, ...] = (b'"toolUseResult"', b'"isMeta":true', b'"isSidechain":true')

FILE_CACHE_MAX_ENTRIES: int = 8192

_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class OpenLaunch:

    agent_id: str
    kind: str
    task_id: str
    launched_at: datetime
    output_path: Optional[str] = None
    deadline: Optional[datetime] = None
    owner_active_at: Optional[datetime] = None
    agent_type: Optional[str] = None
    description: Optional[str] = None


@dataclass
class _Ledger:

    launches: Dict[str, OpenLaunch] = field(default_factory=dict)
    stopped: Set[str] = field(default_factory=set)

    def copy(self) -> "_Ledger":
        return _Ledger(dict(self.launches), set(self.stopped))


@dataclass(frozen=True)
class _PromptMark:

    at: Optional[datetime] = None

    def copy(self) -> "_PromptMark":
        return self


def _opt_str(value: Any) -> Optional[str]:
    if value is not None and not isinstance(value, str):
        raise TypeError("expected a string or null")
    return value


def _encode_ledger(ledger: _Ledger) -> Dict[str, Any]:
    rows = [[task_id, launch.agent_id, launch.kind, encode_instant(launch.launched_at),
             launch.output_path, encode_instant(launch.deadline),
             encode_instant(launch.owner_active_at), launch.agent_type, launch.description]
            for task_id, launch in ledger.launches.items()]
    return {"l": rows, "s": sorted(ledger.stopped)}


def _decode_ledger(value: Any) -> _Ledger:
    if not isinstance(value, dict) or set(value) != {"l", "s"}:
        raise ValueError("ledger payload must hold exactly l and s")
    if not isinstance(value["l"], list) or not isinstance(value["s"], list):
        raise TypeError("ledger l and s must be lists")
    launches: Dict[str, OpenLaunch] = {}
    for row in value["l"]:
        if not (isinstance(row, list) and len(row) == 9):
            raise ValueError("a launch row must hold nine values")
        task_id, agent_id, kind, launched, output, deadline, active, agent_type, description = row
        if not all(isinstance(item, str) for item in (task_id, agent_id, kind, launched)):
            raise TypeError("a launch id, agent, kind and time must be strings")
        launches[task_id] = OpenLaunch(
            agent_id, kind, task_id, decode_instant(launched), output_path=_opt_str(output),
            deadline=decode_instant(deadline), owner_active_at=decode_instant(active),
            agent_type=_opt_str(agent_type), description=_opt_str(description))
    if not all(isinstance(item, str) for item in value["s"]):
        raise TypeError("a stopped task id must be a string")
    return _Ledger(launches, set(value["s"]))


def _encode_prompt(mark: _PromptMark) -> Dict[str, Optional[str]]:
    return {"at": encode_instant(mark.at)}


def _decode_prompt(value: Any) -> _PromptMark:
    if not isinstance(value, dict) or set(value) != {"at"}:
        raise ValueError("prompt payload must hold exactly at")
    return _PromptMark(decode_instant(value["at"]))


_LEDGER_SOURCES: Tuple[str, ...] = tuple(sorted({
    "src.core.subagents.parked_launches",
    "src.core.subagents.contract",
    "src.core.attention.turn_counts",
    "src.core.attention.transcript_contract",
    "src.core.attention.transcript_records",
    "src.core.session_token_usage.cache",
    "src.core.session_token_usage.persist_spec",
    *INDEX_SOURCES,
}))

_LEDGERS = IncrementalCache(max_entries=FILE_CACHE_MAX_ENTRIES, persist=PersistSpec(
    "subagents.launch_ledger", 1, _LEDGER_SOURCES, _encode_ledger, _decode_ledger))
_PROMPTS = IncrementalCache(persist=PersistSpec(
    "subagents.prompt_mark", 1, _LEDGER_SOURCES, _encode_prompt, _decode_prompt))
_AGENT_NOTICES = IncrementalCache(max_entries=FILE_CACHE_MAX_ENTRIES,
                                  persist=index_spec("subagents.agent_notices"))


@dataclass(frozen=True)
class OpenLaunches:

    launches: Tuple[OpenLaunch, ...] = ()
    fresh_agents: int = 0
    since: Optional[datetime] = None
    earliest_deadline: Optional[datetime] = None


def _launch_from(record: Dict[str, Any], agent_id: str) -> Optional[OpenLaunch]:
    launch = async_launch(record)
    if launch is None or launch["kind"] not in (KIND_SHELL, KIND_MONITOR):
        return None
    at = parse_timestamp(record.get("timestamp"))
    task_id = launch["task_id"]
    if at is None or not task_id:
        return None
    result = record["toolUseResult"]
    if launch["kind"] == KIND_SHELL:
        output = None
        for block in content_blocks(record, "tool_result"):
            text = block.get("content")
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text
                               if isinstance(part, dict) and isinstance(part.get("text"), str))
            match = _OUTPUT_PATH_RE.search(text) if isinstance(text, str) else None
            if match:
                output = match.group(1)
        return OpenLaunch(agent_id, KIND_SHELL, task_id, at, output_path=output)
    timeout = result.get("timeoutMs")
    deadline = None
    if result.get("persistent") is False and type(timeout) is int and timeout > 0:
        try:
            deadline = at + timedelta(milliseconds=timeout)
        except OverflowError:
            deadline = None
    return OpenLaunch(agent_id, KIND_MONITOR, task_id, at, deadline=deadline)


def _unmeasured_launch(record: Dict[str, Any], agent_id: str) -> Optional[OpenLaunch]:
    at = parse_timestamp(record.get("timestamp"))
    ids = [block.get("tool_use_id") for block in content_blocks(record, "tool_result")]
    key = next((value for value in ids if isinstance(value, str) and value), None)
    if at is None or key is None:
        return None
    return OpenLaunch(agent_id, KIND_SHELL, "shape_unrecognized:" + key, at)


def _scan_launches(handle: BinaryIO, ledger: _Ledger, agent_id: str) -> Tuple[_Ledger, int]:
    scan = LineScan(handle, _LAUNCH_MARKS)
    for line in scan:
        record = decode_object(line)
        if record is None:
            continue
        broken = check_window((record,))
        stopped = stopped_task_id(record)
        if stopped is not None and not broken:
            ledger.stopped.add(stopped)
            continue
        launch = _launch_from(record, agent_id)
        if launch is None and broken:
            launch = _unmeasured_launch(record, agent_id)
        if launch is not None:
            ledger.launches[launch.task_id] = launch
    return ledger, scan.offset


def _scan_prompts(handle: BinaryIO, mark: _PromptMark, _unused: str) -> Tuple[_PromptMark, int]:
    scan = LineScan(handle, (_PROMPT_MARK,), _PROMPT_REJECTS)
    newest = mark.at
    for line in scan:
        record = decode_object(line)
        if record is None or not _is_real_user_prompt(record):
            continue
        at = parse_timestamp(record.get("timestamp"))
        if at is not None and (newest is None or at > newest):
            newest = at
    return _PromptMark(newest), scan.offset


def _incremental(path: Path, store: IncrementalCache, fresh: Callable[[], Any],
                 scan: Callable[[BinaryIO, Any, str], Tuple[Any, int]], tag: str) -> Any:
    key = os.path.abspath(str(path))
    try:
        stat = os.stat(key)
        signature = stat_signature(stat)
        with _CACHE_LOCK:
            unchanged = store.unchanged(key, signature)
            known = store.knows(key)
        if unchanged is not None:
            return unchanged
        if stat.st_size > MAX_COLD_PARENT_BYTES and not known:
            return None
        with open(key, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            with _CACHE_LOCK:
                resume = store.resume_point(key, size=stat.st_size,
                                            mtime_ns=stat.st_mtime_ns, head=head)
            if resume is None:
                handle.seek(0)
                accumulator = fresh()
            else:
                offset, remembered = resume
                handle.seek(offset)
                accumulator = remembered.copy()
            accumulator, offset = scan(handle, accumulator, tag)
    except OSError as exc:
        logger.debug("parked_launch_read_failed", error=str(exc), error_type=type(exc).__name__)
        return None
    with _CACHE_LOCK:
        store.remember(key, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                       head=head, offset=offset, totals=accumulator,
                       signature=signature)
    return accumulator


def newest_real_prompt(parent_path: Path) -> Optional[datetime]:
    mark = _incremental(parent_path, _PROMPTS, _PromptMark, _scan_prompts, "")
    return mark.at if mark is not None else None


def _retired(task_id: str, ledger: _Ledger, *indexes: Optional[CompletionIndex]) -> bool:
    if task_id in ledger.stopped:
        return True
    for index in indexes:
        end = index.by_agent_id.get(task_id) if index is not None else None
        if end is not None and end.status is not None:
            return True
    return False


def _candidates(directory: Path, since: datetime, index: Optional[CompletionIndex]) -> Set[str]:
    found: Set[str] = set()
    floor = (since - CLOCK_SKEW).timestamp()
    with os.scandir(directory) as entries:
        for entry in entries:
            match = _AGENT_FILE_RE.match(entry.name)
            if match is None:
                continue
            try:
                if entry.stat().st_mtime >= floor:
                    found.add(match.group(1))
            except OSError:
                continue
    for agent_id, end in (index.by_agent_id.items() if index is not None else ()):
        if end.at > since and _AGENT_FILE_RE.match("agent-%s.jsonl" % agent_id):
            if (directory / ("agent-%s.jsonl" % agent_id)).is_file():
                found.add(agent_id)
    return found


def _owner_activity(directory: Path, agent_id: str,
                    index: Optional[CompletionIndex]) -> Optional[datetime]:
    line = read_line_facts(directory / ("agent-%s.jsonl" % agent_id))
    meta = read_meta_facts(directory / ("agent-%s.meta.json" % agent_id))
    tool_use_id = (meta.fields or {}).get("toolUseId")
    end = index.end_for(agent_id, tool_use_id if isinstance(tool_use_id, str) else None) \
        if index is not None else None
    moments = [at for at in (line.last_at or line.mtime, end.at if end else None) if at]
    return max(moments) if moments else None


def _owner_identity(directory: Path, agent_id: str) -> Tuple[Optional[str], Optional[str]]:
    meta = read_meta_facts(directory / ("agent-%s.meta.json" % agent_id))
    fields = meta.fields or {}
    agent_type = fields.get("agentType")
    description = fields.get("description")
    return (
        agent_type if isinstance(agent_type, str) and agent_type else None,
        _redact_summary(description) if isinstance(description, str) else None,
    )


def find_open_launches(
    parent_path: Path,
    *,
    last_prompt_at: Optional[datetime],
    process_started_at: Optional[datetime],
    now: datetime,
) -> OpenLaunches:
    since = last_prompt_at or process_started_at
    if since is None:
        return OpenLaunches()
    directory = subagents_dir_for(parent_path)
    index = read_completion_index(parent_path)
    try:
        candidates = _candidates(directory, since, index)
    except FileNotFoundError:
        return OpenLaunches(since=since)
    except OSError as exc:
        logger.debug("parked_launch_dir_unreadable", error=str(exc))
        return OpenLaunches(since=since)
    found: List[OpenLaunch] = []
    fresh = 0
    for agent_id in sorted(candidates):
        active = _owner_activity(directory, agent_id, index)
        if active is None or active <= since:
            continue
        fresh += 1
        path = directory / ("agent-%s.jsonl" % agent_id)
        ledger = _incremental(path, _LEDGERS, _Ledger, _scan_launches, agent_id)
        if ledger is None or not ledger.launches:
            continue
        own = read_completion_index(path, cache=_AGENT_NOTICES)
        agent_type, description = _owner_identity(directory, agent_id)
        for launch in ledger.launches.values():
            if _retired(launch.task_id, ledger, own, index):
                continue
            if process_started_at is not None and launch.launched_at < process_started_at:
                continue
            if launch.deadline is not None and launch.deadline <= now:
                continue
            found.append(replace(launch, owner_active_at=active,
                                  agent_type=agent_type, description=description))
    deadlines = [launch.deadline for launch in found if launch.deadline is not None]
    return OpenLaunches(tuple(found), fresh, since, min(deadlines) if deadlines else None)


def conversation_launches(parent_path: Path) -> Optional[List[Tuple[OpenLaunch, bool]]]:
    parent = _incremental(parent_path, _LEDGERS, _Ledger, _scan_launches, "")
    if parent is None:
        return None
    index = read_completion_index(parent_path)
    found = [(launch, _retired(launch.task_id, parent, index))
             for launch in parent.launches.values()]
    directory = subagents_dir_for(parent_path)
    try:
        names = sorted(entry.name for entry in os.scandir(directory)
                       if _AGENT_FILE_RE.match(entry.name))
    except OSError:
        names = []
    for name in names:
        agent_id = _AGENT_FILE_RE.match(name).group(1)
        path = directory / name
        ledger = _incremental(path, _LEDGERS, _Ledger, _scan_launches, agent_id)
        if ledger is None or not ledger.launches:
            continue
        own = read_completion_index(path, cache=_AGENT_NOTICES)
        found.extend((launch, _retired(launch.task_id, ledger, own, index))
                     for launch in ledger.launches.values())
    return found


__all__ = [
    "OpenLaunch", "OpenLaunches", "conversation_launches", "find_open_launches",
    "newest_real_prompt",
]
