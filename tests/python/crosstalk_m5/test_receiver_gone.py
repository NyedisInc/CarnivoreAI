
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.crosstalk import bus, directory, gone, store
from src.core.mcp.common import ToolError

CARDS = [{"id": "uuid-asleep", "name": "Sleeper", "session_uuid": "uuid-asleep", "tmux_name": "carnivore_sleeper",
          "asleep": True, "is_you": False, "provider": "claude", "host": "this"}]


@pytest.fixture
def patched(monkeypatch):
    def conn():
        c = sqlite3.connect(":memory:")
        c.executescript("CREATE TABLE crosstalk_messages (receiver_id, receiver_key, sender_id, sender_key);"
                        "CREATE TABLE sessions (session_uuid, tmux_name);"
                        "INSERT INTO crosstalk_messages VALUES ('ses_gone', 'uuid-gone', 'ses_boss', 'uuid-boss');"
                        "INSERT INTO sessions VALUES ('uuid-asleep', 'carnivore_sleeper');")
        return c

    async def cards(view, **_kw):
        return CARDS

    async def sender(view, caller, cards, infos=None):
        return {"key": "me", "id": "me", "uuid": None, "epoch": 1, "name": "me"}

    monkeypatch.setattr(store, "_conn", conn)
    monkeypatch.setattr(directory, "list_cards", cards)
    monkeypatch.setattr(bus, "_sender", sender)
    return SimpleNamespace(app=None)


def _identities(view, to):
    return asyncio.run(bus.identities(view, SimpleNamespace(external=False, tmux_name="x"), to, asleep="allow"))


def test_a_gone_receiver_is_refused_an_asleep_one_resolves_and_a_stranger_is_unknown(patched):
    with pytest.raises(ToolError, match=gone.RECEIVER_GONE):
        _identities(patched, "ses_gone")
    _, receiver = _identities(patched, "carnivore_sleeper")
    assert receiver["asleep"] is True and receiver["uuid"] == "uuid-asleep"
    with pytest.raises(ToolError, match="no agent matches"):
        _identities(patched, "ses_never_existed")
