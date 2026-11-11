
from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace
from typing import Any, List

import httpx
import pytest

from src.config import settings as app_settings
from src.core import resource_push
from src.core.argent import fallback_spend as fs
from src.core.argent import health, mint, notices, registration, row_state, session_ref as refs
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient
from src.core.argent.pair_credential import PairRefused
from src.core.argent.pair_sync import SwitchBody
from src.core.argent.store import ArgentStore
from src.core.budget_hold import gate
from src.core.budget_hold.store import HoldStore
from src.core.launch_profiles import create_seam
from src.core.layouts import broadcast as layout_broadcast
from src.core.resource_push import topics
from src.core.sessions.session_events import RENAMED, SessionEvent
from tests.argent.test_argent_fallback_spend import CONV, IDS, METERED, _line, _stamp, world  # noqa: F401
from tests.argent.test_argent_launch_overlay import KEY, NOW, ctx, launch, on, report, run  # noqa: F401
from tests.argent.test_argent_pair_sync import GATEWAY, SERVER, net  # noqa: F401
from tests.argent.test_argent_pair_sync import run as net_run

MINT = 1793872800.0 - 10



def test_a_peer_cannot_set_addresses_or_turn_on_a_computer_with_no_login(net) -> None:  # noqa: F811
    b = net.computers["b"]
    with pytest.raises(PairRefused) as refused:
        net_run(net, b.sync.receive_switch("a", SwitchBody(clock=1, enabled=True, server_url="https://evil.test", gateway_url="https://evil.test"), object()))
    assert refused.value.code == "address_locked" and (b.cfg().server_url, b.cfg().gateway_url, b.cfg().enabled) == ("", "", False)
    b.flip(serverUrl=SERVER)
    b.login()
    with pytest.raises(PairRefused):
        net_run(net, b.sync.receive_switch("a", SwitchBody(clock=2, enabled=True, server_url=SERVER, gateway_url="https://evil.test"), object()))
    assert b.cfg().gateway_url == "" and not b.cfg().enabled
    c = net.computers["c"]
    c.flip(serverUrl=SERVER, gatewayUrl=GATEWAY)
    net_run(net, c.sync.receive_switch("a", SwitchBody(clock=3, enabled=True, server_url=SERVER, gateway_url=GATEWAY), object()))
    assert not c.cfg().enabled
    c.login()
    net_run(net, c.sync.receive_switch("a", SwitchBody(clock=4, enabled=True, server_url=SERVER, gateway_url=GATEWAY), object()))
    assert c.cfg().enabled



def test_a_carried_gateway_is_a_public_name_on_443() -> None:
    from src.core.argent.gateway_reach import GatewayTarget, ReachError, target_of

    assert target_of("https://gw.argent.test") == GatewayTarget("gw.argent.test", 443)
    for bad in ("https://192.168.1.9", "https://[fd00::1]", "https://gw.argent.test:22", "https://nas.local"):
        with pytest.raises(ReachError):
            target_of(bad)



class Paths:

    def __init__(self, gateway: Any = None, gateway_status: int = 200) -> None:
        self.paths: List[str] = []
        self.gateway, self.gateway_status = gateway, gateway_status

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.paths.append(request.url.path)
            if request.url.path.endswith("/gateway"):
                if isinstance(self.gateway, str):
                    return httpx.Response(self.gateway_status, text=self.gateway)
                return httpx.Response(self.gateway_status, json=self.gateway if self.gateway is not None else {"first_metered_at": None, "last_metered_at": None, "metered_count": 0})
            return httpx.Response(200, json=IDS if request.method == "GET" else {})
        return httpx.MockTransport(handle)


@pytest.fixture
def pending(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(app_settings, "state_dir_override", world.tmp)
    seen: List[str] = []
    monkeypatch.setattr(notices, "untethered_launch", lambda ref, name, reason: seen.append(reason))
    monkeypatch.setattr(resource_push, "notify", lambda *a, **k: None)
    world.session = dataclasses.replace(world.session, tmux="carnivore_api")
    ref = refs.ref_for_name("ten_1", "carnivore_api")
    row_state.record_launch("ten_1", ref, working_dir="/w", tethered=True, reason="", key_id="k1", clock=lambda: MINT)
    row_state.confirm("ten_1", ref)
    world.seen, world.ref = seen, ref

    def go(argent: Any, now: float) -> int:
        client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=argent.transport())
        return asyncio.run(fs.report_session(client, "ten_1", world.session, world.cursors, projects_dir=world.tmp / "projects", clock=lambda: now))

    world.go = go
    return world


