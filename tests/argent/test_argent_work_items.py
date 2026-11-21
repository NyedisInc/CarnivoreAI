
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException

from src.api.argent import work_items as routes
from src.config import settings as app_settings
from src.core import resource_push
from src.core.argent import work_items
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.device_login import DeviceLogin
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.plugins.sdk import ports
from src.models.session_requests import CreateSessionRequest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
TOKEN = "FIXTURE-asicli-not-a-secret"
SERVER = "https://cp.argent.test"
ROW = {"id": "wi_new", "kind": "feature", "parent_id": "wi_proj1", "title": "login rework", "status": "open", "updated_at": "2026-11-05T13:00:00Z"}


def fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


def etag_server(calls: List[httpx.Request], *, page: Any = None, status: int = 200, create: Any = None) -> httpx.MockTransport:
    body = page if page is not None else fixture("work_items_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            data = dict(create if create is not None else ROW)
            return httpx.Response(int(data.pop("_http_status", 200)), json=data)
        if status != 200:
            return httpx.Response(status, json={"error": {"code": "x", "message": "x"}})
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json=body, headers={"etag": '"v1"'})

    return httpx.MockTransport(handler)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    topics: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: topics.append(topic))
    store, keychain = ArgentStore(state), Keychain()
    tokens = TokenStore(keychain)
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    ports.register(PORT_NAME, {"on": True})
    yield {"state": state, "topics": topics, "store": store, "config": config}
    set_runtime(None)
    ports.unregister(PORT_NAME)
    work_items._pull.transport = None
    asyncio.run(work_items.stop())


def serve(calls: List[httpx.Request], **kw: Any) -> None:
    work_items._pull.transport, work_items._pull.client = etag_server(calls, **kw), None


def titles(env: Dict[str, Any], **kw: Any) -> List[str]:
    return [r["title"] for r in work_items.list_rows("ten_1", **kw)["items"]]


def test_pull_fills_the_cache_announces_once_and_a_304_keeps_the_rows(env: Dict[str, Any]) -> None:
    calls: List[httpx.Request] = []
    serve(calls)
    assert asyncio.run(work_items.pull_once()) == work_items.OK
    assert sorted(titles(env)) == ["Fixture Feature", "Fixture Project", "Fixture Story"]
    assert work_items.list_rows("ten_1")["rev"] == 7
    assert env["topics"] == ["argent_work_items"]
    assert asyncio.run(work_items.pull_once()) == work_items.OK
    assert calls[-1].headers["if-none-match"] == '"v1"'
    assert titles(env, kind="story", q="STORY") == ["Fixture Story"] and titles(env, parent_id="wi_feat1") == ["Fixture Story"]
    assert env["topics"] == ["argent_work_items"], "no change, no announcement"
    assert TOKEN not in b"".join(p.read_bytes() for p in env["state"].rglob("*") if p.is_file()).decode("latin1")


def test_a_changed_page_replaces_rows_and_announces_again(env: Dict[str, Any]) -> None:
    page = fixture("work_items_page.json")
    serve([], page=page)
    asyncio.run(work_items.pull_once())
    page["items"] = page["items"][:1]
    serve([], page=page)
    asyncio.run(work_items.pull_once())
    assert titles(env) == ["Fixture Project"] and env["topics"] == ["argent_work_items"] * 2


def test_merged_rows_are_hidden_and_followed_and_a_cycle_ends(env: Dict[str, Any]) -> None:
    page = fixture("work_items_page.json")
    story = page["items"][2]
    page["items"] += [dict(story, id="wi_old", title="Old Story", merged_into="wi_mid"), dict(story, id="wi_mid", title="Mid", merged_into="wi_story1"),
                      dict(story, id="wi_a", merged_into="wi_b"), dict(story, id="wi_b", merged_into="wi_a")]
    serve([], page=page)
    asyncio.run(work_items.pull_once())
    assert "Old Story" not in titles(env) and "Mid" not in titles(env)
    assert work_items.resolve("ten_1", "wi_old")["id"] == "wi_story1"
    assert work_items.resolve("ten_1", "wi_a") is None and work_items.resolve("ten_1", "wi_none") is None
    assert work_items.resolve("ten_1", "wi_story1")["id"] == "wi_story1"


def test_unknown_enum_values_read_as_unknown_and_other_tenants_stay_apart(env: Dict[str, Any]) -> None:
    page = fixture("work_items_page.json")
    page["items"][0].update(kind="epic")
    page["items"][1].update(sprint_state="paused")
    serve([], page=page)
    asyncio.run(work_items.pull_once())
    rows = {r["id"]: r for r in work_items.list_rows("ten_1")["items"]}
    assert rows["wi_proj1"]["kind"] == "unknown" and rows["wi_feat1"]["sprint_state"] == "unknown" and rows["wi_story1"]["kind"] == "story"
    assert work_items.list_rows("ten_other")["items"] == []


