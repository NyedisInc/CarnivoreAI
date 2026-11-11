
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.argent import context as routes
from src.config import settings as app_settings
from src.core.argent import declare, notices, timeline, work_items
from src.core.argent.client import ArgentClient, Unauthorized
from src.core.argent.device_login import DeviceLogin
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.cplugs.sdk import ports

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
TOKEN = "FIXTURE-asicli-not-a-secret"
SERVER = "https://cp.argent.test"


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class Argent:

    def __init__(self, mode: str = "up") -> None:
        self.mode, self.attempts, self.accepted = mode, [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.attempts.append((request.url.path, body, request.headers.get("authorization")))
        if self.mode == "down":
            raise httpx.ConnectError("down")
        if self.mode == "dark":
            return httpx.Response(404, json={})
        if self.mode == "not_found":
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})
        if self.mode == "refuse":
            return httpx.Response(400, json={"error": {"code": "bad_request", "message": "x"}})
        if self.mode == "login":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "x"}})
        self.accepted.append((request.url.path, body))
        return httpx.Response(200, json=json.loads((FIXTURES / "context_post_ok.json").read_text()))

    def client(self) -> ArgentClient:
        return ArgentClient(SERVER, lambda: TOKEN, transport=httpx.MockTransport(self.handler))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    overflow: List[int] = []
    monkeypatch.setattr(notices, "queue_overflow", lambda n: overflow.append(n))
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    page = json.loads((FIXTURES / "work_items_page.json").read_text())
    work_items.replace_all("ten_1", page["items"], 7)
    ports.register(PORT_NAME, {"on": True})
    yield {"state": state, "overflow": overflow, "store": store}
    set_runtime(None)
    ports.unregister(PORT_NAME)
    work_items._pull.transport, work_items._pull.client = None, None
    asyncio.run(timeline.stop())


def posted(argent: Argent) -> List[tuple]:
    return [(path.split("/")[4], body["sub_agent_id"], body["work_item_id"]) for path, body in argent.accepted]


def assert_in_order(rows: List[tuple], expected: List[tuple]) -> None:
    assert rows == expected, f"replayed {rows}, queued {expected}"


def _run_on(make: Any) -> Any:

    async def go() -> Any:
        timeline.start()
        try:
            return await make()
        finally:
            await timeline.stop()

    return asyncio.run(go())


def _request(names: Dict[str, Optional[str]]) -> Any:
    async def get_session_info(session_id: str) -> Any:
        name = names.get(session_id)
        return SimpleNamespace(tmux_session=name) if name else None

    manager = SimpleNamespace(get_session_info=get_session_info)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))


def test_declared_while_argent_is_down_replays_in_order_once_it_is_back(env: Dict[str, Any]) -> None:
    argent = Argent("down")
    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(argent.handler), None

    async def scenario() -> None:
        timeline.start()
        assert (await declare.declare("sess_a", "wi_proj1", "picker"))["changed"] is True
        await declare.declare("sess_a", "wi_feat1", "card", sub_agent_id="agent_9")
        assert (await declare.declare("sess_a", "wi_proj1", "picker"))["changed"] is False
        await declare.declare("sess_a", "wi_story1", "classifier")
        await declare.declare("sess_b", "wi_proj1", "picker")
        for _ in range(5):
            await asyncio.sleep(0.02)
        assert argent.accepted == [] and timeline.backlog("ten_1") == 4 and argent.attempts, "down: queued, tried, nothing lost"
        argent.mode = "up"
        timeline.poke()
        for _ in range(100):
            if timeline.backlog("ten_1") == 0:
                break
            await asyncio.sleep(0.02)

    asyncio.run(scenario())
    assert_in_order(posted(argent), [("sess_a", "", "wi_proj1"), ("sess_a", "agent_9", "wi_feat1"), ("sess_a", "", "wi_story1"), ("sess_b", "", "wi_proj1")])
    for path, body in argent.accepted:
        assert set(body) == {"sub_agent_id", "work_item_id", "ts", "reason"} and path.endswith("/context")
    assert [b["reason"] for _, b in argent.accepted] == ["picker", "card", "classifier", "picker"]
    assert {a[2] for a in argent.attempts} == {f"Bearer {TOKEN}"}
    assert TOKEN not in b"".join(p.read_bytes() for p in env["state"].rglob("*") if p.is_file()).decode("latin1")
    with pytest.raises(AssertionError):
        assert_in_order(list(reversed(posted(argent))), posted(argent))


