
from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Dict, List, Optional, Sequence

import sqlite3

from src.core.db import transaction
from src.core.messaging import store as base


_MESSAGE_COLUMNS = ("id", "provider_id", "conversation_id", "binding_id", "session_uuid", "direction", "kind",
                    "provider_message_id", "event_id", "in_reply_to", "sent_at", "received_at", "text", "status",
                    "reason", "delivered_at", "batch_id")


def _insert_message(conn: sqlite3.Connection, row: Dict[str, Any]) -> bool:
    values = {"id": base.new_id("m_", 16), "conversation_id": "", "binding_id": "", "provider_message_id": "",
              "received_at": time.time(), **row}
    cols = [c for c in _MESSAGE_COLUMNS if c in values]
    cur = conn.execute(f"INSERT OR IGNORE INTO messaging_messages ({', '.join(cols)}) VALUES "
                       f"({', '.join('?' * len(cols))})", [values[c] for c in cols])
    return cur.rowcount == 1


def record_event(provider_id: str, event_id: int, rows: Sequence[Dict[str, Any]], *,
                 event_ts: Optional[float] = None) -> int:
    with closing(base._conn()) as conn:
        with transaction(conn):
            inserted = sum(1 for r in rows if _insert_message(conn, {**r, "provider_id": provider_id,
                                                                      "event_id": event_id}))
            conn.execute("UPDATE messaging_providers SET cursor = MAX(cursor, ?), last_event_at = COALESCE(?, "
                         "last_event_at), updated_at = ? WHERE id = ?", (event_id, event_ts, time.time(), provider_id))
        if inserted:
            base._changed(conn)
        return inserted


def supersede(provider_id: str, event_id: int, provider_message_id: str, *, unsent: bool, new_text: str,
              note_for: Any) -> List[str]:
    touched: List[str] = []
    now = time.time()
    with closing(base._conn()) as conn:
        with transaction(conn):
            rows = conn.execute("SELECT * FROM messaging_messages WHERE provider_id = ? AND provider_message_id = ? "
                                "AND direction = 'in' AND kind = 'message' AND binding_id != ''",
                                (provider_id, provider_message_id)).fetchall()
            for row in rows:
                if row["status"] in base.PENDING:
                    if unsent:
                        conn.execute("UPDATE messaging_messages SET status = 'failed', reason = 'unsent' WHERE id = ?",
                                     (row["id"],))
                    else:
                        conn.execute("UPDATE messaging_messages SET text = ?, edited_at = ? WHERE id = ?",
                                     (new_text, now, row["id"]))
                elif row["status"] in ("delivered", "delivering"):
                    _insert_message(conn, {
                        "provider_id": provider_id, "conversation_id": row["conversation_id"],
                        "binding_id": row["binding_id"], "session_uuid": row["session_uuid"], "direction": "in",
                        "kind": "note", "provider_message_id": f"{provider_message_id}#{event_id}",
                        "event_id": event_id, "sent_at": now, "text": note_for(row["text"]), "status": "queued"})
                else:
                    continue
                if row["session_uuid"]:
                    touched.append(row["session_uuid"])
            conn.execute("UPDATE messaging_providers SET cursor = MAX(cursor, ?), updated_at = ? WHERE id = ?",
                         (event_id, now, provider_id))
        if touched:
            base._changed(conn)
    return sorted(set(touched))


def advance_cursor(provider_id: str, event_id: int) -> None:
    with closing(base._conn()) as conn:
        with transaction(conn):
            conn.execute("UPDATE messaging_providers SET cursor = MAX(cursor, ?) WHERE id = ?", (event_id, provider_id))


def pending_for(session_uuid: str) -> List[Dict[str, Any]]:
    with closing(base._conn()) as conn:
        return base._rows(conn.execute("SELECT * FROM messaging_messages WHERE session_uuid = ? AND direction = 'in' AND "
                                  "status IN ('queued','held') ORDER BY received_at, id", (session_uuid,)))


def set_status(row_ids: Sequence[str], status: str, *, reason: Optional[str] = None, batch_id: Optional[str] = None,
               only_from: Sequence[str] = ()) -> List[str]:
    if not row_ids:
        return []
    now = time.time()
    with closing(base._conn()) as conn:
        moved: List[str] = []
        with transaction(conn):
            for rid in row_ids:
                guard = f" AND status IN ({','.join('?' * len(only_from))})" if only_from else ""
                n = conn.execute(f"UPDATE messaging_messages SET status = ?, reason = ?, batch_id = COALESCE(?, batch_id), "
                                 f"delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END WHERE id = ?{guard}",
                                 [status, reason, batch_id, status, now, rid, *only_from]).rowcount
                if n:
                    moved.append(rid)
        if moved:
            base._changed(conn)
        return moved


def recover_uncertain() -> int:
    with closing(base._conn()) as conn:
        with transaction(conn):
            n = conn.execute("UPDATE messaging_messages SET status = 'failed', reason = 'delivery_uncertain' "
                             "WHERE status = 'delivering'").rowcount
        base._changed(conn)
        return n


