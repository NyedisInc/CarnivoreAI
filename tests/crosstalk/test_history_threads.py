
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import crosstalk_routes
from src.core.crosstalk import history, store
from src.core.db_steps import STEPS
from src.core.resource_push.topics import CROSSTALK

ALICE = {'key': 'uuid-a', 'id': 'ses_a', 'uuid': 'uuid-a', 'epoch': 1, 'name': 'Alice', 'provider': 'claude'}
BOB = {'key': 'uuid-b', 'id': 'ses_b', 'uuid': 'uuid-b', 'epoch': 2, 'name': 'Bob', 'provider': 'codex'}
CAROL = {'key': 'uuid-c', 'id': 'ses_c', 'uuid': 'uuid-c', 'epoch': 3, 'name': 'Carol', 'provider': 'claude'}
PEER = {'key': 'peer:x:uuid-p', 'id': 'remote:peer-x:p', 'uuid': None, 'epoch': None, 'name': 'Far', 'provider': 'claude'}


@pytest.fixture
def bus(tmp_path, monkeypatch):
    path = tmp_path / 'cloude.db'

    def connect():
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        STEPS[56](conn)
        STEPS[89](conn)
        STEPS[93](conn)
        conn.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL)')
        conn.execute('CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT UNIQUE, project_id INTEGER)')
        conn.executemany('INSERT INTO projects VALUES (?,?)', [(1, 'alpha'), (2, 'beta')])
        conn.executemany('INSERT INTO sessions VALUES (?,?,?)', [(11, 'uuid-a', 1), (12, 'uuid-b', 1), (13, 'uuid-c', 2)])
    monkeypatch.setattr(store, '_conn', connect)
    named: list[str] = []
    monkeypatch.setattr(store.resource_push, 'notify', named.append)
    monkeypatch.setattr(store, '_notify_swarm', lambda *keys: None)
    clock = iter(range(1000, 2000))
    monkeypatch.setattr(store, 'time', SimpleNamespace(time=lambda: float(next(clock))))
    for left, right in ((ALICE, BOB), (ALICE, CAROL), (CAROL, PEER)):
        store.grant_contact(left['key'], right['key'], left['epoch'], right['epoch'])
    return named


def _send(sender: dict, receiver: dict, text: str, thread: str) -> dict:
    return store.reserve(sender=sender, receiver=receiver, text=text, thread=thread)


def test_threads_filter_by_session_project_and_participant_and_page(bus):
    _send(ALICE, BOB, 'ab one', 't-ab')
    _send(BOB, ALICE, 'ab two', 't-ab')
    _send(ALICE, CAROL, 'ac one', 't-ac')
    _send(CAROL, PEER, 'cp one ghp_' + 'x' * 36, 't-cp')

    every = history.list_threads()['threads']
    assert [t['thread'] for t in every] == ['t-cp', 't-ac', 't-ab']
    ab = every[2]
    assert ab['message_count'] == 2 and ab['last_preview'] == 'ab two'
    assert [(p['name'], p['provider'], p['project_id'], p['project_name']) for p in ab['participants']] == [
        ('Alice', 'claude', 1, 'alpha'), ('Bob', 'codex', 1, 'alpha')]
    peer_side = next(p for p in every[0]['participants'] if p['key'] == PEER['key'])
    assert peer_side['project_id'] is None
    assert 'ghp_' + 'x' * 36 not in every[0]['last_preview']

    def ids(**kw):
        return [t['thread'] for t in history.list_threads(**kw)['threads']]

    assert ids(session='ses_b') == ['t-ab']
    assert ids(session='uuid-c') == ['t-cp', 't-ac']
    assert ids(session_row=13) == ['t-cp', 't-ac']
    assert ids(session_row=99) == []
    assert ids(project=1) == ['t-ac', 't-ab']
    assert ids(project=2) == ['t-cp', 't-ac']
    assert ids(participant='uuid-b') == ['t-ab']
    assert ids(project=2, participant='uuid-a') == ['t-ac']

    page = history.list_threads(limit=2)
    assert [t['thread'] for t in page['threads']] == ['t-cp', 't-ac'] and page['next_before'] is not None
    rest = history.list_threads(limit=2, before=page['next_before'])
    assert [t['thread'] for t in rest['threads']] == ['t-ab'] and rest['next_before'] is None

    thread = history.thread_messages('t-ab')
    assert [m['text'] for m in thread['messages']] == ['ab one', 'ab two']
    assert [m['text'] for m in history.thread_messages('t-ab', limit=1)['messages']] == ['ab two']
    with pytest.raises(history.HistoryError):
        history.thread_messages('t-ab', participant='uuid-c')
    with pytest.raises(HTTPException) as refused:
        asyncio.run(crosstalk_routes.thread_messages('t-none', before=None, limit=10))
    assert refused.value.status_code == 404


def test_every_write_of_crosstalk_messages_names_the_topic(bus):
    bus.clear()
    row = _send(ALICE, BOB, 'hello', 't-ab')
    assert bus == [CROSSTALK]
    claimed = store.claim_for(BOB['key'])
    assert claimed['id'] == row['id'] and bus == [CROSSTALK] * 2
    assert store.mark_native_pending(row['id'], 'a' * 32)
    assert bus == [CROSSTALK] * 3
    store.finish(row['id'], 'delivered')
    assert bus == [CROSSTALK] * 4
    assert store.claim_for(BOB['key']) is None and bus == [CROSSTALK] * 4