def test_a_resend_carries_the_same_ts_and_two_changes_never_share_one(env: Dict[str, Any]) -> None:
    argent = Argent("down")
    first = timeline.record("ten_1", "s", "", "wi_proj1", "picker", clock=lambda: 100.0)
    second = timeline.record("ten_1", "s", "", "wi_feat1", "picker", clock=lambda: 100.0)
    assert first["ts"] < second["ts"], "a rising ts per (session, sub-agent): Argent de-duplicates on it"
    for _ in range(2):
        asyncio.run(timeline.replay(argent.client(), "ten_1"))
    sent = [(a[1]["work_item_id"], a[1]["ts"]) for a in argent.attempts]
    assert sent == [("wi_proj1", first["ts"])] * 2, "the head blocks its session: the resend is the same row"
    argent.mode = "up"
    assert asyncio.run(timeline.replay(argent.client(), "ten_1")) == 2
    assert [b["ts"] for _, b in argent.accepted] == [first["ts"], second["ts"]]
    assert asyncio.run(timeline.replay(argent.client(), "ten_1")) == 0, "acked rows are not sent again"
    assert timeline._next_ts(second["ts"], 0.0) > second["ts"]


def test_rows_go_only_to_the_tenant_that_queued_them(env: Dict[str, Any]) -> None:
    timeline.record("ten_1", "s1", "", "wi_proj1", "picker")
    timeline.record("ten_2", "s2", "", "wi_proj9", "picker")
    argent = Argent("up")
    assert asyncio.run(timeline.replay(argent.client(), "ten_1")) == 1
    assert posted(argent) == [("s1", "", "wi_proj1")]
    assert timeline.backlog("ten_2") == 1 and timeline.backlog("ten_1") == 0
    with pytest.raises(AssertionError):
        assert posted(argent) == [("s1", "", "wi_proj1"), ("s2", "", "wi_proj9")]
    assert timeline.current("ten_2", "s1") == [] and len(timeline.current("ten_2", "s2")) == 1


def test_past_the_cap_the_oldest_are_dropped_with_a_notice(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timeline, "MAX_UNACKED", 3)
    for n in range(5):
        timeline.record("ten_1", "s", "", f"wi_{n}", "picker")
    assert timeline.backlog("ten_1") == 3 and env["overflow"] == [1, 1]
    argent = Argent("up")
    asyncio.run(timeline.replay(argent.client(), "ten_1"))
    assert [i for _, _, i in posted(argent)] == ["wi_2", "wi_3", "wi_4"], "the newest are kept"
    timeline.record("ten_2", "s", "", "wi_x", "picker")
    assert env["overflow"] == [1, 1], "the cap is per tenant"


def test_a_missing_route_a_refusal_and_a_401_each_do_the_right_thing(env: Dict[str, Any]) -> None:
    timeline.record("ten_1", "s1", "", "wi_proj1", "picker")
    timeline.record("ten_1", "s1", "agent_1", "wi_feat1", "picker")
    timeline.record("ten_1", "s2", "", "wi_proj1", "picker")
    dark = Argent("dark")
    assert asyncio.run(timeline.replay(dark.client(), "ten_1")) == 0 and timeline.backlog("ten_1") == 3, "contract C dark: queue only"
    assert len(dark.attempts) == 2, "one try per session: the later row of s1 waits behind its first"
    login = Argent("login")
    with pytest.raises(Unauthorized):
        asyncio.run(timeline.replay(login.client(), "ten_1"))
    assert timeline.backlog("ten_1") == 3, "a 401 acknowledges nothing"
    refuse = Argent("refuse")
    assert asyncio.run(timeline.replay(refuse.client(), "ten_1")) == 3 and timeline.backlog("ten_1") == 0, "a 400 is dropped, never looped"


def test_a_sub_agent_inherits_the_root_item_until_it_declares_its_own(env: Dict[str, Any]) -> None:
    timeline.record("ten_1", "s", "", "wi_proj1", "picker")
    declared = timeline.current("ten_1", "s")
    assert timeline.effective(declared, "agent_7") == "wi_proj1" and timeline.effective(declared, "") == "wi_proj1"
    timeline.record("ten_1", "s", "agent_7", "wi_feat1", "card")
    declared = timeline.current("ten_1", "s")
    assert timeline.effective(declared, "agent_7") == "wi_feat1" and timeline.effective(declared, "agent_8") == "wi_proj1"
    assert timeline.effective([], "agent_7") == "" and timeline.effective([{"sub_agent_id": "x", "work_item_id": "wi_a"}], "agent_7") == ""


