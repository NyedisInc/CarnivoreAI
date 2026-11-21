from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from src.core import session_change_notice, ui_preferences_store
from src.core.crosstalk import spawn_layout
from src.core.preferences_push import broadcast


def _result() -> ui_preferences_store.UpdateResult:
    return ui_preferences_store.UpdateResult(ui_preferences_store.COMMITTED, 7, {"theme": "x"}, {"theme": "x"})


class _Manager:

    def __init__(self) -> None:
        self.sent: list = []

    async def broadcast(self, text: str) -> None:
        self.sent.append(json.loads(text))


def test_the_state_alone_is_enough_and_the_frame_carries_the_revision(monkeypatch) -> None:
    published: list = []
    monkeypatch.setattr(session_change_notice, "publish", lambda state, frame: published.append(frame))
    manager = _Manager()
    asyncio.run(broadcast.broadcast_changed(SimpleNamespace(connection_manager=manager), _result(), "tab-1"))
    assert manager.sent[0]["revision"] == 7 and manager.sent[0]["origin_client_id"] == "tab-1"
    assert published == manager.sent


def test_no_connection_manager_is_a_quiet_no_op(monkeypatch) -> None:
    monkeypatch.setattr(session_change_notice, "publish", lambda *a: (_ for _ in ()).throw(AssertionError("published")))
    assert asyncio.run(broadcast.broadcast_changed(SimpleNamespace(), _result(), None)) is None


def test_a_transport_failure_never_fails_the_save(monkeypatch) -> None:
    class Broken(_Manager):
        async def broadcast(self, text: str) -> None:
            raise OSError("socket gone")

    monkeypatch.setattr(session_change_notice, "publish", lambda *a: None)
    asyncio.run(broadcast.broadcast_changed(SimpleNamespace(connection_manager=Broken()), _result(), None))


def test_the_spawn_layout_announces_without_a_faked_request(monkeypatch) -> None:
    told: list = []

    async def fake(state, result, client_id):
        told.append((state, client_id))

    class Store:
        def read(self):
            return {"values": {}, "revision": 1}

        def update(self, changes, revision):
            return _result()

    monkeypatch.setattr(spawn_layout, "broadcast_changed", fake)
    monkeypatch.setattr(spawn_layout, "add_to_arrangement", lambda *a: {"v": 1, "sessions": {}})
    state = SimpleNamespace(ui_preferences_store=Store())
    assert asyncio.run(spawn_layout.persist(SimpleNamespace(state=state), "p", "c")) == "saved"
    assert told == [(state, None)]


def test_the_first_parameter_is_the_state_not_a_request() -> None:
    import inspect

    assert list(inspect.signature(broadcast.broadcast_changed).parameters)[0] == "app_state"
