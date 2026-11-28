
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from src.config import settings as app_settings
from src.core.argent import lifecycle, mint, registration
from src.core.argent import session_ref as refs
from src.core.argent import settings as argent_settings
from src.core.argent.device_login import DeviceLogin
from src.core.argent.registration import Registrar
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.sessions import session_events
from src.core.sessions.session_events import ENDED, RENAMED, STARTED, SessionEvent

TOKEN = "FIXTURE-asicli-not-a-secret"
FIXTURE_KEY = "FIXTURE-" + "per-session-key-" + "0123456789abcdef"


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url="https://gw.argent.test", ca_path="", enabled=True)
    monkeypatch.setattr(registration.settings_module, "read", lambda path=None: cfg)
    monkeypatch.setattr(mint.settings_module, "read", lambda path=None: cfg)
    monkeypatch.setattr(registration, "computer_display_name", lambda: "Fixture Mac")
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    box: Dict[str, Any] = {"calls": [], "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        box["calls"].append((request.url.path, body, request.headers.get("authorization", "")))
        if box["status"] != 200:
            return httpx.Response(box["status"], json={"error": {"code": "x", "message": "m"}})
        return httpx.Response(200, json={"agent_id": "agent-1", "id": "agent-1"})

    box["registrar"] = Registrar(transport=httpx.MockTransport(handler))
    unsub_registrar, unsub_rename = session_events.subscribe(box["registrar"]), session_events.subscribe(registration.follow_rename)
    box["unsub"] = lambda: (unsub_registrar(), unsub_rename())
    box["state"] = state
    yield box
    box["unsub"]()
    set_runtime(None)


def started(name: str = "carnivore_api", **kw: Any) -> SessionEvent:
    return SessionEvent(kind=STARTED, tmux_name=name, reason="created", session_row_id=7, session_uuid="uuid-7", display_name=kw.pop("display_name", "api"),
                        project=kw.pop("project", "Billing"), agent_family=kw.pop("agent_family", "claude"), **kw)


def test_started_registers_with_the_documented_payload_and_a_repeat_is_harmless(env):
    run(session_events.emit(started(display_name="  " + "n" * 200, project="p" * 200)))
    path, body, auth = env["calls"][0]
    assert path == "/v1/my/carnivore-sessions/register" and auth == f"Bearer {TOKEN}"
    assert body == {"session_uuid": "carnivore_api", "display_name": "n" * 120, "project": "p" * 120, "tool_kind": "claude", "computer": "Fixture Mac"}
    run(session_events.emit(started(display_name="api")))
    assert env["calls"][1][1]["session_uuid"] == "carnivore_api"
    assert refs.ref_for_uuid("ten_1", "uuid-7") == "carnivore_api"
    for family, kind in (("codex", "codex"), ("", "other"), ("aider", "other")):
        assert registration.tool_kind(family) == kind
    with pytest.raises(AssertionError):
        assert body["display_name"] == "n" * 200


def test_ended_deregisters_under_the_fixed_id_even_after_a_rename(env):
    run(session_events.emit(started()))
    run(session_events.emit(SessionEvent(kind=RENAMED, tmux_name="carnivore_billing", old_name="carnivore_api")))
    assert refs.ref_for_name("ten_1", "carnivore_billing") == "carnivore_api"
    run(session_events.emit(SessionEvent(kind=ENDED, tmux_name="carnivore_billing", reason="destroyed", session_uuid="uuid-7")))
    path, body, _ = env["calls"][-1]
    assert path == "/v1/my/carnivore-sessions/deregister" and body == {"session_uuid": "carnivore_api"}
    with pytest.raises(AssertionError):
        assert body == {"session_uuid": "carnivore_billing"}


def test_an_argent_failure_or_a_hang_never_blocks_or_raises_into_the_session(env, monkeypatch):
    env["status"] = 500
    run(session_events.emit(started()))
    run(session_events.emit(SessionEvent(kind=ENDED, tmux_name="carnivore_api", reason="stopped")))

    async def hang(event: SessionEvent) -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(session_events, "LISTENER_TIMEOUT_SECONDS", 0.05)
    unsub = session_events.subscribe(hang)
    try:
        run(asyncio.wait_for(session_events.emit(started()), 2))
    finally:
        unsub()


def test_a_logged_out_computer_makes_no_call_and_a_remote_row_is_never_announced(env):
    class Manager:
        def _datastore_connection(self):
            return None

        def tmux_socket_name(self):
            return "cloude"

    run(session_events.announce(Manager(), STARTED, "remote:peer-1:carnivore_api", reason="adopted"))
    assert env["calls"] == []
    run(session_events.announce(Manager(), STARTED, "carnivore_local", reason="adopted"))
    assert [c[0] for c in env["calls"]] == ["/v1/my/carnivore-sessions/register"]
    env["calls"].clear()
    ArgentStore(env["state"]).clear_login()
    run(session_events.emit(started()))
    assert env["calls"] == []


def test_a_later_mint_register_keeps_the_project_and_computer_p5_registered(env):
    run(session_events.emit(started()))
    seen: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"agent_id": "agent-1", "key": FIXTURE_KEY, "id": "k1"})

    key = run(mint.mint_session_key("carnivore_api", "api", "claude", transport=httpx.MockTransport(handler)))
    assert seen[0]["project"] == "Billing" and seen[0]["computer"] == "Fixture Mac"
    assert key.key_id == "k1"


