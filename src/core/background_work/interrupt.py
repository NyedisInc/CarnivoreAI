
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.background_work.tree import PaneTree

SHELL_FAMILY: str = "shell"
DEAD_STATUS: str = "dead"

REFUSE_NOT_AN_AGENT: str = "not_an_agent"
REFUSE_DEAD: str = "session_dead"
REFUSE_NO_AGENT: str = "no_agent_process"

ESCAPE: str = "\x1b"


@dataclass(frozen=True)
class InterruptVerdict:

    allowed: bool
    code: Optional[str]
    detail: str


def check_facts(*, agent_family: Optional[str], activity_status: Optional[str]) -> InterruptVerdict:
    if agent_family == SHELL_FAMILY:
        return InterruptVerdict(False, REFUSE_NOT_AN_AGENT,
                                "this is a plain shell session; an escape there is a keystroke "
                                "in somebody's prompt")
    if activity_status == DEAD_STATUS:
        return InterruptVerdict(False, REFUSE_DEAD, "the session's pane is dead")
    return InterruptVerdict(True, None, "the listing row names an agent session")


def check_pane(tree: PaneTree) -> InterruptVerdict:
    if tree.agent_pid is None:
        return InterruptVerdict(False, REFUSE_NO_AGENT,
                                "no claude or codex process runs in this pane")
    return InterruptVerdict(True, None, f"the pane runs its agent as pid {tree.agent_pid}")


__all__ = [
    "DEAD_STATUS", "ESCAPE", "InterruptVerdict", "REFUSE_DEAD", "REFUSE_NOT_AN_AGENT",
    "REFUSE_NO_AGENT", "SHELL_FAMILY", "check_facts", "check_pane",
]
