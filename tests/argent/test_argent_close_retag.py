
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException

from src.api.argent import close as routes
from src.config import settings as app_settings
from src.core.argent import close, retag, session_ref, work_items, writeback
from src.core.argent.device_login import DeviceLogin
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
SERVER = "https://cp.argent.test"
LEAK = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3


def _ago(**kw: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


SINCE, UNTIL = _ago(days=2), _ago(days=1)
NOW = 1_793_836_800.0


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class World:

    def __init__(self) -> None:
        self.http: List[Any] = []
        self.on = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.http.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        if request.url.path == "/v1/my/retag":
            return httpx.Response(200, json=json.loads((FIXTURES / "retag_ok.json").read_text()))
        return httpx.Response(200, json={"ok": True})

    def calls(self, suffix: str) -> List[Dict[str, Any]]:
        return [b for m, p, b in self.http if m == "POST" and p.endswith(suffix)]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    w = World()
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", "FIXTURE-asicli-not-a-secret")
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    work_items.replace_all("ten_1", json.loads((FIXTURES / "work_items_page.json").read_text())["items"] + [
        {"id": "wi_story2", "kind": "story", "parent_id": "wi_feat1", "title": "Second Story", "status": "open"}], 7)
    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(w.handler), None
    monkeypatch.setattr(writeback, "is_running", lambda: w.on)
    monkeypatch.setattr(writeback, "poke", lambda: None)
    monkeypatch.setattr(work_items, "poke", lambda: None)
    yield w
    work_items._pull.transport, work_items._pull.client = None, None
    set_runtime(None)


def waiting() -> List[Dict[str, Any]]:
    import sqlite3
    from contextlib import closing

    from src.core.argent import store

    with closing(store.open_db()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM writeback WHERE milestone = 'close'")]


def refused(coro: Any) -> close.Refused:
    with pytest.raises(close.Refused) as caught:
        asyncio.run(coro)
    return caught.value


def test_close_tells_argent_and_queues_the_done_comment(world: World) -> None:
    out = asyncio.run(close.close_item("wi_story1", "shipped in 1.4"))
    assert out == {"work_item_id": "wi_story1", "closed": True, "status_refused": False}
    assert world.calls("/work-items/wi_story1/close") == [{"reason": "shipped in 1.4", "comment": False}]
    rows = waiting()
    assert len(rows) == 1 and rows[0]["item_id"] == "wi_story1" and json.loads(rows[0]["payload"])["reason"] == "shipped in 1.4"
    assert refused(close.close_item("wi_nope", "")).code == "unknown_work_item" and len(world.calls("/close")) == 1


def test_a_credential_in_the_reason_is_never_sent(world: World) -> None:
    assert refused(close.close_item("wi_story1", f"done {LEAK}")).code == "blocked_secret"
    assert world.http == [] and waiting() == []


def test_the_comment_text_is_the_owners_reason_and_posts_as_a_comment(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writeback, "beast_armed", lambda: True)
    monkeypatch.setattr(writeback, "install_id", lambda: "install-fixture")
    asyncio.run(close.close_item("wi_story1", "shipped in 1.4"))
    asyncio.run(writeback.run_pass(world_client(world), "ten_1", now=time.time() + 5))
    posted = world.calls("/writeback")
    assert len(posted) == 1 and posted[0]["kind"] == "comment" and posted[0]["body"].endswith("closed: shipped in 1.4")


def world_client(w: World) -> Any:
    from src.core.argent.client import ArgentClient

    return ArgentClient(SERVER, lambda: "FIXTURE-asicli-not-a-secret", transport=httpx.MockTransport(w.handler))


def bind_session(name: str = "carnivore_api") -> str:
    return session_ref.ref_for_name("ten_1", name)


def manager(found: bool = True, remote: bool = False) -> Any:
    info = SimpleNamespace(tmux_session="carnivore_api") if found else None

    async def get_session_info(_id: str) -> Any:
        return info

    backends = {"remote:peer-1:x": SimpleNamespace(host_key="peer-1", tmux_session="x")} if remote else {}
    return SimpleNamespace(get_session_info=get_session_info, _registry=SimpleNamespace(backends=backends))


def retag_body(**over: Any) -> routes.RetagBody:
    base = {"session_id": "ses_1", "since": SINCE, "until": UNTIL, "work_item_id": "wi_story2", "reason": "wrong story picked"}
    return routes.RetagBody(**{**base, **over})


def call_route(body: routes.RetagBody, mgr: Any) -> Any:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=mgr)))
    return asyncio.run(routes.retag(request, body))


