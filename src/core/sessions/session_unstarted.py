
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from src.core.attention.evidence import FAMILY_CLAUDE
from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    ResumeTarget,
    continuity_phrase,
)


def _absent_from_every_root(uuid: str, working_dir: Optional[str]) -> bool:
    """True only when EVERY claude transcript root measured the conversation absent.

    Inputs: uuid (str), working_dir (str | None). Output: bool - a present hit, or a root that could not be
      read (unchecked), answers False: not having looked is not an absence.
    Example: _absent_from_every_root("c1f766ce-...", "/x") -> False when a relay profile holds the .jsonl
    """
    from src.core.claude_config.transcript_roots import claude_transcript_roots
    from src.core.session_transcript_presence import conversation_presence

    return all(
        conversation_presence(uuid, working_dir=working_dir, corpus_root=root).missing
        for root in claude_transcript_roots()
    )


def _record_is_this_live_process(record: object) -> bool:
    from src.core.attention.record_identity import RecordIdentity

    pid, start = getattr(record, "pid", None), getattr(record, "proc_start", None)
    if pid is None or not start:
        return False
    identity = RecordIdentity()
    identity.refresh([(pid, start)])
    return identity.proven(pid, start) is True


def never_had_a_turn(
    tmux_name: str, uuid: str, working_dir: Optional[str], *, recorded_work: bool = True
) -> bool:
    from src.core.attention.registry_read import REG_OK, registry_for_session

    if recorded_work or not tmux_name or not uuid:
        return False
    record = registry_for_session(tmux_name=tmux_name, claude_session_uuid=uuid)
    if record.verdict != REG_OK or record.stale_cause or record.session_uuid != uuid:
        return False
    if not _record_is_this_live_process(record):
        return False
    return _absent_from_every_root(uuid, working_dir)


def downgrade_if_unstarted(
    target: ResumeTarget, tmux_name: str, working_dir: Optional[str], *, recorded_work: bool = True
) -> ResumeTarget:
    if target.outcome != CONVERSATION_RESUMED or not target.claude_session_uuid:
        return target
    if (target.family or FAMILY_CLAUDE) != FAMILY_CLAUDE:
        return target
    if not never_had_a_turn(
        tmux_name, target.claude_session_uuid, working_dir, recorded_work=recorded_work
    ):
        return target
    return replace(
        target,
        outcome=CONVERSATION_NONE_RECORDED,
        claude_session_uuid=None,
        detail=continuity_phrase(CONVERSATION_NONE_RECORDED),
    )


def row_has_recorded_work(
    last_work_at: Optional[str], session_uuid: Optional[str], state_dir: object
) -> bool:
    from pathlib import Path

    from src.core.attention_history.store import DB_NAME, has_events

    if last_work_at or not session_uuid:
        return True
    return has_events(Path(str(state_dir)) / DB_NAME, session_uuid) is not False
