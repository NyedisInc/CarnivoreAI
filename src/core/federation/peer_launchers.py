
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.federation.peer_fanout import PeerAnswer


class Launcher(BaseModel):
    """One launch profile as a paired computer may see it: the id it is launched by, its name and its family."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=100)
    name: str = Field(max_length=200)
    family: str = Field(max_length=32)


class LauncherSummary(BaseModel):

    model_config = ConfigDict(extra="forbid")

    launchers: List[Launcher] = Field(default_factory=list, max_length=200)


def summary_of(profiles: Any) -> LauncherSummary:
    return LauncherSummary(launchers=[Launcher(id=p.id, name=p.label, family=p.harness) for p in profiles])


def ssh_families() -> List[str]:
    from src.core.hosts.probe import AGENT_NAMES
    from src.core.sessions.remote_sessions import SHELL_FAMILY

    return [*AGENT_NAMES, SHELL_FAMILY]


def shown_for(answers: List[PeerAnswer]) -> Dict[str, Any]:
    if not answers:
        return {"status": "unavailable", "reason": "not_paired"}
    answer = answers[0]
    if answer.data is None:
        return {"status": "unavailable", "reason": answer.reason or "no_answer"}
    try:
        summary = LauncherSummary.model_validate(answer.data)
    except ValidationError:
        return {"status": "unavailable", "reason": "bad_answer"}
    return {"status": "ok", "launchers": [l.model_dump() for l in summary.launchers]}
