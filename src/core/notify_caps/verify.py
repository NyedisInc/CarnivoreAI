
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from src.core.approvals.dialog_gate import CLEAR, dialog_verdict
from src.core.native_push.wiring import store_for
from src.core.notify_caps import effects
from src.core.notify_caps.store import CapRecord, CapStore

Result = Tuple[int, Dict[str, Any]]
NOT_FOUND: Result = (404, {"error": "not_found"})
GONE: Result = (409, {"error": "already_answered", "where": "elsewhere"})


def verify(store: CapStore, app_state: Any, cap: Optional[str], now: Optional[float] = None) -> Tuple[Optional[CapRecord], Optional[Result]]:
    record = store.find(cap)
    if record is None:
        return None, NOT_FOUND
    if not any(row["id"] == record.device_row_id for row in store_for(app_state).list()):
        return None, NOT_FOUND
    if (time.time() if now is None else now) >= record.expires:
        return None, (410, {"error": "expired"})
    if record.retired_at is not None and record.used_at is None:
        return None, GONE
    return record, None


async def ask_is_open(app_state: Any, record: CapRecord) -> Optional[Result]:
    session_id = str(record.target.get("session", ""))
    if record.target.get("type") != "dialog" or effects.is_remote(session_id):
        return None
    verdict = await dialog_verdict(app_state, session_id)
    return GONE if verdict == CLEAR else None
