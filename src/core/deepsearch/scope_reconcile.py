
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import structlog

from src.core.db import transaction
from src.core.deepsearch import constants as K
from src.core.deepsearch import index_scope
from src.core.deepsearch.byte_source import open_source
from src.core.deepsearch.live import store
from src.core.deepsearch.live.indexer import FileSpec, in_scope
from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db
from src.core.transcript_source import constants as TS
from src.core.transcript_source import scope as scope_mod
from src.core.transcript_source.dataless import is_dataless_file

logger = structlog.get_logger()

BATCH_FILES: int = 200
BATCH_ROWS: int = 5000


def settle(conn: sqlite3.Connection, *, sleep: Callable[[float], None] = time.sleep,
           clock: Callable[[], float] = time.monotonic) -> int:
    total = 0
    after = 0
    while True:
        scope = index_scope.read()
        if scope is None:
            logger.warning("deepsearch_scope_unreadable_settle_skipped")
            return total
        started = clock()
        batch = _batch(conn, scope, after)
        if batch is None:
            continue
        seen, settled, after = batch
        total += settled
        if seen == 0:
            break
        sleep(min(C.BULK_REST_MAX_SECONDS, C.BULK_REST_RATIO * (clock() - started)))
    if not scope_mod.includes_subagents(scope) and index_scope.read() == scope:
        with plugin_db.lock_for(index_scope.PLUGIN_ID), transaction(conn):
            conn.execute(f"DELETE FROM {C.CURSORS_TABLE} WHERE file_kind = ?", (K.FILE_SUBAGENT,))
    if total:
        logger.info("deepsearch_scope_settled", scope=scope, rows=total)
    return total


def _batch(conn: sqlite3.Connection, scope: str, after: int) -> Optional[Tuple[int, int, int]]:
    rows: List[store.LiveFile] = [store.LiveFile(*r) for r in conn.execute(
        f"SELECT {', '.join(store._COLUMNS)}, id FROM {K.LIVE_TABLE} WHERE scope IS NOT ? AND id > ? ORDER BY id LIMIT ?",
        (scope, after, BATCH_FILES))]
    if not rows:
        return 0, 0, after
    wanted: Dict[int, Optional[bool]] = {int(r.id): _wanted(scope, r) for r in rows}
    seen = settled = removed = 0
    last = after
    with plugin_db.lock_for(index_scope.PLUGIN_ID), transaction(conn):
        if index_scope.read() != scope:
            return None
        for row in rows:
            seen, last = seen + 1, int(row.id)
            verdict = wanted[last]
            live = conn.execute(f"SELECT id FROM {K.LIVE_TABLE} WHERE id = ? AND scope IS NOT ?", (row.id, scope)).fetchone()
            if live is not None and verdict is not None:
                _settle_row(conn, row, verdict, scope)
                settled += 1
                removed += max(1, int(row.rows or 0))
            if removed >= BATCH_ROWS:
                break
    return seen, settled, last


def _wanted(scope: str, row: store.LiveFile) -> Optional[bool]:
    spec = FileSpec(row.conversation_id, row.path, row.file_kind, row.family)
    if scope != scope_mod.SCOPE_HUMAN or row.file_kind == K.FILE_SUBAGENT:
        return in_scope(scope, spec)
    if row.base_point_id == K.VAULT_MARK:
        try:
            head = open_source(row.path, row.base_point_id, row.conversation_id, row.file_kind).read(0, TS.ENTRYPOINT_SCAN_BYTES)
        except OSError as exc:
            logger.warning("deepsearch_scope_vault_head_unreadable", conversation_id=row.conversation_id, error=str(exc)[:200])
            return None
        return in_scope(scope, spec, head)
    if is_dataless_file(Path(row.path)):
        return None
    return in_scope(scope, spec)


def _settle_row(conn: sqlite3.Connection, live: store.LiveFile, now_in: bool, scope: str) -> None:
    if bool(live.in_scope) == now_in:
        conn.execute(f"UPDATE {K.LIVE_TABLE} SET scope = ? WHERE id = ?", (scope, live.id))
        return
    store.delete_file(conn, int(live.id))
    if now_in:
        plugin_db.delete_cursor(conn, live.path)
        return
    if live.file_kind == K.FILE_SUBAGENT:
        plugin_db.delete_cursor(conn, live.path)
        return
    live.id, live.rows, live.in_scope, live.scope = None, 0, 0, scope
    live.indexed_offset = live.indexed_lines = 0
    live.last_serial = live.last_serial_offset = None
    store.save(conn, live)
