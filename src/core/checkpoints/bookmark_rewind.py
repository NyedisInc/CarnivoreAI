
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.checkpoints.revert import RevertResult
from src.core.checkpoints.store import KIND_TURN, Checkpoint, CheckpointStore

logger = structlog.get_logger()

MODE_CONVERSATION, MODE_FILES, MODE_BOTH = "conversation", "files", "both"
MID_TURN, NO_SNAPSHOT = "mid_turn", "no_snapshot"
FILES_NOT_RESTORED = "conversation rewound, files not restored"


def turn_snapshot(store: CheckpointStore, session_uuid: str, entry_uuid: str) -> Optional[Checkpoint]:
    return next((cp for cp in store.for_session(session_uuid)
                 if cp.kind == KIND_TURN and cp.prompt_uuid == entry_uuid), None)


def _is_turn_prompt(conversation: str, entry_uuid: str, working_dir: Optional[str]) -> bool:
    from src.core.bookmarks import locate, transcript_index
    from src.core.bookmarks.errors import BookmarkError

    try:
        index = transcript_index.cached_index(locate.find_transcript(conversation, working_dir))
    except (BookmarkError, OSError):
        return True
    node = index.nodes.get(entry_uuid)
    return node is None or node.prompt or node.turn_start


def files_unavailable(store: CheckpointStore, mark: Dict[str, Any], working_dir: Optional[str]) -> Optional[str]:
    if turn_snapshot(store, mark["session_uuid"], mark["entry_uuid"]) is not None:
        return None
    if not _is_turn_prompt(mark["claude_session_uuid"], mark["entry_uuid"], working_dir):
        return MID_TURN
    return NO_SNAPSHOT


def annotate(store: CheckpointStore, marks: List[Dict[str, Any]], working_dir: Optional[str]) -> List[Dict[str, Any]]:
    for mark in marks:
        cp = turn_snapshot(store, mark["session_uuid"], mark["entry_uuid"])
        mark["files_checkpoint_id"] = cp.id if cp is not None else None
        mark["files_unavailable"] = None if cp is not None else files_unavailable(store, mark, working_dir)
    return marks


@dataclass
class Outcome:

    conversation: Optional[Dict[str, Any]]
    files: Optional[RevertResult]
    files_error: Optional[str] = None
    why: Optional[str] = None


async def run(mode: str, *, conversation: Callable[[], Awaitable[Dict[str, Any]]],
              files: Callable[[], Awaitable[RevertResult]]) -> Outcome:
    if mode == MODE_FILES:
        return Outcome(conversation=None, files=await files())
    if mode != MODE_BOTH:
        raise ValueError(f"unknown rewind mode {mode!r}")
    said = await conversation()
    if not said.get("ok"):
        return Outcome(conversation=said, files=None, files_error=FILES_NOT_RESTORED,
                       why=said.get("detail") or "the conversation rewind did not finish")
    try:
        done = await files()
    except Exception as exc:  # noqa: BLE001
        why = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        logger.warning("bookmark_rewind_files_failed", error=type(exc).__name__, why=why)
        return Outcome(conversation=said, files=None, files_error=FILES_NOT_RESTORED, why=why)
    return Outcome(conversation=said, files=done)
