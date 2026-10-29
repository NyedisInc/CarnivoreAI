
from __future__ import annotations

import json
import secrets as _random
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, Iterable, List, Optional, Sequence

import structlog

from src.config import settings
from src.core import resource_push
from src.core.db import connect, db_path_for, transaction
from src.core.mcp import family_signals
from src.core.resource_push.topics import MESSAGING

log = structlog.get_logger(__name__)

PENDING = ("queued", "held")
DIRECTIONS = ("in", "out", "both")
INBOUND = ("in", "both")
OUTBOUND = ("out", "both")


class StoreRefused(ValueError):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _conn() -> sqlite3.Connection:
    return connect(db_path_for(settings.get_state_dir()), create=False)


def new_id(prefix: str, hex_chars: int = 12) -> str:
    return prefix + _random.token_hex(hex_chars // 2)


_index_lock = threading.Lock()
_by_uuid: Dict[str, Dict[str, Any]] = {}
_row_uuid: Dict[int, str] = {}


def _refresh_index(conn: sqlite3.Connection) -> None:
    by_uuid: Dict[str, Dict[str, Any]] = {}
    for row in conn.execute("SELECT session_uuid, direction FROM messaging_bindings"):
        entry = by_uuid.setdefault(row["session_uuid"], {"directions": set(), "held": 0, "pending": 0})
        entry["directions"].update(("in", "out") if row["direction"] == "both" else (row["direction"],))
    for row in conn.execute("SELECT session_uuid, status, COUNT(*) AS n FROM messaging_messages WHERE direction = 'in' "
                            "AND status IN ('queued','held') AND session_uuid IS NOT NULL GROUP BY session_uuid, status"):
        entry = by_uuid.setdefault(row["session_uuid"], {"directions": set(), "held": 0, "pending": 0})
        entry["pending"] += row["n"]
        if row["status"] == "held":
            entry["held"] += row["n"]
    rows: Dict[int, str] = {}
    if by_uuid:
        marks = ",".join("?" * len(by_uuid))
        try:
            rows = {int(r[0]): str(r[1]) for r in conn.execute(
                f"SELECT id, session_uuid FROM sessions WHERE session_uuid IN ({marks})", list(by_uuid))}
        except sqlite3.OperationalError as exc:
            log.warning("messaging_index_rows_unread", error=str(exc))
    with _index_lock:
        _by_uuid.clear()
        _by_uuid.update({u: {**e, "directions": sorted(e["directions"])} for u, e in by_uuid.items()})
        _row_uuid.clear()
        _row_uuid.update(rows)


def refresh_index() -> None:
    with closing(_conn()) as conn:
        _refresh_index(conn)


def mark_for_row(row_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if row_id is None:
        return None
    with _index_lock:
        uuid = _row_uuid.get(int(row_id))
        entry = _by_uuid.get(uuid) if uuid else None
        if not entry or not entry["directions"]:
            return None
        return {"directions": list(entry["directions"]), "held": int(entry["held"])}


def pending_uuids() -> List[str]:
    with _index_lock:
        return [u for u, e in _by_uuid.items() if e["pending"]]


def has_pending(session_uuid: Optional[str]) -> bool:
    with _index_lock:
        entry = _by_uuid.get(session_uuid or "")
        return bool(entry and entry["pending"])


def uuid_for_row(row_id: Optional[int]) -> Optional[str]:
    with _index_lock:
        return _row_uuid.get(int(row_id)) if row_id is not None else None


def _changed(conn: sqlite3.Connection) -> None:
    _refresh_index(conn)
    resource_push.notify(MESSAGING)


def _rows(cursor: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in cursor]


def _provider(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    out["capabilities"] = json.loads(out["capabilities"]) if out.get("capabilities") else None
    out["gap"] = json.loads(out["gap"]) if out.get("gap") else None
    for key in ("enabled", "allow_private", "allow_plain_http"):
        out[key] = bool(out[key])
    return out



def create_provider(*, provider_id: str, name: str, owner_label: str, allow_private: bool, allow_plain_http: bool,
                    capabilities: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    with closing(_conn()) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO messaging_providers (id, name, owner_label, allow_private, allow_plain_http, "
                         "capabilities, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (provider_id, name, owner_label, int(allow_private), int(allow_plain_http),
                          json.dumps(capabilities), now, now))
        family_signals.invalidate("messaging")
        _changed(conn)
        return _provider(conn.execute("SELECT * FROM messaging_providers WHERE id = ?", (provider_id,)).fetchone())


_PROVIDER_FIELDS = frozenset({"name", "owner_label", "enabled", "allow_private", "allow_plain_http", "capabilities",
                              "stream_state", "gap", "last_event_at"})


def update_provider(provider_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    bad = set(fields) - _PROVIDER_FIELDS
    if bad:
        raise ValueError(f"unknown provider fields: {sorted(bad)}")
    values = {k: (json.dumps(v) if k in ("capabilities", "gap") and v is not None else
                  int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    with closing(_conn()) as conn:
        if values:
            with transaction(conn):
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE messaging_providers SET {sets}, updated_at = ? WHERE id = ?",
                             [*values.values(), time.time(), provider_id])
            _changed(conn)
        return _provider(conn.execute("SELECT * FROM messaging_providers WHERE id = ?", (provider_id,)).fetchone())


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    with closing(_conn()) as conn:
        return _provider(conn.execute("SELECT * FROM messaging_providers WHERE id = ?", (provider_id,)).fetchone())


def list_providers() -> List[Dict[str, Any]]:
    with closing(_conn()) as conn:
        return [_provider(r) for r in conn.execute("SELECT * FROM messaging_providers ORDER BY created_at")]


def _fail_pending(conn: sqlite3.Connection, where: str, args: Sequence[Any], reason: str) -> None:
    conn.execute(f"UPDATE messaging_messages SET status = 'failed', reason = ? WHERE direction = 'in' "
                 f"AND status IN ('queued','held') AND {where}", [reason, *args])


def delete_provider(provider_id: str) -> bool:
    with closing(_conn()) as conn:
        with transaction(conn):
            _fail_pending(conn, "provider_id = ?", (provider_id,), "provider_deleted")
            convs = [r[0] for r in conn.execute("SELECT id FROM messaging_conversations WHERE provider_id = ?",
                                                (provider_id,))]
            for cid in convs:
                conn.execute("DELETE FROM messaging_bindings WHERE conversation_id = ?", (cid,))
                conn.execute("DELETE FROM messaging_notices WHERE conversation_id = ?", (cid,))
            conn.execute("DELETE FROM messaging_conversations WHERE provider_id = ?", (provider_id,))
            removed = conn.execute("DELETE FROM messaging_providers WHERE id = ?", (provider_id,)).rowcount
        family_signals.invalidate("messaging")
        _changed(conn)
        return bool(removed)



def create_conversation(*, conversation_id: str, provider_id: str, label: str, match_key: str) -> Dict[str, Any]:
    with closing(_conn()) as conn:
        try:
            with transaction(conn):
                conn.execute("INSERT INTO messaging_conversations (id, provider_id, label, match_key, created_at) "
                             "VALUES (?,?,?,?,?)", (conversation_id, provider_id, label, match_key, time.time()))
        except sqlite3.IntegrityError:
            raise StoreRefused("already_added") from None
        _changed(conn)
        return dict(conn.execute("SELECT * FROM messaging_conversations WHERE id = ?", (conversation_id,)).fetchone())


def list_conversations(provider_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT id, provider_id, label, created_at FROM messaging_conversations"
    with closing(_conn()) as conn:
        if provider_id:
            return _rows(conn.execute(sql + " WHERE provider_id = ? ORDER BY created_at", (provider_id,)))
        return _rows(conn.execute(sql + " ORDER BY created_at"))


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM messaging_conversations WHERE id = ?", (conversation_id,)).fetchone()
        return dict(row) if row else None


def conversation_by_match(provider_id: str, match_key: str) -> Optional[Dict[str, Any]]:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM messaging_conversations WHERE provider_id = ? AND match_key = ?",
                           (provider_id, match_key)).fetchone()
        return dict(row) if row else None


def rename_conversation(conversation_id: str, label: str) -> Optional[Dict[str, Any]]:
    with closing(_conn()) as conn:
        with transaction(conn):
            n = conn.execute("UPDATE messaging_conversations SET label = ? WHERE id = ?", (label, conversation_id)).rowcount
        if not n:
            return None
        _changed(conn)
    return get_conversation(conversation_id)


def delete_conversation(conversation_id: str) -> bool:
    with closing(_conn()) as conn:
        with transaction(conn):
            _fail_pending(conn, "conversation_id = ?", (conversation_id,), "unbound")
            conn.execute("DELETE FROM messaging_bindings WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM messaging_notices WHERE conversation_id = ?", (conversation_id,))
            removed = conn.execute("DELETE FROM messaging_conversations WHERE id = ?", (conversation_id,)).rowcount
        _changed(conn)
        return bool(removed)



def _binding(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    out["default"] = bool(out.pop("is_default"))
    out["held_notice"] = bool(out["held_notice"])
    return out


def create_binding(*, conversation_id: str, session_uuid: str, direction: str, is_default: bool,
                   created_by: str) -> Dict[str, Any]:
    if direction not in DIRECTIONS:
        raise ValueError("direction must be in, out or both")
    binding_id = new_id("b_")
    with closing(_conn()) as conn:
        try:
            with transaction(conn):
                if conn.execute("SELECT 1 FROM messaging_conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                    raise StoreRefused("conversation_not_found")
                if is_default:
                    conn.execute("UPDATE messaging_bindings SET is_default = 0 WHERE conversation_id = ?", (conversation_id,))
                conn.execute("INSERT INTO messaging_bindings (id, conversation_id, session_uuid, direction, is_default, "
                             "created_at, created_by) VALUES (?,?,?,?,?,?,?)",
                             (binding_id, conversation_id, session_uuid, direction, int(is_default), time.time(), created_by))
        except sqlite3.IntegrityError:
            raise StoreRefused("already_bound") from None
        _changed(conn)
        return _binding(conn.execute("SELECT * FROM messaging_bindings WHERE id = ?", (binding_id,)).fetchone())


def update_binding(binding_id: str, *, direction: Optional[str] = None, is_default: Optional[bool] = None,
                   held_notice: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    if direction is not None and direction not in DIRECTIONS:
        raise ValueError("direction must be in, out or both")
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM messaging_bindings WHERE id = ?", (binding_id,)).fetchone()
        if row is None:
            return None
        with transaction(conn):
            if is_default:
                conn.execute("UPDATE messaging_bindings SET is_default = 0 WHERE conversation_id = ?",
                             (row["conversation_id"],))
            conn.execute("UPDATE messaging_bindings SET direction = ?, is_default = ?, held_notice = ? WHERE id = ?",
                         (direction or row["direction"], int(row["is_default"] if is_default is None else is_default),
                          int(row["held_notice"] if held_notice is None else held_notice), binding_id))
        _changed(conn)
        return _binding(conn.execute("SELECT * FROM messaging_bindings WHERE id = ?", (binding_id,)).fetchone())


def delete_binding(binding_id: str, *, reason: str = "unbound") -> bool:
    with closing(_conn()) as conn:
        with transaction(conn):
            _fail_pending(conn, "binding_id = ?", (binding_id,), reason)
            removed = conn.execute("DELETE FROM messaging_bindings WHERE id = ?", (binding_id,)).rowcount
        _changed(conn)
        return bool(removed)


def get_binding(binding_id: str) -> Optional[Dict[str, Any]]:
    with closing(_conn()) as conn:
        return _binding(conn.execute("SELECT * FROM messaging_bindings WHERE id = ?", (binding_id,)).fetchone())


def list_bindings(*, session_uuid: Optional[str] = None, conversation_id: Optional[str] = None) -> List[Dict[str, Any]]:
    clauses, args = [], []
    for name, column, value in (("session_uuid", "b.session_uuid", session_uuid),
                                ("conversation_id", "b.conversation_id", conversation_id)):
        if value is None:
            continue
        if not value:
            raise ValueError(f"list_bindings: {name} is empty; pass None for no filter")
        clauses.append(f"{column} = ?")
        args.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM messaging_messages m WHERE m.binding_id = b.id AND m.direction = 'in' "
            f"AND m.status = 'held') AS held FROM messaging_bindings b{where} ORDER BY b.created_at", args)
        return [_binding(r) for r in rows]