def insert_outbound(row: Dict[str, Any]) -> str:
    row_id = base.new_id("m_", 16)
    with closing(base._conn()) as conn:
        with transaction(conn):
            _insert_message(conn, {"id": row_id, "direction": "out", "status": "queued", **row})
        base._changed(conn)
    return row_id


def finish_outbound(row_id: str, *, status: str, reason: Optional[str] = None,
                    provider_message_id: Optional[str] = None, sent_at: Optional[float] = None) -> None:
    with closing(base._conn()) as conn:
        with transaction(conn):
            conn.execute("UPDATE messaging_messages SET status = ?, reason = ?, provider_message_id = COALESCE(?, "
                         "provider_message_id), sent_at = COALESCE(?, sent_at), delivered_at = CASE WHEN ? = 'delivered' "
                         "THEN ? ELSE delivered_at END WHERE id = ?",
                         (status, reason, provider_message_id, sent_at, status, time.time(), row_id))
        base._changed(conn)


def record_replay_proof(provider_id: str, *, at: Optional[float] = None) -> None:
    now = time.time() if at is None else at
    with closing(base._conn()) as conn:
        with transaction(conn):
            conn.execute("UPDATE messaging_providers SET replay_proven_at = MAX(COALESCE(replay_proven_at, 0), ?) "
                         "WHERE id = ?", (now, provider_id))
        base._changed(conn)


def reply_binding(provider_id: str, provider_message_id: Optional[str]) -> Optional[str]:
    if not provider_message_id:
        return None
    with closing(base._conn()) as conn:
        row = conn.execute("SELECT binding_id FROM messaging_messages WHERE provider_id = ? AND direction = 'out' AND "
                           "kind = 'message' AND provider_message_id = ?", (provider_id, provider_message_id)).fetchone()
        return row[0] if row and row[0] else None


def last_traffic(provider_id: str) -> Dict[str, Optional[float]]:
    with closing(base._conn()) as conn:
        inbound = conn.execute("SELECT MAX(received_at) FROM messaging_messages WHERE provider_id = ? "
                               "AND direction = 'in' AND kind = 'message'", (provider_id,)).fetchone()[0]
        outbound = conn.execute("SELECT MAX(delivered_at) FROM messaging_messages WHERE provider_id = ? "
                                "AND direction = 'out' AND status = 'delivered'", (provider_id,)).fetchone()[0]
    return {"last_inbound_at": inbound, "last_outbound_at": outbound}


def count_since(*, since: float, direction: str, conversation_id: Optional[str] = None,
                binding_id: Optional[str] = None, provider_id: Optional[str] = None,
                accepted_only: bool = False) -> int:
    clauses, args = ["direction = ?", "received_at >= ?", "kind = 'message'"], [direction, since]
    for col, val in (("conversation_id", conversation_id), ("binding_id", binding_id), ("provider_id", provider_id)):
        if val is not None:
            clauses.append(f"{col} = ?")
            args.append(val)
    if accepted_only:
        clauses.append("(status != 'failed' OR reason NOT IN ('wrong_conversation','not_owner','weak_identity',"
                       "'not_routable','provider_disabled','no_inbound_binding','empty','rate_limited','no_target'))")
    with closing(base._conn()) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM messaging_messages WHERE {' AND '.join(clauses)}", args).fetchone()[0])


def list_messages(*, binding_id: Optional[str] = None, status: Optional[str] = None, before: Optional[float] = None,
                  limit: int = 100) -> List[Dict[str, Any]]:
    clauses, args = ["1 = 1"], []
    for col, val in (("binding_id", binding_id), ("status", status)):
        if val:
            clauses.append(f"{col} = ?")
            args.append(val)
    if before is not None:
        clauses.append("received_at < ?")
        args.append(before)
    with closing(base._conn()) as conn:
        return base._rows(conn.execute(f"SELECT * FROM messaging_messages WHERE {' AND '.join(clauses)} "
                                  "ORDER BY received_at DESC, id DESC LIMIT ?", [*args, max(1, min(500, limit))]))


def get_message(row_id: str) -> Optional[Dict[str, Any]]:
    with closing(base._conn()) as conn:
        row = conn.execute("SELECT * FROM messaging_messages WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None


NOT_RETRIABLE = frozenset({"unsent", "not_owner", "weak_identity", "wrong_conversation", "not_routable", "empty"})


def retry(row_id: str) -> Optional[Dict[str, Any]]:
    with closing(base._conn()) as conn:
        with transaction(conn):
            n = conn.execute(
                "UPDATE messaging_messages SET status = 'queued', reason = NULL WHERE id = ? AND direction = 'in' AND "
                f"status = 'failed' AND reason NOT IN ({','.join('?' * len(NOT_RETRIABLE))}) AND binding_id IN "
                "(SELECT id FROM messaging_bindings)", (row_id, *sorted(NOT_RETRIABLE))).rowcount
        if not n:
            return None
        base._changed(conn)
    return get_message(row_id)


def claim_notice(conversation_id: str, notice: str, episode: str) -> bool:
    with closing(base._conn()) as conn:
        with transaction(conn):
            n = conn.execute("INSERT OR IGNORE INTO messaging_notices (conversation_id, notice, episode, sent_at) "
                             "VALUES (?,?,?,?)", (conversation_id, notice, episode, time.time())).rowcount
        return n == 1