def test_off_queues_nothing_and_starts_nothing(env: Dict[str, Any]) -> None:
    ports.unregister(PORT_NAME)
    assert timeline.is_running() is False
    with pytest.raises(declare.DeclareError) as err:
        asyncio.run(declare.declare("sess_a", "wi_proj1", "picker"))
    assert err.value.code == "feature_off"
    asyncio.run(declare.declare_at_create("sess_a", "wi_proj1"))
    assert timeline.backlog("ten_1") == 0 and timeline.current("ten_1", "sess_a") == []
    request = _request({"ses_a": "sess_a"})
    assert asyncio.run(routes.get_context(request, "ses_a")) == {"enabled": False, "session_id": None, "agents": [], "queued": 0}
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.put_context(request, "ses_a", routes.ContextDeclaration(work_item_id="wi_proj1")))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "feature_off"
    ports.register(PORT_NAME, {"on": True})
    assert _run_on(lambda: declare.declare("sess_a", "wi_proj1", "picker"))["changed"] is True


def test_the_routes_declare_read_back_and_refuse_what_they_must(env: Dict[str, Any]) -> None:
    request = _request({"ses_a": "sess_a"})

    async def scenario() -> None:
        timeline.start()
        try:
            put = await routes.put_context(request, "ses_a", routes.ContextDeclaration(work_item_id="wi_feat1"))
            assert put["changed"] is True and put["work_item_id"] == "wi_feat1" and put["session_id"] == "sess_a"
            await routes.put_context(request, "ses_a", routes.ContextDeclaration(work_item_id="wi_story1", sub_agent_id="agent_3", source="mcp-self"))
            got = await routes.get_context(request, "ses_a")
            assert got["enabled"] is True and got["session_id"] == "sess_a"
            by_agent = {a["sub_agent_id"]: a for a in got["agents"]}
            assert by_agent[""]["work_item_id"] == "wi_feat1" and by_agent["agent_3"]["effective_work_item_id"] == "wi_story1"
            assert by_agent["agent_3"]["source"] == "mcp-self"
            for bad, code, status in ((dict(work_item_id="wi_nope"), "unknown_work_item", 404), (dict(work_item_id="wi_proj1", sub_agent_id="a b"), "bad_sub_agent", 422)):
                with pytest.raises(HTTPException) as refused:
                    await routes.put_context(request, "ses_a", routes.ContextDeclaration(**bad))
                assert (refused.value.status_code, refused.value.detail["code"]) == (status, code)
            with pytest.raises(HTTPException) as gone:
                await routes.get_context(request, "ses_missing")
            assert gone.value.status_code == 404
        finally:
            await timeline.stop()

    asyncio.run(scenario())
    with pytest.raises(ValidationError):
        routes.ContextDeclaration(work_item_id="wi_proj1", source="classifier")


def test_argents_own_not_found_drops_the_row_but_a_bare_404_keeps_it(env: Dict[str, Any]) -> None:
    timeline.record("ten_1", "s1", "", "wi_proj1", "picker")
    timeline.record("ten_1", "s1", "agent_1", "wi_feat1", "picker")
    assert asyncio.run(timeline.replay(Argent("dark").client(), "ten_1")) == 0 and timeline.backlog("ten_1") == 2
    gone = Argent("not_found")
    assert asyncio.run(timeline.replay(gone.client(), "ten_1")) == 2 and timeline.backlog("ten_1") == 0, "a permanent refusal is dropped, not looped"
    assert len(gone.attempts) == 2


def test_a_merged_item_is_declared_as_its_target_and_the_picker_story_lands_at_create(env: Dict[str, Any]) -> None:
    page = json.loads((FIXTURES / "work_items_page.json").read_text())
    work_items.replace_all("ten_1", page["items"] + [dict(page["items"][2], id="wi_old", merged_into="wi_story1")], 8)

    async def go() -> Dict[str, Any]:
        await declare.declare_at_create("sess_c", "wi_old")
        await declare.declare_at_create("sess_d", "wi_unknown")
        return {"c": timeline.current("ten_1", "sess_c"), "d": timeline.current("ten_1", "sess_d")}

    found = _run_on(go)
    assert [r["work_item_id"] for r in found["c"]] == ["wi_story1"] and [r["reason"] for r in found["c"]] == ["picker"] and found["d"] == []
