
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict

from src.core.deepsearch import constants as K
from src.core.deepsearch import index_scope
from src.core.db_ddl import search_index as ddl
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.cache import flip
from src.core.deepsearch.live import catchup

STATE_RUNNING: str = "running"
STATE_STALLED: str = "stalled"
REASON_FTS_UNAVAILABLE: str = "fts_unavailable"


def index_status(state_dir: Path) -> Dict[str, Any]:
    from src.core.db import connect, db_path_for
    from src.core.transcript_manifest import constants as TM
    from src.core.transcript_source import scope as scope_mod

    state, reason = STATE_RUNNING, None
    if not ddl.fts_supported():
        state, reason = STATE_STALLED, REASON_FTS_UNAVAILABLE
    scope = index_scope.current()
    kinds = {TM.KIND_CONVERSATION} | ({TM.KIND_SUBAGENT} if scope_mod.includes_subagents(scope) else set())
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        cache_db.attach_cache(conn, state_dir)
        newest, conversations = conn.execute(
            f"SELECT MAX(indexed_at), COUNT(DISTINCT conversation_id) FROM {K.CACHE_LIVE_REF} WHERE rows > 0").fetchone()
        coverage = catchup.coverage(conn, kinds)
        backup_files, backup_conversations = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT conversation_id) FROM {K.CACHE_LIVE_REF} WHERE base_point_id = ?",
            (K.VAULT_MARK,)).fetchone()
    coverage["from_backup"] = {"files": int(backup_files), "conversations": int(backup_conversations)}
    if not scope_mod.includes_subagents(scope):
        coverage[K.FILE_SUBAGENT] = {"files": None, "indexed": None}
    return {"state": state, "reason": reason, "newest_indexed_at": newest, "conversations": int(conversations),
            "scope": scope, "coverage": coverage, "cache": flip.info(state_dir)}
