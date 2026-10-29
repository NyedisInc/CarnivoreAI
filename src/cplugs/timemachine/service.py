
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from src.cplugs.timemachine import checks
from src.cplugs.timemachine import constants as K

_LOCK = threading.Lock()
_misses = 0
_may_be_open = True

_RECHECK = {"id": "recheck", "label_key": "app_alert.action.recheck", "method": "POST", "route": "/cplugs/timemachine/check"}
_OPEN_PRIVACY = {"id": "open_privacy", "label_key": "app_alert.action.open_privacy", "method": "POST",
                 "route": "/alerts/open-system-settings", "body": {"pane": "full_disk_access"}}


def reset() -> None:
    global _misses, _may_be_open
    _misses, _may_be_open = 0, True


def _raise_unknown(alert: Any, reason: str) -> None:
    explainer = {"id": "check_access", "label_key": K.ACTION_CHECK_ACCESS, "explain_key": K.EXPLAIN_BY_REASON[reason],
                 "actions": [_OPEN_PRIVACY, _RECHECK]}
    alert(K.ALERT_KEY, "warn", K.TITLE_UNKNOWN, {"reason": reason}, detail_key=K.DETAIL_UNKNOWN_BY_REASON[reason], actions=[explainer, _RECHECK])


def run_pass(ctx: Any, now: Optional[float] = None) -> Dict[str, str]:
    global _misses, _may_be_open
    with _LOCK:
        verdict = checks.check_time_machine(time.time() if now is None else now)
        out = {"state": "none" if verdict is None else verdict.state}
        if verdict is not None and "reason" in verdict.params:
            out["reason"] = verdict.params["reason"]
        alert, resolve = getattr(ctx, "alert", None), getattr(ctx, "alert_resolve", None)
        if alert is None or resolve is None:
            return {**out, "outcome": "not_granted"}
        if not ctx.enabled_now():
            return {**out, "outcome": "off"}
        if verdict is not None and verdict.state == checks.FIRING:
            _misses, _may_be_open = 0, True
            alert(K.ALERT_KEY, "warn", K.TITLE_STALE, verdict.params, detail_key=K.DETAIL_STALE, actions=[_RECHECK])
            return {**out, "outcome": "raised"}
        if verdict is not None and verdict.state == checks.UNKNOWN:
            _misses += 1
            if _misses < K.TM_UNKNOWN_PASSES_TO_ALERT:
                return {**out, "outcome": "kept"}
            _may_be_open = True
            _raise_unknown(alert, verdict.params["reason"])
            return {**out, "outcome": "raised"}
        _misses = 0
        if verdict is not None and verdict.state == checks.BUSY:
            return {**out, "outcome": "kept"}
        if not _may_be_open:
            return {**out, "outcome": "quiet"}
        resolve(K.ALERT_KEY)
        _may_be_open = False
        return {**out, "outcome": "resolved"}
