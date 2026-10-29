"""The prompt-press seam: answer a plain yes on an eligible permission prompt when beast mode's grid says to.

HOW IT DECIDES, from the watcher observation it is handed (nothing is captured here):
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

import structlog

from src.core.approvals.answer import AnswerRefused, Choice
from src.core.approvals.deliver import SOURCE_BEAST, deliver_answer
from src.core.approvals.extract import FAMILY_CLAUDE, FAMILY_CODEX, Dialog
from src.core.approvals.plain_answer import PLAIN_YES, plain_yes_label, summarize
from src.core.approvals.startup_extract import answer_needs_owner

logger = structlog.get_logger()

SETTLE_SECONDS: float = 2.0
HISTORY_ACTION = "session_prompt"
NOTIFY_TYPE = "session.beast_approved"

_FAMILIES = (FAMILY_CLAUDE, FAMILY_CODEX)


def eligible_dialog(observation: Any) -> Optional[Dialog]:
    if observation is None or getattr(observation, "stale", False):
        return None
    evidence = observation.evidence
    if getattr(evidence, "startup_screen", None) is not None:
        return None
    dialog = getattr(evidence, "dialog", None)
    if dialog is None or dialog.family not in _FAMILIES or plain_yes_label(dialog) is None:
        return None
    if answer_needs_owner(dialog):
        return None
    return dialog


class BeastPromptsEngine:

    def __init__(self, get_manager: Callable[[], Any], get_watcher: Callable[[], Any], *,
                 enabled: Callable[[Dialog], bool], on_answered: Callable[[Any, Dialog], None],
                 on_expiry: Optional[Callable[[], Any]] = None, expired: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.monotonic, settle_seconds: float = SETTLE_SECONDS) -> None:
        self._manager = get_manager
        self._watcher = get_watcher
        self._enabled = enabled
        self._on_answered = on_answered
        self._on_expiry = on_expiry
        self._expired = expired
        self._clock = clock
        self._settle = settle_seconds
        self._seen: Dict[str, Tuple[str, float]] = {}
        self._attempted: Dict[str, str] = {}
        self._tasks: Set[asyncio.Task] = set()

    def on_observation(self, target: Any, observation: Any) -> Optional[asyncio.Task]:
        self._maybe_expire()
        key = str(target.key)
        dialog = eligible_dialog(observation)
        shown = getattr(getattr(observation, "evidence", None), "dialog", None)
        if shown is None or (self._attempted.get(key) not in (None, shown.fingerprint)):
            self._attempted.pop(key, None)
        if dialog is None:
            self._seen.pop(key, None)
            return None
        now = self._clock()
        fingerprint, first = self._seen.get(key, (dialog.fingerprint, now))
        if fingerprint != dialog.fingerprint:
            first = now
        self._seen[key] = (dialog.fingerprint, first)
        if (now - first < self._settle or self._attempted.get(key) == dialog.fingerprint
                or str(target.session_id).startswith("remote:") or not self._enabled(dialog)):
            return None
        self._attempted[key] = dialog.fingerprint
        return self._spawn(self._answer(str(target.session_id), dialog))

    def _spawn(self, coro: Any) -> Optional[asyncio.Task]:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return None
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _maybe_expire(self) -> None:
        if self._on_expiry is not None and self._expired() and not any(
                getattr(t, "beast_expiry", False) for t in self._tasks):
            task = self._spawn(self._on_expiry())
            if task is not None:
                task.beast_expiry = True  # type: ignore[attr-defined]

    async def _answer(self, session_id: str, seen: Dialog) -> Optional[Dialog]:
        manager = self._manager()
        info = await manager.get_session_info(session_id) if manager is not None else None
        if info is None or not self._enabled(seen):
            return None
        tool, command = summarize(seen)
        try:
            dialog = await deliver_answer(manager=manager, watcher=self._watcher(), info=info,
                                          fingerprint=seen.fingerprint, choice=Choice(plain=PLAIN_YES),
                                          source=SOURCE_BEAST)
        except AnswerRefused as exc:
            logger.info("beast_prompt_refused", session_id=session_id, reason=exc.reason, tool=tool or None)
            return None
        logger.info("beast_prompt_approved", session_id=session_id, tmux=info.tmux_session, kind=dialog.kind,
                    tool=tool or None, command=command or None, fingerprint=dialog.fingerprint[:12])
        self._on_answered(info, dialog)
        return dialog
