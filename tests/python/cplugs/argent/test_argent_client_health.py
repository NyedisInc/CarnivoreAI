
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
import structlog
from fastapi import HTTPException

from src.api.argent import status as status_routes
from src.config import settings as app_settings
from src.core import relay_keychain, resource_push
from src.core.argent import health, settings as argent_settings
from src.core.argent.client import ArgentClient, Unauthorized
from src.core.argent.device_login import DeviceLogin
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore, TokenUnavailable
from src.plugins import argent as argent_cplug
from src.plugins.sdk import ports

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "tests" / "fixtures" / "argent"
TOKEN = "FIXTURE-asicli-not-a-secret"
GATEWAY, SERVER = "https://gw.argent.test", "https://cp.argent.test"


def fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def serve(routes: Dict[str, Any]) -> httpx.MockTransport:
    calls: Dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        want = routes.get(request.url.path)
        if isinstance(want, Exception):
            raise want
        if isinstance(want, list):
            index = calls.get(request.url.path, 0)
            calls[request.url.path] = index + 1
            want = want[min(index, len(want) - 1)]
        if want is None:
            return httpx.Response(200, json={})
        body = fixture(want)
        return httpx.Response(int(body.pop("_http_status", 400 if "authorization_pending" in json.dumps(body) else 200)), json=body)

    return httpx.MockTransport(handler)


def ready(name: str) -> httpx.MockTransport:
    return serve({health.READY_PATH: name})


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"unrelated": 1}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    topics: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: topics.append(topic))
    store, keychain = ArgentStore(state), FakeKeychain()
    tokens = TokenStore(keychain)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens, transport=login_transport(), sleep=no_sleep)))
    yield {"config": config, "state": state, "store": store, "keychain": keychain, "tokens": tokens, "topics": topics}
    set_runtime(None)
    asyncio.run(health.stop())
    ports.unregister(PORT_NAME)


async def no_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


def login_transport() -> httpx.MockTransport:
    return serve({"/v1/my/cli/device": "device_start.json", "/v1/my/cli/token": ["device_token_pending.json", "device_token_pending.json", "device_token_ok.json"]})


def leaks(secret: str, env: Dict[str, Any], logs: List[Any], *views: Any) -> List[str]:
    found = []
    if secret in env["config"].read_text():
        found.append("config.json")
    for path in env["state"].rglob("*"):
        if path.is_file() and secret.encode() in path.read_bytes():
            found.append(str(path.name))
    if secret in repr(logs):
        found.append("logs")
    found += [f"view{i}" for i, v in enumerate(views) if secret in json.dumps(v, default=str)]
    return found



@pytest.mark.parametrize("transport, state", [
    (ready("health_ready_ok.json"), health.UP),
    (ready("health_ready_cap_1mib.json"), health.CAP_TOO_LOW),
    (ready("health_ready_404.json"), health.UNSUPPORTED),
    (serve({health.READY_PATH: httpx.ConnectError("refused")}), health.DOWN),
])
def test_health_states_follow_the_recorded_ready_route(transport: httpx.MockTransport, state: str) -> None:
    report = asyncio.run(health.probe(GATEWAY, SERVER, transport=transport))
    assert report.state == state


def test_a_wrong_expectation_would_fail_so_the_states_are_real() -> None:
    assert asyncio.run(health.probe(GATEWAY, SERVER, transport=ready("health_ready_cap_1mib.json"))).state != health.UP
    assert asyncio.run(health.probe("", SERVER)).state == health.UNKNOWN


def test_an_expired_login_shows_even_when_the_gateway_is_up() -> None:
    assert asyncio.run(health.probe(GATEWAY, SERVER, transport=ready("health_ready_ok.json"), login_expired=True)).state == health.LOGIN_EXPIRED


def test_switch_on_is_refused_with_a_named_reason_unless_everything_is_ready() -> None:
    def refusal(name: str, **kw: Any) -> Any:
        report = asyncio.run(health.probe(GATEWAY, SERVER, transport=ready(name)))
        args = {"server_url": SERVER, "gateway_url": GATEWAY, "logged_in": True, "login_expired": False, **kw}
        return health.switch_on_refusal(report, **args)

    assert refusal("health_ready_ok.json") is None
    assert refusal("health_ready_cap_1mib.json") == "cap_too_low"
    assert refusal("health_ready_404.json") == "gateway_unsupported"
    assert refusal("health_ready_ok.json", logged_in=False) == "not_logged_in"
    assert refusal("health_ready_ok.json", login_expired=True) == "login_expired"
    assert refusal("health_ready_ok.json", server_url="") == "server_url_empty"
    unchained = asyncio.run(health.probe(GATEWAY, SERVER, transport=serve({health.READY_PATH: "health_ready_cap_1mib.json"})))
    assert health.switch_on_refusal(unchained, server_url=SERVER, gateway_url=GATEWAY, logged_in=True, login_expired=False) == "cap_too_low"



