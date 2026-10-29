
from __future__ import annotations

import threading
from typing import Dict, List, Tuple

import structlog

from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

_open: Dict[int, Dict[int, object]] = {}
_lock = threading.Lock()


def remember(item_id: int, message_id: int, ref: object) -> None:
    with _lock:
        _open.setdefault(item_id, {})[message_id] = ref


def dismiss(ctx: CplugContext, item_id: int) -> int:
    with _lock:
        refs: List[Tuple[int, object]] = list(_open.pop(item_id, {}).items())
    if not refs:
        return 0
    try:
        dismiss_toast = ctx.toast_dismiss
    except AttributeError as exc:
        logger.warning("task_manager_question_toast_dismiss_unavailable", item=item_id, error=str(exc))
        return 0
    cleared = sum(1 for _, ref in refs if dismiss_toast(ref))
    logger.info("task_manager_question_toasts_dismissed", item=item_id, cleared=cleared)
    return cleared


def forget_all() -> None:
    with _lock:
        _open.clear()
