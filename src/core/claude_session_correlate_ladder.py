"""The corrected two-rung ladder: pane argv, then transcript timing.

THE LADDER, MOST DECISIVE FIRST.

  1. PANE ARGV (:mod:`src.core.claude_resume_argv`). Read the pane's own
     process tree; if a `claude` process anywhere in it carries a valid
     `--resume <uuid>`, that IS the conversation - a direct read, zero
     ambiguity, and the only rule that can ever find a resumed session.
     Covers both process topologies (pane pid is claude directly, or
     pane pid is a shell with claude as a descendant) via one BFS walk.

  3. Otherwise CANNOT DETERMINE, exactly as before.

Every safeguard from the original design is preserved unchanged: never
guess on multiplicity, never write a uuid already on another row, never
un-archive, fail soft on every filesystem/process read, and the v12->v13
provenance column - now carrying a THIRD value,
`SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV`, distinct from the timing
rule's `SESSION_CLAUDE_UUID_SOURCE_CORRELATED` because a direct argv read
is materially stronger evidence than a timestamp match and collapsing
the two into one label would hide that difference from anything
rendering it later (see db_models.py's SESSION_CLAUDE_UUID_SOURCE_* block
for the full three-way ranking).
"""

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
    """Run the two-rung ladder and return whichever rung matched, if any.

    Description: rule 1 runs first and, on a match, short-circuits -
      rule 2 is not even attempted, since a resumed conversation's own
      transcript would only ever mislead the timing rule (it predates
      the pane). Rule 1 is skipped entirely (falls straight to rule 2)
      when `pane_pid` is None or the process table could not be read -
      both are "no argv evidence available", not "argv evidence says no
      match", and the correct response to "could not evaluate" here is
      to try the next rung, not to give up.
    Inputs: pane_pid (int | None) - the tmux pane's own foreground pid.
      None when it could not be probed. working_dir (str | None),
      tmux_created_epoch (int | None) - forwarded to rule 2 unchanged.
      projects_dir (Path | None) - override for tests, forwarded to rule
      2. process_table (Sequence[ProcessRow] | None) - override for
      tests; when None, :func:`list_process_table` is called for a real
      `ps` snapshot.
    Output: LadderResult.
    Example: correlate_adopted_session_ladder(pane_pid=4242,
        working_dir='/x', tmux_created_epoch=1788016091).method
      # 'pane_argv'
    """
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
