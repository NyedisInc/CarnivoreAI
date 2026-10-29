
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from src.core.approvals.answer import SETTLE_SECONDS, AnswerRefused, Choice, answer_dialog
from src.core.approvals.answer_all import QuestionAnswer, answer_all
from src.core.approvals.ask_questions import locate_ask
from src.core.approvals.extract import DIALOG_SCROLLBACK_LINES, Dialog, unreadable_dialog
from src.core.approvals.plain_answer import APPROVABLE_KINDS, summarize
from src.core.attention_reader import AttentionEvidenceReader

logger = structlog.get_logger()

SOURCE_OWNER = "owner"
SOURCE_OWNER_BANNER = "owner_banner"
SOURCE_BEAST = "beast"
SOURCE_AUTO = "auto"

_LOCKS: Dict[str, asyncio.Lock] = {}

_NEXT_READS: int = 6
_NEXT_GAP_SECONDS: float = 0.2


async def _show_next_question(watcher: Any, row_id: str, answered: Dialog) -> None:
    tick = getattr(watcher, "tick_sessions", None)
    if tick is None:
        return
    more = answered.question_index is not None and answered.question_index < len(answered.tabs)
    for _ in range(_NEXT_READS if more else 1):
        await asyncio.sleep(_NEXT_GAP_SECONDS if more else SETTLE_SECONDS)
        await tick({row_id})
        seen = watcher.observation_for(row_id)
        shown = seen.evidence.dialog if seen is not None else None
        if shown is not None and shown.fingerprint != answered.fingerprint:
            return


async def deliver_answer(*, manager: Any, watcher: Optional[Any], info: Any, fingerprint: str,
                         choice: Choice, source: str) -> Dialog:
    tmux_name = info.tmux_session
    session_id = info.session.id
    if not tmux_name:
        raise AnswerRefused("session_gone")
    socket = manager.tmux_socket_name()

    async def capture() -> Optional[str]:
        return await asyncio.to_thread(AttentionEvidenceReader._capture, socket, str(tmux_name), DIALOG_SCROLLBACK_LINES)

    async def send(data: str) -> None:
        try:
            await manager.send_input(data, session_id=session_id)
        except ValueError as exc:
            raise AnswerRefused("not_running") from exc

    async with _LOCKS.setdefault(session_id, asyncio.Lock()):
        dialog = await answer_dialog(family=info.agent_family, fingerprint=fingerprint,
                                     choice=choice, capture=capture, send=send)
        if not choice.dismiss:
            await _show_next_question(watcher, session_id, dialog)
    tool, command = summarize(dialog) if dialog.kind in APPROVABLE_KINDS else ("", "")
    logger.info("session_dialog_answered", session_id=session_id, kind=dialog.kind,
                fingerprint=dialog.fingerprint[:12], choice=choice.kind, source=source,
                tool=tool or None, command=command or None)
    return dialog


async def deliver_answers(*, manager: Any, watcher: Optional[Any], info: Any, questions_fingerprint: str,
                          answers: List[QuestionAnswer], source: str) -> str:
    tmux_name = info.tmux_session
    session_id = info.session.id
    if not tmux_name:
        raise AnswerRefused("session_gone")
    socket = manager.tmux_socket_name()

    async def capture() -> Optional[str]:
        return await asyncio.to_thread(AttentionEvidenceReader._capture, socket, str(tmux_name), DIALOG_SCROLLBACK_LINES)

    async def send(data: str) -> None:
        try:
            await manager.send_input(data, session_id=session_id)
        except ValueError as exc:
            raise AnswerRefused("not_running") from exc

    async with _LOCKS.setdefault(session_id, asyncio.Lock()):
        asked, located = await asyncio.to_thread(locate_ask, info, watcher)
        if not located:
            raise AnswerRefused("no_transcript_questions")
        if asked is None:
            raise AnswerRefused("no_questions")
        if asked.fingerprint != questions_fingerprint:
            raise AnswerRefused("questions_changed")
        via = await answer_all(asked=asked, answers=answers, capture=capture, send=send)
        await _show_next_question(watcher, session_id, unreadable_dialog("claude"))
    logger.info("session_dialog_answered_all", session_id=session_id, questions=len(answers), via=via,
                fingerprint=questions_fingerprint[:12], source=source)
    return via
