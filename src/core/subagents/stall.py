
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.background_work.leftovers import armed_monitor_owners
from src.core.subagents.parent_index import parse_timestamp
from src.core.subagents.parked_launches import conversation_launches
from src.core.subagents.reader import read_subagents
from src.core.subagents.scan_inputs import AgentFilesSignature
from src.models.subagents import SessionSubagents, SubagentInfo

logger = structlog.get_logger(__name__)

STALL_AFTER: timedelta = timedelta(minutes=5)

STALL_NOTIFY_AFTER: timedelta = timedelta(minutes=15)

_STATUS_RUNNING = "running"


@dataclass(frozen=True)
class StalledAgent:

    agent_id: str
    description: Optional[str]
    last_activity_at: datetime
    idle_seconds: int


def idle_seconds(last_activity_at: Optional[datetime], now: datetime) -> Optional[int]:
    if last_activity_at is None:
        return None
    return max(0, int((now - last_activity_at).total_seconds()))


def stalled_seconds(
    *, status: str, last_activity_at: Optional[datetime], waiting_on_monitor: bool, now: datetime,
) -> Optional[int]:
    if status != _STATUS_RUNNING or waiting_on_monitor:
        return None
    idle = idle_seconds(last_activity_at, now)
    if idle is None or idle < STALL_AFTER.total_seconds():
        return None
    return idle


def mark_stalled(
    result: SessionSubagents, transcript_path: Path, *,
    process_started_at: Optional[datetime], now: datetime,
) -> None:
    quiet: List[Tuple[SubagentInfo, datetime]] = []
    for row in result.subagents:
        at = parse_timestamp(row.last_activity_at)
        if stalled_seconds(status=row.status, last_activity_at=at, waiting_on_monitor=False,
                           now=now) is not None and at is not None:
            quiet.append((row, at))
    if not quiet:
        return
    launches = conversation_launches(transcript_path)
    if launches is None:
        logger.debug("subagent_stall_unproven", reason="launch_ledger_unreadable")
        return
    armed = armed_monitor_owners(launches, [row.id for row, _ in quiet], now=now,
                                 process_started_at=process_started_at)
    for row, at in quiet:
        row.stalled_seconds = stalled_seconds(status=row.status, last_activity_at=at,
                                              waiting_on_monitor=row.id in armed, now=now)


def read_marked(
    transcript_path: Path, *, conversation_uuid: Optional[str],
    process_started_at: Optional[datetime] = None, now: Optional[datetime] = None,
    files: AgentFilesSignature = None,
) -> SessionSubagents:
    instant = now or datetime.now(timezone.utc)
    result = read_subagents(transcript_path, conversation_uuid=conversation_uuid,
                            process_started_at=process_started_at, now=instant, files=files)
    if result.state == "ok":
        mark_stalled(result, transcript_path, process_started_at=process_started_at, now=instant)
    return result


def stalled_agents(result: SessionSubagents) -> Tuple[StalledAgent, ...]:
    found: List[StalledAgent] = []
    for row in result.subagents:
        at = parse_timestamp(row.last_activity_at)
        if row.stalled_seconds is not None and at is not None:
            found.append(StalledAgent(row.id, row.description, at, row.stalled_seconds))
    return tuple(found)


__all__ = [
    "STALL_AFTER", "STALL_NOTIFY_AFTER", "StalledAgent", "idle_seconds", "mark_stalled",
    "read_marked", "stalled_agents", "stalled_seconds",
]