def test_a_401_reads_as_login_expired_and_pauses_nothing_else(env: Dict[str, Any]) -> None:
    env["store"].set_login("ten_fixture1", "idn_fixture1", "Fixture Person", 43200)
    assert env["store"].login_expired() is False
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"code": "unauthorized", "message": "no"}}))
    client = ArgentClient(SERVER, lambda: TOKEN, transport=transport, on_unauthorized=env["store"].mark_login_expired)
    with pytest.raises(Unauthorized):
        asyncio.run(client.get("/v1/my/anything"))
    assert env["store"].login_expired() is True
    view = status_routes._login_view()
    assert view["state"] == "login_expired" and TOKEN not in json.dumps(view)


def test_a_304_answers_the_cached_body_and_the_etag_is_sent() -> None:
    seen: List[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("if-none-match"))
        return httpx.Response(304) if request.headers.get("if-none-match") else httpx.Response(200, json={"rev": 7}, headers={"etag": '"v7"'})

    client = ArgentClient(SERVER, lambda: TOKEN, transport=httpx.MockTransport(handler))
    first, second = asyncio.run(_two(client))
    assert (first.not_modified, second.not_modified, second.body) == (False, True, {"rev": 7}) and seen == [None, '"v7"']


async def _two(client: ArgentClient) -> Any:
    return await client.get("/v1/my/x"), await client.get("/v1/my/x")



def test_device_login_stores_the_token_only_in_the_keychain(env: Dict[str, Any]) -> None:
    async def run() -> Any:
        flow = await status_routes.get_runtime().login.start(SERVER)
        assert flow["state"] == "pending" and flow["user_code"] == "ABCD-EFGH" and "device_code" not in json.dumps(flow)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if status_routes.get_runtime().login.public()["state"] != "pending":
                break
        return status_routes.get_runtime().login.public()

    with structlog.testing.capture_logs() as logs:
        public = asyncio.run(run())
    assert public["state"] == "done" and public["tenant_changed_from"] == ""
    assert env["keychain"].items == {(relay_keychain.ARGENT_CLI_SERVICE, "ten_fixture1"): TOKEN}
    block = json.loads(env["config"].read_text())["argent"]
    assert block["tokenPointer"] == {"service": "carnivore-argent-cli", "account": "ten_fixture1"} and json.loads(env["config"].read_text())["unrelated"] == 1
    assert env["store"].get_login()["display_name"] == "Fixture Person"
    assert leaks(TOKEN, env, logs, public, asyncio.run(status_routes.get_status()), status_routes.get_runtime().login.public()) == []
    assert "argent_status" in env["topics"]


def test_the_leak_check_can_fail(env: Dict[str, Any]) -> None:
    env["config"].write_text(json.dumps({"argent": {"token": TOKEN}}))
    (env["state"] / "leak.txt").write_text(TOKEN)
    assert leaks(TOKEN, env, [{"event": f"login {TOKEN}"}], {"t": TOKEN}) == ["config.json", "leak.txt", "logs", "view0"]


def test_a_different_tenant_is_reported_and_the_old_login_is_replaced(env: Dict[str, Any]) -> None:
    env["store"].set_login("ten_old", "i", "Old", 100)
    assert env["store"].set_login("ten_fixture1", "idn_fixture1", "Fixture Person", 100) == "ten_old"
    assert env["store"].get_login()["tenant_id"] == "ten_fixture1"


def test_the_real_keychain_item_is_refused_under_test() -> None:
    with pytest.raises(TokenUnavailable):
        TokenStore().write("ten_fixture1", TOKEN)
    assert TokenStore().read("ten_fixture1") is None



REAL_PROBE = health.probe


