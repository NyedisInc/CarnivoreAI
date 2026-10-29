
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.crosstalk import bus, directory
from src.core.mcp.common import ToolError

CARDS: List[Dict[str, Any]] = [
    {"id": "ses_1", "name": "Alpha Builder", "session_uuid": "uuid-1", "tmux_name": "cloude_alpha",
     "asleep": True, "is_you": False, "provider": "claude", "host": "this"},
]


@pytest.fixture
def patched(monkeypatch):
    async def cards(view, **_kw):
        return CARDS

    async def sender(view, caller, cards, infos=None):
        return {"key": "me", "id": "me", "uuid": None, "epoch": 1, "name": "me"}

    monkeypatch.setattr(directory, "list_cards", cards)
    monkeypatch.setattr(bus, "_sender", sender)
    return SimpleNamespace(app=None)


def _identities(view, to):
    caller = SimpleNamespace(external=False, tmux_name="x")
    return asyncio.run(bus.identities(view, caller, to, asleep="allow"))


def test_a_prefix_or_fuzzy_name_is_refused_with_suggestions(patched):
    for typo in ("alph", "Alpha Bilder"):
        with pytest.raises(ToolError, match="Alpha Builder"):
            _identities(patched, typo)


def test_an_exact_name_still_resolves(patched):
    _, receiver = _identities(patched, "@alpha builder")
    assert receiver["uuid"] == "uuid-1"


def test_a_bad_message_never_resolves_a_recipient(monkeypatch):
    called: List[str] = []

    async def spy(*_a, **_k):
        called.append("identities")
        raise AssertionError("must not resolve")

    monkeypatch.setattr(bus, "identities", spy)
    caller = SimpleNamespace(external=False)
    for text, expect in (("", False), ("x" * 20, "yes"), ("bad\x00char", False)):
        with pytest.raises(ToolError):
            asyncio.run(bus.send(SimpleNamespace(), caller, to="anyone", text=text, expect_reply=expect))
    assert called == []
