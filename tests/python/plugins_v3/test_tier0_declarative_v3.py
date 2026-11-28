
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.agent_manifests import engine as agent_engine
from src.plugins.host import routes as host_routes, runtime as host_runtime, sidecar_boot, sidecar_routes, sidecar_ui
from src.plugins.host.egress_log import EgressLog
from src.plugins.host.fetch_proxy import PluginFetch, RateLimiter
from src.plugins.host.fetch_transport import RawResponse
from src.plugins.host.secret_store import SecretStore
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_spec import build_spec
from src.plugins.runtime import sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.supervisor import TIER0_STATE, Supervisor
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2


class _FakeKeychain:
    def __init__(self) -> None:
        self.items: Dict[tuple, str] = {}

    def read(self, service: str, account: str):
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class _MockTransport:
    def __init__(self, calls: List[Any]):
        self._calls = calls

    def send(self, **kw):
        self._calls.append(SimpleNamespace(**kw))
        return RawResponse(status=200, headers=[("content-type", "application/json")], body=b'{"delivered":true}')


@pytest.mark.parametrize(
    "bad_block",
    [
        {"mcp": {"tools": [{"name": "my_tool", "description": "d", "gate": "read"}]}},
        {"ui": {"routes": ["act"]}},
        {"timers": {"tick": {"every_seconds": 5}}},
        {"services": {"provides": [{"name": "acme.kv", "methods": ["get"]}]}},
    ],
)
def test_tier0_contradiction_raises_manifest_v2_error(bad_block: dict) -> None:
    raw = {
        "schema": 2,
        "id": "badtier0",
        "name": "Bad Tier 0",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Missing [run] cannot declare code hooks",
        "author": "Tester",
        **bad_block,
    }
    with pytest.raises(ManifestV2Error, match="Tier 0"):
        parse_manifest_v2(raw)


@pytest.mark.asyncio
async def test_tier0_supervisor_zero_subprocess_and_cplug_row_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom_interp():
        raise AssertionError("Tier 0 must NEVER call sandbox.find_interpreter()")

    async def _boom_spawn(*_a, **_kw):
        raise AssertionError("Tier 0 must NEVER spawn a subprocess")

    monkeypatch.setattr(sandbox, "find_interpreter", _boom_interp)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom_spawn)

    code = tmp_path / "code" / "zero"
    code.mkdir(parents=True)
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "zero"
name = "Zero Widget"
version = "1.0.0"
kind = "widget"
description = "Declarative Tier 0"
author = "Tester"

[ui.widget]
title = "Zero"
document = { schema = 1, root = { type = "text", value = "No process" } }
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "zero")
    assert sm.tier0 is True
    d = SidecarDefinition(manifest=sm, item_id="local/zero", install_key="inst-zero", code_root=code, folder=tmp_path / "data" / "zero")
    spec = build_spec(d, frozenset(), {}, consent_owed=False)

    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"t" * 32))
    sup = Supervisor(
        tmp_path / "state",
        "9.9.9",
        disp,
        lambda _pid, _k, _why: None,
        lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        lambda _row: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )

    assert await sup.activate(spec) == TIER0_STATE
    assert sup.process("zero") is None
    assert sup.available("zero") is True
    assert await sup.ensure("zero") is None

    from dataclasses import replace
    from src.plugins.host import state as owner_state

    owner_state.update(tmp_path / "state", sm, None, lambda st: replace(st, enabled=True, digest=sm.code_digest))
    app_state = SimpleNamespace(sidecar_runtime=SimpleNamespace(supervisor=sup, safe_mode=lambda: {}))
    host = host_runtime.Host(tmp_path / "state", app=SimpleNamespace(state=app_state))
    row = host_routes.cplug_row(host, d)
    assert row["state"] == "active"
    assert row["process"] == TIER0_STATE

    await sup.enter_safe_mode()
    assert sup.state("zero") == "disabled (safe mode)"
    assert sup.available("zero") is False

    sup.set_safe_mode(False)
    assert await sup.enable(spec) == TIER0_STATE
    await sup.revoke("zero", "bad")
    assert sup.state("zero") == "revoked"
    await sup.shutdown()


