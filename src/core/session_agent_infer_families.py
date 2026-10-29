
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from src.core.claude_resume_argv import ProcessRow, find_claude_commands_in_tree
from src.core.codex_process_infer import (
    CODEX_FAMILY,
    find_codex_commands_in_tree,
    resolve_codex_inference,
)
from src.core.session_agent_infer import (
    AgentInference,
    CLAUDE_FAMILY,
    INFER_FAMILY,
    INFER_WRAPPER,
    resolve_agent_inference,
)


@dataclass(frozen=True)
class PaneAgentInference:

    family: Optional[str]
    inference: AgentInference

    @property
    def named(self) -> bool:
        return (
            self.family is not None
            and self.inference.outcome in (INFER_WRAPPER, INFER_FAMILY)
            and bool(self.inference.agent_type)
        )


def infer_pane_agent(
    *,
    pane_pid: Optional[int],
    table: Optional[Sequence[ProcessRow]],
    pane_current_command: Optional[str],
    wrappers: Sequence,
) -> PaneAgentInference:
    read = table is not None and pane_pid is not None
    claude_cmds = find_claude_commands_in_tree(int(pane_pid), table) if read else []
    claude = resolve_agent_inference(
        claude_argv=claude_cmds[0] if claude_cmds else None,
        pane_current_command=pane_current_command,
        process_table_read=read,
        wrappers=wrappers,
    )
    if claude.outcome in (INFER_WRAPPER, INFER_FAMILY):
        return PaneAgentInference(CLAUDE_FAMILY, claude)
    if not read:
        return PaneAgentInference(None, claude)

    codex_cmds = find_codex_commands_in_tree(int(pane_pid), table)
    codex = resolve_codex_inference(
        codex_argv=codex_cmds[0] if codex_cmds else None,
        pane_current_command=pane_current_command,
    )
    if codex.outcome == INFER_FAMILY:
        return PaneAgentInference(CODEX_FAMILY, codex)
    return PaneAgentInference(None, claude)