def test_retag_moves_own_spend_and_sends_the_session_window_item_and_reason(world: World) -> None:
    ref = bind_session()
    out = call_route(retag_body(), manager())
    assert out["moved_micros"] == 450000 and out["to_work_item_id"] == "wi_story2"
    assert world.calls("/retag") == [{"session_id": ref, "since": SINCE, "until": UNTIL, "to_work_item_id": "wi_story2", "reason": "wrong story picked"}]


def test_retag_refuses_what_is_not_own_spend(world: World) -> None:
    bind_session()
    for mgr, code in ((manager(found=False), 404), (manager(remote=True), 409)):
        with pytest.raises(HTTPException) as caught:
            call_route(retag_body(session_id="remote:peer-1:x" if code == 409 else "ses_9"), mgr)
        assert caught.value.status_code == code
    other = SimpleNamespace(tmux_session="carnivore_other")

    async def info(_id: str) -> Any:
        return other

    with pytest.raises(HTTPException) as caught:
        call_route(retag_body(), SimpleNamespace(get_session_info=info, _registry=SimpleNamespace(backends={})))
    assert caught.value.detail["code"] == "not_own_session" and retag.own_ref("ten_1", "carnivore_other") == ""
    assert world.http == []


@pytest.mark.parametrize("over,code", [
    ({"reason": "no"}, "bad_reason"), ({"reason": "x" * 201}, "bad_reason"), ({"reason": "  "}, "bad_reason"), ({"reason": f"oops {LEAK}"}, "blocked_secret"),
    ({"since": _ago(days=40)}, "range_too_long"), ({"until": _ago(days=3)}, "bad_range"), ({"until": _ago(days=-1)}, "bad_range"), ({"since": SINCE.rstrip("Z")}, "bad_range"),
    ({"since": "last tuesday"}, "bad_range"), ({"work_item_id": "wi_nope"}, "unknown_work_item"),
])
def test_retag_refuses_a_bad_request_before_any_call(world: World, over: Dict[str, Any], code: str) -> None:
    bind_session()
    with pytest.raises(HTTPException) as caught:
        call_route(retag_body(**over), manager())
    assert caught.value.detail["code"] == code and world.http == []


def test_the_range_cap_is_31_days_and_not_in_the_future() -> None:
    assert retag.check_range("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", now=NOW) == ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
    with pytest.raises(close.Refused) as caught:
        retag.check_range("2026-10-01T00:00:00Z", "2026-11-01T00:00:01Z", now=NOW)
    assert caught.value.code == "range_too_long"
    with pytest.raises(close.Refused) as caught:
        retag.check_range("2026-11-04T00:00:00Z", "2026-11-06T00:00:00Z", now=NOW)
    assert caught.value.code == "bad_range"


def test_off_makes_no_call_and_queues_nothing(world: World) -> None:
    bind_session()
    world.on = False
    assert refused(close.close_item("wi_story1", "x")).code == "feature_off"
    with pytest.raises(HTTPException) as caught:
        call_route(retag_body(), manager())
    assert caught.value.detail["code"] == "feature_off" and world.http == [] and waiting() == []


def _answer(world: World, status: int, fixture: str) -> None:
    inner = world.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/my/retag":
            return httpx.Response(status, json=json.loads((FIXTURES / fixture).read_text()))
        return inner(request)

    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(handler), None


def test_retag_refusals_get_plain_messages(world: World) -> None:
    bind_session()
    for status, fixture, words in ((400, "retag_window_empty_400.json", "has no spend for this session"), (409, "retag_dest_over_cap_409.json", "paused or would go over its budget")):
        _answer(world, status, fixture)
        with pytest.raises(HTTPException) as caught:
            call_route(retag_body(), manager())
        assert caught.value.status_code == status and words in caught.value.detail["message"]
    _answer(world, 409, "retag_dest_over_cap_409.json")
    assert "destination paused" not in str(refused(retag.retag("carnivore_api", SINCE, UNTIL, "wi_story2", "wrong story picked")))


