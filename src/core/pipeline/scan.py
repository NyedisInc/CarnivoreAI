
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.pipeline.deliver import FileTarget
from src.core.pipeline.log import log_error
from src.core.pipeline.observe import TRIGGER_SCAN
from src.core.pipeline import plugin_db
from src.core.pipeline.plugin_db import db_path
from src.core.transcript_manifest import constants as TM

logger = structlog.get_logger()

SCAN_INTERVAL_SECONDS: float = TM.SCAN_INTERVAL_SECONDS

_COLUMNS = "path, conversation_id, family, kind, status, dataless, gone_at, complete_bytes"


@dataclass(frozen=True)
class ManifestFile:

    path: str
    conversation_id: str
    family: str
    kind: str
    dataless: bool
    gone: bool
    complete_bytes: int

    @property
    def deliverable(self) -> bool:
        return not self.gone and not self.dataless and self.kind in (TM.KIND_CONVERSATION, TM.KIND_SUBAGENT)

    def target(self, rewritten: bool = False) -> FileTarget:
        return FileTarget(self.path, self.conversation_id, self.family, self.kind, rewritten)


def load_rows(db: Path) -> List[ManifestFile]:
    """Every manifest row that names a conversation; [] when the table does not exist yet. Raises sqlite3.Error."""
    from src.core.db import connect
    from src.core.transcript_manifest import store

    with closing(connect(Path(db), create=False)) as conn:
        if not store.table_present(conn):
            return []
        return [ManifestFile(r[0], r[1], r[2], r[3], bool(r[5]), r[6] is not None, int(r[7] or 0))
                for r in conn.execute(f"SELECT {_COLUMNS} FROM {TM.TABLE} WHERE conversation_id IS NOT NULL "
                                      "AND conversation_id != ''")]


def read_cursors(state_dir: Path, plugin: C.Plugin) -> Dict[str, Tuple[int, str]]:
    path = db_path(state_dir, plugin)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)) as conn:
        present = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                               (C.CURSORS_TABLE,)).fetchone()
        if not present:
            return {}
        return {r[0]: (int(r[1]), r[2]) for r in conn.execute(
            f"SELECT path, offset, conversation_id FROM {C.CURSORS_TABLE}")}


def behind(plugin: C.Plugin, rows: Iterable[ManifestFile], cursors: Dict[str, Tuple[int, str]],
           rewritten: Set[str]) -> List[ManifestFile]:
    out = []
    for row in rows:
        if not row.deliverable or not plugin.reads(row.family, row.kind):
            continue
        held = cursors.get(row.path)
        if row.complete_bytes - (held[0] if held else 0) > 0 or row.path in rewritten:
            out.append(row)
    return out


def removed_conversations(rows: Iterable[ManifestFile], cursors: Dict[str, Tuple[int, str]]) -> Dict[str, str]:
    held = {conv for _, conv in cursors.values()}
    mains: Dict[str, List[ManifestFile]] = {}
    for row in rows:
        if row.kind == TM.KIND_CONVERSATION and row.conversation_id in held:
            mains.setdefault(row.conversation_id, []).append(row)
    return {conv: rs[0].family for conv, rs in mains.items() if all(r.gone for r in rs)}


def removed_files(rows: Iterable[ManifestFile], cursors: Dict[str, Tuple[int, str]]) -> List[ManifestFile]:
    return [row for row in rows if row.gone and row.path in cursors]


class Scanner:

    def __init__(self, state_dir: Path, db: Optional[Path], plugins: Sequence[C.Plugin],
                 mark_file: Callable[[FileTarget, str], bool], mark_removed: Callable[[str, str, str], bool],
                 *, refresh_fn: Optional[Callable[[], Any]] = None, wall: Callable[[], float] = time.time,
                 mark_file_removed: Optional[Callable[[FileTarget, str], bool]] = None) -> None:
        self._state_dir = Path(state_dir)
        self._db = db
        self._plugins = tuple(plugins)
        self._mark_file = mark_file
        self._mark_removed = mark_removed
        self._mark_file_removed = mark_file_removed
        self._refresh = refresh_fn
        self._wall = wall
        self.last: Optional[Dict[str, Any]] = None

    def run_once(self) -> Dict[str, Any]:
        from src.core.db import DatastoreError

        record: Dict[str, Any] = {"status": "ok", "error": None, "files": 0, "marked": 0, "removed": 0,
                                  "at": self._wall()}
        if self._db is None:
            record["status"] = "off"
        else:
            try:
                result = self._walk()
                rewritten = {r.path for r in getattr(result, "changed", ()) if r.status == TM.STATUS_REWRITTEN}
                rows = load_rows(self._db)
                record["files"] = len(rows)
                marked, removed = self._mark_behind(rows, rewritten)
                record.update(marked=marked, removed=removed)
            except (sqlite3.Error, OSError, DatastoreError) as exc:
                record.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:C.ERROR_CHARS])
                log_error("pipeline_scan_failed", plugin="scan", error=exc)
        self.last = record
        logger.debug("pipeline_scan", **{k: v for k, v in record.items() if k != "error"})
        return record

    def _walk(self) -> Any:
        if self._refresh is not None:
            return self._refresh()
        from src.core.transcript_manifest.refresh import refresh

        return refresh(Path(self._db))

    def _mark_behind(self, rows: List[ManifestFile], rewritten: Set[str]) -> Tuple[int, int]:
        files: Dict[str, ManifestFile] = {}
        gone: Dict[str, str] = {}
        gone_files: Dict[str, ManifestFile] = {}
        for plugin in self._plugins:
            self._settle(plugin)
            try:
                cursors = read_cursors(self._state_dir, plugin)
            except sqlite3.Error as exc:
                log_error("pipeline_scan_cursors_unreadable", plugin=plugin.id, error=exc)
                continue
            for row in behind(plugin, rows, cursors, rewritten):
                files[row.path] = row
            if plugin.per_file_removal:
                gone_files.update((row.path, row) for row in removed_files(rows, cursors))
            else:
                gone.update(removed_conversations(rows, cursors))
        for row in files.values():
            self._mark_file(row.target(row.path in rewritten), TRIGGER_SCAN)
        for conv, family in gone.items():
            self._mark_removed(conv, family, TRIGGER_SCAN)
        if self._mark_file_removed is not None:
            for row in gone_files.values():
                self._mark_file_removed(row.target(), TRIGGER_SCAN)
        return len(files), len(gone) + len(gone_files)

    def _settle(self, plugin: C.Plugin) -> None:
        if plugin.before_scan is None:
            return
        try:
            with plugin_db.lock_for(plugin.id):
                conn = plugin_db.open_db(self._state_dir, plugin)
            try:
                plugin.before_scan(conn)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            log_error("pipeline_scan_settle_failed", plugin=plugin.id, error=exc)

    def mark_pass(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"marked": 0, "removed": 0, "error": None}
        if self._db is None:
            return out
        from src.core.db import DatastoreError

        try:
            out["marked"], out["removed"] = self._mark_behind(load_rows(self._db), set())
        except (sqlite3.Error, OSError, DatastoreError) as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:C.ERROR_CHARS]
            log_error("pipeline_mark_pass_failed", plugin="scan", error=exc)
        return out

    def targets_for(self, plugin: C.Plugin) -> List[FileTarget]:
        if self._db is None:
            return []
        return [r.target() for r in load_rows(self._db) if r.deliverable and plugin.reads(r.family, r.kind)]
