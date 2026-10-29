
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Optional

from src.core.crosstalk import store

THREADS_LIMIT = 50
THREADS_MAX = 200
MESSAGES_LIMIT = 200
MESSAGES_MAX = 500
PREVIEW_CHARS = 160


class HistoryError(ValueError):
    pass


def redact(value: Any) -> Any:
    from src.core.mcp.read_tools import scrub
    return scrub(value)


def _clamp(limit: int, maximum: int) -> int:
    return min(max(int(limit), 1), maximum)


def _session_keys(conn: sqlite3.Connection, session: Optional[str], session_row: Optional[int]) -> list[str]:
    keys: list[str] = [session] if session else []
    lookups = []
    if session:
        lookups.append(('SELECT session_uuid FROM sessions WHERE session_uuid=?', (session,)))
    if session_row is not None:
        lookups.append(('SELECT session_uuid FROM sessions WHERE id=?', (session_row,)))
    for sql, args in lookups:
        try:
            row = conn.execute(sql, args).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row and row[0] and row[0] not in keys:
            keys.append(row[0])
    return keys


def _filters(conn: sqlite3.Connection, *, session: Optional[str], session_row: Optional[int],
             project: Optional[int], participant: Optional[str]) -> tuple[str, list[Any]]:
    clauses = ["m.source != 'system'"]
    args: list[Any] = []
    if session is not None or session_row is not None:
        keys = _session_keys(conn, session, session_row)
        if not keys:
            return '1=0', []
        marks = ','.join('?' * len(keys))
        clauses.append(f'(m.sender_id IN ({marks}) OR m.receiver_id IN ({marks}) OR m.sender_uuid IN ({marks}) '
                       f'OR m.receiver_uuid IN ({marks}) OR m.sender_key IN ({marks}) OR m.receiver_key IN ({marks}))')
        args.extend(keys * 6)
    if project is not None:
        clauses.append('(m.sender_uuid IN (SELECT session_uuid FROM sessions WHERE project_id=?) '
                       'OR m.receiver_uuid IN (SELECT session_uuid FROM sessions WHERE project_id=?))')
        args.extend([project, project])
    if participant is not None:
        clauses.append('(m.sender_key=? OR m.receiver_key=?)')
        args.extend([participant, participant])
    return ' AND '.join(clauses), args


def _projects_of(conn: sqlite3.Connection, uuids: set[str]) -> dict[str, dict]:
    if not uuids:
        return {}
    marks = ','.join('?' * len(uuids))
    try:
        rows = conn.execute(f'''SELECT s.session_uuid, p.id, p.display_name FROM sessions s JOIN projects p
            ON p.id = s.project_id WHERE s.session_uuid IN ({marks})''', tuple(uuids)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: {'id': row[1], 'name': row[2]} for row in rows}


def _participant(row: sqlite3.Row, side: str, projects: dict[str, dict]) -> dict:
    uuid = row[f'{side}_uuid']
    project = projects.get(uuid) if uuid else None
    return {'key': row[f'{side}_key'], 'id': row[f'{side}_id'], 'session_uuid': uuid,
            'name': row[f'{side}_name'] or row[f'{side}_id'], 'provider': row[f'{side}_provider'],
            'model': row[f'{side}_model'], 'project_id': project['id'] if project else None,
            'project_name': project['name'] if project else None}


def list_threads(*, session: Optional[str] = None, session_row: Optional[int] = None, project: Optional[int] = None,
                 participant: Optional[str] = None, before: Optional[float] = None,
                 limit: int = THREADS_LIMIT) -> dict:
    limit = _clamp(limit, THREADS_MAX)
    with closing(store._conn()) as conn:
        where, args = _filters(conn, session=session, session_row=session_row, project=project, participant=participant)
        having, tail = ('HAVING MAX(m.created_at) < ?', [before]) if before is not None else ('', [])
        groups = conn.execute(f'''SELECT m.thread, COUNT(*) AS n, MAX(m.created_at) AS last_at, MIN(m.created_at) AS first_at
            FROM crosstalk_messages m WHERE {where} GROUP BY m.thread {having}
            ORDER BY last_at DESC, m.thread LIMIT ?''', (*args, *tail, limit)).fetchall()
        lasts: list[sqlite3.Row] = []
        for group in groups:
            lasts.append(conn.execute('''SELECT * FROM crosstalk_messages WHERE thread=? AND source != 'system'
                ORDER BY created_at DESC, rowid DESC LIMIT 1''', (group['thread'],)).fetchone())
        uuids = {u for row in lasts for u in (row['sender_uuid'], row['receiver_uuid']) if u}
        projects = _projects_of(conn, uuids)
    threads = []
    for group, last in zip(groups, lasts):
        sides = sorted((_participant(last, 'sender', projects), _participant(last, 'receiver', projects)),
                       key=lambda card: str(card['key']))
        threads.append({'thread': group['thread'], 'participants': sides, 'message_count': group['n'],
                        'last_at': group['last_at'], 'first_at': group['first_at'],
                        'last_preview': last['text'][:PREVIEW_CHARS], 'last_sender_key': last['sender_key'],
                        'last_status': last['status']})
    next_before = threads[-1]['last_at'] if len(threads) == limit else None
    return redact({'threads': threads, 'next_before': next_before})


def thread_messages(thread: str, *, participant: Optional[str] = None, before: Optional[float] = None,
                    limit: int = MESSAGES_LIMIT) -> dict:
    limit = _clamp(limit, MESSAGES_MAX)
    with closing(store._conn()) as conn:
        clauses, args = ['thread=?'], [thread]
        if participant is not None:
            clauses.append('(sender_key=? OR receiver_key=?)')
            args.extend([participant, participant])
        if before is not None:
            clauses.append('created_at<?')
            args.append(before)
        rows = conn.execute(f'''SELECT * FROM crosstalk_messages WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, rowid DESC LIMIT ?''', (*args, limit)).fetchall()
    if not rows and before is None:
        raise HistoryError('no such thread')
    messages = [dict(row) for row in reversed(rows)]
    if participant is not None:
        store._confirm_read(participant, messages)
    next_before = messages[0]['created_at'] if len(messages) == limit else None
    return redact({'thread': thread, 'messages': messages, 'next_before': next_before})


def task_item_trail(task_item: int, *, limit: int = MESSAGES_LIMIT) -> dict:
    limit = _clamp(limit, MESSAGES_MAX)
    with closing(store._conn()) as conn:
        rows = conn.execute('''SELECT id,thread,sender_name,receiver_name,created_at,status,text FROM crosstalk_messages
            WHERE task_item=? AND source<>'system' ORDER BY created_at DESC, rowid DESC LIMIT ?''',
            (task_item, limit)).fetchall()
    messages = [{**{k: row[k] for k in ('id', 'thread', 'sender_name', 'receiver_name', 'created_at', 'status')},
                 'preview': ((row['text'] or '').strip().splitlines() or [''])[0][:PREVIEW_CHARS]}
                for row in reversed(rows)]
    return redact({'task_item': task_item, 'messages': messages})
