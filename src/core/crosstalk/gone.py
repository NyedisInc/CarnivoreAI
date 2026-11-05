
from __future__ import annotations

import secrets
import sqlite3
import time
from contextlib import closing

import structlog

from src.core.crosstalk import store, waiting_reads
from src.core.db import DatastoreUnreadableError, transaction

logger = structlog.get_logger(__name__)

RECEIVER_GONE = 'receiver_gone'

RECEIVER_TORN_DOWN = 'receiver_torn_down'
DROP_NOTICE_TAIL = f'dropped: {RECEIVER_TORN_DOWN}'


def gone_message(to: str) -> str:
    return (f'{RECEIVER_GONE}: {to} is no longer running and is not asleep (torn down or closed); nothing was sent. '
            'Use agents_lookup to find who is live now.')


def is_known_gone(to: str) -> bool:
    handle = (to or '').strip().lstrip('@')
    if not handle:
        return False
    try:
        with closing(store._conn()) as conn:
            row = conn.execute(
                'SELECT 1 FROM crosstalk_messages WHERE receiver_id=? OR receiver_key=? OR sender_id=? OR sender_key=? '
                'UNION ALL SELECT 1 FROM sessions WHERE session_uuid=? OR tmux_name=? LIMIT 1',
                (handle, handle, handle, handle, handle, handle)).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning('crosstalk.gone_lookup_failed', error=type(exc).__name__)
        return False
    return row is not None


def drop_for_torn_down(receiver_key: str) -> int:
    if not receiver_key:
        return 0
    now = time.time()
    try:
        with closing(store._conn()) as conn, transaction(conn):
            rows = conn.execute(f"SELECT * FROM crosstalk_messages WHERE receiver_key=? AND status IN ('queued','held') "
                                f"AND source IN ({waiting_reads.NOTICE_SOURCES},'system') ORDER BY created_at", (receiver_key,)).fetchall()
            senders: dict[str, list[sqlite3.Row]] = {}
            for item in rows:
                conn.execute("UPDATE crosstalk_messages SET status='failed', reason=? WHERE id=?", (RECEIVER_TORN_DOWN, item['id']))
                if item['source'] != 'peer' and item['source'] != 'system':
                    senders.setdefault(item['sender_key'], []).append(item)
            for sender_key, items in senders.items():
                first = items[0]
                external = sender_key.startswith('mcp-token:') or sender_key == 'owner'
                ids = ', '.join(i['id'] for i in items)
                conn.execute('''INSERT INTO crosstalk_messages
                    (id,source,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_uuid,receiver_epoch,
                     sender_name,sender_provider,text,in_reply_to,status,created_at,expires_at,delivered_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('m-' + secrets.token_urlsafe(12), 'system', first['thread'], 'crosstalk-system', sender_key,
                     'crosstalk-system', first['sender_id'], first['sender_uuid'], first['sender_epoch'],
                     'crosstalk', 'system', f"message {ids} to {first['receiver_id']} {DROP_NOTICE_TAIL}",
                     first['id'], 'delivered' if external else 'queued', now, now + store.MESSAGE_LIFETIME,
                     now if external else None))
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning('crosstalk.torn_down_drop_failed', error=type(exc).__name__)
        return 0
    if rows:
        store._notify()
    return len(rows)
