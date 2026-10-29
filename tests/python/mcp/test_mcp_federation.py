
from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.api import peer_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.crosstalk import store as crosstalk_store
from src.core.crosstalk.delivery import peer as peer_delivery
from src.core.federation import peer_hosts, peer_links, peer_listing, peer_terminal_proxy, shadow_rows
from src.core.federation.peer_client import PeerUnreachable
from src.core.mcp import federated, pending, write_tools
from src.models import Session, SessionInfo
from tests.python.mcp.test_mcp_endpoint import SECRET, _call
from tests.python.mcp.test_mcp_write import _text, env  # noqa: F401

PEER_IID = "iid-studio"
OWNER_UUID = "11111111-2222-4333-8444-555555555555"


class FakeClient:
    def __init__(self):
        self.calls, self.answers = [], {}

    async def request(self, method, path, *, json=None, timeout=None):
        self.calls.append((method, path.split("?")[0], json))
        answer = self.answers.get((method, path.split("?")[0]), (200, {"ok": True}))
        if isinstance(answer, Exception):
            raise answer
        if answer == "hang":
            await asyncio.sleep(60)
        return SimpleNamespace(status_code=answer[0], body=__import__("json").dumps(answer[1]).encode(),
                               headers={"content-type": "application/json"}, json=lambda: answer[1])


class FakeLinks:
    def __init__(self, client):
        self._client = client

    def client(self, _iid):
        return self._client

    def minor(self, _iid):
        return 0

    def state(self, _iid):
        return "connected"


class FakeSocket:
    def __init__(self, sent):
        self.sent, self.frames = sent, [f"\x1b[31mhi\x1b[0m token={SECRET}\r\n".encode(), json.dumps({"type": "terminal.ready"})]

    async def recv(self):
        if not self.frames:
            await asyncio.sleep(60)
        return self.frames.pop(0)

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        pass


@pytest.fixture()
def peer(env, monkeypatch, tmp_path):  # noqa: F811
    client, mgr, cfg, slept = env
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        row = peer_hosts.upsert(conn, install_id=PEER_IID, label="studio", grant_id="g", fid="f", initiator=True, ssh_target="studio")
        conn.execute("UPDATE hosts SET peer_state = 'connected' WHERE key = ?", (row.key,))
        shadow_rows.sync_peer(conn, host_key=row.key, peer_install_id=PEER_IID, complete=True,
                              rows=[{"session_uuid": OWNER_UUID, "row_id": 7, "name": "carnivore_api", "working_dir": "/w"}])
    fake = FakeClient()
    monkeypatch.setattr(peer_links, "LINKS", FakeLinks(fake))
    wire = f"remote:{row.key}:carnivore_api"
    info = SessionInfo(session=Session(id=wire, working_dir="/w"), tmux_session="carnivore_api", label="api", host_key=row.key,
                       host_label="studio", host_state="up", activity_status="idle", session_uuid="shadow")

    listed = [info]

    async def rows(force=False):
        return list(listed)

    monkeypatch.setattr(federated, "peer_infos", rows)
    sent: list = []

    async def connect_upstream(_client, url):
        sent.append(url)
        return FakeSocket(sent)

    monkeypatch.setattr(peer_terminal_proxy, "connect_upstream", connect_upstream)
    return SimpleNamespace(http=client, mgr=mgr, cfg=cfg, fake=fake, wire=wire, key=row.key, sent=sent, info=info, listed=listed)


def test_sessions_list_holds_both_macs_and_status_reads_the_peer_row(peer):
    rows = json.loads(_text(_call(peer.http, peer.mgr, "sessions_list")))["sessions"]
    assert [r["id"] for r in rows] == ["ses_a_row2", "ses_b", peer.wire]
    assert rows[2]["host"] == "studio" and rows[2]["host_state"] == "up" and "host" not in rows[0]
    assert json.loads(_text(_call(peer.http, peer.mgr, "session_status", {"target": peer.wire})))["id"] == peer.wire


