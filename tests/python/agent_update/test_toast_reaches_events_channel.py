
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core import session_change_notice
from src.core.notifications import agent_message


def test_broadcast_publishes_toast_new_on_events_and_session_socket(monkeypatch):
    from src.api import websocket

    sent, published = [], []
    async def to_session(session_id, payload):
        sent.append((session_id, payload))
    monkeypatch.setattr(websocket.connection_manager, "broadcast_to_session", to_session)
    monkeypatch.setattr(session_change_notice, "publish", lambda state, frame: published.append((state, frame)) or 1)
    toast = SimpleNamespace(session_id="ses_1", id="t1")
    monkeypatch.setattr("src.models.ToastNewMessage", lambda toast: SimpleNamespace(model_dump_json=lambda: '{"type": "toast.new", "toast": {"id": "t1"}}'))
    state = object()

    asyncio.run(agent_message._broadcast(toast, app_state=state))

    assert [s for s, _ in sent] == ["ses_1"]
    assert published == [(state, {"type": "toast.new", "toast": {"id": "t1"}})]
