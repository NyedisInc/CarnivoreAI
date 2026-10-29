
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

import structlog

from src.core.crate_import import idmap as ids
from src.core.crate_import import policy
from src.core.crate_import import rows_write as rw
from src.core.crate_import.keyrules import REF, rule_for
from src.core.inventory.model import MAIN_STORE

logger = structlog.get_logger()

CROSSTALK = f"{MAIN_STORE}.crosstalk_messages"
MCP_EVENTS = f"{MAIN_STORE}.mcp_events"
MESSAGING = f"{MAIN_STORE}.messaging_messages"
ITEMS = f"{MAIN_STORE}.work_items"
TABLES: Tuple[str, ...] = policy.HISTORY_TABLES
OPEN_STATUSES = ("queued", "held", "delivering")
EXPIRED = "expired"
FAILED = "failed"
REASON_IMPORTED = "imported: this message was in a crate and was never delivered here"


def _final(key: str, row: Dict[str, Any]) -> Dict[str, Any]:
    if row.get("status") not in OPEN_STATUSES:
        return row
    return {**row, "status": EXPIRED if key == CROSSTALK else FAILED, "reason": REASON_IMPORTED}


def _rekey(ctx: rw.WriteCtx, key: str, row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    table = key.rpartition(".")[2]
    for column in list(out):
        rule = rule_for(MAIN_STORE, table, column)
        if rule is not None and rule.kind == REF and out[column] is not None:
            out[column] = ids.ref(ctx.conn, ctx.idmap, rule, out[column])
    if table == "crosstalk_messages" and out.get("task_item") is not None:
        out["task_item"] = ctx.idmap.get(ITEMS, out["task_item"])
    return out


def _write_text_id(ctx: rw.WriteCtx, key: str, rows: List[Dict[str, Any]]) -> None:
    counts, table = ctx.table_counts(key), key.rpartition(".")[2]
    for source in rows:
        row = rw.own_columns(ctx, table, _final(key, _rekey(ctx, key, source)))
        if ctx.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row.get("id"),)).fetchone() is not None:
            counts.present += 1
            continue
        try:
            inserted, _rowid = rw.insert_row(ctx, table, row, ignore=True)
        except sqlite3.IntegrityError as exc:
            logger.info("crate_import_history_refused", table=key, error=str(exc)[:120])
            counts.skip("refused_by_unique_rule")
            continue
        counts.inserted += 1 if inserted else 0
        counts.present += 0 if inserted else 1


def write_history(ctx: rw.WriteCtx, sanitized: Dict[str, List[Dict[str, Any]]]) -> None:
    _write_text_id(ctx, CROSSTALK, sanitized.get(CROSSTALK, []))
    _write_text_id(ctx, MESSAGING, sanitized.get(MESSAGING, []))
    rw.write_generic(ctx, MCP_EVENTS, sanitized.get(MCP_EVENTS, []))
