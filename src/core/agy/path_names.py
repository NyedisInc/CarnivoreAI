
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.terminal_paths.resolve import Resolved, split_line

MAX_READ_BYTES = 8 * 1024 * 1024

_cache: Dict[str, Tuple[Tuple[int, int], List[str]]] = {}


def _arg_paths(record: object) -> List[str]:
    out: List[str] = []
    calls = record.get("tool_calls") if isinstance(record, dict) else None
    for call in calls if isinstance(calls, list) else []:
        args = call.get("args") if isinstance(call, dict) else None
        for value in (args or {}).values() if isinstance(args, dict) else []:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            if isinstance(value, str) and value.startswith("/") and "\n" not in value and len(value) < 4096:
                out.append(os.path.normpath(value))
    return out


def named_paths(transcript: Path) -> List[str]:
    try:
        stat = transcript.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        hit = _cache.get(str(transcript))
        if hit and hit[0] == key:
            return hit[1]
        with open(transcript, "rb") as handle:
            if stat.st_size > MAX_READ_BYTES:
                handle.seek(stat.st_size - MAX_READ_BYTES)
                handle.readline()
            lines = handle.read().splitlines()
    except OSError:
        return []
    seen: Dict[str, None] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        for path in _arg_paths(record):
            seen[path] = None
    paths = list(seen)
    _cache[str(transcript)] = (key, paths)
    return paths


def resolve_bare(text: str, transcript: Optional[Path]) -> Optional[Resolved]:
    name, line = split_line(text.strip())
    if transcript is None or not name or "/" in name or name in (".", ".."):
        return None
    matches = [p for p in named_paths(transcript) if os.path.basename(p) == name and os.path.isfile(p)]
    return Resolved(matches[0], "file", line) if len(matches) == 1 else None