def _probe_with(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = REAL_PROBE

    async def probe(*args: Any, **kwargs: Any) -> Any:
        return await real(*args, transport=ready(name), **kwargs)

    monkeypatch.setattr(health, "probe", probe)


def _put(**fields: Any) -> Any:
    return asyncio.run(status_routes.put_settings(status_routes.ArgentSettingsPatch(**fields)))


def test_switching_on_is_refused_off_the_feature_and_without_a_ready_gateway_and_lands_when_ready(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _put(server_url=SERVER + "/", gateway_url=GATEWAY)
    assert argent_settings.read().server_url == SERVER
    with pytest.raises(HTTPException) as off:
        _put(enabled=True)
    assert off.value.detail["code"] == "feature_off"
    ports.register(PORT_NAME, {"on": True})
    env["store"].set_login("ten_fixture1", "idn_fixture1", "Fixture Person", 43200)
    _probe_with(monkeypatch, "health_ready_cap_1mib.json")
    with pytest.raises(HTTPException) as low:
        _put(enabled=True)
    assert low.value.status_code == 409 and low.value.detail["code"] == "switch_refused" and argent_settings.read().enabled is False
    _probe_with(monkeypatch, "health_ready_ok.json")
    assert _put(enabled=True)["settings"]["enabled"] is True and argent_settings.read().enabled is True
    assert _put(server_url="", enabled=False)["settings"]["enabled"] is False
    with pytest.raises(HTTPException) as bad:
        _put(server_url="file:///etc/passwd")
    assert bad.value.detail["code"] == "server_url_invalid"


def test_an_address_change_while_on_is_refused_when_empty_and_checked_when_retargeted(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _put(server_url=SERVER, gateway_url=GATEWAY)
    ports.register(PORT_NAME, {"on": True})
    env["store"].set_login("ten_fixture1", "idn_fixture1", "Fixture Person", 43200)
    _probe_with(monkeypatch, "health_ready_ok.json")
    assert _put(enabled=True)["settings"]["enabled"] is True
    for field in ("gateway_url", "server_url"):
        with pytest.raises(HTTPException) as empty:
            _put(**{field: ""})
        assert empty.value.status_code == 409 and empty.value.detail["code"] == "address_required"
    assert argent_settings.read().enabled is True and argent_settings.read().gateway_url == GATEWAY
    _probe_with(monkeypatch, "health_ready_cap_1mib.json")
    with pytest.raises(HTTPException) as bad:
        _put(gateway_url="https://gw2.argent.test")
    assert bad.value.detail["code"] == "switch_refused" and argent_settings.read().gateway_url == GATEWAY
    _probe_with(monkeypatch, "health_ready_ok.json")
    assert _put(gateway_url="https://gw2.argent.test")["settings"]["enabled"] is True and argent_settings.read().gateway_url == "https://gw2.argent.test"


def test_log_out_deletes_the_token_forgets_the_login_and_turns_the_switch_off(env: Dict[str, Any]) -> None:
    env["tokens"].write("ten_fixture1", TOKEN)
    env["store"].set_login("ten_fixture1", "idn_fixture1", "Fixture Person", 43200)
    argent_settings.update(lambda b: b.update(enabled=True, tokenPointer=env["tokens"].pointer("ten_fixture1")))
    result = asyncio.run(status_routes.delete_login())
    assert env["keychain"].items == {} and env["store"].get_login() is None
    assert result["settings"]["enabled"] is False and "tokenPointer" not in json.loads(env["config"].read_text())["argent"]



def test_with_the_feature_off_no_poller_exists_and_it_follows_the_feature_switch(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> List[bool]:
        seen = [health.is_running()]
        await argent_cplug._start(None)
        seen.append(health.is_running())
        await argent_cplug._stop(None)
        await asyncio.sleep(0.05)
        seen.append(health.is_running())
        return seen

    assert asyncio.run(run()) == [False, True, False]
    assert health.latest().state == health.UNKNOWN
    assert asyncio.run(status_routes.get_status())["feature_on"] is False


def test_the_off_state_proof_can_fail(env: Dict[str, Any]) -> None:
    async def run() -> bool:
        await argent_cplug._start(None)
        return health.is_running()

    assert asyncio.run(run()) is True



def argent_lines() -> List[str]:
    text = (ROOT / "client" / "js" / "i18n" / "catalog.en.js").read_text()
    return [line for line in text.splitlines() if re.match(r"\s*'argent\.", line)]


def test_no_argent_string_says_plugin_and_none_has_a_dash() -> None:
    lines = argent_lines()
    assert len(lines) > 30
    assert [line for line in lines if re.search(r"plugin", line, re.I)] == []
    assert [line for line in lines if "—" in line or "–" in line] == []
    assert re.search(r"plugin", "'argent.shell.x': 'a plugin'", re.I)


def test_a_token_answer_without_a_tenant_takes_it_from_the_cli_config(env: Dict[str, Any]) -> None:
    seen: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/my/cli/device":
            return httpx.Response(200, json=fixture("device_start.json"))
        if path == "/v1/my/cli/token":
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "Bearer", "expires_in": 43200, "identity_display": "Live Person"})
        if path == "/v1/my/cli/config":
            seen.append(request.headers.get("authorization", ""))
            return httpx.Response(200, json={"tenant_slug": "live-tenant", "identity_display": "Live Person"})
        return httpx.Response(404, json={})

    runtime = status_routes.get_runtime()
    set_runtime(Runtime(store=runtime.store, tokens=runtime.tokens, login=DeviceLogin(runtime.store, runtime.tokens, transport=httpx.MockTransport(handler), sleep=no_sleep)))

    async def run() -> Any:
        await status_routes.get_runtime().login.start(SERVER)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if status_routes.get_runtime().login.public()["state"] != "pending":
                break
        return status_routes.get_runtime().login.public()

    assert asyncio.run(run())["state"] == "done"
    assert seen == [f"Bearer {TOKEN}"]
    assert env["keychain"].items == {(relay_keychain.ARGENT_CLI_SERVICE, "live-tenant"): TOKEN}
    assert env["store"].get_login()["display_name"] == "Live Person"