def test_tier0_declarative_widget_served_via_get_ui_with_zero_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("no subprocess")))

    code = tmp_path / "code" / "widget0"
    code.mkdir(parents=True)
    (code / "widget.json").write_text(
        json.dumps({"schema": 1, "root": {"type": "text", "value": "Hello from Tier 0 file"}}),
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "widget0"
name = "Widget Zero"
version = "1.0.0"
kind = "widget"
description = "Declarative widget"
author = "Tester"

[ui.widget]
ui_file = "widget.json"
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "widget0")
    d = SidecarDefinition(manifest=sm, item_id="local/widget0", install_key="inst-w0", code_root=code, folder=tmp_path / "data" / "widget0")

    from dataclasses import replace
    from src.plugins.host import owner_switch, state as owner_state

    owner_switch.write(tmp_path / "state", True)
    owner_state.update(tmp_path / "state", sm, None, lambda st: replace(st, enabled=True, digest=sm.code_digest))
    app_state = SimpleNamespace()
    host = host_runtime.Host(tmp_path / "state", app=SimpleNamespace(state=app_state))
    live = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=app_state), asyncio.new_event_loop(), env_safe=lambda: False)
    try:
        live.supervisor.set_safe_mode(False)
        live.supervisor._state["widget0"] = TIER0_STATE
        app_state.sidecar_runtime = live
        monkeypatch.setattr(host_runtime, "host_for", lambda _app: host)
        monkeypatch.setattr(host_runtime, "find", lambda cid: d if cid == "widget0" else None)
        monkeypatch.setattr(host, "install_key", lambda cid: "inst-w0" if cid == "widget0" else cid)

        app = FastAPI()
        app.include_router(sidecar_ui.router)
        app.dependency_overrides[require_auth] = lambda: {"role": "owner"}
        client = TestClient(app)

        res = client.get("/cplugs/widget0/ui/widget")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["stale"] is False
        assert data["document"]["root"]["value"] == "Hello from Tier 0 file"
    finally:
        live.loop.close()


