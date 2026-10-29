
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core.db import get_meta, set_meta, table_exists

logger = structlog.get_logger()

LEDGER_PREFIX = "crate_import:"
UNDO_PREFIX = "crate_undo:"
PHASE_UNDONE = "undone"


def entries_from(conn: sqlite3.Connection, source_install: str) -> List[Dict[str, Any]]:
    if not table_exists(conn, "meta"):
        return []
    out: List[Dict[str, Any]] = []
    for key, value in conn.execute("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key", (LEDGER_PREFIX + "%",)):
        try:
            entry = json.loads(value)
        except ValueError:
            logger.warning("crate_import_ledger_entry_unreadable", key=key)
            continue
        if isinstance(entry, dict) and entry.get("source_install") == source_install and entry.get("phase") != PHASE_UNDONE:
            out.append({"import_id": key[len(LEDGER_PREFIX):], **entry})
    return out


def known_keys(conn: sqlite3.Connection, source_install: str, table: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for entry in entries_from(conn, source_install):
        merged.update((entry.get("key_map") or {}).get(table) or {})
    return merged


def key_for(import_id: str) -> str:
    return LEDGER_PREFIX + import_id


def read_entry(conn: sqlite3.Connection, import_id: str) -> Optional[Dict[str, Any]]:
    raw = get_meta(conn, key_for(import_id))
    if raw is None:
        return None
    try:
        entry = json.loads(raw)
    except ValueError:
        logger.warning("crate_import_ledger_entry_unreadable", key=key_for(import_id))
        return None
    return entry if isinstance(entry, dict) else None


def write_entry(conn: sqlite3.Connection, import_id: str, entry: Dict[str, Any]) -> None:
    set_meta(conn, key_for(import_id), json.dumps(entry, sort_keys=True, separators=(",", ":")))


def set_phase(conn: sqlite3.Connection, import_id: str, phase: str) -> bool:
    entry = read_entry(conn, import_id)
    if entry is None:
        return False
    entry["phase"] = phase
    write_entry(conn, import_id, entry)
    return True


def set_field(conn: sqlite3.Connection, import_id: str, name: str, value: Any) -> bool:
    entry = read_entry(conn, import_id)
    if entry is None:
        return False
    entry[name] = value
    write_entry(conn, import_id, entry)
    return True


def all_entries(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not table_exists(conn, "meta"):
        return []
    out: List[Dict[str, Any]] = []
    for key, value in conn.execute("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key", (LEDGER_PREFIX + "%",)):
        try:
            entry = json.loads(value)
        except ValueError:
            logger.warning("crate_import_ledger_entry_unreadable", key=key)
            continue
        if isinstance(entry, dict):
            out.append({"import_id": key[len(LEDGER_PREFIX):], **entry})
    return out


def read_undo(conn: sqlite3.Connection, import_id: str) -> Optional[Dict[str, Any]]:
    raw = get_meta(conn, UNDO_PREFIX + import_id)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("crate_import_undo_record_unreadable", import_id=import_id)
        return None
    return record if isinstance(record, dict) else None


def write_undo(conn: sqlite3.Connection, import_id: str, record: Dict[str, Any]) -> None:
    set_meta(conn, UNDO_PREFIX + import_id, json.dumps(record, sort_keys=True, separators=(",", ":")))


def mark_undone(conn: sqlite3.Connection, import_id: str, when: str) -> bool:
    entry = read_entry(conn, import_id)
    if entry is None:
        return False
    entry["phase"], entry["undone_at"] = PHASE_UNDONE, when
    write_entry(conn, import_id, entry)
    conn.execute("DELETE FROM meta WHERE key = ?", (UNDO_PREFIX + import_id,))
    return True