def test_feature_off_has_no_subscriber_and_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "state_dir_override", tmp_path)
    monkeypatch.setattr(session_events, "_listeners", [])
    monkeypatch.setattr(session_events, "_tasks", set())
    assert session_events._listeners == []
    run(session_events.announce(object(), STARTED, "carnivore_api"))
    session_events.schedule(object(), STARTED, "carnivore_api")
    assert session_events._tasks == set()
    lifecycle._hear_sessions()
    lifecycle._hear_sessions()
    assert len(session_events._listeners) == 2
    lifecycle._deafen()
    assert session_events._listeners == []
    assert not (tmp_path / "argent.db").exists()


def test_a_deleted_sessions_name_reused_mints_a_fresh_id_but_a_stopped_one_keeps_its_id(env):
    run(session_events.emit(started()))
    run(session_events.emit(SessionEvent(kind=ENDED, tmux_name="carnivore_api", reason="stopped", session_uuid="uuid-7")))
    assert refs.ref_for_name("ten_1", "carnivore_api") == "carnivore_api"
    run(session_events.emit(SessionEvent(kind=ENDED, tmux_name="carnivore_api", reason="destroyed", session_uuid="uuid-7")))
    run(session_events.emit(started(display_name="new")))
    new_ref = refs.ref_for_name("ten_1", "carnivore_api")
    assert new_ref != "carnivore_api" and env["calls"][-1][1]["session_uuid"] == new_ref
    assert refs.ref_for_uuid("ten_1", "uuid-7") == new_ref
    with pytest.raises(AssertionError):
        assert new_ref == "carnivore_api"


def test_the_agent_id_is_read_from_argents_nested_register_answer():
    from src.core.argent.mint import registered_agent_id
    assert registered_agent_id({"outcome": "created", "session": {"agent_id": "a1", "session_uuid": "s"}}) == "a1"
    assert registered_agent_id({"agent_id": "a2"}) == "a2"
    assert registered_agent_id({"outcome": "created", "session": {}}) == ""


def test_the_mint_reads_argents_real_wire_shapes(env):
    run(session_events.emit(started()))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/register"):
            return httpx.Response(200, json={"outcome": "created", "session": {"agent_id": "agent-1", "session_uuid": "s"}})
        return httpx.Response(201, json={"id": "k1", "agent_id": "agent-1", "plaintext_key": FIXTURE_KEY, "key_prefix": "x"})

    key = run(mint.mint_session_key("carnivore_api", "api", "copilot", transport=httpx.MockTransport(handler)))
    assert str(key) == FIXTURE_KEY and key.key_id == "k1"
