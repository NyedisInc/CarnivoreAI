
from __future__ import annotations

import glob
import os
import sqlite3
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")

MAX_ENTRIES = 512

_Sig = Optional[Tuple[int, int]]

_lock = threading.Lock()
_dir_matches: "OrderedDict[Tuple[str, str], Tuple[int, List[str]]]" = OrderedDict()
_rollouts: "OrderedDict[Tuple[str, str], Tuple[str, Tuple[Optional[int], ...]]]" = OrderedDict()
_db_answers: "OrderedDict[Hashable, Tuple[Tuple[_Sig, _Sig], object]]" = OrderedDict()


def clear() -> None:
    with _lock:
        _dir_matches.clear()
        _rollouts.clear()
        _db_answers.clear()


def _put(cache: "OrderedDict", key: Hashable, value: object) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > MAX_ENTRIES:
            cache.popitem(last=False)


def _get(cache: "OrderedDict", key: Hashable) -> Optional[Any]:
    with _lock:
        held = cache.get(key)
        if held is not None:
            cache.move_to_end(key)
        return held


def _drop(cache: "OrderedDict", key: Hashable) -> None:
    with _lock:
        cache.pop(key, None)


def _sig(path: str) -> _Sig:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def glob_in_dir(directory: str, pattern: str) -> List[str]:
    key = (directory, pattern)
    try:
        mtime = os.stat(directory).st_mtime_ns
    except OSError:
        _drop(_dir_matches, key)
        return []
    held = _get(_dir_matches, key)
    if held is not None and held[0] == mtime:
        return list(held[1])
    matches = glob.glob(os.path.join(directory, pattern))
    _put(_dir_matches, key, (mtime, matches))
    return list(matches)


_ROLLOUT_ANCESTORS = 4


def _rollout_sig(path: str) -> Tuple[Optional[int], ...]:
    sigs = []
    node = path
    for _ in range(_ROLLOUT_ANCESTORS + 1):
        try:
            sigs.append(os.stat(node).st_mtime_ns)
        except OSError:
            sigs.append(None)
        node = os.path.dirname(node)
    return tuple(sigs)


def remembered_rollout(codex_home: str, thread_uuid: str, walk: Callable[[], Optional[str]]) -> Optional[str]:
    key = (codex_home, thread_uuid)
    held = _get(_rollouts, key)
    if held is not None:
        if held[1] == _rollout_sig(held[0]) and held[1][0] is not None:
            return held[0]
        _drop(_rollouts, key)
    found = walk()
    if found is not None:
        _put(_rollouts, key, (found, _rollout_sig(found)))
    return found


def read_turn_row(
    connect: Callable[[str], Optional[sqlite3.Connection]], db_path: str, thread_uuid: str
) -> Tuple[Optional[Tuple[Optional[str], Optional[int]]], bool]:
    con = connect(db_path)
    if con is None:
        return None, False
    try:
        row = con.execute(
            "SELECT status FROM thread_turns WHERE thread_id = ? "
            "ORDER BY rollout_ordinal DESC LIMIT 1",
            (thread_uuid,),
        ).fetchone()
        if row is None:
            return None, True
        try:
            off = con.execute(
                "SELECT next_rollout_byte_offset FROM "
                "thread_history_projection_state WHERE thread_id = ?",
                (thread_uuid,),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("codex_offset_read_failed", error=str(exc))
            return (row[0], None), False
        return (row[0], off[0] if off is not None else None), True
    except sqlite3.Error as exc:
        logger.debug("codex_record_read_failed", error=str(exc))
        return None, False
    finally:
        con.close()


def remembered_turn_row(
    connect: Callable[[str], Optional[sqlite3.Connection]], db_path: str, thread_uuid: str
) -> Optional[Tuple[Optional[str], Optional[int]]]:
    return remembered_db_read(db_path, ("turn", thread_uuid), lambda: read_turn_row(connect, db_path, thread_uuid))


def remembered_db_read(
    db_path: str, key: Hashable, load: Callable[[], Tuple[T, bool]]
) -> T:
    full_key = (db_path, key)
    sig = (_sig(db_path), _sig("%s-wal" % db_path))
    if sig[0] is None:
        _drop(_db_answers, full_key)
        return load()[0]
    held = _get(_db_answers, full_key)
    if held is not None and held[0] == sig:
        return held[1]  # type: ignore[return-value]
    value, cacheable = load()
    if cacheable and (_sig(db_path), _sig("%s-wal" % db_path)) == sig:
        _put(_db_answers, full_key, (sig, value))
    return value
