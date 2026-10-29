
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import pytest

from src.cplugs.host import identity, runtime, sidecar_registry
from src.cplugs.host import state as owner_state
from src.cplugs.runtime.owner_tokens import OwnerTokens, TokenRefused
from src.cplugs.runtime.process import ProcessEnded
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401

NAME, ITEM = "clock", "acme/clock"
CPLUG = {"schema": 1, "id": NAME, "name": "Clock", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
         "permissions": {"app": []}, "tools": [], "routes": ["ping", "fire"]}

def _async(fn):
    async def call(name):
        return fn(name)
    return call



class FakeProc:

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.reply: Callable[[], Any] = lambda: {"status": 200, "body": {"ok": True}}

    async def request(self, method: str, params: Dict[str, Any], timeout: float = 5.0) -> Any:
        assert method == "route.handle" and timeout == 5.0
        self.calls.append(params)
        out = self.reply()
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.main import app

    state = tmp_path / "state"
    root = state / "cplug-code" / NAME
    root.mkdir(parents=True)
    (root / "cplug.json").write_text(json.dumps(CPLUG))
    (root / "main.py").write_text("x = 1\n")
    record = identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    rows = [SimpleNamespace(item_id=ITEM, kind="cplug", source_index_url="https://index.example/v1", publisher_key_id="K")]
    before = sidecar_registry.current()
    sidecar_registry.install(sidecar_registry.SidecarRegistry(state, lambda: rows))
    assert sidecar_registry.current().reload() == 1 and sidecar_registry.find(NAME).manifest.routes == ("ping", "fire")
    m = sidecar_registry.find(NAME).manifest
    owner_state.update(state, m, None, lambda st: replace(st, digest=m.code_digest))
    proc, tokens, flag = FakeProc(), OwnerTokens(), {"on": True, "running": True, "state": "running", "safe": {"off": False}}
    app.state.cplugs_host = runtime.Host(state, app)
    app.state.sidecar_runtime = SimpleNamespace(
        tokens=tokens, safe_mode=lambda: flag["safe"],
        supervisor=SimpleNamespace(process=lambda name: proc if flag["running"] and name == NAME else None,
                                   ensure=_async(lambda name: proc if flag["running"] and name == NAME else None),
                                   state=lambda name: flag["state"]))
    monkeypatch.setattr(runtime.Host, "enabled", lambda self, cid: flag["on"] if cid == NAME else False)
    from src.cplugs.host import sidecar_routes

    sidecar_routes._calls.clear()
    yield SimpleNamespace(proc=proc, flag=flag, tokens=tokens, key=record.uuid, routes=sidecar_routes)
    del app.state.cplugs_host
    del app.state.sidecar_runtime
    sidecar_registry.install(before)


def url(route: str = "ping", cid: str = NAME) -> str:
    return f"/api/v1/cplugs/{cid}/r/{route}"


