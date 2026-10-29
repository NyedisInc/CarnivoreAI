
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import structlog

from src.core.pipeline.contract import Lineage

logger = structlog.get_logger()

_LOCAL = threading.local()


def _reader(db_path: Path) -> sqlite3.Connection:
    """This thread's read-only connection to ``db_path``, opened on first use and after the file is replaced.

    Inputs: db_path - carnivore.db. Output: sqlite3.Connection (``query_only``, so a write through it is refused).
    Raises: DatastoreError, sqlite3.Error, OSError - the database cannot be opened.
    """
    from src.core.db import connect

    key = str(db_path)
    st = os.stat(key)
    ident = (st.st_dev, st.st_ino)
    cached = getattr(_LOCAL, "entry", None)
    if cached is not None and cached[0] == key and cached[1] == ident:
        return cached[2]
    if cached is not None:
        _drop_reader()
    conn = connect(Path(db_path), create=False)
    conn.execute("PRAGMA query_only = ON")
    _LOCAL.entry = (key, ident, conn)
    return conn


def _drop_reader() -> None:
    cached = getattr(_LOCAL, "entry", None)
    _LOCAL.entry = None
    if cached is not None:
        try:
            cached[2].close()
        except sqlite3.Error as exc:
            logger.debug("pipeline_lineage_close_failed", error=type(exc).__name__)


def lineage_of(db_path: Path, conversation_id: str) -> Optional[Lineage]:
    from src.core.db import DatastoreError
    from src.core.lineage import constants as LN

    marks = ", ".join("?" for _ in LN.CONTINUATION_KINDS)
    try:
        row = _reader(Path(db_path)).execute(
            f"SELECT parent_id, edge_kind, detail_json FROM {LN.EDGES_TABLE} WHERE child_type = ? AND child_id = ? "
            f"AND parent_type = ? AND edge_kind IN ({marks}) ORDER BY created_at DESC LIMIT 1",
            (LN.NODE_CONVERSATION, conversation_id, LN.NODE_CONVERSATION, *LN.CONTINUATION_KINDS)).fetchone()
    except (sqlite3.Error, OSError, DatastoreError) as exc:
        _drop_reader()
        logger.debug("pipeline_lineage_unreadable", error=type(exc).__name__)
        return None
    if row is None:
        return None
    try:
        detail = json.loads(row[2] or "{}")
    except ValueError:
        detail = {}
    fork = (detail.get("uuid") or detail.get("logical_parent_uuid")) if isinstance(detail, dict) else None
    return Lineage(row[0], row[1], fork)