def test_a_metered_request_flips_pending_to_tethered_and_calls_use_the_ref(pending) -> None:
    pending.write(_line(METERED, _stamp(5)))
    argent = Paths({"first_metered_at": MINT + 12, "last_metered_at": MINT + 12, "metered_count": 3})
    pending.go(argent, MINT + 100)
    assert row_state.lookup("ten_1", "carnivore_api")["state"] == "tethered"
    assert argent.paths and all("/agent-sessions/carnivore_api/" in p for p in argent.paths), argent.paths


def test_a_request_argent_never_metered_flips_pending_to_not_tethered_after_the_grace(pending) -> None:
    pending.write(_line("req_direct", _stamp(5)))
    pending.go(Paths(), MINT + 10 + 5 + row_state.TRAFFIC_GRACE_SECONDS - 30)
    assert row_state.lookup("ten_1", "carnivore_api")["state"] == "pending"
    argent = Paths()
    pending.go(argent, MINT + 10 + 5 + row_state.TRAFFIC_GRACE_SECONDS + 1)
    got = row_state.lookup("ten_1", "carnivore_api")
    assert (got["state"], got["reason"]) == ("not tethered", row_state.NO_TRAFFIC_REASON) and pending.seen == [row_state.NO_TRAFFIC_REASON]
    assert any(p.endswith("/usage") for p in argent.paths) and not any("/12/" in p for p in argent.paths)


def test_a_row_with_no_traffic_stays_pending_and_a_settled_row_is_never_rewritten(pending) -> None:
    pending.go(Paths(), MINT + 99999)
    assert row_state.lookup("ten_1", "carnivore_api")["state"] == "pending"
    assert row_state.first_traffic("ten_1", pending.ref, seen=True, unmetered_at=0, now=MINT) == "tethered"
    assert row_state.first_traffic("ten_1", pending.ref, seen=False, unmetered_at=1.0, now=MINT + 9999) == "", "only a PENDING row moves"



def test_a_session_end_flushes_unreported_spend_once(pending) -> None:
    pending.write(_line("req_tail", _stamp(7)))
    row_state.first_traffic("ten_1", pending.ref, seen=False, unmetered_at=1.0, now=MINT + 9999)
    fs._known.clear()
    fs._known["carnivore_api"] = pending.session
    argent = Paths()
    client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=argent.transport())
    sent = asyncio.run(fs.flush_ended("ten_1", "carnivore_api", client, projects_dir=pending.tmp / "projects"))
    assert sent == 1 and any(p.endswith("/agent-sessions/carnivore_api/usage") for p in argent.paths)
    assert asyncio.run(fs.flush_ended("ten_1", "carnivore_api", client)) == 0, "forgotten after the flush"
    assert asyncio.run(fs.flush_ended("ten_1", "never-seen", client)) == 0



def test_a_rename_while_logged_out_keeps_the_argent_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "state_dir_override", tmp_path)
    assert refs.ref_for_name("ten_1", "carnivore_x") == "carnivore_x"
    asyncio.run(registration.follow_rename(SessionEvent(kind=RENAMED, tmux_name="carnivore_y", old_name="carnivore_x")))
    assert refs.ref_for_name("ten_1", "carnivore_y") == "carnivore_x", "no second id was minted"
    assert not hasattr(refs, "agent_id_for")



def test_a_resume_launch_of_an_oversize_transcript_launches_direct(on, tmp_path, monkeypatch) -> None:  # noqa: F811
    transcript = tmp_path / "big.jsonl"
    transcript.write_bytes(b"x" * 90)
    monkeypatch.setattr(health._poller, "latest", report(body_cap_bytes=100))
    from src.core.argent import overlay as overlay_module

    monkeypatch.setattr(overlay_module, "family_conversation_presence", lambda *a, **k: SimpleNamespace(path=transcript))
    plan = launch(tmp_path)
    resume = dataclasses.replace(plan, argv_tail=("--resume", CONV))
    prepared = run(create_seam.prepare(resume, overlay_ctx=ctx(tmp_path)))
    assert json.loads(prepared.record)["argent"]["reason"] == "too large for gateway cap" and on["mints"] == []
    fresh = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert json.loads(fresh.record)["argent"]["tethered"] is True
    transcript.write_bytes(b"x" * 10)
    small = run(create_seam.prepare(resume, overlay_ctx=ctx(tmp_path)))
    assert json.loads(small.record)["argent"]["tethered"] is True



