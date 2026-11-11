
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Set, Tuple

import structlog

from src.core import session_change_notice
from src.core.attention.evidence import REASON_PANE_DEAD
from src.core.notifications import contracts
from src.core.notifications.sources import common, died_capture

logger = structlog.get_logger(__name__)

TYPE_ID = "session.died"
FRAME_TYPE = "session.died"
DEAD_READS = 2


class DiedTracker:

    def __init__(self, manager: Any, app_state: Any,
                 emit: Callable[[contracts.NotifyEvent], None] = contracts.emit) -> None:
        self._manager = manager
        self._app_state = app_state
        self._emit = emit
        self._reads: Dict[str, Tuple[Any, int]] = {}
        self._fired: Dict[str, Any] = {}
        self._tasks: Set["asyncio.Task[None]"] = set()

    def observe(self, target: Any, observation: Any) -> bool:
        key, generation = target.key, target.generation
        if target.session_id not in self._manager._registry.sessions or observation.verdict.reason != REASON_PANE_DEAD:
            self._reads.pop(key, None)
            self._fired.pop(key, None)
            return False
        previous, count = self._reads.get(key, (generation, 0))
        count = count + 1 if previous == generation else 1
        self._reads[key] = (generation, count)
        if count < DEAD_READS or self._fired.get(key) == generation or not self._deliberate_free(target):
            return False
        self._fired[key] = generation
        self._publish(target)
        return True

    def _deliberate_free(self, target: Any) -> bool:
        backend = self._manager._registry.backends.get(target.session_id)
        return not (getattr(backend, "_attention_stopping", False) or getattr(backend, "_attention_restarting", False))

    def _publish(self, target: Any) -> None:
        stamp = common.now()
        fields = common.session_fields(self._manager, target.session_id)
        name = fields.get("session_ref") or fields.get("tmux_name") or target.session_id
        session_change_notice.publish(self._app_state, {
            "type": FRAME_TYPE, "session_id": target.session_id, "session_name": name,
        })
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._raise(target, stamp, fields, {})
        else:
            task = loop.create_task(self._capture_then_raise(target, stamp, fields))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        logger.info("session_died_notified", session_id=target.session_id)

    async def _capture_then_raise(self, target: Any, stamp: float, fields: Dict[str, Any]) -> None:
        hint: Dict[str, Any] = {}
        try:
            socket = self._manager.tmux_socket_name()
            hint = await died_capture.capture(socket, fields.get("tmux_name") or "")
        except (AttributeError, OSError, ValueError) as exc:
            logger.info("notify_died_capture_skipped", error_type=type(exc).__name__)
        self._raise(target, stamp, fields, hint)

    def _raise(self, target: Any, stamp: float, fields: Dict[str, Any], hint: Dict[str, Any]) -> None:
        self._emit(contracts.NotifyEvent(
            type_id=TYPE_ID, kind=FRAME_TYPE, title=common.type_title(TYPE_ID), ts=stamp,
            severity=contracts.SEVERITY_ERROR, instance_key=f"died:{target.key}:{stamp:.0f}",
            card_hint=hint or None, **fields,
        ))
