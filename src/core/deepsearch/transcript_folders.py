
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from src.core.pipeline import reader

_CWD = re.compile(rb'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
TAIL_SCAN_MAX: int = 8 << 20
READ_SECONDS: float = 3.0
GATE_KEY_PREFIX: str = "peer-gate:"
MEMO_MAX: int = 50_000

_memo: Dict[Tuple[str, int, int, int, int, int], Tuple[str, ...]] = {}


def _values(line: bytes) -> Set[str]:
    found: Set[str] = set()
    for match in _CWD.finditer(line):
        text = match.group(1)
        if not text:
            continue
        try:
            value = json.loads(b'"' + text + b'"')
        except ValueError:
            value = text.decode("utf-8", "replace")
        if value:
            found.add(value)
    return found


def _own(record: Any) -> Set[str]:
    found: Set[str] = set()
    if isinstance(record, dict):
        for holder in (record, record.get("payload")):
            if isinstance(holder, dict) and isinstance(holder.get("cwd"), str) and holder["cwd"]:
                found.add(holder["cwd"])
    return found


def folders_in(data: bytes) -> Set[str]:
    found: Set[str] = set()
    for raw in data.split(b"\n"):
        if b'"cwd"' not in raw:
            continue
        values = _values(raw)
        if all(v.startswith("/") for v in values):
            found |= values
            continue
        try:
            found |= _own(json.loads(raw))
        except ValueError:
            found |= values
    return found


def folders_in_lines(lines: Iterable[bytes]) -> Set[str]:
    found: Set[str] = set()
    for raw in lines:
        if b'"cwd"' in raw:
            found |= folders_in(raw)
    return found


def _scan_range(path: str, start: int, end: int) -> Tuple[str, ...]:
    with open(path, "rb") as handle:
        handle.seek(start)
        return tuple(sorted(folders_in(handle.read(end - start))))


def tail_folders(path: str, covered_to: int) -> Optional[Tuple[str, ...]]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size < covered_to:
        return None
    if st.st_size == covered_to:
        return ()
    if st.st_size - covered_to > TAIL_SCAN_MAX:
        return None
    key = (path, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, covered_to)
    hit = _memo.get(key)
    if hit is not None:
        return hit
    try:
        found = reader.timed(_scan_range, path, covered_to, st.st_size, timeout=READ_SECONDS, key=GATE_KEY_PREFIX + path)
    except (OSError, reader.ReadTimeout):
        return None
    if len(_memo) >= MEMO_MAX:
        _memo.clear()
    _memo[key] = found
    return found
