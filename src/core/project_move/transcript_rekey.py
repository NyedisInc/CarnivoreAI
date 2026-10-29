
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from src.core.db import table_exists, transaction
from src.core.project_move.paths import prefix_params, prefix_where
from src.core.deepsearch import constants as search_constants
from src.core.transcript_manifest import constants as manifest_constants


def _rekey_table(conn: sqlite3.Connection, table: str, source: str, target: str, *, relative: bool) -> int:
    params = prefix_params(source)
    rows = conn.execute(f"SELECT id, path FROM {table} WHERE {prefix_where('path')}", params).fetchall()
    changed = 0
    for row_id, path in rows:
        new_path = target + path[len(source):]
        if conn.execute(f"SELECT 1 FROM {table} WHERE path = ?", (new_path,)).fetchone():
            continue
        if relative:
            conn.execute(f"UPDATE {table} SET path = ?, source_path = ? || substr(source_path, ?) WHERE id = ?",
                         (new_path, os.path.basename(target), len(os.path.basename(source)) + 1, row_id))
        else:
            conn.execute(f"UPDATE {table} SET path = ? WHERE id = ?", (new_path, row_id))
        changed += 1
    return changed


def rekey_transcript_rows(conn: sqlite3.Connection, transcript_moves: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {"transcript_files": 0, "search_live": 0}
    for move in transcript_moves:
        source, target = str(move["from"]), str(move["to"])
        if table_exists(conn, manifest_constants.TABLE):
            counts["transcript_files"] += _rekey_table(conn, manifest_constants.TABLE, source, target, relative=True)
        if table_exists(conn, search_constants.LIVE_TABLE):
            counts["search_live"] += _rekey_table(conn, search_constants.LIVE_TABLE, source, target, relative=False)
    return counts


def forget_moved_in_cache(state_dir: Path, transcript_moves: Sequence[Mapping[str, Any]]) -> int:
    from src.core.deepsearch.cache import db as cache_db
    from src.core.deepsearch.live import store

    removed = 0
    if not cache_db.cache_path(state_dir).exists():
        return 0
    with closing(cache_db.open_cache(state_dir)) as conn:
        for move in transcript_moves:
            prefix = str(move["from"]).rstrip("/") + "/"
            for (live_id,) in conn.execute(f"SELECT id FROM {search_constants.LIVE_TABLE} WHERE substr(path, 1, ?) = ?",
                                           (len(prefix), prefix)).fetchall():
                with transaction(conn):
                    store.delete_file(conn, int(live_id))
                removed += 1
    return removed
