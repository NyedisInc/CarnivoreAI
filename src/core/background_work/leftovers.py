
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.background_work.batch import OUTCOME_REFUSED, TargetOutcome
from src.core.attention.turn_counts import KIND_MONITOR
from src.core.background_work.listing import ListedProcess
from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_PRESENT
from src.core.subagents.parent_index import parked_agent_ids, read_completion_index
from src.core.subagents.parked_launches import OpenLaunch, conversation_launches
from src.core.subagents.reader import agent_statuses

STATUS_DONE: str = "done"

REFUSE_NOT_LEFTOVER: str = "not_leftover"


def leftover_task_ids(
    live_task_ids: Iterable[str],
    owner_by_task: Mapping[str, str],
    finished: FrozenSet[str],
) -> FrozenSet[str]:
    return frozenset(
        task_id for task_id in live_task_ids
        if owner_by_task.get(task_id) in finished
    )


def locate_conversation(
    conversation_uuid: Optional[str],
    working_dir: Optional[str],
    *,
    projects_dir: Optional[Path] = None,
) -> Optional[Path]:
    if not conversation_uuid:
        return None
    location = claude_reader.locate_transcript(
        conversation_uuid, working_dir=working_dir, projects_dir=projects_dir,
    )
    if location.outcome != CONVERSATION_PRESENT:
        return None
    return location.path


def finished_agent_ids(
    transcript_path: Optional[Path],
    agent_ids: Iterable[str],
    *,
    process_started_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Optional[FrozenSet[str]]:
    wanted = tuple(dict.fromkeys(agent_ids))
    if not wanted:
        return frozenset()
    if transcript_path is None:
        return None
    statuses = agent_statuses(transcript_path, wanted, process_started_at=process_started_at)
    if statuses is None:
        return None
    done = frozenset(agent for agent, status in statuses.items() if status == STATUS_DONE)
    if not done:
        return done
    launches = conversation_launches(transcript_path)
    index = read_completion_index(transcript_path)
    if launches is None or index is None:
        return None
    instant = now or datetime.now(timezone.utc)
    armed = armed_monitor_owners(launches, done, now=instant, process_started_at=process_started_at)
    return done - armed - parked_agent_ids(index, done)


def armed_monitor_owners(
    launches: Sequence[Tuple[OpenLaunch, bool]],
    agent_ids: Iterable[str],
    *,
    now: datetime,
    process_started_at: Optional[datetime],
) -> FrozenSet[str]:
    wanted = frozenset(agent_ids)
    return frozenset(
        launch.agent_id for launch, retired in launches
        if not retired
        and launch.kind == KIND_MONITOR
        and launch.agent_id in wanted
        and launch.deadline is not None
        and launch.deadline > now
        and (process_started_at is None or launch.launched_at >= process_started_at)
    )


def owner_finished_by_pid(
    listed: Sequence[ListedProcess],
    owner_of: Mapping[str, str],
    owners_ok: bool,
    finished: Optional[FrozenSet[str]],
) -> Mapping[int, Optional[bool]]:
    answers = {}
    for process in listed:
        agent = owner_of.get(process.task_id) if process.task_id else None
        if not owners_ok:
            answers[process.pid] = None
        elif agent is None:
            answers[process.pid] = False
        elif finished is None:
            answers[process.pid] = None
        else:
            answers[process.pid] = agent in finished
    return answers


def leftover_count(marks: Mapping[int, Optional[bool]]) -> Optional[int]:
    if any(mark is None for mark in marks.values()):
        return None
    return sum(1 for mark in marks.values() if mark)


@dataclass(frozen=True)
class StopPlan:

    targets: List[Tuple[int, str]]
    refused: List[TargetOutcome]


def plan_stop(
    listed: Sequence[ListedProcess],
    marks: Mapping[int, Optional[bool]],
    requested: Optional[Sequence[Tuple[int, str]]],
) -> StopPlan:
    leftovers = {p.pid: p.start for p in listed if marks.get(p.pid) is True}
    if requested is None:
        return StopPlan(sorted(leftovers.items()), [])
    targets: List[Tuple[int, str]] = []
    refused: List[TargetOutcome] = []
    for pid, start in requested:
        if leftovers.get(pid) == start and start:
            targets.append((pid, start))
        else:
            refused.append(TargetOutcome(
                pid=pid, outcome=OUTCOME_REFUSED, code=REFUSE_NOT_LEFTOVER,
                detail=f"pid {pid} is not a leftover shell of this session (its owner has not finished, or it is not measured)",
            ))
    return StopPlan(targets, refused)


__all__ = [
    "REFUSE_NOT_LEFTOVER", "STATUS_DONE", "StopPlan", "armed_monitor_owners", "finished_agent_ids",
    "leftover_count", "leftover_task_ids", "locate_conversation", "owner_finished_by_pid", "plan_stop",
]
