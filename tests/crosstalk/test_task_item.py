
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.api import crosstalk_routes
from src.core.crosstalk import ddl, store
from src.core.db_steps import STEPS
from src.core.mcp import crosstalk_tools

ALICE = {'key': 'uuid-a', 'id': 'ses_a', 'uuid': 'uuid-a', 'epoch': 1, 'name': 'Alice', 'provider': 'claude'}
BOB = {'key': 'uuid-b', 'id': 'ses_b', 'uuid': 'uuid-b', 'epoch': 2, 'name': 'Bob', 'provider': 'codex'}


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
    monkeypatch.setattr(store, '_conn', connect)
    monkeypatch.setattr(store, '_notify', lambda: None)
    monkeypatch.setattr(store, '_notify_swarm', lambda *keys: None)
    clock = iter(range(1000, 2000))
    monkeypatch.setattr(store, 'time', SimpleNamespace(time=lambda: float(next(clock))))
    store.grant_contact(ALICE['key'], BOB['key'], ALICE['epoch'], BOB['epoch'])


def test_send_stores_task_item_and_a_reply_inherits_it_unless_it_gives_one(bus):
    first = store.reserve(sender=ALICE, receiver=BOB, text='please review the diff', task_item=934)
    assert first['task_item'] == 934
    inherited = store.reserve(sender=BOB, receiver=ALICE, text='looks good\nsecond line', in_reply_to=first['id'])
    assert inherited['task_item'] == 934 and inherited['thread'] == first['thread']
    changed = store.reserve(sender=ALICE, receiver=BOB, text='and this one is task 7', in_reply_to=inherited['id'], task_item=7)
    assert changed['task_item'] == 7
    plain = store.reserve(sender=ALICE, receiver=BOB, text='no task here')
    assert plain['task_item'] is None
    for bad in (0, -3, True, '934'):
        with pytest.raises(store.BusRefused, match='task_item'):
            store.reserve(sender=ALICE, receiver=BOB, text=f'bad {bad!r}', task_item=bad)


def test_trail_route_lists_only_that_items_messages_oldest_first_with_the_first_line(bus):
    store.reserve(sender=ALICE, receiver=BOB, text='first line ghp_' + 'x' * 36 + '\nsecond line', task_item=934)
    store.reserve(sender=ALICE, receiver=BOB, text='other task', task_item=12)
    store.reserve(sender=BOB, receiver=ALICE, text='done', task_item=934)
    trail = asyncio.run(crosstalk_routes.task_item_messages(task_item=934, limit=200))
    assert trail['task_item'] == 934
    assert [(m['sender_name'], m['receiver_name']) for m in trail['messages']] == [('Alice', 'Bob'), ('Bob', 'Alice')]
    assert trail['messages'][0]['preview'].startswith('first line ') and 'second line' not in trail['messages'][0]['preview']
    assert 'ghp_' + 'x' * 36 not in trail['messages'][0]['preview']
    assert asyncio.run(crosstalk_routes.task_item_messages(task_item=99, limit=200))['messages'] == []


def test_the_migration_is_idempotent_and_the_mcp_schemas_carry_the_field():
    conn = sqlite3.connect(':memory:')
    STEPS[56](conn)
    ddl.apply_v94(conn)
    ddl.apply_v94(conn)
    assert 'task_item' in {r[1] for r in conn.execute('PRAGMA table_info(crosstalk_messages)')}
    for name in ('crosstalk_send', 'crosstalk_reply'):
        assert crosstalk_tools.WRITE_TOOLS[name][1]['task_item']['type'] == 'integer'
