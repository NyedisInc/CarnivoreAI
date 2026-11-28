
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

STATE_FOLDER = "agy-state"

_CODES = {"working": "busy", "tool_use": "busy", "reviewing": "busy", "idle": "idle"}


def state_folder(state_dir: Path) -> Path:
    return Path(state_dir) / STATE_FOLDER


def read_state(state_dir: Path, pid: Optional[int]) -> Optional[Dict[str, Any]]:
    if pid is None:
        return None
    try:
        with open(state_folder(state_dir) / ("%d.json" % int(pid)), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def status_code(state: Optional[Dict[str, Any]]) -> Optional[str]:
    if not state:
        return None
    if state.get("tool_confirmation_pending"):
        return "waiting"
    code = _CODES.get(str(state.get("agent_state") or ""))
    if code == "idle" and _background_running(state):
        return "busy"
    return code


def _background_running(state: Dict[str, Any]) -> bool:
    tasks = state.get("task_count")
    if isinstance(tasks, int) and not isinstance(tasks, bool) and tasks > 0:
        return True
    subagents = state.get("subagents")
    return isinstance(subagents, list) and any(
        isinstance(s, dict) and s.get("status") == "running" for s in subagents
    )


TEAMWORK_PREFIX = "teamwork"


def teamwork_active(state: Optional[Dict[str, Any]]) -> Optional[bool]:
    if not state:
        return None
    subagents = state.get("subagents")
    return isinstance(subagents, list) and any(
        isinstance(s, dict) and str(s.get("name") or "").startswith(TEAMWORK_PREFIX) and s.get("status") == "running"
        for s in subagents
    )


def quota_exhausted(state: Optional[Dict[str, Any]]) -> bool:
    quota = (state or {}).get("quota")
    if not isinstance(quota, dict):
        return False
    for bucket in quota.values():
        if not isinstance(bucket, dict):
            continue
        if bucket.get("disabled") or bucket.get("remaining_fraction") == 0 or bucket.get("remaining_amount") == 0:
            return True
    return False


def prune(state_dir: Path, live_pids: set) -> int:
    removed = 0
    try:
        entries = list(os.scandir(state_folder(state_dir)))
    except OSError:
        return 0
    for entry in entries:
        stem = entry.name[:-5] if entry.name.endswith(".json") else ""
        if stem.isdigit() and int(stem) not in live_pids:
            try:
                os.unlink(entry.path)
                removed += 1
            except OSError:
                pass
    return removed


_CONV_CACHE_LOCK = threading.Lock()
_CONV_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Dict[str, Any]]]] = {}


def _conversation_index(folder: Path) -> Dict[str, Dict[str, Any]]:
    try:
        entries = [e for e in os.scandir(folder) if e.name.endswith(".json")]
    except OSError:
        return {}
    fp_items = []
    for e in entries:
        try:
            st = e.stat()
            fp_items.append((e.name, st.st_ino, st.st_size, st.st_mtime_ns))
        except OSError:
            continue
    fp_items.sort()
    fp = tuple(fp_items)
    key = os.fspath(folder)
    with _CONV_CACHE_LOCK:
        cached = _CONV_CACHE.get(key)
        if cached is not None and cached[0] == fp:
            return cached[1]
    by_conv: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        try:
            with open(e.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        cid = data.get("conversation_id")
        if not isinstance(cid, str) or not cid:
            continue
        prev = by_conv.get(cid)
        if prev is None or (data.get("written_at") or 0) > (prev.get("written_at") or 0):
            by_conv[cid] = data
    with _CONV_CACHE_LOCK:
        if len(_CONV_CACHE) > 16:
            _CONV_CACHE.clear()
        _CONV_CACHE[key] = (fp, by_conv)
    return by_conv


def state_for_conversation(state_dir: Path, conversation_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not conversation_id:
        return None
    found = _conversation_index(state_folder(state_dir)).get(conversation_id)
    return dict(found) if found is not None else None