def test_a_budget_held_pane_is_skipped_by_the_layout_broadcast(tmp_path, monkeypatch) -> None:
    store = HoldStore(tmp_path / "argent.db")
    store.set_hold("wi_1", "checkout", ["7"])
    monkeypatch.setattr(gate, "STORE", store)
    monkeypatch.setattr(gate, "switch_on", lambda: True)
    sent: List[str] = []

    async def paste(text: str) -> None:
        sent.append(text)

    backend = SimpleNamespace(paste_and_submit=paste)
    member = SimpleNamespace(session_row_id=7, session_uuid="u7")
    held = SimpleNamespace(session_row_id=7, session=SimpleNamespace(id="ses_7"), activity_status="idle", startup_gate="ready")
    out = asyncio.run(layout_broadcast._send_one(member, held, backend, "git status"))
    assert (out.status, out.code) == (layout_broadcast.FAILED, "budget_held") and sent == []
    free = SimpleNamespace(session_row_id=8, session=SimpleNamespace(id="ses_8"), activity_status="idle", startup_gate="ready")
    assert asyncio.run(layout_broadcast._send_one(SimpleNamespace(session_row_id=8, session_uuid="u8"), free, backend, "git status")).status == layout_broadcast.SENT
    assert sent == ["git status"]


def test_the_codex_note_is_not_typed_into_a_held_session(tmp_path, monkeypatch) -> None:
    from src.api import checkpoint_codex_note as note
    from src.core.approvals import dialog_gate

    store = HoldStore(tmp_path / "argent.db")
    store.set_hold("wi_1", "checkout", ["7"])
    monkeypatch.setattr(gate, "STORE", store)
    monkeypatch.setattr(gate, "switch_on", lambda: True)

    async def clear(app, sid):
        return dialog_gate.CLEAR

    monkeypatch.setattr(dialog_gate, "dialog_verdict", clear)
    typed: List[str] = []

    class Manager:
        _registry = SimpleNamespace(registered_ids_for_tmux_name=lambda name: ["ses_7"])

        async def get_session_info(self, session_id):
            return SimpleNamespace(session_row_id=7, activity_status="idle", startup_gate="ready")

        async def send_command(self, text, session_id):
            typed.append(text)

    row = SimpleNamespace(agent_type="codex", tmux_name="carnivore_c")
    monkeypatch.setattr(note.rows, "family_of", lambda agent: "codex")
    sent, why = asyncio.run(note.tell_codex(Manager(), object(), row, SimpleNamespace(conversation="c", prompt_uuid="p")))
    assert sent is False and "budget" in (why or "") and typed == []



def test_a_401_seen_by_any_client_pushes_the_status_topic_and_the_phase_follows_the_clock(tmp_path, monkeypatch) -> None:
    pushed: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: pushed.append(topic))
    clock = [1000.0]
    store = ArgentStore(tmp_path, clock=lambda: clock[0])
    assert store.login_phase() == "out"
    store.set_login("ten_1", "id_1", "P", 3600)
    assert store.login_phase() == "ok"
    clock[0] += 3600 - 60
    assert store.login_phase() == "soon"
    store.mark_login_expired()
    store.mark_login_expired()
    assert pushed == [topics.ARGENT_STATUS], "pushed once, on the change"
    assert store.login_phase() == "expired"


def test_settle_asks_the_gateway_and_a_wrong_answer_never_claims_not_tethered(pending) -> None:
    pending.write(_line("req_direct", _stamp(5)))
    late = MINT + 10 + 5 + row_state.TRAFFIC_GRACE_SECONDS + 1
    own = {"error": {"code": "not_found"}}
    for argent in (Paths(gateway_status=404, gateway="no such route"), Paths(gateway_status=404, gateway=own), Paths(gateway="<html>NOC</html>"), Paths(gateway={}),
                   Paths(gateway={"metered_count": "3", "first_metered_at": MINT + 12}), Paths(gateway={"metered_count": 2, "first_metered_at": "garbage"})):
        pending.go(argent, late)
        assert row_state.lookup("ten_1", "carnivore_api")["state"] == "pending", argent.gateway
        assert not any(p.endswith("/usage") for p in argent.paths), "an unverified row posts nothing of its own"
    pending.go(Paths(gateway={"metered_count": 2, "first_metered_at": MINT - 50}), MINT + 100)
    assert row_state.lookup("ten_1", "carnivore_api")["state"] == "pending"
