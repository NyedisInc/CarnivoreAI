
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import mcp_health_listing, mcp_reconnect_routes
from src.core.mcp_health.fold import McpDrop, McpHealth
from src.models import Session, SessionInfo
from tests.python.cplugs.mcphealth.plugin_on import app_state, plugin_on

HEALTH = McpHealth(dropped=(McpDrop("linear", "dropped", datetime(2026, 10, 10, tzinfo=timezone.utc), True),))


def _info(status="idle", family="claude"):
    session = Session(id="ses_1", working_dir="/tmp", tmux_session="t1")
    return SessionInfo(session=session, activity_status=status, agent_family=family)


class _Manager:
    def __init__(self, info, health):
        self.info = info
        self.health = health

    async def get_session_info(self, _sid):
        return self.info


def _request(manager):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))


def _call(manager, server=None):
    return asyncio.run(mcp_reconnect_routes.reconnect_mcp(
        _request(manager), "ses_1", mcp_reconnect_routes.McpReconnectRequest(server=server)))


@pytest.fixture(autouse=True)
def plugin():
    with plugin_on() as port:
        yield port


@pytest.fixture
def pasted(monkeypatch):
    sent = []

    async def fake(request, session_id, text, **kw):
        sent.append((text, kw))

    monkeypatch.setattr(mcp_reconnect_routes, "paste_through_gates", fake)
    monkeypatch.setattr(mcp_reconnect_routes, "refuse_remote", lambda *a, **k: None)
    return sent


def test_listing_stamps_the_ports_answer_and_null_when_unmeasured():
    for health, expect in ((HEALTH, ["linear"]), (None, None)):
        manager = _Manager(_info(), health)
        info = manager.info
        mcp_health_listing.mark_mcp_health(app_state(manager), [info])
        got = info.mcp_health
        assert (None if got is None else [d.name for d in got.dropped]) == expect


def test_listing_stamps_empty_health_as_measured_ok_not_null():
    manager = _Manager(_info(), McpHealth())
    mcp_health_listing.mark_mcp_health(app_state(manager), [manager.info])
    assert manager.info.mcp_health is not None and manager.info.mcp_health.dropped == []


def test_idle_session_gets_the_command_through_the_guarded_path(pasted):
    answer = _call(_Manager(_info("idle"), HEALTH))
    assert answer.sent and answer.command == "/mcp reconnect linear"
    assert pasted == [("/mcp reconnect linear", {"idle_only": True, "fresh_dialog_check": True})]


@pytest.mark.parametrize("status,family,health,code", [
    ("working", "claude", HEALTH, "session_busy"),
    ("question", "claude", HEALTH, "session_busy"),
    ("idle", "codex", HEALTH, "not_claude"),
    ("idle", "claude", None, "mcp_not_measured"),
    ("idle", "claude", McpHealth(), "nothing_dropped"),
])
def test_refusals_write_nothing(pasted, status, family, health, code):
    with pytest.raises(HTTPException) as err:
        _call(_Manager(_info(status, family), health))
    assert err.value.status_code == 409 and err.value.detail["code"] == code
    assert pasted == []


def test_unknown_server_refused(pasted):
    with pytest.raises(HTTPException) as err:
        _call(_Manager(_info(), HEALTH), "other")
    assert err.value.detail["code"] == "unknown_server" and pasted == []
