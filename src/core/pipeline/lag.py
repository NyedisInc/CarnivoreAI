
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db
from src.core.transcript_manifest import constants as TM

CACHE_SECONDS: float = 30.0

_lock = threading.Lock()
_cache: Dict[Tuple[str, str, str], Tuple[float, "Lag"]] = {}


@dataclass(frozen=True)
class Lag:

    files_tracked: int
    lag_bytes: int
    behind_conversations: int


def _cursor_offsets(state_dir: Path, plugin: C.Plugin) -> Dict[str, int]:
    """{file path: consumed offset} from the plugin's database, {} when it does not exist yet. Raises: sqlite3.Error."""
    path = plugin_db.db_path(state_dir, plugin)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)) as conn:
        present = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                               (C.CURSORS_TABLE,)).fetchone()
        if not present:
            return {}
        return {p: int(o or 0) for p, o in conn.execute(f'SELECT path, "offset" FROM {C.CURSORS_TABLE}')}


def compute(state_dir: Path, db_path: Path, plugin: C.Plugin) -> Lag:
    from src.core.db import connect

    offsets = _cursor_offsets(Path(state_dir), plugin)
    behind: Dict[str, int] = {}
    with closing(connect(Path(db_path), create=False)) as conn:
        rows = conn.execute(
            f"SELECT path, conversation_id, family, kind, dataless, gone_at, complete_bytes FROM {TM.TABLE} "
            "WHERE conversation_id IS NOT NULL AND conversation_id != ''")
        for path, conv, family, kind, dataless, gone_at, complete in rows:
            if gone_at is not None or dataless or kind not in (TM.KIND_CONVERSATION, TM.KIND_SUBAGENT):
                continue
            if not plugin.reads(family, kind):
                continue
            gap = int(complete or 0) - offsets.get(path, 0)
            if gap > 0:
                behind[conv] = behind.get(conv, 0) + gap
    return Lag(files_tracked=len(offsets), lag_bytes=sum(behind.values()), behind_conversations=len(behind))


def lag_of(state_dir: Path, db_path: Path, plugin: C.Plugin, *, now: Optional[float] = None) -> Lag:
    key = (str(state_dir), str(db_path), plugin.id)
    moment = time.monotonic() if now is None else now
    with _lock:
        hit = _cache.get(key)
    if hit is not None and moment - hit[0] < CACHE_SECONDS:
        return hit[1]
    found = compute(state_dir, db_path, plugin)
    with _lock:
        _cache[key] = (moment, found)
    return found


def forget(state_dir: Optional[Path] = None) -> None:
    """Drop the cached lag of one state directory (all when None), so the next read measures afresh. Output: None."""
    with _lock:
        for key in [k for k in _cache if state_dir is None or k[0] == str(state_dir)]:
            del _cache[key]
