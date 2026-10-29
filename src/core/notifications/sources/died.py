
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

import structlog

from src.core import session_change_notice
from src.core.attention.evidence import REASON_PANE_DEAD
from src.core.notifications import contracts
from src.core.notifications.sources import common

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
        self._emit(contracts.NotifyEvent(
            type_id=TYPE_ID, kind=FRAME_TYPE, title=common.type_title(TYPE_ID), ts=stamp,
            severity=contracts.SEVERITY_ERROR, instance_key=f"died:{target.key}:{stamp:.0f}", **fields,
        ))
        session_change_notice.publish(self._app_state, {
            "type": FRAME_TYPE, "session_id": target.session_id, "session_name": name,
        })
        logger.info("session_died_notified", session_id=target.session_id)
