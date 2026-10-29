
from __future__ import annotations

import asyncio
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any

from src.config import settings
from src.core import resource_push
from src.core.crosstalk import card_push
from src.core.crosstalk import landing
from src.core.db import connect, db_path_for, transaction
from src.core.resource_push.topics import CROSSTALK

MAX_TEXT = 20_000
RATE_PER_MINUTE = 60
QUEUE_PER_RECEIVER = 50
LOOP_PER_TEN_MINUTES = 30
MESSAGE_LIFETIME = 24 * 3600
_change_event: asyncio.Event | None = None
_change_loop: asyncio.AbstractEventLoop | None = None
_change_seq = 0
_change_lock = threading.Lock()


def _notify() -> None:
    global _change_event, _change_seq
    with _change_lock:
        _change_seq += 1
    resource_push.notify(CROSSTALK)
    if _change_event is not None and _change_loop is not None:
        try:
            _change_loop.call_soon_threadsafe(_change_event.set)
        except RuntimeError:
            pass


def version() -> int:
    return _change_seq


async def changed(timeout: float, since: int) -> bool:
    global _change_event, _change_loop
    loop = asyncio.get_running_loop()
    if _change_seq != since:
        return True
    if _change_event is None or _change_event.is_set() or _change_loop is not loop:
        _change_event = asyncio.Event()
    _change_loop = loop
    event = _change_event
    try:
        await asyncio.wait_for(event.wait(), timeout)
        return True
    except asyncio.TimeoutError:
        return False


class BusRefused(ValueError):
    pass


def _conn() -> sqlite3.Connection:
    return connect(db_path_for(settings.get_state_dir()), create=False)


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def pair_key(left: str, right: str) -> str:
    return '|'.join(sorted((left, right)))


def _resume_parts(source: str) -> tuple[str, int, int, int, int]:
    parts = source.split('|')
    def generation(prefix: str) -> int:
        value = next((p[2:] for p in parts[1:] if p.startswith(prefix)), '0')
        return int(value) if value.isdecimal() else 0
    return (parts[0], generation('o='), generation('r='), generation('w='), generation('q='))


def _resume_source(base: str, outgoing: int, received: int, window_out: int, window_in: int) -> str:
    return f'{base}|o={outgoing}|r={received}|w={window_out}|q={window_in}'


def contact(left: str, right: str, left_epoch: int | None, right_epoch: int | None) -> bool:
    keys = sorted(((left, left_epoch), (right, right_epoch)))
    with closing(_conn()) as conn:
        row = conn.execute('SELECT left_epoch,right_epoch FROM crosstalk_contacts WHERE pair_key=?',
                           (pair_key(left, right),)).fetchone()
    return bool(row and row['left_epoch'] == keys[0][1] and row['right_epoch'] == keys[1][1])


def grant_contact(left: str, right: str, left_epoch: int | None, right_epoch: int | None,
                  *, source: str = 'owner') -> None:
    keys = sorted(((left, left_epoch), (right, right_epoch)))
    with closing(_conn()) as conn, transaction(conn):
        conn.execute('''INSERT INTO crosstalk_contacts
            (pair_key,left_key,right_key,left_epoch,right_epoch,granted_at,source,last_owner_input,paused)
            VALUES (?,?,?,?,?,?,?,?,0)
            ON CONFLICT(pair_key) DO UPDATE SET left_epoch=excluded.left_epoch,
            right_epoch=excluded.right_epoch, granted_at=excluded.granted_at, source=excluded.source,
            last_owner_input=excluded.last_owner_input, paused=0''',
            (pair_key(left, right), keys[0][0], keys[1][0], keys[0][1], keys[1][1], time.time(), source, time.time()))
    _notify()


def owner_input(session_key: str) -> list[tuple[str, int | None, int | None, int]]:
    updates = []
    with closing(_conn()) as conn, transaction(conn):
        rows = conn.execute('SELECT * FROM crosstalk_contacts WHERE left_key=? OR right_key=?',
                            (session_key, session_key)).fetchall()
        for row in rows:
            base, outgoing, received, window_out, window_in = _resume_parts(row['source'])
            if window_out >= 2**31 - 1:
                raise BusRefused('owner input generation exhausted')
            window_out += 1
            conn.execute('UPDATE crosstalk_contacts SET last_owner_input=?,source=? WHERE pair_key=?',
                         (time.time(), _resume_source(base, outgoing, received, window_out, window_in), row['pair_key']))
            other = row['right_key'] if row['left_key'] == session_key else row['left_key']
            updates.append((other, row['left_epoch'] if row['left_key'] == session_key else row['right_epoch'],
                            row['right_epoch'] if row['left_key'] == session_key else row['left_epoch'], window_out))
    _notify()
    return updates


