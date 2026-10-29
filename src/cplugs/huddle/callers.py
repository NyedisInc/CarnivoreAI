
from __future__ import annotations

import time
from contextlib import closing
from typing import List, Optional, Sequence, Tuple

from src.cplugs.huddle.rules import ALL_LIST
from src.cplugs.sdk import CplugStorage


REASON_LAST_CALLER = "last_task_manager_caller"
REASON_ONLY_SESSION = "only_session"
REASON_PICK = "pick"

Caller = Tuple[str, str, float]
Candidate = Tuple[str, str]


def note_caller(storage: CplugStorage, key: str, list_key: str, at: Optional[float] = None,
                legacy_id: Optional[str] = None) -> None:
    with closing(storage.connect(True)) as conn, conn:
        if legacy_id and legacy_id != key:
            conn.execute("UPDATE OR IGNORE work_callers SET session_id = ? WHERE session_id = ?", (key, legacy_id))
            conn.execute("DELETE FROM work_callers WHERE session_id = ?", (legacy_id,))
        conn.execute("INSERT OR REPLACE INTO work_callers VALUES (?, ?, ?)",
                     (key, list_key, time.time() if at is None else at))


def recent_callers(storage: CplugStorage) -> List[Caller]:
    with closing(storage.connect(False)) as conn:
        rows = conn.execute("SELECT session_id, list_key, at FROM work_callers ORDER BY at DESC").fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def pick_default(candidates: Sequence[Candidate], list_key: str, callers: Sequence[Caller]) -> Tuple[Optional[str], str]:
    live = {}
    for ses_id, key in candidates:
        live[key] = ses_id
        live[ses_id] = ses_id
    for name, key, _at in callers:
        if name in live and (list_key == ALL_LIST or key == list_key):
            return live[name], REASON_LAST_CALLER
    if list_key != ALL_LIST and len(candidates) == 1:
        return candidates[0][0], REASON_ONLY_SESSION
    return None, REASON_PICK
