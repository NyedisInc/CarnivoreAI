
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.crosstalk import directory, native_mirror, store

LOCAL = {"id": "ses_local", "name": "Local", "session_uuid": "u-l", "provider": "claude", "model": None}
PEER = {"id": "ses_bob", "name": "Bob Builder", "session_uuid": "u-b", "provider": "claude", "model": None,
        "tmux_name": "cloude_bob", "former_names": []}


@pytest.fixture
def mirror(monkeypatch):
    async def cards(view, **_kw):
        return [LOCAL, PEER]

    monkeypatch.setattr(directory, "list_cards", cards)
    monkeypatch.setattr(native_mirror, "BatchView", lambda *_a: None)
    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    info = SimpleNamespace(session=SimpleNamespace(id="ses_local"))
    return app, info


def _run(mirror, backlog):
    app, info = mirror
    asyncio.run(native_mirror._deliver(app, info, backlog))


def test_an_oversize_event_is_dropped_not_retried_forever(mirror, monkeypatch):
    def refuse(**_kw):
        raise store.BusRefused("native message exceeds crosstalk size limit")

    monkeypatch.setattr(store, "mirror_native", refuse)
    backlog = {"k": ("k", "inbound", "Bob Builder", "huge")}
    _run(mirror, backlog)
    assert backlog == {}


def test_a_transient_error_keeps_the_event(mirror, monkeypatch):
    def flaky(**_kw):
        raise OSError("db busy")

    monkeypatch.setattr(store, "mirror_native", flaky)
    backlog = {"k": ("k", "inbound", "Bob Builder", "hi")}
    _run(mirror, backlog)
    assert "k" in backlog


def test_a_fuzzy_peer_name_is_never_mirrored(mirror, monkeypatch):
    stored = []
    monkeypatch.setattr(store, "mirror_native", lambda **kw: stored.append(kw))
    backlog = {"k": ("k", "inbound", "Bob Bilder", "hi")}
    _run(mirror, backlog)
    assert stored == [] and "k" in backlog
