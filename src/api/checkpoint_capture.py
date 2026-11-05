
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Optional, Set, Tuple

import structlog

from src.api.session_git_routes import _session_directory
from src.core.attention.codex_pane_home import pane_codex_home
from src.core.bookmarks import rows
from src.core.bookmarks.errors import BookmarkError, TranscriptUnavailable
from src.core.bookmarks.locate import find_transcript
from src.core.checkpoints import capture as capture_mod
from src.core.checkpoints import cleanup, pins
from src.core.checkpoints.store import KIND_TURN, get_store, state_root
from src.core.checkpoints.turns import newest_codex_turn, newest_turn
from src.core.swarm.reply_turns import read_tail
from src.cplugs.host.session_uuid_reads import session_uuids
from src.cplugs.sdk import turn_events

logger = structlog.get_logger()

TAIL_BYTES = 8 * 1024 * 1024

_unsubscribe: Optional[Callable[[], None]] = None
_running: Set[str] = set()
_again: Set[str] = set()
_tasks: "Set[asyncio.Task[None]]" = set()


def codex_rollout(thread: str, codex_home: Optional[str] = None) -> Optional[str]:
    from src.core.attention.codex_gather import _UUID, DEFAULT_CODEX_HOME, rollout_path_in_sessions

    return rollout_path_in_sessions(codex_home or DEFAULT_CODEX_HOME, thread) if _UUID.match(thread or "") else None


def checkpointable(row: rows.SessionRow) -> Optional[str]:
    try:
        rows.require_bookmarkable(row)
        return "claude"
    except BookmarkError:
        pass
    ok = rows.family_of(row.agent_type) == "codex" and row.host_key == "local" and bool(row.claude_session_uuid)
    return "codex" if ok else None


def _snapshot_turn(session_uuid: str, directory: Path, conversation: str, working_dir: Optional[str],
                   family: str = "claude", pane: Tuple[Optional[str], Optional[str]] = (None, None)) -> Optional[str]:
    try:
        path = codex_rollout(conversation, pane_codex_home(*pane)) if family == "codex" else str(find_transcript(conversation, working_dir))
        if path is None:
            return "no_transcript"
        records = read_tail(path, TAIL_BYTES)
    except (TranscriptUnavailable, OSError):
        return "no_transcript"
    turn = newest_codex_turn(records) if family == "codex" else newest_turn(records)
    if turn is None:
        return "no_prompt"
    store = get_store()
    previous = store.for_session(session_uuid)
    if not turn.used_tools and previous and previous[0].kind == KIND_TURN:
        last = previous[0]
        if last.prompt_uuid != turn.prompt_uuid:
            store.put(session_uuid=session_uuid, conversation=conversation, prompt_uuid=turn.prompt_uuid,
                      kind=KIND_TURN, work_tree=last.work_tree, shadow=last.shadow, ref=last.ref,
                      commit_sha=last.commit_sha, tree_sha=last.tree_sha, head_sha=last.head_sha,
                      left_out=last.left_out, capture_ms=0)
        return None
    result = capture_mod.capture(directory, session_uuid=session_uuid, conversation=conversation,
                                 prompt_uuid=turn.prompt_uuid, store=store, state_root=state_root())
    cleanup.prune_session(store, session_uuid)
    if result.checkpoint is not None and turn.prompt_uuid in store.pinned_prompts(session_uuid):
        pins.refresh_session(store, session_uuid)
    return result.skipped


async def on_turn_end(manager: Any, ses_id: str) -> Optional[str]:
    if ses_id.startswith("remote:"):
        return "remote"
    info = await manager.get_session_info(ses_id)
    row_id = getattr(info, "session_row_id", None) if info is not None else None
    if row_id is None:
        return "gone"
    session_uuid = (await asyncio.to_thread(session_uuids, [row_id])).get(row_id)
    if not session_uuid:
        return "no_row"
    try:
        row = await asyncio.to_thread(rows.read_row, session_uuid)
    except BookmarkError:
        return "not_claude"
    family = checkpointable(row)
    if family is None or not row.claude_session_uuid:
        return "not_claude"
    conversation = row.claude_session_uuid
    directory = await _session_directory(manager, info)
    if directory is None:
        return "no_folder"
    if session_uuid in _running:
        _again.add(session_uuid)
        return "queued"
    _running.add(session_uuid)
    try:
        while True:
            _again.discard(session_uuid)
            reason = await asyncio.to_thread(_snapshot_turn, session_uuid, directory, conversation, row.working_dir,
                                             family, (row.tmux_socket, row.tmux_name))
            if session_uuid not in _again:
                return reason
    finally:
        _running.discard(session_uuid)


async def _guarded(manager: Any, ses_id: str) -> None:
    try:
        reason = await on_turn_end(manager, ses_id)
        if reason not in (None, "gone", "remote", "not_claude"):
            logger.debug("checkpoint_turn_skipped", session_id=ses_id, reason=reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("checkpoint_turn_failed", session_id=ses_id, error=type(exc).__name__)


def subscribe(manager: Any) -> None:
    global _unsubscribe
    unsubscribe()
    loop = asyncio.get_running_loop()

    def listener(ses_id: Optional[str]) -> None:
        if not ses_id:
            return

        def start() -> None:
            task = loop.create_task(_guarded(manager, ses_id), name="turn-checkpoint")
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)

        loop.call_soon_threadsafe(start)

    _unsubscribe = turn_events.subscribe(listener)
    task = loop.create_task(asyncio.to_thread(cleanup.at_start, get_store(), state_root()), name="turn-checkpoint-start")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def unsubscribe() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
