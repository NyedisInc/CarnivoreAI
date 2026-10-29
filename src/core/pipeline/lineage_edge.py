
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

from src.core.pipeline.contract import Lineage

logger = structlog.get_logger()

def lineage_of(db_path: Path, conversation_id: str) -> Optional[Lineage]:
    from src.core.db import DatastoreError
    from src.core.db_reuse import datastore_pool
    from src.core.lineage import constants as LN

    marks = ", ".join("?" for _ in LN.CONTINUATION_KINDS)
    try:
        with closing(datastore_pool.lend(Path(db_path))) as lent, datastore_pool.read_only(lent) as conn:
            row = conn.execute(
                f"SELECT parent_id, edge_kind, detail_json FROM {LN.EDGES_TABLE} WHERE child_type = ? AND child_id = ? "
                f"AND parent_type = ? AND edge_kind IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                (LN.NODE_CONVERSATION, conversation_id, LN.NODE_CONVERSATION, *LN.CONTINUATION_KINDS)).fetchone()
    except (sqlite3.Error, OSError, DatastoreError) as exc:
        datastore_pool.forget_if_broken(Path(db_path), exc)
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
