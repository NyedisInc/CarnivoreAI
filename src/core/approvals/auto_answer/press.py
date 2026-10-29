
from __future__ import annotations

from typing import Any, Awaitable, Callable

from src.core.approvals.answer import AnswerRefused, Choice
from src.core.approvals.deliver import SOURCE_AUTO, deliver_answer

Answer = Callable[[str, str, str], Awaitable[None]]


class AckRefused(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def route_answer(app_state: Any, get_manager: Callable[[], Any]) -> Answer:
    async def answer(session_id: str, fingerprint: str, label: str) -> None:
        manager = get_manager()
        info = await manager.get_session_info(session_id) if manager is not None else None
        if info is None:
            raise AckRefused("session_gone")
        try:
            await deliver_answer(manager=manager, watcher=getattr(app_state, "attention_watcher", None), info=info,
                                 fingerprint=fingerprint, choice=Choice(option=label), source=SOURCE_AUTO)
        except AnswerRefused as exc:
            raise AckRefused(exc.reason) from exc

    return answer