def test_read_output_on_a_peer_is_redacted_here(peer):
    out = json.loads(_text(_call(peer.http, peer.mgr, "session_read_output", {"target": peer.wire})))
    assert "hi" in out["output"] and SECRET not in out["output"] and "\x1b" not in out["output"]
    assert "observer=1" in peer.sent[0] and "interactive" not in peer.sent[0] and "session_id=carnivore_api" in peer.sent[0]


def test_a_bare_tmux_name_never_names_a_peer_session(peer):
    body = _call(peer.http, peer.mgr, "session_status", {"target": "carnivore_api"})
    assert body["isError"] is True


@pytest.mark.parametrize("action,args", [("session_stop", {}), ("session_restart", {}),
                                         ("session_send_keys", {"text": "yes", "keys": ["Enter"]})])
def test_peer_writes_wait_in_the_inbox_even_with_the_setting_off_and_approve_runs_them(peer, action, args):
    peer.cfg.gate_cross_session_actions = False
    answer = json.loads(_text(_call(peer.http, peer.mgr, action, {"target": peer.wire, **args})))
    assert answer["status"] == "pending" and not peer.fake.calls and len(peer.sent) == 0
    row = peer.http.get("/api/v1/agent-actions").json()["items"][0]
    assert row["args_summary"].startswith("on studio:") and row["target_session_id"] == peer.wire
    assert peer.http.post(f"/api/v1/agent-actions/{answer['id']}/approve").status_code == 200
    if action == "session_send_keys":
        assert peer.sent[-1] == b"yes\r" and "interactive=1" in peer.sent[0]
    elif action == "session_stop":
        assert peer.fake.calls == [("POST", f"/sessions/{OWNER_UUID}/sleep", None)]
    else:
        assert peer.fake.calls == [("POST", "/sessions/respawn", {"confirm_restart_live": True, "session_name": "carnivore_api"})]


def test_deny_is_a_tool_error_and_sends_nothing_to_the_peer(peer):
    answer = json.loads(_text(_call(peer.http, peer.mgr, "session_stop", {"target": peer.wire})))
    peer.http.post(f"/api/v1/agent-actions/{answer['id']}/deny")
    body = _call(peer.http, peer.mgr, "approval_wait", {"id": answer["id"]})
    assert body["isError"] is True and "denied" in _text(body) and not peer.fake.calls


def test_send_message_to_a_peer_needs_first_contact_and_forwards_a_pinned_receipt(peer, monkeypatch) -> None:
    asked = json.loads(_text(_call(peer.http, peer.mgr, "session_send_message", {"target": peer.wire, "text": "hello"})))
    assert asked["status"] == "pending" and peer.fake.calls == []
    action = pending.get_store().get(asked["id"])
    assert action.action == "crosstalk_send" and action.args == {"to": peer.wire, "text": "hello"}
    assert peer.http.post(f"/api/v1/agent-actions/{asked['id']}/approve").status_code == 200
    receipt = json.loads(_text(action.result))
    message = crosstalk_store.get(receipt["id"])
    assert message["status"] == "queued" and message["receiver_key"] == "shadow"

    async def sender_info(session_id: str | None = None) -> SessionInfo | None:
        return peer.mgr.infos[0] if session_id == "ses_a_row2" else None

    monkeypatch.setattr(peer.mgr, "get_session_info", sender_info)
    path = "/api/v1/crosstalk/peer-deliver"
    peer.fake.answers[("POST", path)] = (200, {"status": "delivered"})
    assert asyncio.run(peer_delivery.deliver(peer.http.app, peer.info, message)) == ("delivered", None)
    assert peer.fake.calls[0][0:2] == ("POST", path)
    forwarded = peer.fake.calls[0][2]
    assert forwarded["id"] == receipt["id"] and forwarded["text"] == "hello"
    assert forwarded["sender_uuid"] == "uuid-11" and forwarded["receiver_key"] == "shadow"
    assert all("one-shot" not in call[1] for call in peer.fake.calls)

    peer.fake.answers[("POST", path)] = (409, {"detail": {"code": "dialog_open"}})
    refused = asyncio.run(peer_delivery.deliver(peer.http.app, peer.info, message))
    assert refused[0] == "failed" and "409" in refused[1]

    peer.fake.answers[("POST", path)] = (409, {"detail": {"code": "receiver_not_ready"}})
    assert asyncio.run(peer_delivery.deliver(peer.http.app, peer.info, message))[0] == "held"
    peer.fake.answers[("POST", path)] = (404, {"detail": "Not Found"})
    assert asyncio.run(peer_delivery.deliver(peer.http.app, peer.info, message))[0] == "failed"


