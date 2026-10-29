
import sqlite3

import pytest

from src.core.crosstalk import store
from src.core.db_steps import STEPS


def test_pinned_contact_and_atomic_reservation_survive_reopen(tmp_path, monkeypatch):
    path = tmp_path / 'cloude.db'

    def connect():
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        STEPS[56](conn)
        STEPS[89](conn)
        STEPS[93](conn)
    monkeypatch.setattr(store, '_conn', connect)
    monkeypatch.setattr(store, '_notify', lambda: None)
    alice = {'key': 'uuid-a', 'id': 'sa', 'uuid': 'uuid-a', 'epoch': 11,
             'name': 'Alice', 'provider': 'claude', 'model': 'opus'}
    bob = {'key': 'uuid-b', 'id': 'sb', 'uuid': 'uuid-b', 'epoch': 22,
           'name': 'Bob', 'provider': 'codex', 'model': 'astra'}
    eve = {'key': 'uuid-e', 'id': 'se', 'uuid': 'uuid-e', 'epoch': 33,
           'name': 'Eve', 'provider': 'codex', 'model': 'astra'}
    store.grant_contact(alice['key'], bob['key'], alice['epoch'], bob['epoch'])
    first = store.reserve(sender=alice, receiver=bob, text='hello', expect_reply=True)
    assert first['status'] == 'queued'
    assert store.get(first['id'])['text'] == 'hello'
    assert store.messages_for('uuid-e', thread=first['thread']) == []
    with pytest.raises(store.BusRefused, match='identical message'):
        store.reserve(sender=alice, receiver=bob, text='hello')
    store.grant_contact(eve['key'], bob['key'], eve['epoch'], bob['epoch'])
    with pytest.raises(store.BusRefused, match='another pair'):
        store.reserve(sender=eve, receiver=bob, text='not mine', thread=first['thread'])
    with pytest.raises(store.BusRefused, match='previous pane'):
        store.reserve(sender={**alice, 'epoch': 12}, receiver=bob, text='new pane')
    claimed = store.claim_for('uuid-b')
    assert claimed['id'] == first['id']
    store.finish(first['id'], 'delivered')
    assert store.get(first['id'])['status'] == 'delivered'
    for index in range(29):
        store.reserve(sender=alice, receiver=bob, text=f'message {index}')
    with pytest.raises(store.BusRefused, match='loop breaker'):
        store.reserve(sender=alice, receiver=bob, text='message 31')
    store.owner_input('uuid-a')
    with pytest.raises(store.BusRefused, match='paused'):
        store.reserve(sender=alice, receiver=bob, text='still paused')
    store.resume_pair('uuid-a', 'uuid-b')
    assert store.reserve(sender=alice, receiver=bob, text='resumed')['status'] == 'queued'
    store.watch(watcher_key='uuid-a', watcher_id='sa', watcher_epoch=11,
                target_key='uuid-b', target_id='sb', target_epoch=22)
    assert store.notify_idle('uuid-b', 22) == ['uuid-a']
    assert any(m['source'] == 'system' and 'idle' in m['text'] for m in store.messages_for('uuid-a'))
