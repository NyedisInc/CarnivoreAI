
from __future__ import annotations

from src.core.mcp.common import ToolError

from .conftest import LEAK, assert_fixed


def test_crosstalk_send_refusal_answers_a_code(driver, monkeypatch):
    from src.core.crosstalk import bus

    async def refuse(*_a, **_k):
        raise ToolError(f"pair not granted {LEAK}")

    monkeypatch.setattr(bus, "send", refuse)
    response, events = driver.call("POST", "/crosstalk/messages", object(), json={"to": "x", "text": "hi"})
    assert_fixed(response, 409, "crosstalk_refused", events)


def test_crosstalk_unknown_thread_answers_a_code(driver, monkeypatch):
    from src.core.crosstalk import history

    def unknown(*_a, **_k):
        raise history.HistoryError(f"no thread {LEAK}")

    monkeypatch.setattr(history, "thread_messages", unknown)
    response, events = driver.call("GET", "/crosstalk/threads/abc/messages", object())
    if response.status_code == 404 and "code" not in str(response.json()):
        raise AssertionError("route path changed: " + response.text)
    assert_fixed(response, 404, "crosstalk_thread_unknown", events)


def test_agent_action_not_pending_answers_a_code(driver, monkeypatch):
    from src.core.mcp import pending

    class Store:
        def deny(self, _id):
            raise ValueError(f"already decided {LEAK}")

    monkeypatch.setattr(pending, "get_store", lambda: Store())
    response, events = driver.call("POST", "/agent-actions/a1/deny", object())
    assert_fixed(response, 409, "agent_action_not_pending", events)