def test_the_peer_client_never_doubles_the_api_prefix() -> None:
    from src.core.federation.peer_client import _url
    assert _url("/api/v1/crosstalk/peer-deliver") == "/api/v1/crosstalk/peer-deliver"
    assert _url("/federation/hello") == "/api/v1/federation/hello"


def test_an_older_peer_without_a_route_is_a_named_tool_error(peer):
    peer.fake.answers[("POST", f"/sessions/{OWNER_UUID}/sleep")] = (404, {"detail": "Not Found"})
    answer = json.loads(_text(_call(peer.http, peer.mgr, "session_stop", {"target": peer.wire})))
    peer.http.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    body = _call(peer.http, peer.mgr, "approval_wait", {"id": answer["id"]})
    assert "older Carnivore" in _text(body)


def test_create_on_a_peer_is_gated_counts_toward_the_caps_and_needs_a_dir(peer, monkeypatch):
    assert _call(peer.http, peer.mgr, "session_create", {"peer": "studio", "project": "x"})["isError"] is True
    peer.fake.answers[("POST", "/sessions")] = (201, {"id": "ses_new", "working_dir": "/w2"})
    peer.fake.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    answer = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w2"})))
    assert answer["status"] == "pending" and not peer.fake.calls
    peer.http.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert peer.fake.calls[0] == ("POST", "/sessions", {"working_dir": "/w2", "host_key": "local"})
    assert list(write_tools._created) == [f"remote:{peer.key}:cloude_new"]
    peer.listed.append(peer.info.model_copy(update={"session": Session(id=f"remote:{peer.key}:cloude_new", working_dir="/w2")}))
    monkeypatch.setattr(write_tools, "MAX_CREATED_PER_AGENT", 1)
    again = json.loads(_text(_call(peer.http, peer.mgr, "session_create", {"peer": "studio", "working_dir": "/w3"})))
    peer.http.post(f"/api/v1/agent-actions/{again['id']}/approve")
    assert "limit 1" in _text(_call(peer.http, peer.mgr, "approval_wait", {"id": again["id"]}))


def test_a_hung_peer_never_stalls_local_tools(peer, monkeypatch):
    monkeypatch.setattr(federated, "peer_infos", lambda force=False: peer_listing.peer_rows(peer_auth.open_db, force=force))
    peer.fake.answers[("GET", "/sessions/list")] = "hang"
    started = time.monotonic()
    rows = json.loads(_text(_call(peer.http, peer.mgr, "sessions_list")))["sessions"]
    assert time.monotonic() - started < 4
    assert {r["id"] for r in rows} >= {"ses_a_row2", "ses_b"}
    assert all(r.get("host_state") != "up" for r in rows if r["id"].startswith("remote:"))


def test_an_unreachable_link_fails_a_read_cleanly_and_bounded(peer, monkeypatch):
    async def down(_client, url):
        raise peer_terminal_proxy.PeerUnavailable()

    monkeypatch.setattr(peer_terminal_proxy, "connect_upstream", down)
    body = _call(peer.http, peer.mgr, "session_read_output", {"target": peer.wire})
    assert body["isError"] is True and "studio" in _text(body)
    peer.fake.answers[("GET", "/sessions/carnivore_api/note")] = PeerUnreachable("timeout")
    assert _call(peer.http, peer.mgr, "session_notes_get", {"target": peer.wire})["isError"] is True
