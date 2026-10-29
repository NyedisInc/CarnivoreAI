
from __future__ import annotations

import os
import sqlite3
import time
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Set, Tuple

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_DEFAULT_S, connect_readonly
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.deepsearch import constants as K
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.live import store as live_store
from src.core.deepsearch.transcript_folders import tail_folders
from src.core.hosts.identity import is_remote_root

logger = structlog.get_logger()


class AirGapUnreadable(RuntimeError):
    pass


READ_BUDGET_SECONDS: float = 20.0


def fold(path: str) -> str:
    return unicodedata.normalize("NFC", os.path.realpath(os.path.expanduser(path))).casefold()


@dataclass(frozen=True)
class PeerGate:

    ids: FrozenSet[int]
    roots: Tuple[str, ...]

    @property
    def active(self) -> bool:
        return bool(self.ids or self.roots)

    def inside_folded(self, folded: str) -> bool:
        return any(folded == root or folded.startswith(root.rstrip(os.sep) + os.sep) for root in self.roots)

    def inside(self, path: str) -> bool:
        return self.inside_folded(fold(path))

    def admitted(self, conn: sqlite3.Connection, meta: Dict[str, Dict[str, Any]]) -> Set[str]:
        if not self.active:
            return set(meta)
        deadline = time.monotonic() + READ_BUDGET_SECONDS
        files = _files_of(conn, list(meta))
        keep: Set[str] = set()
        for conv, row in meta.items():
            wd = row.get("working_dir")
            if row.get("project_id") in self.ids or (isinstance(wd, str) and wd and self.inside(wd)):
                continue
            if self._proven_outside(files.get(conv, ()), deadline):
                keep.add(conv)
        return keep

    def _proven_outside(self, files: Iterable["GateFile"], deadline: float) -> bool:
        files = list(files)
        if not files:
            return False
        for file in files:
            folders = file.folders
            if not folders:
                return False
            if time.monotonic() > deadline:
                return False
            extra = () if file.from_vault else tail_folders(file.path, file.indexed_offset)
            if extra is None:
                return False
            if any(not os.path.isabs(f) or self.inside(f) for f in (*folders, *extra)):
                return False
        return True


class GateFile(NamedTuple):

    path: str
    indexed_offset: int
    folders: FrozenSet[str]
    from_vault: bool = False


def _files_of(conn: sqlite3.Connection, conversations: list) -> Dict[str, List[GateFile]]:
    rows: List[Tuple[str, int, str, int, Optional[str]]] = []
    for start in range(0, len(conversations), 500):
        chunk = conversations[start:start + 500]
        marks = ", ".join("?" for _ in chunk)
        rows.extend(tuple(r) for r in conn.execute(
            f"SELECT conversation_id, id, path, indexed_offset, base_point_id FROM {K.LIVE_TABLE} "
            f"WHERE in_scope = 1 AND conversation_id IN ({marks})", chunk))
    ledger = live_store.folders_of(conn, [r[1] for r in rows])
    out: Dict[str, List[GateFile]] = {}
    for conv, live_id, path, offset, mark in rows:
        out.setdefault(conv, []).append(GateFile(path, int(offset), frozenset(ledger.get(int(live_id), ())),
                                                 mark == K.VAULT_MARK))
    return out


def load_gate(state_dir: Path) -> PeerGate:
    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            rows = conn.execute("SELECT id, root, raw_path FROM projects WHERE air_gap = 1").fetchall()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("deepsearch_peer_air_gap_unreadable", error_type=type(exc).__name__)
        raise AirGapUnreadable(type(exc).__name__) from exc
    return PeerGate(frozenset(int(r["id"]) for r in rows),
                    tuple(sorted({fold(p) for r in rows for p in (r["root"], r["raw_path"])
                                  if p and not is_remote_root(p)})))


def ledger_folders(state_dir: Path) -> Set[str]:
    path = cache_db.cache_path(state_dir)
    if not path.exists():
        return set()
    try:
        with closing(connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)) as conn:
            return {row[0] for row in conn.execute(f"SELECT DISTINCT folder FROM {K.FOLDERS_TABLE}")}
    except sqlite3.Error as exc:
        logger.info("deepsearch_ledger_folders_unreadable", error_type=type(exc).__name__)
        return set()
