
from __future__ import annotations

import asyncio
import json
import time

from src.core.federation import peer_terminal_proxy
from src.core.mcp import federated, pending, write_tools
from src.core.mcp.tools import clean_output
from src.models import Session
from tests.python.mcp.test_mcp_endpoint import _call, _hdr, _rpc
from tests.python.mcp.test_mcp_federation import peer  # noqa: F401
from tests.python.mcp.test_mcp_write import _text, env  # noqa: F401

AK = "sk-ant-api03-" + "Zx9Qw7Er5Ty3" * 8


class BusySocket:

    def __init__(self):
        self.n = 0

    async def recv(self):
        if self.n == 0:
            self.n += 1
            return b"\x1b[1;1H> working on it\r\n"
        await asyncio.sleep(0.2)
        self.n += 1
        return b"\x1b[5;1H\xe2\x9c\xbb Thinking... (%ds)" % self.n

    async def send(self, data):
        pass

    async def close(self):
        pass


def _use_socket(monkeypatch, socket):
    async def connect_upstream(_client, url):
        return socket

    monkeypatch.setattr(peer_terminal_proxy, "connect_upstream", connect_upstream)


def test_m1_a_working_peer_session_still_reads_its_first_paint_fast(peer, monkeypatch):  # noqa: F811
    _use_socket(monkeypatch, BusySocket())
    started = time.monotonic()
    body = _call(peer.http, peer.mgr, "session_read_output", {"target": peer.wire})
    assert body.get("isError") is not True and "working on it" in _text(body) and time.monotonic() - started < 4


def test_m1_a_peer_that_never_answers_the_close_does_not_stretch_the_read(peer, monkeypatch):  # noqa: F811
    class SlowClose(BusySocket):
        async def close(self):
            await asyncio.sleep(30)

    _use_socket(monkeypatch, SlowClose())
    started = time.monotonic()
    body = _call(peer.http, peer.mgr, "session_read_output", {"target": peer.wire})
    assert body.get("isError") is not True and time.monotonic() - started < 4


def test_l2_only_frames_before_ready_are_kept(peer, monkeypatch):  # noqa: F811
    class Paint(BusySocket):
        frames = [b"\x1b[1;1H> cat .env\r\n", json.dumps({"type": "terminal.ready"}), b"\x1b[3;41H" + AK[40:].encode()]

        async def recv(self):
            return self.frames.pop(0) if self.frames else await asyncio.sleep(60)

    _use_socket(monkeypatch, Paint())
    raw = asyncio.run(federated.read_screen(peer.info))
    assert b"cat .env" in raw and AK[40:].encode() not in raw
    assert AK[40:] not in clean_output(raw, 100)


def test_m2_the_create_card_shows_agent_type_and_name(peer):  # noqa: F811
    a = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w", "agent_type": "claude"})))
    b = json.loads(_text(_call(peer.http, peer.mgr, "session_create",
                               {"peer": "studio", "working_dir": "/w", "agent_type": "codex-yolo", "name": "boss"})))
    rows = {r["id"]: r for r in peer.http.get("/api/v1/agent-actions").json()["items"]}
    assert rows[b["id"]]["args"]["agent_type"] == "codex-yolo" and rows[b["id"]]["args"]["name"] == "boss"
    assert "codex-yolo" in rows[b["id"]]["args_summary"] and "boss" in rows[b["id"]]["args_summary"]
    assert rows[a["id"]]["args"]["agent_type"] == "claude" and rows[a["id"]]["args_summary"] != rows[b["id"]]["args_summary"]


def test_m3_the_cap_reads_a_fresh_listing_not_the_batchs_cached_one(peer, monkeypatch):  # noqa: F811
    monkeypatch.setattr(write_tools, "MAX_CREATED_PER_AGENT", 1)
    peer.fake.answers[("POST", "/sessions")] = (201, {"id": "ses_new", "working_dir": "/w2"})
    peer.fake.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    a = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w2"})))
    r = peer.http.post("/mcp", headers=_hdr(peer.mgr), json=[
        _rpc("tools/call", {"name": "sessions_list", "arguments": {}}, 1),
        _rpc("tools/call", {"name": "session_create", "arguments": {"peer": "studio", "working_dir": "/w3"}}, 2)])
    b = json.loads(r.json()[1]["result"]["content"][0]["text"])
    assert peer.http.post(f"/api/v1/agent-actions/{a['id']}/approve").status_code == 200
    created = f"remote:{peer.key}:cloude_new"
    peer.listed.append(peer.info.model_copy(update={"session": Session(id=created, working_dir="/w2")}))
    assert peer.http.post(f"/api/v1/agent-actions/{b['id']}/approve").status_code == 200
    result = _call(peer.http, peer.mgr, "approval_wait", {"id": b["id"]})
    assert result["isError"] is True and "limit 1" in _text(result)
    assert created in write_tools._created


def test_l1_a_peer_create_never_holds_the_create_lock_over_the_network(peer, monkeypatch):  # noqa: F811
    seen: list = []
    real = peer.fake.request

    async def request(method, path, *, json=None, timeout=None):
        if method == "POST" and path.split("?")[0] == "/sessions":
            seen.append((write_tools._create_lock.locked(), list(write_tools._reserved)))
        return await real(method, path, json=json, timeout=timeout)

    monkeypatch.setattr(peer.fake, "request", request)
    peer.fake.answers[("POST", "/sessions")] = (201, {"id": "ses_new", "working_dir": "/w2"})
    peer.fake.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    a = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w2"})))
    peer.http.post(f"/api/v1/agent-actions/{a['id']}/approve")
    assert len(seen) == 1 and seen[0][0] is False and len(seen[0][1]) == 1
    assert write_tools._reserved == [] and list(write_tools._created) == [f"remote:{peer.key}:cloude_new"]


def test_l1_a_failed_peer_create_releases_its_reserved_slot(peer):  # noqa: F811
    peer.fake.answers[("POST", "/sessions")] = (500, {"detail": "boom"})
    a = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w2"})))
    peer.http.post(f"/api/v1/agent-actions/{a['id']}/approve")
    assert write_tools._reserved == [] and not write_tools._created


def test_l3_the_inbox_item_for_a_peer_target_names_the_peer(peer):  # noqa: F811
    _call(peer.http, peer.mgr, "session_stop", {"target": peer.wire})
    items = asyncio.run(pending.AgentActionProvider(pending.get_store(), lambda: None).items())
    assert items[0]["host"] == peer.key


def test_l5_the_final_revalidation_forces_a_fresh_peer_listing(peer, monkeypatch):  # noqa: F811
    forced: list = []

    async def rows(force=False):
        forced.append(force)
        return list(peer.listed)

    monkeypatch.setattr(federated, "peer_infos", rows)
    asyncio.run(federated.resolved_again(peer.wire, None))
    assert forced == [True]
