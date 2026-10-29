
from __future__ import annotations

import asyncio

from src.core.mcp import channel, instructions, protocol, tools
from src.core.mcp.caller import AgentCaller
from tests.python.mcp.test_mcp_endpoint import _hdr, _rpc, env  # noqa: F401

MAX_DESCRIPTION_CHARS = 400


def test_instructions_fit_under_the_client_cut_in_every_variant():
    for scope in ("write", "read"):
        for chan in (False, True):
            caller = AgentCaller("ses_x", "t", "ses_x", scope=scope)
            assert len(instructions.guide(caller, channel=chan)) <= instructions.MAX_CHARS == 1800
    assert len(instructions.guide(None, channel=True)) <= 1800


def test_channel_rule_comes_first_and_names_the_owner():
    text = instructions.guide(None, channel=True)
    assert text.startswith("CHANNEL EVENTS")
    assert "OWNER's own instructions" in text.split("\n\n")[0]
    assert "CHANNEL EVENTS" not in instructions.guide(None, channel=False)


def test_instructions_carry_no_tool_list():
    assert "\nTools\n" not in instructions.guide(None)


def test_every_non_huddle_description_is_capped():
    long = {d["name"]: len(d["description"]) for d in tools.tool_definitions(None)
            if not d["name"].startswith("huddle_") and len(d["description"]) > MAX_DESCRIPTION_CHARS}
    assert long == {}


def test_initialize_declares_list_changed():
    assert protocol.server_capabilities(False)["tools"] == {"listChanged": True}


def test_session_id_carries_the_fingerprint_and_a_match_passes(env):
    client, mgr, _ = env
    sid = client.post("/mcp", json=_rpc("initialize", {}), headers=_hdr(mgr)).headers["mcp-session-id"]
    assert len(sid.split(".")[0]) == protocol.FINGERPRINT_CHARS
    r = client.post("/mcp", json=_rpc("tools/list"), headers={**_hdr(mgr), "Mcp-Session-Id": sid})
    assert r.status_code == 200


def test_changed_tool_list_answers_404_and_initialize_still_works(env, monkeypatch):
    client, mgr, _ = env
    sid = client.post("/mcp", json=_rpc("initialize", {}), headers=_hdr(mgr)).headers["mcp-session-id"]
    headers = {**_hdr(mgr), "Mcp-Session-Id": sid}
    real = tools.tool_definitions
    monkeypatch.setattr(tools, "tool_definitions", lambda c=None: real(c)[:-1])
    r = client.post("/mcp", json=_rpc("tools/list"), headers=headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == protocol.SESSION_EXPIRED
    again = client.post("/mcp", json=_rpc("initialize", {}), headers=headers)
    assert again.status_code == 200
    fresh = {**_hdr(mgr), "Mcp-Session-Id": again.headers["mcp-session-id"]}
    assert client.post("/mcp", json=_rpc("tools/list"), headers=fresh).status_code == 200


def test_old_shape_and_foreign_session_ids_are_stale_and_no_id_is_fine(env):
    client, mgr, _ = env
    for sid in ("randomtokenwithoutdot", "deadbeefdeadbeef.abc"):
        r = client.post("/mcp", json=_rpc("ping"), headers={**_hdr(mgr), "Mcp-Session-Id": sid})
        assert r.status_code == 404
    assert client.post("/mcp", json=_rpc("ping"), headers=_hdr(mgr)).status_code == 200


def test_stream_sends_list_changed_once_when_the_fingerprint_moves():
    state = {"fp": "a"}

    async def run() -> list[str]:
        out: list[str] = []
        body = channel.stream_events("t", "ses_x", channel.ChannelRegistry(), max_s=0.5, keepalive_s=0.05,
                                     fingerprint=lambda: state["fp"])
        async for chunk in body:
            out.append(chunk)
            if len(out) == 2:
                state["fp"] = "b"
        return out

    chunks = asyncio.run(run())
    assert sum(channel.TOOLS_CHANGED_METHOD in c for c in chunks) == 1
