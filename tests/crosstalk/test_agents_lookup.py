
from __future__ import annotations

import asyncio
import json

import pytest

from src.core.crosstalk import directory
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.models import Session, SessionInfo


def _info(sid, tmux, label, family, host="local", state="up", row=None):
    return SessionInfo(session=Session(id=sid, working_dir="/w", model="m1"), tmux_session=tmux, label=label,
                       agent_family=family, host_key=host, host_label="this" if host == "local" else host,
                       host_state=state, activity_status="idle", session_row_id=row,
                       session_uuid=None if host == "local" else "u-" + sid)


class FakeManager:
    def __init__(self, local, peers):
        self.local, self.peers = local, peers

    async def list_session_infos(self):
        return self.local

    async def list_peer_infos(self):
        return self.peers


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [])
    monkeypatch.setattr(directory, "_session_details", lambda ids: {i: (f"uuid-{i}", "Claude Title" if i == 5 else None, []) for i in ids})
    return FakeManager(
        [_info("ses_1", "cloude_a", "Zed-Misc UI", "claude", row=1),
         _info("ses_2", "cloude_b", "Zed-Misc Api", "codex", row=2),
         _info("ses_3", "cloude_c", "Twin", "claude", row=3),
         _info("ses_4", "cloude_d", "Twin", "codex", row=4),
         _info("ses_5", "cloude_e", None, "claude", row=5)],
        [_info("remote:peer-x:cloude_r", "cloude_r", "Remote Bot", "claude", host="hosta", state="disconnected")])


def _run(coro):
    return asyncio.run(coro)


def _names(res):
    return [a["name"] for a in res["agents"]]


def test_name_spellings_all_hit_the_same_agent(mgr):
    for q in ("Zed-Misc UI", "@zed-misc ui", "zed_misc-ui", "ZED.MISC.UI", "ses_1", "cloude_a"):
        res = _run(directory.lookup(mgr, query=q))
        assert _names(res)[:1] == ["Zed-Misc UI"] and not res["ambiguous"], q
    assert _run(directory.lookup(mgr, query="zed_misc-ui"))["match"] == "normalized"
    assert _run(directory.lookup(mgr, query="zed-misc ui"))["match"] == "label"


def test_lower_tiers_and_no_match(mgr):
    assert _run(directory.lookup(mgr, query="remote"))["match"] == "prefix"
    assert _run(directory.lookup(mgr, query="bot"))["match"] == "substring"
    fuzzy = _run(directory.lookup(mgr, query="zed-misc uii"))
    assert fuzzy["match"] == "fuzzy" and _names(fuzzy)[0] == "Zed-Misc UI"
    none = _run(directory.lookup(mgr, query="zzzzzz"))
    assert none["agents"] == [] and none["match"] is None


def test_same_label_is_ambiguous_never_guessed(mgr):
    res = _run(directory.lookup(mgr, query="@twin"))
    assert res["ambiguous"] and sorted(a["id"] for a in res["agents"]) == ["ses_3", "ses_4"]
    assert not _run(directory.lookup(mgr, query="@twin", provider="codex"))["ambiguous"]


def test_provider_filter_card_fields_and_remote(mgr):
    res = _run(directory.lookup(mgr, provider="Codex"))
    assert {a["provider"] for a in res["agents"]} == {"codex"}
    card = next(a for a in _run(directory.lookup(mgr))["agents"] if a["id"] == "ses_1")
    assert card["handle"] == "@Zed-Misc UI" and card["session_uuid"] == "uuid-1" and card["model"] == "m1"
    assert next(a for a in _run(directory.lookup(mgr))["agents"] if a["id"] == "ses_5")["name"] == "Claude Title"
    assert card["reachable_via"] == ["paste"]
    remote = _run(directory.lookup(mgr, query="remote bot"))["agents"][0]
    assert remote["host"] == "hosta" and remote["host_state"] == "disconnected" and remote["session_uuid"] == "u-remote:peer-x:cloude_r"
    assert remote["reachable_via"] == []
    assert not any(a["host"] == "hosta" for a in _run(directory.lookup(mgr, include_remote=False))["agents"])


def test_self_excluded_unless_asked_and_limit(mgr):
    assert "ses_1" not in [a["id"] for a in _run(directory.lookup(mgr, self_tmux="cloude_a"))["agents"]]
    mine = _run(directory.lookup(mgr, self_tmux="cloude_a", include_self=True))["agents"]
    assert [a["id"] for a in mine if a["is_you"]] == ["ses_1"]
    small = _run(directory.lookup(mgr, limit=2))
    assert len(small["agents"]) == 2 and small["truncated"]


def test_mcp_tool_listed_read_scope_and_called(mgr):
    assert "agents_lookup" in [d["name"] for d in tools.tool_definitions(AgentCaller("s", "t", "s", scope="read"))]
    caller = AgentCaller("ses_1", "cloude_a", "ses_1")
    res = _run(tools.call_tool(mgr, caller, "agents_lookup", {"query": "@twin"}))
    body = json.loads(res["content"][0]["text"])
    assert body["ambiguous"] and "isError" not in res
    bad = _run(tools.call_tool(mgr, caller, "agents_lookup", {"limit": "x"}))
    assert bad["isError"]
