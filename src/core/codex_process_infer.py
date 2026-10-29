
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from src.core.claude_resume_argv import (
    MAX_TREE_DEPTH,
    ProcessRow,
    find_commands_in_tree,
)
from src.core.db_models import SESSION_FAMILY_SOURCE_INFERRED_PROCESS
from src.core.session_agent_infer import (
    AgentInference,
    INFER_FAMILY,
    INFER_NOT_CLAUDE,
)

CODEX_FAMILY: str = "codex"

_SCRIPT_HOSTS = frozenset({"node", "nodejs", "bun"})


def is_codex_command(command: str) -> bool:
    words = (command or "").split()
    if not words:
        return False
    head = Path(words[0]).name
    if head == CODEX_FAMILY:
        return True
    return head in _SCRIPT_HOSTS and len(words) > 1 and Path(words[1]).name == CODEX_FAMILY


def find_codex_commands_in_tree(
    root_pid: int,
    processes: Sequence[ProcessRow],
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> List[str]:
    return find_commands_in_tree(
        root_pid, processes, is_codex_command, max_depth=max_depth
    )


def resolve_codex_inference(
    *, codex_argv: Optional[str], pane_current_command: Optional[str]
) -> AgentInference:
    current = (pane_current_command or "").strip().rsplit("/", 1)[-1].lower()
    if codex_argv or current == CODEX_FAMILY:
        return AgentInference(
            INFER_FAMILY,
            agent_type=CODEX_FAMILY,
            family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
            detail=(
                "a codex process is running in this pane's tree"
                if codex_argv
                else "the pane's own foreground command is codex"
            ),
        )
    return AgentInference(
        INFER_NOT_CLAUDE,
        detail="the process table was read and this pane's tree holds no codex",
    )
