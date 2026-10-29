
import sqlite3

from src.core.crosstalk import store
from src.core.db_steps import STEPS


def test_owner_messages_returns_the_newest_rows_in_ascending_order(tmp_path, monkeypatch):
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
    clock = iter(range(1000, 2000))
    monkeypatch.setattr(store.time, 'time', lambda: float(next(clock)))
    alice = {'key': 'uuid-a', 'id': 'sa', 'uuid': 'uuid-a', 'epoch': 1, 'name': 'A', 'provider': 'claude', 'model': 'm'}
    bob = {'key': 'uuid-b', 'id': 'sb', 'uuid': 'uuid-b', 'epoch': 2, 'name': 'B', 'provider': 'codex', 'model': 'm'}
    store.grant_contact(alice['key'], bob['key'], alice['epoch'], bob['epoch'])
    texts = [f'message {n}' for n in range(5)]
    for text in texts:
        store.reserve(sender=alice, receiver=bob, text=text)
    assert [m['text'] for m in store.owner_messages('sa', limit=3)] == texts[2:]
    assert [m['text'] for m in store.owner_messages('sa', limit=50)] == texts
    first = store.owner_messages('sa', limit=50)[1]['created_at']
    assert [m['text'] for m in store.owner_messages('sa', since=first, limit=2)] == texts[3:]
