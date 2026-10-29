
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Sequence, Set

import structlog

from src.core.db import transaction
from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db, reader
from src.core.deepsearch import constants as K
from src.core.deepsearch import fallback_hook as fb
from src.core.deepsearch import index_scope
from src.core.deepsearch import indexer as point_indexer
from src.core.deepsearch import scope_reconcile
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch.cache import ddl as cache_ddl
from src.core.deepsearch.extract import extract
from src.core.deepsearch.live import store
from src.core.deepsearch.live.indexer import FileSpec, in_scope, rules_for
from src.core.deepsearch.live.range_rows import Pending, RangeRows, read_rows
from src.core.deepsearch.transcript_folders import folders_in_lines
from src.core.transcript_manifest.tail import line_serial
from src.core.transcript_source import scope as scope_mod

logger = structlog.get_logger()

PLUGIN_ID = "deepsearch"
DB_NAME = K.CACHE_FILENAME
SCHEMA_VERSION = 3


class IndexGap(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start_over(conn: sqlite3.Connection) -> bool:
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (K.LIVE_TABLE,)).fetchone()
    if present is None:
        return False
    for table in (K.FTS_TABLE, K.ROWS_TABLE, K.LIVE_TABLE, K.FOLDERS_TABLE):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"DELETE FROM {C.CURSORS_TABLE}")
    return True


def migrate(conn: sqlite3.Connection, from_version: int) -> None:
    started_over = _start_over(conn)
    for statement in cache_ddl.statements():
        conn.execute(statement)
    if started_over:
        conn.execute(f"UPDATE {K.CACHE_META_TABLE} SET state = ?, built_at = NULL WHERE id = 1", (K.CACHE_BUILDING,))
        logger.info("deepsearch_index_started_over", reason="first_open_by_the_pipeline" if from_version == 0 else "folder_ledger")
    conn.execute(f"PRAGMA user_version = {K.CACHE_VERSION}")


def on_caught_up(conn: sqlite3.Connection) -> None:
    changed = conn.execute(f"UPDATE {K.CACHE_META_TABLE} SET state = ?, built_at = COALESCE(built_at, ?) "
                           "WHERE id = 1 AND state != ?", (K.CACHE_READY, _utc_now(), K.CACHE_READY)).rowcount
    if changed:
        logger.info("deepsearch_cache_ready")
    _read_backups(conn)


def _read_backups(conn: sqlite3.Connection) -> None:
    from src.core.deepsearch import vault_lane  # noqa: PLC0415

    file = conn.execute("PRAGMA database_list").fetchone()[2]
    try:
        vault_lane.sweep(conn, Path(file).parent)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("deepsearch_vault_sweep_failed", error=str(exc)[:300])


def _read_lines(path: str, start: int, end: int, first_number: int, rules: Dict[str, Any], family: str,
                *, whole: bool = True) -> RangeRows:
    def scan() -> RangeRows:
        read = read_rows(Path(path), start, end, first_number, rules, family, with_folders=True)
        if whole and read.end_offset != end:
            raise IndexGap(f"{path}: bytes {start} to {end} are not whole lines any more")
        return read

    return reader.timed(scan, key=path)


class _Plan(NamedTuple):

    scope: str
    kind: str
    live: Optional[store.LiveFile]
    stale: Optional[store.LiveFile]
    held_end: int
    version: str
    overrides: Optional[Dict[str, Any]]


_SKIP, _OUT, _INDEX = "skip", "out_of_scope", "index"


def _plan(conn: sqlite3.Connection, event: C.Appended) -> _Plan:
    scope = index_scope.current()
    skip = _Plan(scope, _SKIP, None, None, 0, "", None)
    if event.file_kind == K.FILE_SUBAGENT and not scope_mod.includes_subagents(scope):
        return skip
    live = store.get(conn, event.path)
    vault_row = None
    if live is not None and live.base_point_id == K.VAULT_MARK:
        live, vault_row = None, live
    if live is not None and live.scope == scope and not live.in_scope:
        return skip
    spec = FileSpec(event.conversation_id, event.path, event.file_kind, event.family)
    if (live is None or live.scope != scope) and not in_scope(scope, spec):
        return _Plan(scope, _OUT, live or vault_row, None, 0, "", None)
    overrides = rules_mod.read_overrides()
    version = rules_mod.version_of(overrides, event.family)
    stale = vault_row
    if live is not None and (not live.in_scope or live.filter_version != version):
        live, stale = None, live
    held_end = live.indexed_offset if live is not None else 0
    if event.end <= held_end:
        return skip
    return _Plan(scope, _INDEX, live, stale, held_end, version, overrides)


def _new_live(event: C.Appended, version: str, now: str, *, in_scope_flag: int, scope: str) -> store.LiveFile:
    return store.LiveFile(event.conversation_id, event.path, event.file_kind, event.family, 0, 0, None, 0, 0, None,
                          None, 0, version, in_scope_flag, scope, now, now)


