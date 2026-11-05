
from __future__ import annotations

from typing import Any, Optional, Tuple

import structlog
from fastapi.concurrency import run_in_threadpool

from src.api.checkpoint_capture import codex_rollout
from src.core.bookmarks import rows
from src.core.checkpoints.store import Checkpoint
from src.core.checkpoints.turns import codex_turn_number

logger = structlog.get_logger()

NOTE = ("note from carnivore: the owner put this project's files back to how they were at the end of {turn}. "
        "anything changed on disk after that is gone, so read the files again before you edit them.")


def turn_label(cp: Checkpoint) -> str:
    path = codex_rollout(cp.conversation)
    if path is None:
        return "an earlier turn"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            number = codex_turn_number(handle, cp.prompt_uuid)
    except OSError:
        return "an earlier turn"
    return f"turn {number}" if number else "an earlier turn"


async def tell_codex(manager: Any, app: Any, row: rows.SessionRow, cp: Checkpoint) -> Tuple[bool, Optional[str]]:
    from src.core.approvals.dialog_gate import CLEAR, dialog_verdict

    if rows.family_of(row.agent_type) != "codex":
        return False, None
    session_id = next(iter(manager._registry.registered_ids_for_tmux_name(row.tmux_name)), None) if row.tmux_name else None
    if session_id is None:
        return False, "the session is not running"
    if await dialog_verdict(app, session_id) != CLEAR:
        return False, "a dialog is open in the session"
    note = NOTE.format(turn=await run_in_threadpool(turn_label, cp))
    try:
        await manager.send_command(note, session_id=session_id)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("checkpoint_codex_note_failed", session_id=session_id, error=type(exc).__name__)
        return False, "the note could not be typed into the session"
    return True, None
