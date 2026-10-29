
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.stat_gate.dir_names import entry_names
from src.core.subagents.contract import SHAPE_UNRECOGNIZED, contract_versions
from src.core.subagents.files import (
    FILE_UNREADABLE,
    LineFacts,
    MetaFacts,
    read_line_facts,
    read_meta_facts,
)
from src.core.subagents.parent_index import (
    CompletionIndex,
    RecordedEnd,
    read_completion_index,
)
from src.models.subagents import SessionSubagents, SubagentCounts, SubagentInfo

logger = structlog.get_logger(__name__)

CLOCK_SKEW: timedelta = timedelta(seconds=2)

SILENT_AFTER: timedelta = timedelta(minutes=30)

MAX_LISTED: int = 200

_USER_AGENT_ID = re.compile(r"^[0-9a-f]+$")

_JSONL = ".jsonl"
_META = ".meta.json"
_PREFIX = "agent-"


@dataclass(frozen=True)
class _Candidate:

    agent_id: str
    mtime: float


def subagents_dir_for(transcript_path: Path) -> Path:
    return transcript_path.with_suffix("") / "subagents"


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scan(directory: Path) -> Tuple[List[_Candidate], int]:
    newest: dict = {}
    internal = set()
    for name in entry_names(directory):
        if not name.startswith(_PREFIX):
            continue
        if name.endswith(_META):
            agent_id = name[len(_PREFIX):-len(_META)]
        elif name.endswith(_JSONL):
            agent_id = name[len(_PREFIX):-len(_JSONL)]
        else:
            continue
        if not _USER_AGENT_ID.match(agent_id):
            internal.add(agent_id)
            continue
        try:
            mtime = os.stat(os.path.join(directory, name)).st_mtime
        except OSError:
            mtime = 0.0
        newest[agent_id] = max(mtime, newest.get(agent_id, 0.0))
    candidates = [_Candidate(agent_id, mtime) for agent_id, mtime in newest.items()]
    candidates.sort(key=lambda c: (c.mtime, c.agent_id), reverse=True)
    return candidates, len(internal)


def classify(
    *,
    line: LineFacts,
    end: Optional[RecordedEnd],
    index_available: bool,
    process_started_at: Optional[datetime],
    now: datetime,
) -> Tuple[str, str]:
    if not index_available:
        return "unknown", "parent_unreadable"
    if line.state == SHAPE_UNRECOGNIZED:
        return "unknown", "shape_unrecognized"
    if line.state == FILE_UNREADABLE:
        return "unknown", "transcript_unreadable"
    activity = line.last_at or line.mtime
    if end is not None and (activity is None or end.at >= activity - CLOCK_SKEW):
        return "done", "end_recorded"
    if activity is None:
        return "unknown", "transcript_unreadable"
    if process_started_at is not None and activity < process_started_at:
        return "unknown", "process_restarted"
    if now - activity > SILENT_AFTER:
        return "unknown", "silent"
    return "running", ("resumed_after_end" if end is not None else "no_end_recorded")


def _info(
    directory: Path,
    agent_id: str,
    meta: MetaFacts,
    line: LineFacts,
    index: Optional[CompletionIndex],
    process_started_at: Optional[datetime],
    now: datetime,
) -> SubagentInfo:
    fields = meta.fields or {}
    tool_use_id = fields.get("toolUseId")
    end = index.end_for(agent_id, tool_use_id) if index is not None else None
    spawner = fields.get("parentAgentId")
    if index is not None and isinstance(spawner, str) and _USER_AGENT_ID.match(spawner):
        nested = read_completion_index(
            directory / f"{_PREFIX}{spawner}{_JSONL}", spawner=True
        )
        if nested is None:
            index = None
        else:
            nested_end = nested.end_for(agent_id, tool_use_id)
            if nested_end is not None and (end is None or nested_end.at > end.at):
                end = nested_end
    status, reason = classify(line=line, end=end, index_available=index is not None,
                              process_started_at=process_started_at, now=now)
    shape = fields.get("requestShape")
    return SubagentInfo(
        id=agent_id,
        agent_type=fields.get("agentType"),
        description=fields.get("description"),
        model=fields.get("model"),
        background=(shape == "background") if shape is not None else None,
        spawn_depth=fields.get("spawnDepth"),
        started_at=_iso(line.started_at),
        last_activity_at=_iso(line.last_at or line.mtime),
        status=status,
        status_reason=reason,
        end_status=end.status if (end is not None and status == "done") else None,
        meta_shape=meta.state,
        transcript_shape=line.state,
    )


def read_subagents(
    transcript_path: Path,
    *,
    conversation_uuid: Optional[str],
    process_started_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    max_listed: int = MAX_LISTED,
) -> SessionSubagents:
    instant = now or datetime.now(timezone.utc)
    base = SessionSubagents(
        state="ok", family="claude", conversation_uuid=conversation_uuid,
        contract_versions=contract_versions(), as_of=_iso(instant),
    )
    directory = subagents_dir_for(transcript_path)
    try:
        candidates, internal = _scan(directory)
    except FileNotFoundError:
        base.counts = SubagentCounts(total=0, listed=0, running=0, done=0,
                                     unknown=0, shape_unrecognized=0, internal=0)
        base.detail = "this conversation has launched no subagents"
        return base
    except OSError as exc:
        logger.debug("subagents_dir_unreadable", error=str(exc))
        base.state = "unchecked"
        base.detail = "the subagents directory could not be listed"
        return base
    index = read_completion_index(transcript_path)
    rows: List[SubagentInfo] = []
    for candidate in candidates[:max_listed]:
        stem = directory / f"{_PREFIX}{candidate.agent_id}"
        meta = read_meta_facts(Path(f"{stem}{_META}"))
        line = read_line_facts(Path(f"{stem}{_JSONL}"))
        rows.append(_info(directory, candidate.agent_id, meta, line, index,
                          process_started_at, instant))
    base.subagents = rows
    base.counts = SubagentCounts(
        total=len(candidates),
        listed=len(rows),
        running=sum(1 for row in rows if row.status == "running"),
        done=sum(1 for row in rows if row.status == "done"),
        unknown=sum(1 for row in rows if row.status == "unknown"),
        shape_unrecognized=sum(
            1 for row in rows
            if SHAPE_UNRECOGNIZED in (row.meta_shape, row.transcript_shape)
        ),
        internal=internal,
    )
    if index is None:
        base.detail = ("the parent transcript could not be read, so no status "
                       "could be proven")
    elif len(candidates) > len(rows):
        base.detail = (f"the {len(candidates) - len(rows)} oldest subagents "
                       "were not read")
    return base


__all__ = ["read_subagents", "classify", "subagents_dir_for"]
