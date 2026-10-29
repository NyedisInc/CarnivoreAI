
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.crosstalk import bus
from src.core.mcp.common import ToolError
from src.core.swarm import body


def _run(monkeypatch, wake):
    order: list = []
    monkeypatch.setattr(bus, 'WAKE_WAIT_S', 0.05)

    async def wait_awake(agent_id, **_):
        order.append('awake')
    monkeypatch.setattr(body, 'wake', wake(order))
    monkeypatch.setattr(body, 'wait_awake', wait_awake)
    first = [True]

    async def identities(view, caller, to, asleep='refuse'):
        if first.pop():
            await bus._wake_agent(SimpleNamespace(), 5)
        return {}, {}
    monkeypatch.setattr(bus, 'identities', identities)
    real_send = bus.send

    async def tail(view, caller, **kw):
        order.append('sent')
        return {'status': 'delivered'}

    async def go():
        view = SimpleNamespace(fresh=lambda: view)
        monkeypatch.setattr(bus, 'send', tail)
        answer = await real_send(view, SimpleNamespace(), to='agent:5', text='hi')
        order.append('answered')
        await asyncio.gather(*list(bus._slow_wake_tasks))
        return answer
    return order, asyncio.run(go())


def test_slow_wake_is_queued_and_delivered_after_body_is_up(monkeypatch):
    def wake(order):
        async def slow(app_state, agent_id, reason, authority):
            await asyncio.sleep(0.2)
            order.append('body up')
            return SimpleNamespace(state='awake')
        return slow
    order, answer = _run(monkeypatch, wake)
    assert answer['status'] == 'queued' and answer['receipt'] == 'queued'
    assert order == ['answered', 'body up', 'awake', 'sent']


def test_failed_wake_still_errors(monkeypatch):
    def wake(order):
        async def fail(app_state, agent_id, reason, authority):
            raise body.BodyError('pane died')
        return fail
    with pytest.raises(ToolError, match='pane died'):
        _run(monkeypatch, wake)