def catch_up(conn: sqlite3.Connection, event: C.Appended, limit: int) -> C.CatchUp:
    if not event.lines:
        return C.CatchUp(True)
    plan = _plan(conn, event)
    if plan.kind != _INDEX or plan.held_end >= event.start:
        return C.CatchUp(True)
    rules = rules_for(plan.overrides, event.family, event.file_kind)
    start = plan.held_end
    first_number = plan.live.indexed_lines if plan.live is not None else 0
    end = min(event.start, start + max(1, int(limit)))
    while True:
        found = _read_lines(event.path, start, end, first_number, rules, event.family, whole=end == event.start)
        if found.lines or end >= event.start:
            break
        end = min(event.start, start + 2 * (end - start))
    bytes_read = found.end_offset - start
    with plugin_db.lock_for(PLUGIN_ID):
        with transaction(conn):
            now = _utc_now()
            again = _plan(conn, event)
            held_lines = again.live.indexed_lines if again.live is not None else 0
            if again.kind != _INDEX or again.held_end != start or held_lines != first_number:
                return C.CatchUp(False, bytes_read)
            if again.stale is not None:
                store.delete_file(conn, int(again.stale.id))
            live = again.live or _new_live(event, again.version, now, in_scope_flag=1, scope=again.scope)
            live.indexed_offset, live.indexed_lines = found.end_offset, first_number + found.lines
            live.last_serial, live.last_serial_offset = line_serial(found.last_raw[:-1]), found.last_offset
            live.indexed_at, live.rows = now, live.rows + len(found.rows)
            live.filter_version, live.in_scope, live.scope = again.version, 1, again.scope
            live_id = store.save(conn, live)
            store.add_folders(conn, live_id, found.folders)
            point_indexer.write_rows(conn, K.LIVE_DOC_ID, found.rows, live_id)
    return C.CatchUp(found.end_offset >= event.start, bytes_read)


def _appended(conn: sqlite3.Connection, event: C.Appended) -> None:
    if not event.lines:
        return
    plan = _plan(conn, event)
    now = _utc_now()
    if plan.kind == _SKIP:
        return
    if plan.kind == _OUT:
        if plan.live is not None:
            store.delete_file(conn, int(plan.live.id))
        store.save(conn, _new_live(event, "", now, in_scope_flag=0, scope=plan.scope))
        return
    live, held_end, version = plan.live, plan.held_end, plan.version
    if plan.stale is not None:
        store.delete_file(conn, int(plan.stale.id))
    rules = rules_for(plan.overrides, event.family, event.file_kind)
    cursor = plugin_db.get_cursor(conn, event.path)
    first_number = cursor.lines if cursor is not None else 0
    pending: Pending = []
    folders: Set[str] = set()
    if held_end < event.start:
        gap = _read_lines(event.path, held_end, event.start, live.indexed_lines if live is not None else 0,
                          rules, event.family)
        pending, folders = gap.rows, set(gap.folders)
    indexed_to = max(held_end, event.start)
    for position, line in enumerate(event.lines, start=first_number):
        if line.offset < indexed_to:
            continue
        folders |= folders_in_lines((line.raw,))
        found = extract(line.raw, rules, event.family)
        if found is not None:
            pending.append(((0, line.offset, line.length, position, position, found[0]), found[1]))
    last = event.lines[-1]
    if live is None:
        live = _new_live(event, version, now, in_scope_flag=1, scope=plan.scope)
    live.indexed_offset, live.indexed_lines = event.end, first_number + len(event.lines)
    live.last_serial, live.last_serial_offset = line_serial(last.raw[:-1]), last.offset
    live.indexed_at = now
    live.rows += len(pending)
    live.filter_version, live.in_scope, live.scope = version, 1, plan.scope
    live_id = store.save(conn, live)
    store.add_folders(conn, live_id, folders)
    point_indexer.write_rows(conn, K.LIVE_DOC_ID, pending, live_id)


def _reset(conn: sqlite3.Connection, event: C.FileReset) -> None:
    live = store.get(conn, event.path)
    if live is not None:
        store.delete_file(conn, int(live.id))


def _backup_may_serve() -> bool:

    return bool(fb.sources()) or fb.booting()


def _file_removed(conn: sqlite3.Connection, event: C.FileRemoved) -> None:
    live = store.get(conn, event.path)
    if live is None:
        return
    if live.in_scope and live.base_point_id != K.VAULT_MARK and _backup_may_serve():
        store.set_mark(conn, int(live.id), K.VAULT_MARK)
        logger.info("deepsearch_row_repointed_at_vault", conversation_id=live.conversation_id, file_kind=live.file_kind)
        return
    if live.base_point_id == K.VAULT_MARK and _backup_may_serve():
        return
    store.delete_file(conn, int(live.id))


def on_events(conn: sqlite3.Connection, events: Sequence[C.Event]) -> None:
    for event in events:
        if isinstance(event, C.Appended):
            _appended(conn, event)
        elif isinstance(event, C.FileReset):
            _reset(conn, event)
        elif isinstance(event, C.FileRemoved):
            _file_removed(conn, event)


FILE_KINDS = frozenset({C.FILE_CONVERSATION, C.FILE_SUBAGENT})

DEEPSEARCH = C.Plugin(id=PLUGIN_ID, db_name=DB_NAME, schema_version=SCHEMA_VERSION, migrate=migrate,
                      on_events=on_events, on_caught_up=on_caught_up, in_state_dir=True, file_kinds=FILE_KINDS,
                      catch_up=catch_up, file_kinds_fn=index_scope.file_kinds, before_scan=scope_reconcile.settle,
                      per_file_removal=True)