def test_unknown_disabled_undeclared_and_not_running_are_refused(client, owner_jwt, world):  # noqa: F811
    h = bearer(owner_jwt)
    assert client.get(url("ping", "nosuch"), headers=h).json()["detail"]["code"] == "cplug_unknown"
    assert client.get(url("ping", "huddle"), headers=h).status_code == 404
    r = client.get(url("secret-admin"), headers=h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "cplug_unknown"
    assert client.get("/api/v1/cplugs/clock/r/", headers=h).status_code == 404
    world.flag["on"] = False
    r = client.get(url(), headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_disabled"
    world.flag["on"], world.flag["running"] = True, False
    r = client.get(url(), headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_not_running"
    assert world.proc.calls == []
    assert client.get(url()).status_code in (401, 403)
    world.flag["running"] = True
    assert client.get(url(), headers=h).status_code == 200


def test_a_declared_route_returns_the_plugin_json_and_the_params_it_was_sent(client, owner_jwt, world):  # noqa: F811
    world.proc.reply = lambda: {"status": 201, "body": {"time": "12:00", "n": [1, 2]}}
    r = client.post(url("fire") + "/a/b?x=1&x=2", json={"go": 1}, headers=bearer(owner_jwt))
    assert r.status_code == 201 and r.json() == {"time": "12:00", "n": [1, 2]}
    assert r.headers["content-type"] == "application/json" and r.headers["x-content-type-options"] == "nosniff"
    assert world.proc.calls == [{"route": "fire", "method": "POST", "path_params": {"rest": "a/b"}, "query": {"x": ["1", "2"]},
                                 "body": {"go": 1}, "actor": "owner"}]
    assert client.request("TRACE", url(), headers=bearer(owner_jwt)).status_code == 405


def test_html_or_a_lying_content_type_comes_back_as_json_with_none_of_its_headers(client, owner_jwt, world):  # noqa: F811
    page = "<html><script>alert(1)</script></html>"
    world.proc.reply = lambda: {"status": 200, "body": page, "content_type": "text/html", "content-type": "text/html",
                                "headers": {"Content-Type": "text/html", "Set-Cookie": "sid=1", "X-Plugin": "yes",
                                            "Content-Security-Policy": "default-src *"}}
    r = client.get(url(), headers=bearer(owner_jwt))
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.json() == page and r.content == json.dumps(page).encode()
    assert r.headers["x-content-type-options"] == "nosniff"
    assert not {"set-cookie", "x-plugin"} & set(r.headers)
    assert "default-src *" not in r.headers["content-security-policy"]
    for bad in ({"status": 302, "body": {}}, {"status": 200, "body": float("nan")}, {"body": {}}, "<html>", {"status": True, "body": 1}):
        world.proc.reply = lambda bad=bad: bad
        assert client.get(url(), headers=bearer(owner_jwt)).status_code == 502, bad
    world.proc.reply = lambda: {"status": 200, "body": "x" * (world.routes.MAX_RESPONSE_BYTES + 1)}
    assert client.get(url(), headers=bearer(owner_jwt)).json()["detail"]["code"] == "response_too_large"


def test_request_limits_json_only_timeout_plugin_error_and_rate(client, owner_jwt, world):  # noqa: F811
    h = bearer(owner_jwt)
    big = json.dumps({"a": "x" * world.routes.MAX_REQUEST_BYTES})
    assert client.post(url(), content=big, headers={**h, "Content-Type": "application/json"}).status_code == 413
    assert client.post(url(), content="a=1", headers={**h, "Content-Type": "text/plain"}).status_code == 415
    assert client.post(url(), content="{no", headers={**h, "Content-Type": "application/json"}).status_code == 400
    assert world.proc.calls == []
    import asyncio

    world.proc.reply = lambda: asyncio.TimeoutError()
    assert client.get(url(), headers=h).status_code == 504
    world.proc.reply = lambda: ProcessEnded("plugin_error")
    assert client.get(url(), headers=h).json()["detail"]["code"] == "plugin_error"
    world.proc.reply = lambda: ProcessEnded("exited")
    assert client.get(url(), headers=h).json()["detail"]["code"] == "cplug_not_running"
    world.proc.reply = lambda: {"status": 200, "body": 1}
    world.routes._calls.clear()
    codes = [client.get(url(), headers=h).status_code for _ in range(world.routes.RATE_LIMIT + 1)]
    assert codes[:-1] == [200] * world.routes.RATE_LIMIT and codes[-1] == 429


def test_the_act_route_refuses_an_api_key_and_the_token_is_keyed_by_the_install_uuid(client, owner_jwt, key_store, world):  # noqa: F811
    body = {"cplug_id": NAME, "route": "fire", "session_ref": "ses_one", "body": {"why": "click"}}
    _row, secret = key_store.create("script")
    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(secret))
    assert r.status_code == 403 and r.json()["detail"] == {"reason": "api_key_forbidden"}
    assert world.proc.calls == []

    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt))
    assert r.status_code == 200, r.text
    sent = world.proc.calls[0]
    assert sent["route"] == "fire" and sent["session_ref"] == "ses_one" and sent["actor"] == "owner" and sent["body"] == {"why": "click"}
    token = sent["owner_token"]
    assert token not in r.text
    with pytest.raises(TokenRefused) as wrong:
        world.tokens.redeem(NAME, token, "ses_one")
    assert wrong.value.code == "wrong_session"
    with pytest.raises(TokenRefused) as burned:
        world.tokens.redeem(world.key, token, "ses_one")
    assert burned.value.code == "unknown"
    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt))
    token = world.proc.calls[1]["owner_token"]
    with pytest.raises(TokenRefused) as other:
        world.tokens.redeem("f" * 32, token, "ses_one")
    assert other.value.code == "wrong_session"
    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt))
    token = world.proc.calls[2]["owner_token"]
    with pytest.raises(TokenRefused) as other_ref:
        world.tokens.redeem(world.key, token, "ses_two")
    assert other_ref.value.code == "wrong_session"
    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt))
    token = world.proc.calls[3]["owner_token"]
    world.tokens.redeem(world.key, token, "ses_one")
    with pytest.raises(TokenRefused) as again:
        world.tokens.redeem(world.key, token, "ses_one")
    assert again.value.code == "unknown"
    undeclared = {**body, "route": "nosuch"}
    assert client.post("/api/v1/cplug-owner/act", json=undeclared, headers=bearer(owner_jwt)).status_code == 404
    assert len(world.proc.calls) == 4


