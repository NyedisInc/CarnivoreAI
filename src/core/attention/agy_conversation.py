
from __future__ import annotations

import os
import re
from typing import Dict, Mapping, Optional, Tuple

from src.core.attention.output_holders import open_file_path
from src.core.attention.parent_map import descendants

_SENT = re.compile(r"Forwarding user message to conversation ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_TAIL_BYTES = 262144
_PROGRAM = "agy"

_CACHE: Dict[str, Tuple[Tuple[int, int], Optional[str]]] = {}


def agy_pid_under(pane_pid: Optional[int], parents: Mapping[int, int], commands: Mapping[int, str]) -> Optional[int]:
    if pane_pid is None:
        return None
    root = int(pane_pid)
    for pid in (root, *descendants(root, parents)):
        words = (commands.get(pid) or "").split(None, 1)
        if words and os.path.basename(words[0]) == _PROGRAM:
            return pid
    return None


def conversation_in_log(log_path: str) -> Optional[str]:
    try:
        stat = os.stat(log_path)
        key = (stat.st_mtime_ns, stat.st_size)
        hit = _CACHE.get(log_path)
        if hit is not None and hit[0] == key:
            return hit[1]
        with open(log_path, "rb") as handle:
            handle.seek(max(0, stat.st_size - _TAIL_BYTES))
            found = _SENT.findall(handle.read().decode("utf-8", "replace"))
    except OSError:
        return None
    uuid = found[-1] if found else None
    home = os.path.dirname(os.path.dirname(log_path))
    if uuid is not None and not os.path.isfile(os.path.join(home, "conversations", f"{uuid}.db")):
        uuid = None
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[log_path] = (key, uuid)
    return uuid


def conversation_for_pane(pane_pid: Optional[int], parents: Mapping[int, int], commands: Mapping[int, str]) -> Optional[str]:
    pid = agy_pid_under(pane_pid, parents, commands)
    log = open_file_path(pid, 1) if pid is not None else None
    if not log or os.path.basename(os.path.dirname(log)) != "log":
        return None
    return conversation_in_log(log)