def resume_pair(left: str, right: str) -> None:
    with closing(_conn()) as conn, transaction(conn):
        pair = pair_key(left, right)
        row = conn.execute('SELECT source FROM crosstalk_contacts WHERE pair_key=?', (pair,)).fetchone()
        if row is None:
            raise BusRefused('conversation contact no longer exists')
        base, outgoing, received, window_out, window_in = _resume_parts(row['source'])
        if outgoing >= 2**31 - 1:
            raise BusRefused('resume generation exhausted')
        conn.execute('UPDATE crosstalk_contacts SET paused=0,last_owner_input=?,source=? WHERE pair_key=?',
                     (time.time(), _resume_source(base, outgoing + 1, received, window_out, window_in), pair))
    _notify()


def peer_control_markers(left: str, right: str, left_epoch: int | None, right_epoch: int | None) -> tuple[int, int]:
    keys = sorted(((left, left_epoch), (right, right_epoch)))
    with closing(_conn()) as conn:
        row = conn.execute('SELECT source,left_epoch,right_epoch FROM crosstalk_contacts WHERE pair_key=?',
                           (pair_key(left, right),)).fetchone()
    if row is None or (row['left_epoch'], row['right_epoch']) != (keys[0][1], keys[1][1]):
        return (0, 0)
    _, outgoing, _, window_out, _ = _resume_parts(row['source'])
    return (outgoing, window_out)


def apply_peer_control(left: str, right: str, left_epoch: int | None, right_epoch: int | None,
                       *, resume_generation: int = 0, window_generation: int = 0) -> bool:
    if any(not isinstance(v, int) or v < 0 or v >= 2**31 for v in (resume_generation, window_generation)):
        raise BusRefused('invalid peer loop generation')
    keys = sorted(((left, left_epoch), (right, right_epoch)))
    pair = pair_key(left, right)
    with closing(_conn()) as conn, transaction(conn):
        row = conn.execute('SELECT source,left_epoch,right_epoch FROM crosstalk_contacts WHERE pair_key=?',
                           (pair,)).fetchone()
        if row is None or (row['left_epoch'], row['right_epoch']) != (keys[0][1], keys[1][1]):
            return False
        base, outgoing, received, window_out, window_in = _resume_parts(row['source'])
        resume_new = resume_generation > received
        window_new = window_generation > window_in
        if not resume_new and not window_new:
            return False
        conn.execute('UPDATE crosstalk_contacts SET paused=CASE WHEN ? THEN 0 ELSE paused END,last_owner_input=?,source=? WHERE pair_key=?',
                     (int(resume_new), time.time(), _resume_source(base, outgoing,
                      resume_generation if resume_new else received, window_out,
                      window_generation if window_new else window_in), pair))
    _notify()
    return True


