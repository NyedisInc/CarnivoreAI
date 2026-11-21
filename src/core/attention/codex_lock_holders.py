
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import OrderedDict
from typing import Dict, FrozenSet, Iterable, Optional, Set, Tuple

import structlog

from src.core.attention import output_holders

logger = structlog.get_logger(__name__)

LOCK_DIR_NAME: str = "thread-writer-locks"
LOCK_SUFFIX: str = ".lock"
LSOF_TIMEOUT_SECONDS: float = 1.0
SCAN_BUDGET_SECONDS: float = LSOF_TIMEOUT_SECONDS
LSOF_OUTPUT_CAP_BYTES: int = 1024 * 1024
MAX_SCANNED_DESCRIPTORS: int = 10_000
MAX_HINTS: int = 256

Identity = Tuple[int, int]

_hints: "OrderedDict[Identity, FrozenSet[int]]" = OrderedDict()
_hints_lock = threading.Lock()


def lock_dir_prefixes(codex_home: str) -> Tuple[str, ...]:
    lock_dir = os.path.join(codex_home, LOCK_DIR_NAME)
    return tuple(dict.fromkeys((lock_dir + os.sep, os.path.realpath(lock_dir) + os.sep)))


def lock_uuid(path: str, prefixes: Iterable[str]) -> Optional[str]:
    if not path.endswith(LOCK_SUFFIX):
        return None
    for prefix in prefixes:
        if path.startswith(prefix):
            uuid = path[len(prefix):-len(LOCK_SUFFIX)]
            return uuid if uuid and os.sep not in uuid else None
    return None


def owned_lock_uuids(codex_home: str, pids: Set[int]) -> Set[str]:
    if not pids:
        return set()
    prefixes = lock_dir_prefixes(codex_home)
    if not output_holders.libproc_available():
        return _owned_via_lsof(prefixes, pids)
    owned: Set[str] = set()
    holders: Dict[Identity, Set[int]] = {}
    scanned = 0
    deadline = time.monotonic() + SCAN_BUDGET_SECONDS
    for pid in sorted(pids):
        try:
            entries = output_holders.open_vnode_paths(
                pid, max_entries=MAX_SCANNED_DESCRIPTORS - scanned, deadline=deadline,
            )
        except output_holders.ScanLimitReached as exc:
            logger.debug("codex_lock_scan_over_limit", pids=len(pids), scanned=scanned, reason=str(exc))
            return set()
        if entries is None:
            continue
        scanned += len(entries)
        for identity, path in entries:
            uuid = lock_uuid(path, prefixes)
            if uuid is not None:
                owned.add(uuid)
                holders.setdefault(identity, set()).add(pid)
    _remember(holders)
    return owned


def hinted_holder_live(lock_path: str) -> bool:
    if not output_holders.libproc_available():
        return False
    identity = output_holders.vnode_identity(lock_path)
    if identity is None:
        return False
    with _hints_lock:
        pids = _hints.get(identity)
    if not pids:
        return False
    still = output_holders.holders_among(identity, pids)
    if still != pids:
        _forget(identity, pids, still)
    return bool(still)


def _remember(holders: Dict[Identity, Set[int]]) -> None:
    if not holders:
        return
    with _hints_lock:
        for identity, pids in holders.items():
            _hints[identity] = frozenset(pids)
            _hints.move_to_end(identity)
        while len(_hints) > MAX_HINTS:
            _hints.popitem(last=False)


def _forget(identity: Identity, checked: FrozenSet[int], still: Set[int]) -> None:
    with _hints_lock:
        if _hints.get(identity) != checked:
            return
        if still:
            _hints[identity] = frozenset(still)
        else:
            del _hints[identity]


def _owned_via_lsof(prefixes: Tuple[str, ...], pids: Set[int]) -> Set[str]:
    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", ",".join(str(pid) for pid in sorted(pids)), "-Fn"],
            capture_output=True, text=True, timeout=LSOF_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("codex_lock_lsof_failed", error=str(exc))
        return set()
    if len(result.stdout) > LSOF_OUTPUT_CAP_BYTES:
        return set()
    owned: Set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            uuid = lock_uuid(line[1:], prefixes)
            if uuid is not None:
                owned.add(uuid)
    return owned


__all__ = [
    "LOCK_DIR_NAME", "LOCK_SUFFIX", "MAX_SCANNED_DESCRIPTORS", "MAX_HINTS", "SCAN_BUDGET_SECONDS",
    "hinted_holder_live", "lock_dir_prefixes", "lock_uuid", "owned_lock_uuids",
]