@pytest.mark.parametrize("status, state", [(404, work_items.UNAVAILABLE), (401, work_items.LOGIN_EXPIRED), (503, work_items.UNAVAILABLE)])
def test_argent_answers_set_the_cache_state(env: Dict[str, Any], status: int, state: str) -> None:
    serve([], status=status)
    assert asyncio.run(work_items.pull_once()) == state
    assert (env["store"].login_expired()) == (status == 401)


def test_create_passes_a_409_with_its_candidates_and_caches_a_success(env: Dict[str, Any]) -> None:
    serve([], create=fixture("work_item_create_409.json"))
    body = routes.WorkItemCreate(kind="feature", parent_id="wi_proj1", title="Fixture Feature copy")
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.create_work_item(body))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "conflict"
    assert refused.value.detail["details"]["candidates"] == fixture("work_item_create_409.json")["error"]["details"]["candidates"]
    assert titles(env) == [], "a refused create caches nothing"
    serve([])
    assert asyncio.run(routes.create_work_item(body))["id"] == "wi_new"
    assert titles(env) == ["login rework"] and env["topics"] == ["argent_work_items"]


def test_create_without_a_login_is_refused_before_any_call(env: Dict[str, Any]) -> None:
    calls: List[httpx.Request] = []
    serve(calls)
    env["store"].clear_login()
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.create_work_item(routes.WorkItemCreate(kind="project", title="x")))
    assert refused.value.status_code == 403 and calls == []


def test_get_serves_the_cache_and_marks_a_viewer(env: Dict[str, Any]) -> None:
    serve([])
    asyncio.run(work_items.pull_once())
    out = asyncio.run(routes.list_work_items(kind="feature"))
    assert out["enabled"] and out["state"] == "ok" and [r["id"] for r in out["items"]] == ["wi_feat1"] and out["rev"] == 7
    assert work_items._pull.viewed_at > 0


def test_off_means_no_call_no_poller_no_rows(env: Dict[str, Any]) -> None:
    calls: List[httpx.Request] = []
    serve(calls)
    asyncio.run(work_items.pull_once())
    assert calls
    calls.clear()
    ports.unregister(PORT_NAME)
    assert asyncio.run(routes.list_work_items()) == {"enabled": False, "state": "off", "items": [], "rev": None}
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.create_work_item(routes.WorkItemCreate(kind="project", title="x")))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "feature_off"
    assert calls == [] and not work_items.is_running()


def test_the_poller_exists_only_while_the_feature_is_on(env: Dict[str, Any]) -> None:
    from src.core.argent import lifecycle

    calls: List[httpx.Request] = []
    serve(calls)

    async def go() -> None:
        lifecycle.install()
        ports.unregister(PORT_NAME)
        await asyncio.sleep(0)
        assert not work_items.is_running() and calls == []
        ports.register(PORT_NAME, {"on": True})
        await asyncio.sleep(0.2)
        assert work_items.is_running() and calls, "on: the poller runs and pulls"
        ports.unregister(PORT_NAME)
        await asyncio.sleep(0.2)
        assert not work_items.is_running()

    asyncio.run(go())


def test_story_ref_is_optional_and_bounded() -> None:
    assert CreateSessionRequest().story_ref is None
    assert CreateSessionRequest(story_ref="wi_story1").story_ref == "wi_story1"
    with pytest.raises(ValueError):
        CreateSessionRequest(story_ref="x" * 201)


def test_create_201_is_new_200_is_joined_and_a_404_or_400_is_a_clear_refusal(env: Dict[str, Any]) -> None:
    body = routes.WorkItemCreate(kind="story", parent_id="wi_feat1", title="login rework")
    serve([], create={**ROW, "_http_status": 201})
    assert asyncio.run(routes.create_work_item(body))["created"] is True
    serve([], create=ROW)
    assert asyncio.run(routes.create_work_item(body))["created"] is False
    for status, code, want in ((404, "not_found", "parent_not_found"), (400, "invalid_parent", "invalid_parent")):
        serve([], create={"_http_status": status, "error": {"code": code, "message": "refused"}})
        with pytest.raises(HTTPException) as refused:
            asyncio.run(routes.create_work_item(body))
        assert refused.value.status_code == status and refused.value.detail["code"] == want


def test_state_filter_is_sprint_state_and_a_never_ending_cursor_keeps_the_cache(env: Dict[str, Any]) -> None:
    serve([])
    assert asyncio.run(work_items.pull_once()) == work_items.OK
    assert {r["sprint_state"] for r in work_items.list_rows("ten_1", sprint_state="none")["items"]} == {"none"}
    assert {r["sprint_state"] for r in work_items.list_rows("ten_1", sprint_state="active")["items"]} == {"active"}
    before = titles(env)
    serve([], page={"items": [{**ROW, "id": "wi_x", "title": "partial"}], "next_cursor": "c", "rev": 9})
    assert asyncio.run(work_items.pull_once()) == work_items.UNAVAILABLE
    assert titles(env) == before, "a walk cut off by the page bound must not replace the cache"
