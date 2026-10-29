
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import structlog

from src.core.claude_resume_argv import (
    ProcessRow,
    find_resume_uuid_in_tree,
    list_process_table,
)
from src.core.claude_transcript_correlate import (
    CORRELATE_MATCHED,
    correlate_adopted_session,
)

logger = structlog.get_logger()

LADDER_METHOD_PANE_ARGV = "pane_argv"

LADDER_METHOD_TRANSCRIPT_TIMING = "transcript_timing"


@dataclass(frozen=True)
class LadderResult:

    outcome: str
    claude_session_uuid: Optional[str] = None
    method: Optional[str] = None
    detail: Optional[str] = None
    transcript_path: Optional[str] = None

    @property
    def matched(self) -> bool:
        return self.outcome == CORRELATE_MATCHED


def correlate_adopted_session_ladder(
    *,
    pane_pid: Optional[int],
    working_dir: Optional[str],
    tmux_created_epoch: Optional[int],
    projects_dir: Optional[Path] = None,
    process_table: Optional[Sequence[ProcessRow]] = None,
) -> LadderResult:
    if pane_pid is not None:
        table = (
            process_table if process_table is not None else list_process_table()
        )
        if table is not None:
            uuid = find_resume_uuid_in_tree(pane_pid, table)
            if uuid is not None:
                return LadderResult(
                    outcome=CORRELATE_MATCHED,
                    claude_session_uuid=uuid,
                    method=LADDER_METHOD_PANE_ARGV,
                )

    fallback = correlate_adopted_session(
        working_dir=working_dir,
        tmux_created_epoch=tmux_created_epoch,
        projects_dir=projects_dir,
    )
    if fallback.matched:
        return LadderResult(
            outcome=CORRELATE_MATCHED,
            claude_session_uuid=fallback.claude_session_uuid,
            method=LADDER_METHOD_TRANSCRIPT_TIMING,
            transcript_path=fallback.transcript_path,
        )
    return LadderResult(outcome=fallback.outcome, detail=fallback.detail)
