
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.core.mcp import beast_mode, beast_store
from tests.python.beast_mode.grid import install

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_until_for_each_choice_and_never():
    assert beast_store.until_for(None, NOW) is None
    assert beast_store.until_for(1, NOW) == (NOW + timedelta(hours=1)).isoformat()
    assert beast_store.until_for(8, NOW) == (NOW + timedelta(hours=8)).isoformat()
    with pytest.raises(ValueError):
        beast_store.until_for(3, NOW)


def test_until_passed_fails_closed_on_garbage():
    assert beast_mode.until_passed(None, NOW) is False
    assert beast_mode.until_passed((NOW + timedelta(minutes=1)).isoformat(), NOW) is False
    assert beast_mode.until_passed(NOW.isoformat(), NOW) is True
    assert beast_mode.until_passed("not a time", NOW) is True


def _config(monkeypatch, **mcp):
    block = SimpleNamespace(beast_mode=False, beast_prompts=False, beast_mode_until=None)
    for key, value in mcp.items():
        setattr(block, key, value)
    monkeypatch.setattr(beast_mode, "_config", lambda: block)


def test_expiry_disarms_both_scopes_on_read(monkeypatch):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _config(monkeypatch, beast_mode=True, beast_prompts=True, beast_mode_until=past)
    assert beast_mode.beast_enabled() is False
    assert beast_mode.stored_prompts_armed() is False
    assert beast_mode.armed_but_expired() is True


def test_live_window_keeps_both_scopes(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _config(monkeypatch, beast_mode=True, beast_prompts=True, beast_mode_until=future)
    install(monkeypatch)
    assert beast_mode.beast_enabled() and beast_mode.stored_prompts_armed() and beast_mode.handles("claude_permission")
    assert beast_mode.armed_but_expired() is False


def test_prompts_scope_needs_beast_armed(monkeypatch):
    _config(monkeypatch, beast_mode=False, beast_prompts=True)
    assert beast_mode.stored_prompts_armed() is False


def test_persist_writes_one_block_and_a_disarm_clears_everything(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcp": {"enabled": True, "gate_cross_session_actions": True}}))
    from src.config import settings

    monkeypatch.setattr(settings, "auth_config_file", str(path))
    notified = []
    monkeypatch.setattr(beast_store.resource_push, "notify", lambda topic: notified.append(topic))
    asyncio.run(beast_store.persist(enabled=True, prompts=True, hours=4))
    block = json.loads(path.read_text())["mcp"]
    assert block["beast_mode"] is True and block["beast_prompts"] is True and block["beast_mode_until"]
    assert block["gate_cross_session_actions"] is True
    asyncio.run(beast_store.persist(enabled=False, prompts=True, hours=4))
    block = json.loads(path.read_text())["mcp"]
    assert block["beast_mode"] is False and block["beast_prompts"] is False and block["beast_mode_until"] is None
    assert notified == ["beast_mode", "beast_mode"]
