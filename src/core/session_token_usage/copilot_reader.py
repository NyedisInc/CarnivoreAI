
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from src.core.copilot.store import copilot_home, events_path, iter_events
from src.models.session_token_usage import SessionTokenUsage

FAMILY_COPILOT = "copilot"


def _int(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


_SUMS_LOCK = threading.Lock()
_SUMS_CACHE: Dict[str, Tuple[Tuple[int, int, int], Dict[str, int], Optional[dict]]] = {}
_SUMS_CACHE_MAX = 64


def _sums_for(path: Any) -> Tuple[Dict[str, int], Optional[dict]]:
    key = os.fspath(path)
    try:
        st = os.stat(key)
        fp: Optional[Tuple[int, int, int]] = (st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        fp = None
    if fp is not None:
        with _SUMS_LOCK:
            hit = _SUMS_CACHE.get(key)
        if hit is not None and hit[0] == fp:
            return hit[1], hit[2]
    sums = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0}
    last: Optional[dict] = None
    for data in iter_events(path, ("session.usage_record",)):
        usage = data.get("usage")
        if not isinstance(usage, dict):
            continue
        for k in sums:
            sums[k] += _int(usage.get(k)) or 0
        last = usage
    if fp is not None:
        with _SUMS_LOCK:
            if len(_SUMS_CACHE) >= _SUMS_CACHE_MAX:
                _SUMS_CACHE.clear()
            _SUMS_CACHE[key] = (fp, sums, last)
    return sums, last


def read_copilot_usage(conversation_uuid: Optional[str]) -> Optional[SessionTokenUsage]:
    path = events_path(conversation_uuid, copilot_home())
    if path is None:
        return None
    sums, last = _sums_for(path)
    if last is None:
        return None
    used, size = _int(last.get("inputTokens")), _int(last.get("maxPromptTokens")) or None
    name = last.get("modelDisplayName")
    return SessionTokenUsage(
        state="ok", family=FAMILY_COPILOT, model=last.get("model") or None,
        model_display_name=name.strip() if isinstance(name, str) and name.strip() else None,
        input_tokens=sums["inputTokens"], output_tokens=sums["outputTokens"],
        cache_read_input_tokens=sums["cacheReadTokens"], cache_creation_input_tokens=sums["cacheWriteTokens"],
        total_tokens=sums["inputTokens"] + sums["outputTokens"],
        context_used_tokens=used, context_window_tokens=size,
        context_remaining_pct=round(max(0.0, 100.0 * (1 - used / size)), 1) if used is not None and size else None,
        as_of=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )
