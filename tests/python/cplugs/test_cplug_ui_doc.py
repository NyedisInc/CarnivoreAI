
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import pytest

from src.cplugs.host import identity, runtime, sidecar_boot, sidecar_registry, sidecar_ui, ui_doc
from src.cplugs.runtime.process import ProcessEnded
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401

NAME, ITEM = "clock", "acme/clock"
TOOL = {"name": "refresh_all", "description": "Refresh.", "gate": "read", "inputSchema": {"type": "object"}}
CPLUG = {"schema": 1, "id": NAME, "name": "Clock", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
         "permissions": {"app": []}, "tools": [TOOL], "routes": ["refresh", "toggle"]}
CSP_SHA256 = "ed3e58682f3041678e37c8a44dc5ea7a6b849b829fe0c9ea57c4a2484a3de55e"
ROUTES, TOOLS = ("refresh", "toggle"), ("refresh_all",)
GOOD = {"schema": 1, "data": {"open": 3}, "root": {"type": "section", "title": "pull requests", "children": [
    {"type": "row", "gap": 2, "wrap": True, "children": [
        {"type": "stat", "label": "open", "value": {"bind": "/open"}, "unit": "prs", "tone": "accent"},
        {"type": "badge", "status": "working"}, {"type": "badge", "text": "beta", "tone": "muted"}]},
    {"type": "column", "children": [{"type": "text", "value": "all quiet", "tone": "muted"},
                                    {"type": "meter", "label": "load", "value": 3, "max": 10, "thresholds": [5, 8]}]},
    {"type": "list", "empty": "nothing", "items": [{"type": "text", "value": "one"}]},
    {"type": "table", "columns": ["name", "n"], "rows": [["a", 1], ["b", 2]]},
    {"type": "row", "children": [
        {"type": "button", "label": "refresh", "action": {"call": "route", "route": "refresh", "payload": {"all": True}}},
        {"type": "button", "label": "run", "confirm": "run it?", "tone": "danger", "action": {"call": "tool", "name": "refresh_all"}}]}]}}


def doc(**root: Any) -> Dict[str, Any]:
    return {"schema": 1, "root": root}


def nested(depth: int) -> Dict[str, Any]:
    node: Dict[str, Any] = {"type": "text", "value": "x"}
    for _ in range(depth):
        node = {"type": "column", "children": [node]}
    return {"schema": 1, "root": node}


def button(action: Dict[str, Any]) -> Dict[str, Any]:
    return doc(type="button", label="go", action=action)


KEY = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
REFUSED = [
    ("action_not_declared", button({"call": "route", "route": "wipe"})),
    ("action_not_declared", button({"call": "tool", "name": "session_send_keys"})),
    ("action_not_supported", button({"call": "settings", "key": "theme", "value": "x"})),
    ("action_not_supported", button({"call": "link", "target": {"session": "a"}})),
    ("action_not_declared", button({"call": "route", "route": "refresh", "href": "x"})),
    ("too_deep", nested(ui_doc.MAX_DEPTH + 1)),
    ("secret_shape", doc(type="text", value=KEY)),
    ("secret_shape", button({"call": "route", "route": "refresh", "payload": {"token": KEY}})),
    ("secret_shape", {"schema": 1, "data": {"k": KEY}, "root": {"type": "text", "value": "x"}}),
    ("unknown_node", doc(type="markdown", value="# hi")),
    ("unknown_node", doc(type="script", value="alert(1)")),
    ("unknown_node", doc(type="link", label="x", target="https://example.com")),
    ("link_not_allowed", doc(type="text", value="javascript:alert(1)")),
    ("link_not_allowed", doc(type="text", value="see https://evil.example/x")),
    ("link_not_allowed", doc(type="button", label="data:text/html,x", action={"call": "route", "route": "refresh"})),
    ("unknown_field", doc(type="text", value="x", href="javascript:alert(1)")),
    ("invisible_character", doc(type="text", value="a‮b")),
    ("too_many_nodes", {"schema": 1, "root": {"type": "column", "children": [{"type": "text", "value": "x"}] * (ui_doc.MAX_NODES + 1)}}),
    ("too_many_rows", doc(type="table", columns=["a"], rows=[["x"]] * (ui_doc.MAX_ROWS + 1))),
    ("bad_string", doc(type="text", value="x" * (ui_doc.MAX_TEXT + 1))),
    ("too_large", {"schema": 1, "root": {"type": "column", "children": [{"type": "text", "value": "x" * 1900}] * 40}}),
    ("bad_bind", doc(type="text", value={"bind": "../../etc"})),
    ("bad_schema", {"schema": 2, "root": {"type": "text", "value": "x"}}),
    ("bad_document", {"schema": 1, "root": {"type": "text", "value": "x"}, "script": "x"}),
    ("badge_needs_status_or_text", doc(type="badge", status="working", text="x")),
    ("bad_status", doc(type="badge", status="purple")),
    ("bad_tone", doc(type="text", value="x", tone="rainbow")),
    ("action_not_declared", button({"call": "route", "route": ["refresh"]})),
    ("action_not_declared", button({"call": "route", "route": {"a": 1}})),
    ("action_not_declared", button({"call": "tool", "name": ["refresh_all"]})),
    ("bad_tone", doc(type="text", value="x", tone=["warn"])),
    ("bad_status", doc(type="badge", status=["idle"])),
    ("bad_status", doc(type="badge", status={"a": 1})),
    ("bad_bind", doc(type="text", value={"bind": "/a\n"})),
    ("bad_schema", {"schema": True, "root": {"type": "text", "value": "x"}}),
]


def test_the_validator_refuses_every_rule_break_and_passes_the_good_document():
    cleaned = ui_doc.validate(copy.deepcopy(GOOD), routes=ROUTES, tools=TOOLS)
    assert cleaned == GOOD
    for code, bad in REFUSED:
        with pytest.raises(ui_doc.UiDocError) as raised:
            ui_doc.validate(bad, routes=ROUTES, tools=TOOLS)
        assert raised.value.code == code, (code, raised.value.code, raised.value.path)
    ok = button({"call": "route", "route": "wipe"})
    assert ui_doc.validate(ok, routes=("wipe",), tools=())["root"]["action"]["route"] == "wipe"
    assert ui_doc.validate(nested(ui_doc.MAX_DEPTH - 1), routes=(), tools=())
    assert set(ui_doc.validate(doc(type="text", value="x", tone="warn"), routes=(), tools=())["root"]) == {"type", "value", "tone"}



def _async(fn):
    async def call(name):
        return fn(name)
    return call



class FakeProc:

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.reply: Callable[[], Any] = lambda: {"document": copy.deepcopy(GOOD)}

    async def request(self, method: str, params: Dict[str, Any], timeout: float = 5.0) -> Any:
        assert method == "ui.render" and timeout == 5.0
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
    assert sidecar_registry.current().reload() == 1
    proc, flag = FakeProc(), {"on": True, "running": True, "state": "running", "safe": {"off": False}}
    app.state.cplugs_host = runtime.Host(state, app)
    app.state.sidecar_runtime = SimpleNamespace(
        tokens=None, safe_mode=lambda: flag["safe"],
        supervisor=SimpleNamespace(process=lambda name: proc if flag["running"] and name == NAME else None, state=lambda name: flag["state"],
                                   ensure=_async(lambda name: proc if flag["running"] and name == NAME else None)))
    monkeypatch.setattr(runtime.Host, "enabled", lambda self, cid: flag["on"] if cid == NAME else False)
    sidecar_ui._calls.clear()
    sidecar_ui._good.clear()
    yield SimpleNamespace(proc=proc, flag=flag, key=record.uuid)
    del app.state.cplugs_host
    del app.state.sidecar_runtime
    sidecar_registry.install(before)
    sidecar_ui._good.clear()


def url(surface: str = "widget", cid: str = NAME) -> str:
    return f"/api/v1/cplugs/{cid}/ui/{surface}"