def reserve(*, sender: dict, receiver: dict, text: str, thread: str | None = None,
            in_reply_to: str | None = None, expect_reply: bool = False, source: str = 'crosstalk',
            spawn_task: bool = False, task_item: int | None = None) -> dict:
    if task_item is not None and (isinstance(task_item, bool) or not isinstance(task_item, int) or task_item < 1):
        raise BusRefused('task_item must be a Task Manager item id (a whole number from 1)')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise BusRefused(f'text must contain 1 to {MAX_TEXT} characters')
    if thread is not None and (not isinstance(thread, str)
                               or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', thread)):
        raise BusRefused('thread must be a single-line token of at most 100 characters')
    if in_reply_to is not None and (not isinstance(in_reply_to, str) or len(in_reply_to) > 100):
        raise BusRefused('in_reply_to must be a message id')
    now = time.time()
    msg_id = 'm-' + secrets.token_urlsafe(12)
    loop_paused = False
    with closing(_conn()) as conn, transaction(conn):
        pair = pair_key(sender['key'], receiver['key'])
        row = conn.execute('SELECT * FROM crosstalk_contacts WHERE pair_key=?', (pair,)).fetchone()
        if row is None:
            raise BusRefused('first contact needs owner approval')
        epochs = {row['left_key']: row['left_epoch'], row['right_key']: row['right_epoch']}
        if epochs.get(sender['key']) != sender['epoch'] or epochs.get(receiver['key']) != receiver['epoch']:
            raise BusRefused('contact grant belongs to a previous pane instance')
        if row['paused']:
            raise BusRefused('conversation paused by loop breaker; owner must resume it')
        if conn.execute('SELECT COUNT(*) FROM crosstalk_messages WHERE sender_key=? AND created_at>?',
                        (sender['key'], now - 60)).fetchone()[0] >= RATE_PER_MINUTE:
            raise BusRefused('sender rate limit: 60 messages per minute')
        if conn.execute("SELECT COUNT(*) FROM crosstalk_messages WHERE receiver_key=? AND status IN ('queued','held','delivering')",
                        (receiver['key'],)).fetchone()[0] >= QUEUE_PER_RECEIVER:
            raise BusRefused('receiver queue is full (50 messages)')
        repeat = conn.execute('''SELECT id FROM crosstalk_messages WHERE sender_key=? AND receiver_key=?
            AND text=? AND created_at>? ORDER BY created_at DESC LIMIT 1''',
            (sender['key'], receiver['key'], text, now - 60)).fetchone()
        if repeat:
            raise BusRefused(f'identical message already sent in the last minute: {repeat[0]}')
        since = max(now - 600, row['last_owner_input'])
        count = conn.execute('''SELECT COUNT(*) FROM crosstalk_messages WHERE created_at>=? AND
            ((sender_key=? AND receiver_key=?) OR (sender_key=? AND receiver_key=?))''',
            (since, sender['key'], receiver['key'], receiver['key'], sender['key'])).fetchone()[0]
        if count >= LOOP_PER_TEN_MINUTES:
            conn.execute('UPDATE crosstalk_contacts SET paused=1 WHERE pair_key=?', (pair,))
            loop_paused = True
        if not loop_paused and in_reply_to:
            parent = conn.execute('SELECT thread,sender_key,receiver_key,task_item FROM crosstalk_messages WHERE id=?',
                                  (in_reply_to,)).fetchone()
            if not parent or {parent['sender_key'], parent['receiver_key']} != {sender['key'], receiver['key']}:
                raise BusRefused('reply target is not a message in this pair')
            if task_item is None:
                task_item = parent['task_item']
            if thread and thread != parent['thread']:
                raise BusRefused('thread does not match reply target')
            thread = parent['thread']
        if not loop_paused and thread:
            member = conn.execute('SELECT sender_key,receiver_key FROM crosstalk_messages WHERE thread=? LIMIT 1',
                                  (thread,)).fetchone()
            if member and {member['sender_key'], member['receiver_key']} != {sender['key'], receiver['key']}:
                raise BusRefused('thread belongs to another pair')
        elif not loop_paused:
            thread = 't-' + secrets.token_urlsafe(12)
        if not loop_paused:
            conn.execute('''INSERT INTO crosstalk_messages
            (id,thread,sender_key,receiver_key,sender_id,receiver_id,sender_uuid,receiver_uuid,
            sender_epoch,receiver_epoch,sender_name,sender_provider,sender_model,text,in_reply_to,
            receiver_name,receiver_provider,receiver_model,expect_reply,status,created_at,expires_at,source,
            agent_sent,spawn_task,task_item)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)''',
                (msg_id, thread, sender['key'], receiver['key'], sender['id'], receiver['id'],
                 sender.get('uuid'), receiver.get('uuid'), sender['epoch'], receiver['epoch'],
                 sender['name'], sender['provider'], sender.get('model'), text, in_reply_to,
                 receiver['name'], receiver['provider'], receiver.get('model'),
                 int(expect_reply), 'queued', now, now + MESSAGE_LIFETIME, source, int(spawn_task), task_item))
        result = _row(conn.execute('SELECT * FROM crosstalk_messages WHERE id=?', (msg_id,)).fetchone()) if not loop_paused else None
    _notify()
    _notify_swarm(sender['key'], receiver['key'])
    if loop_paused:
        raise BusRefused('conversation paused by loop breaker after 30 messages without owner input; owner must resume it')
    return result or {}


def get(message_id: str) -> dict | None:
    with closing(_conn()) as conn:
        return _row(conn.execute('SELECT * FROM crosstalk_messages WHERE id=?', (message_id,)).fetchone())


def accept_peer(*, peer_install_id: str, message: dict, sender: dict, receiver: dict) -> dict:
    native_key = f'peer:{peer_install_id}:{message["id"]}'
    now = time.time()
    with closing(_conn()) as conn, transaction(conn):
        existing = conn.execute('SELECT * FROM crosstalk_messages WHERE native_key=?', (native_key,)).fetchone()
        if existing is not None:
            if (existing['sender_key'] != sender['key'] or existing['receiver_key'] != receiver['key']
                    or existing['sender_epoch'] != sender['epoch'] or existing['receiver_epoch'] != receiver['epoch']
                    or existing['text'] != message['text'] or existing['thread'] != message['thread']
                    or existing['in_reply_to'] != message.get('in_reply_to')
                    or existing['sender_name'] != sender['name'] or existing['sender_provider'] != sender['provider']
                    or existing['sender_model'] != sender.get('model')):
                raise BusRefused('peer receipt id was reused with different participants or text')
            return dict(existing)
        if conn.execute("SELECT COUNT(*) FROM crosstalk_messages WHERE sender_key=? AND created_at>?",
                        (sender['key'], now - 60)).fetchone()[0] >= RATE_PER_MINUTE:
            raise BusRefused('sender rate limit: 60 messages per minute')
        if conn.execute("SELECT COUNT(*) FROM crosstalk_messages WHERE receiver_key=? AND status IN ('queued','held','delivering')",
                        (receiver['key'],)).fetchone()[0] >= QUEUE_PER_RECEIVER:
            raise BusRefused('receiver queue is full (50 messages)')
        if conn.execute('''SELECT 1 FROM crosstalk_messages WHERE sender_key=? AND receiver_key=?
                           AND text=? AND created_at>? LIMIT 1''',
                        (sender['key'], receiver['key'], message['text'], now - 60)).fetchone():
            raise BusRefused('identical message already sent in the last minute')
        pair = pair_key(sender['key'], receiver['key'])
        ordered = sorted(((sender['key'], sender['epoch']), (receiver['key'], receiver['epoch'])))
        conn.execute('''INSERT INTO crosstalk_contacts
            (pair_key,left_key,right_key,left_epoch,right_epoch,granted_at,source,last_owner_input,paused)
            VALUES (?,?,?,?,?,?,?,?,0)
            ON CONFLICT(pair_key) DO UPDATE SET left_epoch=excluded.left_epoch,right_epoch=excluded.right_epoch,
            source=CASE WHEN left_epoch IS excluded.left_epoch AND right_epoch IS excluded.right_epoch
                THEN source ELSE excluded.source END,
            last_owner_input=CASE WHEN left_epoch IS excluded.left_epoch AND right_epoch IS excluded.right_epoch
                THEN last_owner_input ELSE excluded.last_owner_input END,
            paused=CASE WHEN left_epoch IS excluded.left_epoch AND right_epoch IS excluded.right_epoch
                THEN paused ELSE 0 END''',
            (pair, ordered[0][0], ordered[1][0], ordered[0][1], ordered[1][1], now, 'peer', now))
        contact_row = conn.execute('SELECT paused,last_owner_input FROM crosstalk_contacts WHERE pair_key=?',
                                   (pair,)).fetchone()
        since = max(now - 600, contact_row['last_owner_input'])
        count = conn.execute('''SELECT COUNT(*) FROM crosstalk_messages WHERE created_at>=? AND
            ((sender_key=? AND receiver_key=?) OR (sender_key=? AND receiver_key=?))''',
            (since, sender['key'], receiver['key'], receiver['key'], sender['key'])).fetchone()[0]
        loop_paused = bool(contact_row['paused']) or count >= LOOP_PER_TEN_MINUTES
        if loop_paused:
            conn.execute('UPDATE crosstalk_contacts SET paused=1 WHERE pair_key=?', (pair,))
        if not loop_paused and message.get('in_reply_to'):
            parent = conn.execute('''SELECT sender_key,receiver_key,thread FROM crosstalk_messages
                                     WHERE id=?''', (message['in_reply_to'],)).fetchone()
            if (parent is None or parent['sender_key'] != receiver['key']
                    or parent['receiver_key'] != sender['key'] or parent['thread'] != message['thread']):
                raise BusRefused('reply target is not a message in this pair and thread')
        if not loop_paused:
            local_id = 'm-peer-' + secrets.token_urlsafe(12)
            conn.execute('''INSERT INTO crosstalk_messages
            (id,native_key,thread,sender_key,receiver_key,sender_id,receiver_id,sender_uuid,receiver_uuid,
             sender_epoch,receiver_epoch,sender_name,sender_provider,sender_model,text,in_reply_to,
             receiver_name,receiver_provider,receiver_model,expect_reply,status,created_at,expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (local_id, native_key, message['thread'], sender['key'], receiver['key'], sender['id'], receiver['id'],
                 sender['uuid'], receiver['uuid'], sender['epoch'], receiver['epoch'], sender['name'],
                 sender['provider'], sender.get('model'), message['text'], message.get('in_reply_to'),
                 receiver['name'], receiver['provider'], receiver.get('model'), int(bool(message.get('expect_reply'))),
                 'queued', now, min(float(message['expires_at']), now + MESSAGE_LIFETIME)))
            conn.execute("UPDATE crosstalk_messages SET source='peer' WHERE id=?", (local_id,))
            result = dict(conn.execute('SELECT * FROM crosstalk_messages WHERE id=?', (local_id,)).fetchone())
    _notify()
    if loop_paused:
        raise BusRefused('conversation paused by loop breaker after 30 messages without owner input; owner must resume it')
    return result


def peer_receipt(peer_install_id: str, origin_id: str) -> dict | None:
    with closing(_conn()) as conn:
        return _row(conn.execute('SELECT * FROM crosstalk_messages WHERE native_key=?',
                                 (f'peer:{peer_install_id}:{origin_id}',)).fetchone())


def peer_reply_origin_id(parent_id: str, peer_install_id: str, *, sender_key: str, receiver_key: str,
                         thread: str) -> str | None:
    with closing(_conn()) as conn:
        row = conn.execute('''SELECT native_key FROM crosstalk_messages WHERE id=? AND source='peer'
                              AND sender_key=? AND receiver_key=? AND thread=?''',
                           (parent_id, receiver_key, sender_key, thread)).fetchone()
    prefix = f'peer:{peer_install_id}:'
    key = row[0] if row else None
    return key[len(prefix):] if isinstance(key, str) and key.startswith(prefix) else None


def messages_for(key: str, *, since: float = 0, thread: str | None = None, limit: int = 100, newest_first: bool = False) -> list[dict]:
    order = 'DESC' if newest_first else 'ASC'
    with closing(_conn()) as conn:
        rows = conn.execute(f'''SELECT * FROM crosstalk_messages WHERE (sender_key=? OR receiver_key=?)
            AND created_at>? AND (? IS NULL OR thread=?) ORDER BY created_at {order} LIMIT ?''',
            (key, key, since, thread, thread, min(max(limit, 1), 200))).fetchall()
    result = [dict(row) for row in rows]
    _confirm_read(key, result)
    return result


def pending_count(key: str) -> int:
    with closing(_conn()) as conn:
        return conn.execute("SELECT COUNT(*) FROM crosstalk_messages WHERE receiver_key=? AND status IN ('queued','held','delivering')",
                            (key,)).fetchone()[0]


def _confirm_read(key: str, rows: list[dict]) -> None:
    ids = [r['id'] for r in rows if r['receiver_key'] == key and r['status'] == 'held'
           and str(r['reason'] or '').startswith('native_receipt_pending:')]
    if not ids:
        return
    settled = []
    with closing(_conn()) as conn, transaction(conn):
        for message_id in ids:
            if conn.execute("""UPDATE crosstalk_messages SET status='delivered', reason=NULL, delivered_at=?
                WHERE id=? AND status='held' AND receiver_key=? AND reason LIKE 'native_receipt_pending:%'""",
                            (time.time(), message_id, key)).rowcount:
                settled.append(message_id)
    if not settled:
        return
    keys = set()
    for row in rows:
        if row['id'] in settled:
            row.update(status='delivered', reason=None)
            keys.update((row['sender_key'], row['receiver_key']))
            card_push.announce(row)
    _notify()
    _notify_swarm(*keys)


def recent_for(key: str, limit: int = 200) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute('SELECT * FROM crosstalk_messages WHERE sender_key=? OR receiver_key=? '
                            'ORDER BY created_at DESC LIMIT ?', (key, key, min(max(limit, 1), 200))).fetchall()
    return [dict(row) for row in reversed(rows)]


def _notify_swarm(*keys: str) -> None:
    from src.core.swarm import activity, push
    activity.mark_talking(push.notify_keys(*keys))


def owner_messages(session_id: str, *, since: float = 0, limit: int = 200) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute('''SELECT * FROM (SELECT * FROM crosstalk_messages WHERE
            (sender_id=? OR receiver_id=? OR sender_uuid=? OR receiver_uuid=?)
            AND created_at>? ORDER BY created_at DESC LIMIT ?) ORDER BY created_at''',
            (session_id, session_id, session_id, session_id, since, min(max(limit, 1), 500))).fetchall()
    return [dict(row) for row in rows]


def deliver_external(message_id: str) -> None:
    with closing(_conn()) as conn, transaction(conn):
        conn.execute("UPDATE crosstalk_messages SET status='delivered', delivered_at=? WHERE id=? AND status='queued'",
                     (time.time(), message_id))
    _notify()


def claim_for(receiver_key: str) -> dict | None:
    with closing(_conn()) as conn, transaction(conn):
        row = conn.execute('''SELECT * FROM crosstalk_messages WHERE receiver_key=? AND status IN ('queued','held')
            AND expires_at>? ORDER BY CASE WHEN reason LIKE 'native_receipt_pending:%' THEN 1 ELSE 0 END,
            created_at LIMIT 1''', (receiver_key, time.time())).fetchone()
        if row:
            conn.execute("UPDATE crosstalk_messages SET status='delivering' WHERE id=?", (row['id'],))
    if row is None:
        return None
    _notify()
    return dict(row)


def recover_uncertain() -> int:
    with closing(_conn()) as conn, transaction(conn):
        count = conn.execute("""UPDATE crosstalk_messages SET
            status=CASE WHEN reason LIKE 'native_receipt_pending:%' THEN 'held' ELSE 'failed' END,
            reason=CASE WHEN reason LIKE 'native_receipt_pending:%' THEN reason
                ELSE 'server restarted during delivery; result uncertain' END
            WHERE status='delivering'""").rowcount
    if count:
        _notify()
    return count


def mark_native_pending(message_id: str, native_msg_id: str, *, conversation_id: str | None = None) -> bool:
    if not re.fullmatch(r'[0-9a-f]{32}', native_msg_id):
        raise ValueError('invalid native receipt id')
    if conversation_id is not None and not re.fullmatch(r'[0-9a-fA-F-]{36}', conversation_id):
        raise ValueError('invalid native conversation id')
    reason = 'native_receipt_pending:' + native_msg_id
    if conversation_id is not None:
        reason += ':' + conversation_id
    with closing(_conn()) as conn, transaction(conn):
        count = conn.execute("""UPDATE crosstalk_messages SET reason=?
            WHERE id=? AND status='delivering'""",
            (reason, message_id)).rowcount
    if count:
        _notify()
    return bool(count)


def finish(message_id: str, status: str, reason: str | None = None) -> None:
    if status not in ('held', 'delivered', 'failed', 'expired'):
        raise ValueError('invalid delivery result')
    with closing(_conn()) as conn, transaction(conn):
        prior = conn.execute("SELECT * FROM crosstalk_messages WHERE id=? AND status='delivering'", (message_id,)).fetchone()
        now = time.time()
        changed = conn.execute('''UPDATE crosstalk_messages SET status=?,reason=?,delivered_at=?
            WHERE id=? AND status='delivering' ''',
            (status, reason, now if status == 'delivered' else None, message_id)).rowcount
        if status == 'delivered' and changed and prior is not None:
            landing.stamp(conn, prior, now)
        row = conn.execute('SELECT * FROM crosstalk_messages WHERE id=?', (message_id,)).fetchone()
    _notify()
    if row is not None:
        _notify_swarm(row['sender_key'], row['receiver_key'])
        if changed and status == 'delivered':
            card_push.announce(dict(row))


def expire() -> list[str]:
    now = time.time()
    wake: list[str] = []
    with closing(_conn()) as conn, transaction(conn):
        due = conn.execute("SELECT * FROM crosstalk_messages WHERE source IN ('crosstalk','peer') AND status IN ('queued','held') AND expires_at<=?", (now,)).fetchall()
        for item in due:
            conn.execute("UPDATE crosstalk_messages SET status='expired',reason='receiver did not become ready within 24 hours' WHERE id=?", (item['id'],))
            if item['source'] == 'peer':
                continue
            external = item['sender_key'].startswith('mcp-token:') or item['sender_key'] == 'owner'
            notice_id = 'm-' + secrets.token_urlsafe(12)
            conn.execute('''INSERT INTO crosstalk_messages
                (id,source,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_uuid,receiver_epoch,
                 sender_name,sender_provider,text,in_reply_to,status,created_at,expires_at,delivered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (notice_id, 'system', item['thread'], 'crosstalk-system', item['sender_key'],
                 'crosstalk-system', item['sender_id'], item['sender_uuid'], item['sender_epoch'],
                 'crosstalk', 'system', f"message {item['id']} to {item['receiver_id']} expired after 24 hours",
                 item['id'], 'delivered' if external else 'queued', now, now + MESSAGE_LIFETIME,
                 now if external else None))
            if not external:
                wake.append(item['sender_key'])
        system_expired = conn.execute("UPDATE crosstalk_messages SET status='expired',reason='status notice could not be delivered' WHERE source='system' AND status IN ('queued','held') AND expires_at<=?", (now,)).rowcount
        conn.execute("UPDATE crosstalk_watches SET status='expired' WHERE status='watching' AND expires_at<=?", (now,))
    if due or system_expired:
        _notify()
    return wake


def next_expiry() -> float | None:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT MIN(expires_at) FROM crosstalk_messages WHERE status IN ('queued','held')").fetchone()
    return row[0] if row else None


def watch(*, watcher_key: str, watcher_id: str, watcher_epoch: int | None,
          target_key: str, target_id: str,
          target_epoch: int | None, once: bool = True) -> dict:
    now = time.time()
    watch_id = 'w-' + secrets.token_urlsafe(12)
    with closing(_conn()) as conn, transaction(conn):
        conn.execute('''INSERT INTO crosstalk_watches
            (id,watcher_key,watcher_id,watcher_epoch,target_key,target_id,target_epoch,once,status,created_at,expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (watch_id, watcher_key, watcher_id, watcher_epoch, target_key, target_id, target_epoch, int(once),
             'watching', now, now + MESSAGE_LIFETIME))
    _notify()
    return {'id': watch_id, 'status': 'watching', 'target': target_id}


def repin(key: str, new_id: str, new_epoch: int | None) -> dict[str, int]:
    with closing(_conn()) as conn, transaction(conn):
        contacts = conn.execute('UPDATE crosstalk_contacts SET left_epoch=? WHERE left_key=?',
                                (new_epoch, key)).rowcount
        contacts += conn.execute('UPDATE crosstalk_contacts SET right_epoch=? WHERE right_key=?',
                                 (new_epoch, key)).rowcount
        pending = conn.execute("""UPDATE crosstalk_messages SET receiver_id=?, receiver_epoch=?
            WHERE receiver_key=? AND status IN ('queued','held')
            AND COALESCE(reason,'') NOT LIKE 'native_receipt_pending:%'""", (new_id, new_epoch, key)).rowcount
        delivered = conn.execute("UPDATE crosstalk_messages SET receiver_epoch=? WHERE receiver_key=? AND status='delivered'",
                                 (new_epoch, key)).rowcount
        watches = conn.execute('UPDATE crosstalk_watches SET watcher_id=?, watcher_epoch=? WHERE watcher_key=?',
                               (new_id, new_epoch, key)).rowcount
        watches += conn.execute('UPDATE crosstalk_watches SET target_id=?, target_epoch=? WHERE target_key=?',
                                (new_id, new_epoch, key)).rowcount
    _notify()
    return {'contacts': contacts, 'pending': pending, 'delivered': delivered, 'watches': watches}


def carry_contact_epochs(key: str, old_epoch: int | None, new_epoch: int | None) -> int:
    if old_epoch is None or new_epoch is None or old_epoch == new_epoch:
        return 0
    with closing(_conn()) as conn, transaction(conn):
        moved = conn.execute('UPDATE crosstalk_contacts SET left_epoch=? WHERE left_key=? AND left_epoch=?',
                             (new_epoch, key, old_epoch)).rowcount
        moved += conn.execute('UPDATE crosstalk_contacts SET right_epoch=? WHERE right_key=? AND right_epoch=?',
                              (new_epoch, key, old_epoch)).rowcount
    if moved:
        _notify()
    return moved


def watches_for(key: str) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute('SELECT * FROM crosstalk_watches WHERE watcher_key=? ORDER BY created_at', (key,)).fetchall()
    return [dict(row) for row in rows]


def notify_idle(target_key: str, target_epoch: int | None) -> list[str]:
    now = time.time()
    wake: list[str] = []
    with closing(_conn()) as conn, transaction(conn):
        watches = conn.execute('''SELECT * FROM crosstalk_watches
            WHERE target_key=? AND target_epoch IS ? AND status='watching' AND expires_at>?''',
            (target_key, target_epoch, now)).fetchall()
        for item in watches:
            conn.execute('''UPDATE crosstalk_watches SET status=CASE WHEN once=1 THEN 'notified' ELSE 'watching' END,
                notifications=notifications+1, notified_at=? WHERE id=?''', (now, item['id']))
            external = item['watcher_key'].startswith('mcp-token:') or item['watcher_key'] == 'owner'
            conn.execute('''INSERT INTO crosstalk_messages
                (id,source,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_epoch,
                 sender_name,sender_provider,text,status,created_at,expires_at,delivered_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('m-' + secrets.token_urlsafe(12), 'system', 't-watch-' + item['id'],
                 'crosstalk-system', item['watcher_key'], 'crosstalk-system', item['watcher_id'], item['watcher_epoch'],
                 'crosstalk', 'system', f"agent {item['target_id']} is idle",
                 'delivered' if external else 'queued', now, now + MESSAGE_LIFETIME,
                 now if external else None))
            if not external:
                wake.append(item['watcher_key'])
    if watches:
        _notify()
    return wake


def mirror_native(*, native_key: str, sender_id: str, receiver_id: str,
                  sender_uuid: str | None, receiver_uuid: str | None,
                  sender_name: str, text: str, sender_provider: str = 'claude',
                  sender_model: str | None = None, receiver_name: str | None = None,
                  receiver_provider: str | None = None, receiver_model: str | None = None,
                  thread: str | None = None,
                  status: str = 'delivered') -> dict:
    if status not in ('delivered', 'failed') or not native_key or not sender_id or not receiver_id:
        raise BusRefused('invalid native message record')
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise BusRefused('native message exceeds crosstalk size limit')
    now = time.time()
    msg_id = 'm-native-' + secrets.token_urlsafe(10)
    with closing(_conn()) as conn, transaction(conn):
        result = conn.execute('''INSERT OR IGNORE INTO crosstalk_messages
            (id,native_key,source,thread,sender_key,receiver_key,sender_id,receiver_id,
             sender_uuid,receiver_uuid,sender_name,sender_provider,sender_model,text,
             receiver_name,receiver_provider,receiver_model,status,created_at,expires_at,delivered_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (msg_id, native_key, 'claude_native', thread or ('t-native-' + native_key[:80]),
             sender_uuid or sender_id, receiver_uuid or receiver_id, sender_id, receiver_id,
             sender_uuid, receiver_uuid, sender_name, sender_provider, sender_model, text,
             receiver_name, receiver_provider, receiver_model,
             status, now, now + MESSAGE_LIFETIME, now if status == 'delivered' else None))
        row = conn.execute('SELECT * FROM crosstalk_messages WHERE native_key=?', (native_key,)).fetchone()
    if result.rowcount:
        _notify()
        if status == 'delivered':
            card_push.announce(dict(row))
    return dict(row)
