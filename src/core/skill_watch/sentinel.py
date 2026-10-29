
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.skill_watch.store import DriftRecord, SkillWatchStore
from src.core.skill_watch.measure import TooLarge, measure_bounded
from src.core.skills.digest import DigestEntry, digest_entries

logger = structlog.get_logger(__name__)

STATE_CLEAN = "clean"
STATE_DRIFTED = "drifted"
STATE_MISSING = "missing"
STATE_UNKNOWN = "unknown"

TTL_SECONDS = 300.0
MAX_ROWS_PER_PASS = 25
MAX_CHANGED_FILES = 50


@dataclass(frozen=True)
class Drift:

    state: str
    changed_files: Optional[List[str]] = None
    checked_at: Optional[float] = None


UNCHECKED = Drift(STATE_UNKNOWN)


def measure_folder(folder: Path) -> Tuple[str, Tuple[DigestEntry, ...], Tuple[str, ...]]:
    entries, anomalies = measure_bounded(str(folder))
    return digest_entries(entries), entries, anomalies


def diff_entries(baseline: Dict[str, Tuple[str, str]],
                 entries: Sequence[DigestEntry]) -> List[str]:
    now = {e.relpath: (e.mode, e.sha256) for e in entries}
    changed = {p for p in set(baseline) | set(now) if baseline.get(p) != now.get(p)}
    return sorted(changed)[:MAX_CHANGED_FILES]


def check_row(store: SkillWatchStore, install_id: str, recorded_digest: str,
              target_paths: Sequence[str], now: Optional[float] = None) -> Drift:
    stamp = time.time() if now is None else now
    state, changed = STATE_UNKNOWN, None
    try:
        folders = [Path(p) for p in target_paths]
        if not folders:
            pass
        elif any(not os.path.lexists(f) for f in folders):
            state = STATE_MISSING
        elif not all(f.is_dir() and not f.is_symlink() for f in folders):
            state = STATE_UNKNOWN
        else:
            state, changed = _compare(store, install_id, recorded_digest, folders)
    except OSError as exc:
        logger.warning("skill_sentinel_unreadable", install_id=install_id, error_type=type(exc).__name__)
        state, changed = STATE_UNKNOWN, None
    try:
        store.save_drift(DriftRecord(install_id, stamp, recorded_digest, state, changed))
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill_sentinel_store_failed", error_type=type(exc).__name__)
    return Drift(state, changed, stamp)


def _compare(store: SkillWatchStore, install_id: str, recorded: str,
             folders: Sequence[Path]) -> Tuple[str, Optional[List[str]]]:
    changed: set = set()
    measured = True
    drifted = False
    for folder in folders:
        try:
            digest, entries, anomalies = measure_folder(folder)
        except TooLarge:
            return STATE_UNKNOWN, None
        if digest == recorded and not anomalies:
            store.save_baseline(install_id, recorded, [(e.relpath, e.mode, e.sha256) for e in entries])
            continue
        drifted = True
        changed.update(anomalies)
        if digest == recorded:
            continue
        baseline = store.baseline(install_id, recorded)
        if baseline is None:
            measured = False
        else:
            changed.update(diff_entries(baseline, entries))
    if not drifted:
        return STATE_CLEAN, None
    listed = sorted(changed)[:MAX_CHANGED_FILES]
    return STATE_DRIFTED, (listed if (measured or changed) else None)


_flight: Dict[str, threading.Lock] = {}
_flight_guard = threading.Lock()
PASS_SECONDS = 4.0


def _lock_for(install_id: str) -> threading.Lock:
    with _flight_guard:
        return _flight.setdefault(install_id, threading.Lock())


def refresh(store: SkillWatchStore, rows: Sequence[Tuple[str, str, Sequence[str]]],
            now: Optional[float] = None, *, force: bool = False) -> Dict[str, Drift]:
    stamp = time.time() if now is None else now
    out: Dict[str, Drift] = {}
    budget = MAX_ROWS_PER_PASS
    deadline = time.monotonic() + PASS_SECONDS
    for install_id, digest, targets in rows:
        kept = store.drift(install_id)
        fresh = not force and kept is not None and kept.row_digest == digest and stamp - kept.checked_at < TTL_SECONDS
        lock = _lock_for(install_id)
        if not fresh and budget > 0 and time.monotonic() < deadline and lock.acquire(blocking=False):
            try:
                budget -= 1
                out[install_id] = check_row(store, install_id, digest, targets, stamp)
            finally:
                lock.release()
        elif kept is not None and kept.row_digest == digest:
            out[install_id] = Drift(kept.state, kept.changed_files, kept.checked_at)
        else:
            out[install_id] = UNCHECKED
    return out