def test_the_route_validates_caches_the_last_good_document_and_serves_it_stale_when_a_render_fails(client, owner_jwt, world):  # noqa: F811
    h = bearer(owner_jwt)
    assert client.get(url("nosuch"), headers=h).json()["detail"]["code"] == "unknown_surface"
    assert client.get(url(cid="nosuch"), headers=h).json()["detail"]["code"] == "cplug_unknown"
    assert client.get(url("widget", "huddle"), headers=h).status_code == 404
    assert client.get(url()).status_code in (401, 403)
    assert world.proc.calls == []
    r = client.get(url("tab") + "?id=7", headers=h)
    assert r.status_code == 200 and r.json() == {"surface": "tab", "stale": False, "document": GOOD}
    assert world.proc.calls == [{"surface": "tab", "params": {"id": "7"}}]
    bad = copy.deepcopy(GOOD)
    bad["root"]["children"][-1]["children"][0]["action"]["route"] = "wipe"
    for answer, reason in [({"document": bad}, "invalid_ui_document"), ({"nope": 1}, "bad_plugin_response"),
                           (asyncio.TimeoutError(), "cplug_timeout"), (ProcessEnded("crashed"), "cplug_not_running")]:
        world.proc.reply = lambda a=answer: a
        r = client.get(url("tab") + "?id=7", headers=h)
        assert r.status_code == 200 and r.json()["stale"] is True and r.json()["reason"] == reason and r.json()["document"] == GOOD
    world.proc.reply = lambda: {"document": bad}
    r = client.get(url("glance"), headers=h)
    assert r.status_code == 502 and r.json()["detail"] == {"code": "invalid_ui_document", "detail": "clock gave no usable glance document",
                                                           "rule": "action_not_declared", "path": "/root/children/4/children/0/action/route"}
    assert client.get(url("tab") + "?id=8", headers=h).status_code == 502
    world.flag["running"] = False
    assert client.get(url("tab") + "?id=7", headers=h).json()["reason"] == "cplug_not_running"
    world.flag["on"] = False
    r = client.get(url("tab") + "?id=7", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_disabled" and "document" not in r.text
    world.flag.update(on=True, running=True)
    world.proc.reply = lambda: {"document": copy.deepcopy(GOOD)}
    csp = client.get(url("tab") + "?id=7", headers=h).headers["content-security-policy"]
    assert hashlib.sha256(csp.encode()).hexdigest() == CSP_SHA256
    assert csp == client.get("/api/v1/cplugs", headers=h).headers["content-security-policy"]


def test_ui_invalidate_names_the_install_topic_at_most_twice_a_second(monkeypatch):
    from src.core import resource_push

    async def run() -> List[Any]:
        frames: List[Dict[str, Any]] = []
        resource_push.install(lambda f: frames.append(f) or 1, loop=asyncio.get_running_loop(), window_seconds=0.01)
        fake = SimpleNamespace(host=runtime.Host(sidecar_boot.Path("."), None), on_loop=lambda fn, *a: fn(*a), _key=lambda pid: "UUID-1",
                                _record_activity=None, _plugin_alert=None)
        invalidate = sidecar_boot.SidecarRuntime._services(fake).invalidate_ui
        start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start < 2.0:
            invalidate("clock", None)
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.6)
        resource_push.uninstall()
        return frames

    frames = asyncio.run(run())
    topics = [t for f in frames for t in f["topics"]]
    assert set(topics) == {"cplug_ui:UUID-1"}
    assert 3 <= len(topics) <= 5, len(topics)


def test_a_hostile_render_is_a_502_or_the_stale_document_never_a_500(client, owner_jwt, world):  # noqa: F811
    hostile = copy.deepcopy(GOOD)
    hostile["root"] = {"type": "button", "label": "x", "action": {"call": "route", "route": ["x"]}}
    world.proc.reply = lambda: {"document": hostile}
    first = client.get(url(), headers=bearer(owner_jwt))
    assert first.status_code == 502 and first.json()["detail"]["rule"] == "action_not_declared"
    world.proc.reply = lambda: {"document": copy.deepcopy(GOOD)}
    assert client.get(url(), headers=bearer(owner_jwt)).json()["stale"] is False
    sidecar_ui._calls.clear()
    world.proc.reply = lambda: {"document": hostile}
    again = client.get(url(), headers=bearer(owner_jwt))
    assert again.status_code == 200 and again.json()["stale"] is True and again.json()["reason"] == "invalid_ui_document"