def test_a_route_that_meets_the_catch_all_is_refused_at_build_time():
    from fastapi import APIRouter

    from src.cplugs.host import routes as host_routes, sidecar_routes

    ahead = APIRouter()
    ahead.routes.extend([*host_routes.host_router.routes, *sidecar_routes.router.routes])
    bad = APIRouter(prefix="/cplugs/huddle")
    bad.add_api_route("/r/{x}", lambda: None, methods=["GET"])
    with pytest.raises(ValueError):
        host_routes.assert_no_shadow(ahead, bad)
    ok = APIRouter(prefix="/cplugs/huddle")
    ok.add_api_route("/things", lambda: None, methods=["GET"])
    host_routes.assert_no_shadow(ahead, ok)


def test_a_held_off_plugin_answers_disabled_and_only_a_never_started_one_answers_not_running(client, owner_jwt, world):  # noqa: F811
    h = bearer(owner_jwt)
    world.flag["running"] = False
    world.flag["state"] = "unknown"
    assert client.get(url(), headers=h).json()["detail"]["code"] == "cplug_not_running"
    for state in ("revoked", "crash_loop", "integrity", "index_expired", "disabled (safe mode)", "disabled"):
        world.flag["state"] = state
        r = client.get(url(), headers=h)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_disabled", state
    world.flag["state"] = "running"
    for why in ("off", "owner", "env"):
        world.flag["safe"] = {why: True}
        assert client.get(url(), headers=h).json()["detail"]["code"] == "cplug_disabled", why
    world.flag["safe"] = {"off": False}
    world.flag["running"] = True
    assert client.get(url(), headers=h).status_code == 200
    assert world.proc.calls and len(world.proc.calls) == 1


def test_a_plugin_401_or_407_never_reaches_the_browser_as_one(client, owner_jwt, world):  # noqa: F811
    h = bearer(owner_jwt)
    for status in (401, 407):
        world.proc.reply = lambda status=status: {"status": status, "body": {"error": "no"}}
        r = client.get(url(), headers=h)
        assert r.status_code == 502 and r.json()["detail"]["code"] == "bad_plugin_response", status
    world.proc.reply = lambda: {"status": 403, "body": {"error": "no"}}
    assert client.get(url(), headers=h).status_code == 403


def test_the_act_body_is_capped_and_an_oversize_frame_leaks_nothing(client, owner_jwt, world):  # noqa: F811
    import asyncio

    from src.cplugs.runtime import frames
    from src.cplugs.runtime.process import PluginProcess

    body = {"cplug_id": NAME, "route": "fire", "session_ref": "ses_one", "body": {"a": "x" * world.routes.MAX_REQUEST_BYTES}}
    r = client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt))
    assert r.status_code == 413 and r.json()["detail"]["code"] == "body_too_large"
    assert world.proc.calls == [] and world.tokens._live == {}
    body["body"] = {"a": "x" * 1000}
    assert client.post("/api/v1/cplug-owner/act", json=body, headers=bearer(owner_jwt)).status_code == 200

    p = PluginProcess(None, None, None, "0", None)
    p._proc = SimpleNamespace()
    with pytest.raises(frames.FrameViolation):
        asyncio.run(p.request("route.handle", {"x": "y" * frames.MAX_FRAME_BYTES}))
    assert p._waiting == {} and p._guard._outstanding == set()
