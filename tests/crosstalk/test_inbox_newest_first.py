
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.crosstalk import bus, store
from src.core.db_steps import STEPS
from src.core.mcp import crosstalk_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError

ALICE = {'key': 'uuid-a', 'id': 'sa', 'uuid': 'uuid-a', 'epoch': 11, 'name': 'Alice', 'provider': 'claude', 'model': 'opus'}
BOB = {'key': 'uuid-b', 'id': 'sb', 'uuid': 'uuid-b', 'epoch': 22, 'name': 'Bob', 'provider': 'codex', 'model': 'astra'}


@pytest.fixture
def messages(tmp_path, monkeypatch):
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
    monkeypatch.setattr(store, 'time', SimpleNamespace(time=lambda: float(next(clock))))
    store.grant_contact(ALICE['key'], BOB['key'], ALICE['epoch'], BOB['epoch'])
    texts = [f'message {n:02d}' for n in range(30)]
    for text in texts:
        store.reserve(sender=ALICE, receiver=BOB, text=text, expect_reply=False)
    return texts


def test_the_store_reads_newest_first_within_the_limit(messages):
    rows = store.messages_for('uuid-b', limit=5, newest_first=True)
    assert [r['text'] for r in rows] == list(reversed(messages))[:5]
    assert [r['text'] for r in store.messages_for('uuid-b', limit=3)] == messages[:3]


def test_the_inbox_defaults_to_the_newest_twenty(messages):
    view = SimpleNamespace()

    async def identity(_view, _caller):
        return BOB

    bus.caller_identity, saved = identity, bus.caller_identity
    try:
        body = asyncio.run(bus.inbox(view, None))
        assert [m['text'] for m in body['messages']] == list(reversed(messages))[:bus.INBOX_LIMIT]
        body = asyncio.run(bus.inbox(view, None, limit=2))
        assert [m['text'] for m in body['messages']] == ['message 29', 'message 28']
    finally:
        bus.caller_identity = saved


def test_the_tool_passes_limit_through_and_validates_it(monkeypatch):
    seen = {}

    async def fake(view, caller, **kwargs):
        seen.update(kwargs)
        return {'messages': [], 'watches': []}

    monkeypatch.setattr(bus, 'inbox', fake)
    caller = AgentCaller('ses_1', 'cloude_a', 'ses_1')
    asyncio.run(crosstalk_tools.crosstalk_inbox(None, caller, {}))
    assert seen['limit'] == 20
    asyncio.run(crosstalk_tools.crosstalk_inbox(None, caller, {'limit': 7}))
    assert seen['limit'] == 7
    for bad in (0, 101, True, 'x'):
        with pytest.raises(ToolError, match='limit'):
            asyncio.run(crosstalk_tools.crosstalk_inbox(None, caller, {'limit': bad}))