def test_a_close_refused_by_a_newer_tracker_state_names_that_state(world: World) -> None:
    inner = world.handler
    world_state = {"v": "in review"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/close"):
            return httpx.Response(200, json={"ok": True, "status_refused": world_state["v"]})
        return inner(request)

    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(handler), None
    out = asyncio.run(close.close_item("wi_story1", ""))
    assert out["status_refused"] is True and out["tracker_state"] == "in review" and "in review" in out["message"]
    world_state["v"] = True  # type: ignore[assignment]
    plain = asyncio.run(close.close_item("wi_story1", ""))
    assert plain["status_refused"] is True and "tracker_state" not in plain


def mirror_rows(milestone: str) -> List[Dict[str, Any]]:
    import sqlite3
    from contextlib import closing

    from src.core.argent import store

    with closing(store.open_db()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM writeback WHERE milestone = ?", (milestone,))]


def test_the_owner_route_close_that_worked_queues_no_mirror_row_and_a_transient_failure_queues_exactly_one(world: World) -> None:
    asyncio.run(close.close_item("wi_story1", "shipped"))
    assert mirror_rows(writeback.MOVE_CLOSE) == []
    inner = world.handler
    answers = {"status": 429}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/close"):
            return httpx.Response(answers["status"], headers={"Retry-After": "60"}, json={"error": "rate limit exceeded"})
        return inner(request)

    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(handler), None
    assert refused(close.close_item("wi_story1", "shipped")).code == "rate_limited"
    assert len(mirror_rows(writeback.MOVE_CLOSE)) == 1
    assert refused(close.close_item("wi_story1", "shipped")).code == "rate_limited" and len(mirror_rows(writeback.MOVE_CLOSE)) == 1
    answers["status"] = 404
    world.http.clear()
    mirror_rows(writeback.MOVE_CLOSE)
    assert refused(close.close_item("wi_story2", "x")).code == "unavailable" and len(mirror_rows(writeback.MOVE_CLOSE)) == 1



class FakeCards:

    def __init__(self) -> None:
        self.rows = {1: self.make(1, "github:wi_story1", "review"), 2: dict(self.make(2, "", "review"), origin={"kind": "owner", "ref": ""})}

    @staticmethod
    def make(card_id: int, ref: str, column: str) -> Dict[str, Any]:
        return {"id": card_id, "title": "Fixture Story", "parent": None, "list_key": "7", "level": "task", "column": column, "state": "open", "holder": None,
                "origin": {"kind": "argent", "ref": ref}}

    async def card(self, card_id: int) -> Any:
        row = self.rows.get(card_id)
        return dict(row) if row else None

    async def policy_read(self, op: str, args: Any) -> Dict[str, Any]:
        return {"rules": {"7": {"auto_done": True, "auto_validate": False}}}

    async def act(self, op: str, card_id: Any, args: Any, by: str) -> Dict[str, Any]:
        row = self.rows[int(card_id)]
        before = row["column"]
        row["column"] = {"done": "done", "set_column": args.get("column"), "start": "in_progress", "set_lane": "in_progress" if args.get("queued") else "todo"}[op]
        if row["column"] != before and not args.get("from_tracker") and row["origin"]["kind"] == "argent" and row["column"] in ("done", "in_progress"):
            from src.core.swarm.cards import port as card_port

            await card_port._mirror(int(card_id), before, row["column"], str(args.get("reason") or ""))
        return {"card": dict(row), "effects": [], "data": {"changed": before != row["column"]}}


@pytest.fixture
def cards(world: World, monkeypatch: pytest.MonkeyPatch) -> FakeCards:
    from src.core.swarm.cards import notices as card_notices, ops, port as card_port

    fake = FakeCards()
    card_port.register(fake)
    monkeypatch.setattr(card_notices, "note", lambda *a, **k: None)

    async def anyone(*a: Any, **k: Any) -> Dict[str, Any]:
        return {}

    monkeypatch.setattr(ops, "_allow", anyone)
    yield fake
    card_port.register(None)


def one_close_row(world: World) -> None:
    rows = mirror_rows(writeback.MOVE_CLOSE)
    assert len(rows) == 1 and rows[0]["item_id"] == "wi_story1" and rows[0]["state"] == "ready"
    assert world.http == []


def test_every_path_into_done_queues_one_close_row_and_none_calls_argent_inline(world: World, cards: FakeCards) -> None:
    from src.core.swarm.cards import ops

    app: Any = SimpleNamespace()
    paths = {
        "owner done": lambda: ops.done(app, 1, {}, by="owner"),
        "board drag": lambda: ops.set_column(app, 1, {"column": "done"}, by="owner"),
        "agent close": lambda: ops.close(app, 1, {"reason": "all validated"}, by="agent:1"),
        "finish": lambda: ops._close_done(app, 1, "finished and validated by its agent", "agent:1"),
    }
    for name, call in paths.items():
        cards.rows[1]["column"] = "review"
        world.http.clear()
        for row in mirror_rows(writeback.MOVE_CLOSE):
            writeback._set(row["id"], None, state=writeback.POSTED)
        asyncio.run(call())
        pending = [r for r in mirror_rows(writeback.MOVE_CLOSE) if r["state"] == "ready"]
        assert len(pending) == 1 and pending[0]["item_id"] == "wi_story1", name
        assert world.http == [], name
    reasons = {json.loads(r["payload"]).get("reason") for r in mirror_rows(writeback.MOVE_CLOSE)}
    assert "all validated" in reasons


def test_a_card_that_is_not_an_argent_story_or_is_already_done_or_feature_off_queues_nothing(world: World, cards: FakeCards) -> None:
    from src.core.swarm.cards import ops

    app: Any = SimpleNamespace()
    asyncio.run(ops.done(app, 2, {}, by="owner"))
    cards.rows[1]["column"] = "done"
    asyncio.run(ops.set_column(app, 1, {"column": "done"}, by="owner"))
    assert mirror_rows(writeback.MOVE_CLOSE) == []
    cards.rows[1]["column"] = "review"
    world.on = False
    asyncio.run(ops.done(app, 1, {}, by="owner"))
    assert mirror_rows(writeback.MOVE_CLOSE) == []


def test_a_tracker_driven_move_to_done_is_never_posted_back(world: World, cards: FakeCards) -> None:
    from src.core.swarm.cards import ops

    asyncio.run(ops.set_column(SimpleNamespace(), 1, {"column": "done", "from_tracker": True}, by="owner"))
    assert cards.rows[1]["column"] == "done" and mirror_rows(writeback.MOVE_CLOSE) == []


def test_a_story_card_entering_in_progress_queues_one_picked_row(world: World, cards: FakeCards) -> None:
    from src.core.swarm.cards import ops

    cards.rows[1]["column"] = "todo"
    asyncio.run(ops.set_column(SimpleNamespace(), 1, {"column": "in_progress"}, by="owner"))
    asyncio.run(ops.set_column(SimpleNamespace(), 1, {"column": "in_progress"}, by="owner"))
    assert len(mirror_rows(writeback.MOVE_PICKED)) == 1 and world.http == []
    cards.rows[1]["column"] = "todo"
    asyncio.run(ops.set_column(SimpleNamespace(), 1, {"column": "review"}, by="owner"))
    assert len(mirror_rows(writeback.MOVE_PICKED)) == 1


def test_a_root_declare_queues_one_picked_row_only_when_the_item_changed_and_a_card_start_adds_none(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.argent import declare, timeline

    monkeypatch.setattr(timeline, "is_running", lambda: True)
    monkeypatch.setattr(timeline, "poke", lambda: None)
    ref = bind_session()
    asyncio.run(declare.declare("carnivore_api", "wi_story1", "picker"))
    asyncio.run(declare.declare("carnivore_api", "wi_story1", "picker"))
    rows = mirror_rows(writeback.MOVE_PICKED)
    assert len(rows) == 1 and rows[0]["item_id"] == "wi_story1" and rows[0]["session_ref"] == ref
    asyncio.run(declare.declare("carnivore_api", "wi_story2", "card"))
    assert len(mirror_rows(writeback.MOVE_PICKED)) == 1
    asyncio.run(declare.declare("carnivore_api", "wi_story2", "picker", "sub1"))
    assert len(mirror_rows(writeback.MOVE_PICKED)) == 1


def test_the_plugin_seam_reaches_the_mirror_from_its_write_thread_and_a_stale_record_is_dropped(world: World, cards: FakeCards) -> None:
    from src.core.swarm.cards import port as card_port

    async def scenario() -> None:
        card_port.register(cards, asyncio.get_running_loop())
        cards.rows[1]["column"] = "done"
        await asyncio.to_thread(card_port.card_moved, 1, "review", "done")
        cards.rows[1]["column"] = "review"
        await asyncio.to_thread(card_port.card_moved, 1, "todo", "done")
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    one_close_row(world)
