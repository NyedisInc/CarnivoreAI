
from __future__ import annotations

import subprocess
from typing import Optional, Sequence

import structlog

from src.core.attention.record_identity import RecordIdentity
from src.core.attention.registry_index import read_registry_index, registry_for_session
from src.core.attention.registry_record import REG_OK
from src.core.claude_resume_argv import ProcessRow, find_rows_in_tree, is_claude_command, list_process_table
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence

logger = structlog.get_logger()

NOT_CONFIRMED = "the pane's conversation was not confirmed before the claim"

FORK_FLAG = "--fork-session"


def confirm_pane_conversation(
    *,
    name: str,
    epoch: int,
    claude_uuid: str,
    working_dir: Optional[str],
    pane_pid: Optional[int],
    registry_dir: Optional[str] = None,
    identity: Optional[RecordIdentity] = None,
    table: Optional[Sequence[ProcessRow]] = None,
) -> Optional[str]:
    if pane_pid is None:
        return "the pane's process tree could not be read"
    processes = table if table is not None else list_process_table()
    if processes is None:
        return "the process table could not be read"
    claudes = find_rows_in_tree(pane_pid, processes, is_claude_command)
    record = registry_for_session(
        tmux_name=name, index=read_registry_index(registry_dir), session_started_epoch=epoch,
    )
    if record.verdict != REG_OK:
        return "claude's own registry has no live record for this pane (%s)" % record.verdict
    if record.pid is None or record.pid not in {row.pid for row in claudes}:
        return "the registry record's pid is not a claude process in this pane's tree"
    if record.started_at is None or not record.proc_start:
        return "the registry record carries no start time to prove its process against"
    proof = identity if identity is not None else RecordIdentity()
    proof.refresh([(record.pid, record.proc_start)])
    if proof.proven(record.pid, record.proc_start) is not True:
        return "the registry record's process start time was not proven to be this pid's"
    if (record.session_uuid or "").lower() != claude_uuid.lower():
        logger.info("adopt_confirm_registry_mismatch", tmux_name=name, argv_uuid=claude_uuid,
                    registry_uuid=record.session_uuid)
        return "claude's registry says the pane has a different conversation open than its argv named"
    if conversation_presence(claude_uuid, working_dir=working_dir).outcome != CONVERSATION_PRESENT:
        return "the conversation has no transcript on disk"
    if any(FORK_FLAG in row.command.split() for row in claudes):
        return "the pane's claude was launched with --fork-session"
    return None


CONFIRM_ERRORS = (OSError, ValueError, TypeError, subprocess.SubprocessError)
