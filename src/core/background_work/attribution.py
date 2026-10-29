
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.subagents.parked_launches import OpenLaunch, conversation_launches

OWNERS_OK: str = "ok"
OWNERS_ABSENT: str = "absent"
OWNERS_UNCHECKED: str = "unchecked"


@dataclass(frozen=True)
class LaunchOwners:

    state: str
    by_task: Dict[str, str] = field(default_factory=dict)

    def owner_of(self, task_id: Optional[str]) -> Optional[str]:
        return self.by_task.get(task_id) if task_id else None


def owners_from(launches: Iterable[Tuple[OpenLaunch, bool]]) -> Dict[str, str]:
    return {launch.task_id: launch.agent_id for launch, _retired in launches
            if launch.agent_id and launch.task_id}


def read_owners(
    conversation_uuid: Optional[str],
    *,
    working_dir: Optional[str],
    projects_dir: Optional[Path] = None,
    reader: Callable[[Path], Optional[list]] = conversation_launches,
) -> LaunchOwners:
    if not conversation_uuid:
        return LaunchOwners(OWNERS_ABSENT)
    location = claude_reader.locate_transcript(
        conversation_uuid, working_dir=working_dir, projects_dir=projects_dir,
    )
    if location.outcome == CONVERSATION_ABSENT:
        return LaunchOwners(OWNERS_ABSENT)
    if location.outcome != CONVERSATION_PRESENT or location.path is None:
        return LaunchOwners(OWNERS_UNCHECKED)
    launches = reader(location.path)
    if launches is None:
        return LaunchOwners(OWNERS_UNCHECKED)
    return LaunchOwners(OWNERS_OK, owners_from(launches))


__all__ = [
    "LaunchOwners", "OWNERS_ABSENT", "OWNERS_OK", "OWNERS_UNCHECKED", "owners_from",
    "read_owners",
]
