
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import pytest
from websockets.sync.client import connect

from src.core.approvals import peer_items
from src.core.approvals.inbox import ApprovalsInbox
from src.core.federation import peer_hosts
from src.core.federation.pairing import ANSWER_ALL_MINOR
from src.core.federation.peer_client import PeerUnreachable
from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_dialog_answer import ASK, call, session_id, tool_results, wait_for


def frames_until(ws, frames: List[Dict[str, Any]], pred, timeout: float = 45.0) -> Dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            frame = json.loads(ws.recv(timeout=1.0))
        except TimeoutError:
            continue
        frames.append(frame)
        if pred(frame):
            return frame
    raise AssertionError(f"no matching frame; saw {frames}")


def test_rig_claude_dialog_lists_publishes_answers_and_clears(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    with ScriptedModel([Step("RIG:ask", "AskUserQuestion", ASK)]) as model:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        ws_url = rig_slot.slot.base.replace("http", "ws", 1) + "/ws/events"
        frames: List[Dict[str, Any]] = []
        with connect(ws_url, subprotocols=["cloude.jwt.v1", rig_slot.slot.token()]) as ws:
            status, empty = call(rig_slot, "GET", "/api/v1/approvals")
            assert status == 200 and empty["items"] == []
            v0 = empty["version"]
            name = rig_slot.create_session("rigapp", "rigclaude", cwork)
            sid = session_id(rig_slot, name)
            rig_slot.wait_for(name, "❯")
            rig_slot.type_line(name, "RIG:ask please")
            rig_slot.wait_for(name, "Pick a colour?")
            shown = frames_until(ws, frames, lambda f: f.get("type") == "approvals" and f.get("count") == 1)
            assert set(shown) == {"type", "version", "count"} and shown["version"] > v0

            _, listing = call(rig_slot, "GET", "/api/v1/approvals")
            (item,) = listing["items"]
            assert (item["source"], item["host"], item["session_id"], item["kind"]) == (
                "dialog", "local", sid, "ask_user_question")
            assert item["question"] == "Pick a colour?" and item["options"] == ["Red", "Blue"]
            assert item["family"] == "claude" and item["session_name"] and item["fingerprint"]
            v1 = listing["version"]

            status, _ = call(rig_slot, "POST", f"/api/v1/sessions/{sid}/dialog/answer",
                             {"fingerprint": item["fingerprint"], "choice": {"option": "Blue"}})
            assert status == 200
            wait_for(lambda: "Blue" in tool_results(model), "claude never got the answer")
            frames_until(ws, frames, lambda f: f.get("type") == "approvals" and f.get("count") == 0)
            _, after = call(rig_slot, "GET", "/api/v1/approvals")
            assert after["items"] == [] and after["version"] > v1
        assert all("Pick a colour" not in json.dumps(f) for f in frames)



PEER = peer_hosts.PeerRow(key="peer-a", label="studio", ssh_target="", ssh_port=None, peer_install_id="iid-a",
                          peer_grant_id="g", peer_fid="f", peer_protocol=1, peer_state="connected",
                          initiator=True, peer_port=None, back_kind="none")


def raw_item(**over: Any) -> Dict[str, Any]:
    item = {"id": "dlg:ses_9:abcd", "source": "dialog", "host": "local", "session_id": "ses_9",
            "tmux_session": "carnivore_api", "kind": "permission", "question": "Proceed?",
            "fingerprint": "f" * 64, "origin_install_id": "iid-a"}
    return {**item, **over}


class Reply:

    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body


class FakeClient:

    def __init__(self, reply: Any) -> None:
        self.reply, self.calls = reply, []

    async def request(self, method: str, path: str, **kw: Any) -> Reply:
        self.calls.append((method, path))
        if isinstance(self.reply, BaseException):
            raise self.reply
        if self.reply == "hang":
            await asyncio.sleep(30)
        return self.reply


class FakeLinks:

    def __init__(self, client: Optional[FakeClient]) -> None:
        self._client = client

    def client(self, _iid: str) -> Optional[FakeClient]:
        return self._client

    def minor(self, _iid: str) -> int:
        return ANSWER_ALL_MINOR


def test_peer_item_is_namespaced_and_forwardable() -> None:
    got = asyncio.run(peer_items._one(PEER, FakeLinks(FakeClient(Reply(200, {"items": [raw_item()]})))))
    (item,) = got
    assert item["host"] == "peer-a" and item["session_id"] == "remote:peer-a:carnivore_api"
    assert item["id"] == "remote:peer-a:dlg:ses_9:abcd"


def test_loop_guard_drops_reexported_and_foreign_items() -> None:
    bad = [raw_item(origin_install_id="someone-else"), raw_item(host="peer-b"),
           raw_item(session_id="remote:peer-b:x"), raw_item(source="agent_action"), raw_item(tmux_session=None),
           raw_item(kind="x" * 500), "junk"]
    got = asyncio.run(peer_items._one(PEER, FakeLinks(FakeClient(Reply(200, {"items": bad})))))
    assert got == []
    merged = [{"source": "dialog", "host": "peer-a", "session_id": "remote:peer-a:x"},
              {"source": "dialog", "host": "local", "session_id": "ses_1"},
              {"source": "agent_action", "host": "local", "session_id": "ses_1"}]
    assert [i["session_id"] for i in peer_items.serve(merged, "me")] == ["ses_1"]


@pytest.mark.parametrize("reply", [Reply(404, {"detail": "nope"}), Reply(500), Reply(200, "not a dict"),
                                   Reply(200, {"items": "nope"}), PeerUnreachable("down")])
def test_older_broken_or_unreachable_peer_is_skipped(reply: Any) -> None:
    assert asyncio.run(peer_items._one(PEER, FakeLinks(FakeClient(reply)))) == []


def test_slow_peer_does_not_stall_the_list(monkeypatch) -> None:
    monkeypatch.setattr(peer_items, "DEADLINE_SECONDS", 0.1)
    start = time.monotonic()
    assert asyncio.run(peer_items._one(PEER, FakeLinks(FakeClient("hang")))) == []
    assert time.monotonic() - start < 2.0


def test_no_link_means_no_items() -> None:
    assert asyncio.run(peer_items._one(PEER, FakeLinks(None))) == []


def test_inbox_bumps_the_version_once_per_change_and_debounces() -> None:
    sent: List[Dict[str, Any]] = []

    class Provider:
        sig = frozenset()

        def signature(self):
            return self.sig

        async def items(self):
            return []

    async def scenario() -> None:
        prov = Provider()
        inbox = ApprovalsInbox(sent.append, debounce=0.05)
        inbox.register(prov)
        assert inbox.refresh() is False and inbox.version == 0
        prov.sig = frozenset({("dialog", "a", "f1")})
        assert inbox.refresh() and inbox.version == 1
        prov.sig = frozenset({("dialog", "a", "f2")})
        assert inbox.refresh() and inbox.version == 2
        assert inbox.refresh() is False
        await asyncio.sleep(0.2)
        assert sent == [{"type": "approvals", "version": 2, "count": 1}]
        prov.sig = frozenset()
        inbox.refresh()
        await asyncio.sleep(0.2)
        assert sent[-1] == {"type": "approvals", "version": 3, "count": 0}

    asyncio.run(scenario())
