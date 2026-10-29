
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import structlog

from src.core.skill_fires.parse import (
    HARNESS_CLAUDE, HARNESS_CODEX, Fire, parse_line,
)
from src.core.skill_fires.store import Cursor, SkillFireStore

logger = structlog.get_logger(__name__)

PASS_BYTES: int = 16 * 1024 * 1024
MAX_LINE: int = 4 * 1024 * 1024
HEAD_BYTES: int = 256

STATE_OK = "ok"
STATE_PARTIAL = "partial"
STATE_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ScanResult:

    state: str
    bytes_read: int = 0
    fires_seen: int = 0


def _read_lines(handle, start: int, budget: int) -> Tuple[List[Tuple[int, bytes]], int, int]:
    lines: List[Tuple[int, bytes]] = []
    offset = start
    consumed = 0
    handle.seek(start)
    while consumed < budget:
        line = handle.readline(MAX_LINE + 1)
        if not line:
            break
        if not line.endswith(b"\n"):
            if len(line) <= MAX_LINE:
                break
            skipped = len(line)
            while True:
                rest = handle.readline(MAX_LINE)
                skipped += len(rest)
                if not rest or rest.endswith(b"\n"):
                    break
            if not rest:
                break
            offset += skipped
            consumed += skipped
            continue
        lines.append((offset, line))
        offset += len(line)
        consumed += len(line)
    return lines, offset, consumed


def scan_file(store: SkillFireStore, path: str, harness: str, profile: str,
              *, budget: int = PASS_BYTES) -> ScanResult:
    try:
        path = os.path.realpath(path)
        size = os.stat(path).st_size
        cursor = store.cursor_for(path)
        if cursor is not None and size == cursor.size and cursor.offset >= size:
            return ScanResult(STATE_OK)
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            reset = cursor is None or size < cursor.size or not head.startswith(cursor.head)
            start = 0 if reset else cursor.offset
            if not reset and cursor.offset >= size:
                return ScanResult(STATE_OK)
            lines, end, consumed = _read_lines(handle, start, budget)
        fires: List[Tuple[int, Fire]] = []
        for offset, line in lines:
            fires.extend((offset, fire) for fire in parse_line(harness, line))
        session_key = Path(path).stem
        store.apply(path, harness=harness, profile=profile, session_key=session_key,
                    cursor=Cursor(size, head, end), fires=fires, reset=reset)
    except (OSError, ValueError) as exc:
        logger.debug("skill_fire_scan_unreadable", error_type=type(exc).__name__)
        return ScanResult(STATE_UNREADABLE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill_fire_scan_failed", error_type=type(exc).__name__)
        return ScanResult(STATE_UNREADABLE)
    return ScanResult(STATE_PARTIAL if consumed >= budget else STATE_OK, consumed, len(fires))


def transcript_roots(home: Path) -> List[Tuple[str, str, Path]]:
    roots: List[Tuple[str, str, Path]] = [(HARNESS_CLAUDE, "default", home / ".claude" / "projects")]
    accounts = home / ".carnivore" / "accounts"
    try:
        for entry in sorted(os.scandir(accounts), key=lambda e: e.name):
            if entry.is_dir(follow_symlinks=False):
                roots.append((HARNESS_CLAUDE, entry.name, Path(entry.path) / "projects"))
    except OSError:
        pass
    roots.append((HARNESS_CODEX, "default", home / ".codex" / "sessions"))
    seen: set = set()
    out: List[Tuple[str, str, Path]] = []
    for root in roots:
        real = os.path.realpath(root[2])
        if root[2].is_dir() and real not in seen:
            seen.add(real)
            out.append(root)
    return out


def profile_for_path(path: str, home: Path) -> str:
    prefix = str(home / ".carnivore" / "accounts") + os.sep
    if path.startswith(prefix):
        return path[len(prefix):].split(os.sep, 1)[0]
    return "default"


def sweep(store: SkillFireStore, roots: Sequence[Tuple[str, str, Path]],
          *, budget: int = PASS_BYTES) -> Tuple[int, bool]:
    touched = 0
    left = budget
    for harness, profile, root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "subagents"]
            for name in filenames:
                if not name.endswith(".jsonl"):
                    continue
                if left <= 0:
                    return touched, False
                result = scan_file(store, os.path.join(dirpath, name), harness, profile, budget=left)
                left -= result.bytes_read
                touched += 1
                if result.state == STATE_PARTIAL:
                    return touched, False
    return touched, True