@pytest.mark.asyncio
async def test_tier0_harness_rules_outbound_channel_and_command_macro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("no subprocess")))

    code = tmp_path / "code" / "pack0"
    code.mkdir(parents=True)
    (code / "myagent.toml").write_text(
        """
id = "myagent"
version = "1"
aliases = ["mya"]

[[rules]]
id = "busy"
state = "working"
priority = 10
region = "bottom_lines(3)"
contains = ["thinking"]
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "pack0"
name = "Pack Zero"
version = "1.0.0"
kind = "plugin"
description = "Tier 0 harness + channel + macro"
author = "Tester"

[permissions]
read = ["sessions"]
write = ["sessions.message"]
network = [{ host = "hooks.example.com", reason = "Deliver alerts", methods = ["POST"] }]
secrets = ["hook_token"]

[harnesses]
files = ["myagent.toml"]

[channels.alerts]
url = "https://hooks.example.com/notify"
method = "POST"
headers = { Authorization = "Bearer $SECRET:hook_token" }
body_template = '{"msg":"{{text}}"}'

[[ui.commands]]
id = "send_ping"
title = "Send Ping"
steps = [
  { method = "sessions.message", params = { ref = "{{session_ref}}", line = "hello from macro" } }
]
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "pack0")
    d = SidecarDefinition(manifest=sm, item_id="local/pack0", install_key="inst-pack0", code_root=code, folder=tmp_path / "data" / "pack0")
    spec = build_spec(
        d,
        frozenset({"sessions.read", "sessions.message", "network_hosts:hooks.example.com", "network_hosts.write:hooks.example.com"}),
        {},
        consent_owed=False,
    )

    pasted: List[tuple] = []
    seen_http: List[Any] = []
    kc = _FakeKeychain()
    secrets = SecretStore(tmp_path / "state", keychain=kc)
    secrets.set("inst-pack0", sm, "hook_token", "testsecretnotreal")

    from src.plugins.host import netguard

    def _make_fetch(_manifest, key):
        return PluginFetch(
            sm,
            key,
            lambda: ("network_hosts:hooks.example.com", "network_hosts.write:hooks.example.com"),
            secrets,
            EgressLog(tmp_path / "state"),
            RateLimiter(per_minute=30),
            peers=lambda: netguard.Peers(frozenset()),
            resolver=lambda _h, _p: ["93.184.216.34"],
            transport=_MockTransport(seen_http),
            is_own=lambda _ip: False,
        )

    from dataclasses import replace
    from src.plugins.host import owner_switch, state as owner_state

    owner_switch.write(tmp_path / "state", True)
    owner_state.update(
        tmp_path / "state",
        sm,
        None,
        lambda st: replace(
            st,
            enabled=True,
            digest=sm.code_digest,
            grants=("sessions.read", "sessions.message", "network_hosts:hooks.example.com", "network_hosts.write:hooks.example.com"),
        ),
    )
    app_state = SimpleNamespace(session_manager=None)
    host = host_runtime.Host(tmp_path / "state", app=SimpleNamespace(state=app_state))
    monkeypatch.setattr(host, "fetch_for", lambda cid: _make_fetch(sm, "inst-pack0") if cid == "pack0" else None, raising=False)
    monkeypatch.setattr(host, "install_key", lambda cid: "inst-pack0" if cid == "pack0" else cid)

    live = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=app_state), asyncio.get_running_loop(), env_safe=lambda: False)
    live.supervisor.set_safe_mode(False)
    await live.supervisor.set_index({"expires_at": "2999-01-01T00:00:00Z"})
    app_state.sidecar_runtime = live
    monkeypatch.setattr(live, "_services", lambda: HostServices(
        activity=lambda _r: None,
        get_session=lambda ref: asyncio.sleep(
            0,
            result={
                "session": {"id": ref, "launched_with": {"permissions": "default"}},
                "launched_with": {"permissions": "default"},
                "host_key": "local",
                "agent_wrapper_label": "claude",
            }
            if ref == "sess-1"
            else None,
        ),
        permission_mode=lambda _ref: asyncio.sleep(0, result="default"),
        paste_line=lambda ref, line: asyncio.sleep(0, result=pasted.append((ref, line)) or {"delivered": True}),
    ))
    live._defs = lambda: {"pack0": d}
    live.dispatcher = HostDispatcher(live._services(), live.tokens)
    live.supervisor._dispatcher = live.dispatcher

    try:
        monkeypatch.setattr(host_runtime, "host_for", lambda _app: host)
        monkeypatch.setattr(host_runtime, "find", lambda cid: d if cid == "pack0" else None)

        assert await live.supervisor.activate(spec) == TIER0_STATE
        matched_cli = agent_engine.identify(100, {101: 100}, {101: "myagent --watch"})
        assert matched_cli is not None
        assert agent_engine.evaluate(matched_cli, "Thinking carefully...").state == "working"

        res_ch = await live.send_channel("pack0", "alerts", {"text": "build done"})
        assert res_ch.status == 200
        assert len(seen_http) == 1
        assert dict((k.lower(), v) for k, v in seen_http[0].headers)["authorization"] == "Bearer testsecretnotreal"
        assert seen_http[0].body == b'{"msg":"build done"}'

        live.supervisor._specs["pack0"] = spec
        monkeypatch.setattr(host_runtime, "host_for", lambda _app: host)
        monkeypatch.setattr(host_runtime, "find", lambda cid: d if cid == "pack0" else None)

        app = FastAPI()
        app.include_router(sidecar_routes.router)
        app.dependency_overrides[require_auth] = lambda: {"role": "owner"}
        client = TestClient(app)
        act_res = client.post(
            "/cplug-owner/act",
            json={"cplug_id": "pack0", "route": "send_ping", "session_ref": "sess-1"},
        )
        assert act_res.status_code == 200, act_res.text
        assert pasted == [("sess-1", "hello from macro")]

        await live.supervisor.disable("pack0")
        assert agent_engine.identify(100, {101: 100}, {101: "myagent --watch"}) is None
    finally:
        agent_engine.unregister_plugin_manifests("pack0")
        await live.supervisor.shutdown()


def test_agent_manifest_redos_rejected_for_tier0_plugin(tmp_path: Path) -> None:
    code = tmp_path / "code" / "redos"
    code.mkdir(parents=True)
    (code / "evil.toml").write_text(
        """
id = "evil"
version = "1"
[[rules]]
id = "r1"
state = "working"
priority = 1
region = "whole_recent"
regex = ["(a+)+b"]
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "redos"
name = "ReDoS"
version = "1.0.0"
kind = "plugin"
description = "Rejects nested quantifier"
author = "Tester"

[harnesses]
files = ["evil.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="nested quantifier"):
        load_sidecar_manifest(code, "redos")


@pytest.mark.parametrize(
    "bad_pattern",
    [
        "(a+)+$",
        "(a|a)+$",
        "(a|ab)+$",
        "(?:a|a)+$",
        "(foo|fo)+$",
        ".*a.*a.*a.*a.*a.*!$",
        ".*a.*a.*!$",
        ".*a*!$",
        "[^!]*a[^!]*a[^!]*a[^!]*!$",
        "[a-z]*x[a-z]*x[a-z]*!$",
        r"\w*x\w*x\w*!$",
        r"(a+)\1+$",
        "(?=a+)+a",
        "(a{100}){2}",
        "a{1,500}",
        "(?:ab)*c(?:ab)*d(?:ab)*$",
        "a*a*a*b",
        "a?" * 30 + "a{30}",
        "(a?){30}a{30}",
        "(" * 500 + "a" + ")" * 500,
        "[ab]+[bc]+[cd]+[de]+!$",
        "(?:[^!]*a)?(?:[^!]*a)?(?:[^!]*a)?(?:[^!]*a)?!$",
        "(?:[^!]*a){1}(?:[^!]*a){1}(?:[^!]*a){1}(?:[^!]*a){1}!$",
        "(?i:a)+(?i:A)+(?i:a)+(?i:A)+!$",
        "^a+a+xa+a+xa+a+xa+a+!$",
        "(?>a*a*a*a*!$)",
        "(?>(a+)+!$)",
        r"[\s\S]*a[\s\S]*!$",
        "a{999999999999999999999999999999}",
        "^" + "(?:a|a|a|a|a|a)" * 10 + "!$",
        "^a+a+" + "(?:a|a|a|a)?" * 4 + "!$",
    ],
)
def test_agent_manifest_rejects_all_hostile_redos_vectors(bad_pattern: str) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(bad_pattern)


@pytest.mark.parametrize(
    "bad_whole_pattern",
    [
        "[^!]*a[^!]*!$",
        "(■|⬝){4,}!$",
        "a{999999999999999999999999999999}",
        "^" + "(?:a|a|a|a|a|a)" * 10 + "!$",
        "[^!]{1,8}" + "(?:a|a|a)?" * 4 + "@$",
        r"(?m)^[^!]+(?:a|[^!])?(?:a|[^!])?(?:a|[^!])?(?:a|[^!])?@$",
        r"(?m)^[^!]+(?:[^!])?(?:[^!])?(?:[^!])?(?:[^!])?@$",
        r"(?m:^)[^!]+(?:[^!])?(?:[^!])?(?:[^!])?(?:[^!])?@$",
    ],
)
def test_agent_manifest_rejects_whole_region_quadratic_regex(bad_whole_pattern: str) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(bad_whole_pattern, whole_region=True)
    toml_text = (
        'id = "wr"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f'regex = [{json.dumps(bad_whole_pattern)}]\n'
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


def test_agent_manifest_huge_quantifier_raises_sidecar_manifest_error_not_overflow(tmp_path: Path) -> None:
    from src.plugins.host.plugin_manifest import SidecarManifestError

    code = tmp_path / "code" / "hugequant"
    code.mkdir(parents=True)
    (code / "huge.toml").write_text(
        'id = "huge"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        'regex = ["a{999999999999999999999999999999}"]\n',
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "hugequant"
name = "Huge Quant"
version = "1.0.0"
kind = "plugin"
description = "Huge quantifier check"
author = "Tester"

[harnesses]
files = ["huge.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "hugequant")


@pytest.mark.parametrize(
    "bad_toml",
    [
        'id = "bad"\nrules = [123]\n',
        'id = "bad"\n[[rules]]\nid = "r1"\nstate = "working"\ncontains = 123\n',
        'id = "bad"\n[[rules]]\nid = "r1"\nstate = "working"\nregex = "foo"\n',
        'id = "bad"\n[[rules]]\nid = "r1"\nstate = "working"\nline_regex = 123\n',
        'id = "bad"\n[[rules]]\nid = "r1"\nstate = "working"\npriority = true\n',
        'id = "bad"\nmin_engine_version = "2"\n',
    ],
)
def test_agent_manifest_rejects_malformed_types_with_rule_file_error(bad_toml: str) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(bad_toml)


def test_agent_manifest_unicode_casefold_and_sidecar_load(tmp_path: Path) -> None:
    p_sharp_s = agent_engine.compile_pattern("(?i)ß")
    assert p_sharp_s.search("ẞ") is not None
    p_ligature = agent_engine.compile_pattern("(?i)ﬁ")
    assert p_ligature.search("ﬁ") is not None

    code = tmp_path / "code" / "unicode_harness"
    code.mkdir(parents=True)
    (code / "uni.toml").write_text(
        """
id = "uni"
version = "1"
[[rules]]
id = "r1"
state = "working"
priority = 1
regex = ["(?i)ß"]
line_regex = ["(?i)ﬁ"]
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "uniharness"
name = "Unicode Harness"
version = "1.0.0"
kind = "plugin"
description = "Validates Unicode casefold patterns"
author = "Tester"

[harnesses]
files = ["uni.toml"]
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "uniharness")
    assert sm.harnesses == ("uni.toml",)


def test_agent_manifest_rejects_deep_gate_nesting_and_recursion_error(tmp_path: Path) -> None:
    from src.plugins.host.plugin_manifest import SidecarManifestError

    gate_body = '{"contains": ["x"]}'
    for _ in range(300):
        gate_body = f'{{all = [{gate_body}]}}'
    harness_toml = (
        'id = "deep"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\npriority = 1\n'
        f'all = [{gate_body}]\n'
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(harness_toml)

    code = tmp_path / "code" / "deepplug"
    code.mkdir(parents=True)
    (code / "deep.toml").write_text(harness_toml, encoding="utf-8")
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "deepplug"
name = "Deep Plug"
version = "1.0.0"
kind = "plugin"
description = "Deep harness gate"
author = "Tester"

[harnesses]
files = ["deep.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "deepplug")


@pytest.mark.asyncio
async def test_tier0_consent_owed_and_unactivated_refusal_and_guards_refused_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from src.plugins.host import owner_switch, sidecar_view, state as owner_state, webhook_routes
    from src.plugins.runtime import guards

    code = tmp_path / "code" / "tzerobypass"
    (code / "views" / "panelv").mkdir(parents=True)
    (code / "views" / "panelv" / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "tzerobypass"
name = "Tier Zero Bypass Check"
version = "1.0.0"
kind = "plugin"
description = "Tests Tier 0 admission and consent_owed"
author = "Tester"

[permissions]
read = ["sessions"]
secrets = ["HOOK_SEC"]

[ui.widget]
title = "W"
document = { schema = 1, root = { type = "text", value = "UNAPPROVED WIDGET" } }

[[ui.views]]
name = "panelv"
surfaces = ["panel"]
files = ["index.html"]

[webhooks.hook1]
hmac_secret = "HOOK_SEC"

[macros.boom]
steps = [
  { method = "storage.put", params = { key = "k", value = "v" } }
]

[macros.need_msg]
steps = [
  { method = "notify.toast", params = { ref = "{{session_ref}}", title = "hi" } }
]
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "tzerobypass")
    d = SidecarDefinition(
        manifest=sm,
        item_id="local/tzerobypass",
        install_key="inst-tzb",
        code_root=code,
        folder=tmp_path / "data" / "tzerobypass",
    )

    owner_switch.write(tmp_path / "state", True)
    owner_state.update(
        tmp_path / "state",
        sm,
        None,
        lambda st: replace(st, enabled=True, digest="stale-digest", grants=("sessions.read", "hooks.inbound:hook1")),
    )
    app_state = SimpleNamespace(session_manager=None)
    host = host_runtime.Host(tmp_path / "state", app=SimpleNamespace(state=app_state))
    live = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=app_state), asyncio.get_running_loop(), env_safe=lambda: False)
    live.supervisor.set_safe_mode(False)
    await live.supervisor.set_index({"expires_at": "2999-01-01T00:00:00Z"})
    app_state.sidecar_runtime = live

    try:
        monkeypatch.setattr(host_runtime, "host_for", lambda _app: host)
        monkeypatch.setattr(host_runtime, "find", lambda cid: d if cid == "tzerobypass" else None)
        monkeypatch.setattr(host, "install_key", lambda cid: "inst-tzb" if cid == "tzerobypass" else cid)

        app = FastAPI()
        app.include_router(sidecar_routes.router)
        app.include_router(sidecar_ui.router)
        app.include_router(sidecar_view.router)
        app.include_router(webhook_routes.public_router)
        app.dependency_overrides[require_auth] = lambda: {"role": "owner"}
        client = TestClient(app)

        r_act = client.post("/cplug-owner/act", json={"cplug_id": "tzerobypass", "route": "boom", "session_ref": "s1"})
        assert r_act.status_code == 409 and r_act.json()["detail"]["code"] == "needs_approval"

        r_ui = client.get("/cplugs/tzerobypass/ui/widget")
        assert r_ui.status_code == 409 and r_ui.json()["detail"]["code"] == "needs_approval"

        r_view = client.post("/cplugs/tzerobypass/view/panelv/ticket")
        assert r_view.status_code == 409 and r_view.json()["detail"]["code"] == "needs_approval"

        r_hook = client.post("/cplugs/tzerobypass/webhook/hook1", json={"x": 1})
        assert r_hook.status_code == 409 and r_hook.json()["detail"]["code"] == "needs_approval"

        with pytest.raises(guards.Refused):
            await live.run_macro("tzerobypass", "boom", session_ref="s1", owner_token="tok")

        owner_state.update(
            tmp_path / "state",
            sm,
            None,
            lambda st: replace(st, enabled=True, digest=sm.code_digest, grants=("sessions.read", "hooks.inbound:hook1")),
        )
        spec_ok = build_spec(d, frozenset({"sessions.read"}), {}, consent_owed=False)
        assert await live.supervisor.activate(spec_ok) == TIER0_STATE

        r_ungranted = client.post("/cplug-owner/act", json={"cplug_id": "tzerobypass", "route": "need_msg", "session_ref": "s1"})
        assert r_ungranted.status_code == 403
        assert r_ungranted.json()["detail"]["code"] == "not_granted"

        stopped_ids: List[str] = []
        orig_on_stopped = live.supervisor.on_stopped

        async def _rec_stop(pid: str) -> None:
            stopped_ids.append(pid)
            if orig_on_stopped is not None:
                await orig_on_stopped(pid)

        live.supervisor.on_stopped = _rec_stop
        spec_stale = build_spec(d, frozenset({"sessions.read"}), {}, consent_owed=True)
        assert await live.supervisor.activate(spec_stale) == "needs_approval"
        assert stopped_ids == ["tzerobypass"]
    finally:
        await live.supervisor.shutdown()
