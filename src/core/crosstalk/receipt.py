
from __future__ import annotations

import sqlite3

from src.core.crosstalk import waiting_reads

PENDING_PREFIX = 'native_receipt_pending:'
HELD_NATIVE = f"status='held' AND reason LIKE '{PENDING_PREFIX}%'"
ANSWERED = """EXISTS (SELECT 1 FROM crosstalk_messages r WHERE r.in_reply_to=crosstalk_messages.id
    AND r.sender_key=crosstalk_messages.receiver_key)"""
DUE_ANSWERED = f"source IN ({waiting_reads.NOTICE_SOURCES}) AND expires_at<=? AND {ANSWERED}"


def settle_held_native(conn: sqlite3.Connection, where: str, params: tuple, now: float) -> list[dict]:
    ids = [r[0] for r in conn.execute(f'SELECT id FROM crosstalk_messages WHERE {HELD_NATIVE} AND ({where})', params)]
    if not ids:
        return []
    marks = ','.join('?' * len(ids))
    conn.execute(f"UPDATE crosstalk_messages SET status='delivered', reason=NULL, delivered_at=? WHERE id IN ({marks})",
                 (now, *ids))
    return [dict(r) for r in conn.execute(f'SELECT * FROM crosstalk_messages WHERE id IN ({marks})', ids)]
