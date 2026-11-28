
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from src.core.cli_command import service as cli_service
from src.core.computers import membership
from src.core.computers.door import Door
from src.core.db_migration import ensure_db_migrated
from src.plugins.cli.auth_discovery import CliHttpClient
from src.plugins.cli.dev_runner import run_dev
from src.plugins.host import dev_lease, developer_mode, risk, runtime, sidecar_boot, sidecar_registry, sideload
from src.plugins.host import state as owner_state
from src.plugins.runtime import sandbox
from src.plugins.sdk.manifest_v2 import parse_manifest_v2
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

NAME = "hotclock"


def _write_v2_widget(folder: Path, *, title: str = "Beat 1", extra_toml: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "carnivore.toml").write_text(
        f"""schema = 2
id = "{NAME}"
name = "Hot Clock"
kind = "plugin"
description = "Hot clock dev plugin."
author = "Tester"
license = "MIT"
version = "1.0.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
write = ["notify"]
{extra_toml}
[ui.widget]
title = "Hot Clock"
""",
        encoding="utf-8",
    )
    (folder / "main.py").write_text(
        f"""from cplug_sdk import Plugin

plugin = Plugin()

@plugin.ui("widget")
async def render(_params):
    return {{"schema": 1, "root": {{"type": "section", "title": "{title}", "children": [{{"type": "text", "value": "{title}"}}]}}}}

if __name__ == "__main__":
    plugin.serve()
""",
        encoding="utf-8",
    )


@pytest.fixture
def dev_world(tmp_path: Path, owner_jwt, key_store, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    published: list[str] = []
    host = SimpleNamespace(
        state_dir=state,
        publish=lambda topic: published.append(topic),
        publish_coalesced=lambda topic, *_a, **_kw: published.append(topic),
        install_key=lambda name: f"inst-{name}",
    )
    loop = asyncio.new_event_loop()
    rt = sidecar_boot.SidecarRuntime(host, app, loop, env_safe=lambda: False, app_version="9.9.9")
    app.state.sidecar_runtime = rt
    app.state.cplugs_host = runtime.Host(state, app)

    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    dev_lease.store_for(state).clear_all()
    src = tmp_path / "src" / NAME
    _write_v2_widget(src, title="Beat 1")

    _row, secret = key_store.create("script")
    with TestClient(app) as tc:
        try:
            yield SimpleNamespace(
                client=tc,
                state=state,
                src=src,
                owner=bearer(owner_jwt),
                key=bearer(secret),
                rt=rt,
                loop=loop,
                published=published,
                app=app,
            )
        finally:
            if tc.portal is not None:
                tc.portal.call(rt.supervisor.shutdown)
            del app.state.sidecar_runtime, app.state.cplugs_host
            sidecar_registry.install(None)
            dev_lease.store_for(state).clear_all()
            loop.close()


def _install_and_consent(w: SimpleNamespace) -> None:
    r_master = w.client.put("/api/v1/cplug-owner/switch", json={"enabled": True}, headers=w.owner)
    assert r_master.status_code == 200, r_master.text
    r_sw = w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner)
    assert r_sw.status_code == 200, r_sw.text
    r_add = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(w.src)}, headers=w.owner)
    assert r_add.status_code == 200, r_add.text
    d = runtime.find(NAME)
    assert d is not None
    owner_state.update(
        w.state,
        d.manifest,
        None,
        lambda s: replace(
            s,
            enabled=True,
            grants=tuple(d.manifest.permissions),
            digest=d.manifest.code_digest,
        ),
    )


def test_dev_lease_fence_and_requires_consent_first(dev_world: SimpleNamespace) -> None:
    w = dev_world
    r_key = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.key)
    assert r_key.status_code == 403 and r_key.json()["detail"] == {"reason": "api_key_forbidden"}

    w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner)
    r_add = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(w.src)}, headers=w.owner)
    assert r_add.status_code == 200
    r_lease = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.owner)
    assert r_lease.status_code == 409 and r_lease.json()["detail"]["code"] == "needs_approval"


def test_dev_hot_reload_under_300ms_and_sse_stream(dev_world: SimpleNamespace) -> None:
    w = dev_world
    if sys.platform == "darwin":
        try:
            sandbox.find_interpreter()
        except sandbox.SandboxUnavailable:
            pytest.skip("darwin interpreter not present")
    _install_and_consent(w)

    r_lease = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src), "ttl_seconds": 60.0}, headers=w.owner)
    assert r_lease.status_code == 200, r_lease.text
    lease_doc = r_lease.json()
    assert lease_doc["plugin_id"] == NAME
    assert lease_doc["source_realpath"] == os.path.realpath(w.src)

    _write_v2_widget(w.src, title="Beat 2")
    r_warm = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": True}, headers=w.owner)
    assert r_warm.status_code == 200, r_warm.text
    warm_doc = r_warm.json()
    assert warm_doc["needs_approval"] is False
    assert warm_doc["process"] == "running"
    assert warm_doc["ui_error"] is None

    w.published.clear()
    _write_v2_widget(w.src, title="Beat 3")
    t0 = time.perf_counter()
    r_hot = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": True}, headers=w.owner)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    assert r_hot.status_code == 200, r_hot.text
    hot_doc = r_hot.json()
    assert hot_doc["status"] == "reloaded"
    assert hot_doc["needs_approval"] is False
    assert hot_doc["process"] == "running"
    assert hot_doc["timings"]["total_ms"] < 300.0, hot_doc
    assert wall_ms < 1000.0

    w.loop.run_until_complete(asyncio.sleep(0))
    assert "cplugs" in w.published
    assert any(t.startswith("cplug_ui:") for t in w.published)

    d_after = runtime.find(NAME)
    st_after = owner_state.get(w.state, d_after.manifest)
    assert st_after.enabled is True
    assert "notify" in st_after.grants
    assert not risk.consent_owed(sideload.TIER_LOCAL, d_after.manifest.code_digest, st_after.digest)

    (w.src / "main.py").write_text(
        """from cplug_sdk import Plugin

plugin = Plugin()

@plugin.ui("widget")
async def render(_params):
    return {"schema": 1, "root": {"type": "bogus_node"}}

if __name__ == "__main__":
    plugin.serve()
""",
        encoding="utf-8",
    )
    r_bad_ui = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": True}, headers=w.owner)
    assert r_bad_ui.status_code == 200, r_bad_ui.text
    assert r_bad_ui.json()["ui_error"] is not None

    r_sse = w.client.get(f"/api/v1/cplug-owner/dev/stream/{NAME}?once=true", headers=w.owner)
    assert r_sse.status_code == 200
    assert "event: reloaded" in r_sse.text
    assert "event: ui_error" in r_sse.text


def test_dev_lease_widening_and_invalidation_paths(dev_world: SimpleNamespace) -> None:
    w = dev_world
    _install_and_consent(w)

    r_lease = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src), "ttl_seconds": 30.0}, headers=w.owner)
    assert r_lease.status_code == 200
    lease_token = r_lease.json()["lease_token"]

    r_ren = w.client.put(
        f"/api/v1/cplug-owner/dev/lease/{NAME}",
        json={"lease_token": lease_token, "ttl_seconds": 45.0},
        headers=w.owner,
    )
    assert r_ren.status_code == 200

    (w.src / "carnivore.toml").write_text(
        f"""schema = 2
id = "{NAME}"
name = "Hot Clock"
kind = "plugin"
description = "Hot clock dev plugin."
author = "Tester"
license = "MIT"
version = "1.0.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
read = ["sessions"]
write = ["notify"]

[ui.widget]
title = "Hot Clock"
""",
        encoding="utf-8",
    )
    r_wide = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": False}, headers=w.owner)
    assert r_wide.status_code == 409, r_wide.text
    detail = r_wide.json()["detail"]
    assert detail["code"] == "permission_widened"
    assert detail["needs_approval"] is True
    assert "permission:sessions.read" in detail["widened"]
    assert dev_lease.store_for(w.state).get(NAME) is None

    _write_v2_widget(w.src, title="Safe")
    w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(w.src)}, headers=w.owner)
    d = runtime.find(NAME)
    owner_state.update(
        w.state,
        d.manifest,
        None,
        lambda s: replace(s, enabled=True, grants=tuple(d.manifest.permissions), digest=d.manifest.code_digest),
    )
    assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.owner).status_code == 200
    assert w.client.delete(f"/api/v1/cplug-owner/dev/lease/{NAME}", headers=w.owner).json()["released"] is True
    assert w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": False}, headers=w.owner).status_code == 409

    assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.owner).status_code == 200
    w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": False}, headers=w.owner)
    assert dev_lease.store_for(w.state).get(NAME) is None

    link = w.src.parent / f"{NAME}-link"
    link.symlink_to(w.src)
    w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner)
    r_sym = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(link)}, headers=w.owner)
    assert r_sym.status_code == 422 and r_sym.json()["detail"]["code"] == "source_missing"


def test_capability_baseline_widening_matrix() -> None:
    base_manifest = SimpleNamespace(
        permissions=("notify.toast",),
        network=SimpleNamespace(
            network_hosts=(SimpleNamespace(host="api.example.com", methods=("GET",), paths=("/v1",), auth=None),),
            lan_hosts=(),
            secrets=(SimpleNamespace(name="api_tok"),),
        ),
        subscriptions=("session.idle",),
        tools=({"name": "ping", "handler": "rpc"},),
        webhooks=(),
        channels=(),
        macros=(),
        harnesses=(),
        ai_features=(),
        trust="sandboxed",
        services_consumes=("kv",),
        events_emit=("demo.tick",),
    )
    base = dev_lease.extract_baseline(base_manifest)

    narrow = SimpleNamespace(
        **{
            **base_manifest.__dict__,
            "network": SimpleNamespace(
                network_hosts=(SimpleNamespace(host="api.example.com", methods=("GET",), paths=("/v1/sub",), auth=None),),
                lan_hosts=(),
                secrets=(SimpleNamespace(name="api_tok"),),
            ),
        }
    )
    assert dev_lease.widening_reasons(base, dev_lease.extract_baseline(narrow)) == []

    widened = SimpleNamespace(
        **{
            **base_manifest.__dict__,
            "permissions": ("notify.toast", "sessions.read"),
            "network": SimpleNamespace(
                network_hosts=(SimpleNamespace(host="api.example.com", methods=("GET", "POST"), paths=("/",), auth=None),),
                lan_hosts=(SimpleNamespace(entry="192.168.1.0/24", methods=("GET",), paths=("/status",)),),
                secrets=(SimpleNamespace(name="api_tok"), SimpleNamespace(name="extra_tok")),
            ),
            "trust": "unrestricted",
            "services_consumes": ("kv", "other.svc"),
            "events_emit": ("demo.tick", "demo.extra"),
        }
    )
    reasons = dev_lease.widening_reasons(base, dev_lease.extract_baseline(widened))
    assert any(r == "permission:sessions.read" for r in reasons)
    assert any(r.startswith("network_methods:api.example.com") for r in reasons)
    assert any(r.startswith("network_paths:api.example.com") for r in reasons)
    assert any(r == "lan_host:192.168.1.0/24" for r in reasons)
    assert any(r == "secret:extra_tok" for r in reasons)
    assert "trust:unrestricted" in reasons
    assert any(r == "service_consume:other.svc" for r in reasons)
    assert any(r == "event_emit:demo.extra" for r in reasons)


def _mv2_raw(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": 2,
        "id": "advplug",
        "name": "Adv Plug",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Adversarial baseline test plugin.",
        "author": "Tester",
        "permissions": {
            "write": ["notify"],
            "network": [{"host": "api.example.com", "reason": "API", "methods": ["GET"], "paths": ["/v1"]}],
            "secrets": [{"key": "tok", "label": "Token"}],
            "events": ["ev.base"],
        },
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "events": {"on": ["session.idle"], "emit": ["adv.ping"]},
        "services": {"provides": [{"name": "adv.svc", "methods": ["ping"]}], "consumes": ["kv"]},
        "channels": {
            "alerts": {
                "url": "https://api.example.com/v1/hook",
                "method": "POST",
                "headers": {"X-Auth": "$SECRET:tok"},
                "body_template": "{\"ok\":true}",
            }
        },
        "macros": {
            "say": {"title": "Say", "steps": [{"action": "notify.toast", "params": {"title": "hi"}}]},
        },
        "ui": {
            "routes": ["status"],
            "commands": [
                {"id": "cmdgo", "title": "Go", "steps": [{"action": "notify.toast", "params": {"title": "go"}}]},
            ],
        },
        "timers": {"tick": {"every_seconds": 60}},
    }
    doc.update(overrides)
    return doc


def test_dev_lease_manifest_v2_comprehensive_widening_and_ttl() -> None:
    base_mv2 = parse_manifest_v2(_mv2_raw())
    base = dev_lease.extract_baseline(base_mv2)

    assert dev_lease._paths_covered(("/v1",), ()) is False
    assert dev_lease._paths_covered(("/",), ()) is True

    cand_ev_allow = parse_manifest_v2(_mv2_raw(permissions={**_mv2_raw()["permissions"], "events": ["ev.base", "ev.secret"]}))
    assert "event_allowed:ev.secret" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_ev_allow))

    cand_ev_on = SimpleNamespace(
        **{
            **base_mv2.__dict__,
            "subscriptions": (),
            "events_on": ("session.idle", "feed.raw"),
        }
    )
    assert "subscription:feed.raw" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_ev_on))

    cand_svc_new = parse_manifest_v2(
        _mv2_raw(services={"provides": [{"name": "adv.svc", "methods": ["ping"]}, {"name": "adv.two", "methods": ["run"]}], "consumes": ["kv"]})
    )
    assert "service_provide:adv.two" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_svc_new))

    cand_svc_meth = parse_manifest_v2(
        _mv2_raw(services={"provides": [{"name": "adv.svc", "methods": ["ping", "write"]}], "consumes": ["kv"]})
    )
    assert "service_provide:adv.svc:write" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_svc_meth))

    for field_override in (
        {"url": "https://api.example.com/v1/exfil"},
        {"method": "PUT"},
        {"headers": {"Authorization": "Bearer $SECRET:tok"}},
        {"body_template": "{\"exfil\":\"$SECRET:tok\"}"},
    ):
        ch = dict(_mv2_raw()["channels"]["alerts"], **field_override)
        cand_ch = parse_manifest_v2(_mv2_raw(channels={"alerts": ch}))
        assert "channel:alerts" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_ch))

    cand_macro = parse_manifest_v2(
        _mv2_raw(macros={"say": {"title": "Say", "steps": [{"action": "notify.toast", "params": {"title": "evil"}}]}})
    )
    assert "macro:say" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_macro))

    cand_cmd = parse_manifest_v2(
        _mv2_raw(
            ui={
                "routes": ["status"],
                "commands": [
                    {"id": "cmdgo", "title": "Go", "steps": [{"action": "notify.toast", "params": {"title": "evil"}}]},
                ],
            }
        )
    )
    assert "ui_command_macro:cmdgo" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_cmd))

    tier0_raw = _mv2_raw()
    del tier0_raw["run"]
    del tier0_raw["timers"]
    del tier0_raw["services"]
    tier0_raw["ui"] = {"commands": [{"id": "cmdgo", "title": "Go", "steps": [{"action": "notify.toast", "params": {"title": "go"}}]}]}
    tier0_base = dev_lease.extract_baseline(parse_manifest_v2(tier0_raw))
    tier0_escalated = dev_lease.extract_baseline(parse_manifest_v2({**tier0_raw, "run": {"cmd": ["python3", "main.py"], "mode": "rpc"}}))
    assert "run:tier0_escalation" in dev_lease.widening_reasons(tier0_base, tier0_escalated)

    cand_cmd_chg = parse_manifest_v2(_mv2_raw(run={"cmd": ["bash", "evil.sh"], "mode": "oneshot"}))
    reasons_run = dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_cmd_chg))
    assert "run_mode:oneshot" in reasons_run
    assert "run_cmd:bash evil.sh" in reasons_run

    cand_rt = parse_manifest_v2(_mv2_raw(ui={**_mv2_raw()["ui"], "routes": ["status", "admin"]}))
    assert "route:admin" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_rt))

    cand_tm = parse_manifest_v2(_mv2_raw(timers={"tick": {"every_seconds": 10}}))
    assert "timer:tick" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_tm))

    cand_view = parse_manifest_v2(
        _mv2_raw(
            ui={
                **_mv2_raw()["ui"],
                "views": [{"name": "dash", "surfaces": ["panel"], "files": ["index.html"]}],
            }
        )
    )
    assert "view:dash" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_view))

    cand_data = SimpleNamespace(**{**base_mv2.__dict__, "data": (SimpleNamespace(id="store1", kind="db", path="a.db", root_setting="", state_path="", default="", policy=SimpleNamespace(purge=""), provides=""),)})
    assert "data:store1" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_data))

    cand_owns = SimpleNamespace(**{**base_mv2.__dict__, "owns": SimpleNamespace(files=("extra.db",))})
    assert "owns_file:extra.db" in dev_lease.widening_reasons(base, dev_lease.extract_baseline(cand_owns))

    ai_base = dev_lease.extract_baseline(
        SimpleNamespace(**{**base_mv2.__dict__, "ai_features": {"sum": SimpleNamespace(capability="embed", calls_per_day=20, tokens_per_day=5000)}})
    )
    ai_lower = dev_lease.extract_baseline(
        SimpleNamespace(**{**base_mv2.__dict__, "ai_features": {"sum": SimpleNamespace(capability="embed", calls_per_day=10, tokens_per_day=2000)}})
    )
    assert dev_lease.widening_reasons(ai_base, ai_lower) == []
    ai_higher = dev_lease.extract_baseline(
        SimpleNamespace(**{**base_mv2.__dict__, "ai_features": {"sum": SimpleNamespace(capability="embed", calls_per_day=20, tokens_per_day=9000)}})
    )
    assert "ai_feature:sum:embed" in dev_lease.widening_reasons(ai_base, ai_higher)

    now = [100.0]
    store = dev_lease.DevTrustLeaseStore(clock=lambda: now[0])
    store.acquire("advplug", "k1", "/tmp/advplug", base_mv2, ttl=5.0)
    now[0] = 106.0
    ok, reason, _ = store.check_reload("advplug", "k1", "/tmp/advplug", base_mv2)
    assert (ok, reason) == (False, "lease_expired")


def test_dev_reload_sideload_revokes_lease_and_source_mismatch_leaves_installed_root_untouched(
    dev_world: SimpleNamespace,
    tmp_path: Path,
) -> None:
    w = dev_world
    _install_and_consent(w)
    assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.owner).status_code == 200

    (w.src / "carnivore.toml").write_text(
        (w.src / "carnivore.toml").read_text(encoding="utf-8").replace('write = ["notify"]', 'read = ["sessions"]\nwrite = ["notify"]'),
        encoding="utf-8",
    )
    r_sync = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(w.src)}, headers=w.owner)
    assert r_sync.status_code == 200 and r_sync.json()["needs_approval"] is True
    assert dev_lease.store_for(w.state).get(NAME) is None

    _write_v2_widget(w.src, title="Reverted")
    r_bypass = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(w.src), "probe_ui": False}, headers=w.owner)
    assert r_bypass.status_code == 409 and r_bypass.json()["detail"]["code"] == "needs_approval"

    assert w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(w.src)}, headers=w.owner).status_code == 200
    d = runtime.find(NAME)
    assert d is not None
    owner_state.update(
        w.state,
        d.manifest,
        None,
        lambda s: replace(s, enabled=True, grants=tuple(d.manifest.permissions), digest=d.manifest.code_digest),
    )
    assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(w.src)}, headers=w.owner).status_code == 200

    installed_main = sideload.code_root_of(w.state, NAME) / "main.py"
    before_bytes = installed_main.read_bytes()
    before_source = sideload.items(w.state)[NAME]["source"]

    evil_src = tmp_path / "evil_src" / NAME
    _write_v2_widget(evil_src, title="EVIL_TITLE")
    r_mis = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(evil_src), "probe_ui": False}, headers=w.owner)
    assert r_mis.status_code == 409 and r_mis.json()["detail"]["code"] == "source_mismatch"
    assert installed_main.read_bytes() == before_bytes
    assert sideload.items(w.state)[NAME]["source"] == before_source


def test_dev_runner_live_uvicorn_sse_and_renew_resilience(
    dev_world: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = dev_world
    if sys.platform == "darwin":
        try:
            sandbox.find_interpreter()
        except sandbox.SandboxUnavailable:
            pytest.skip("darwin interpreter not present")
    _install_and_consent(w)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(w.app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    srv_thread = threading.Thread(target=server.run, daemon=True)
    srv_thread.start()
    try:
        deadline = time.monotonic() + 10.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn test server failed to start"

        token = w.owner["Authorization"].split(" ", 1)[1]
        cli = CliHttpClient(state_dir=w.state, base_url=f"http://127.0.0.1:{port}", token=token)

        seen_events: list[tuple[str, dict[str, Any]]] = []
        edit_done = threading.Event()
        second_edit_sent = threading.Event()

        def _on_event(ev_name: str, payload: dict[str, Any]) -> None:
            seen_events.append((ev_name, payload))
            if ev_name == "reloaded":
                edit_done.set()
                if not second_edit_sent.is_set():
                    second_edit_sent.set()
                    _write_v2_widget(w.src, title="Live SSE Beat 2")

        def _editor() -> None:
            time.sleep(0.25)
            _write_v2_widget(w.src, title="Live SSE Beat 1")

        ed_thread = threading.Thread(target=_editor, daemon=True)
        ed_thread.start()
        rc = run_dev(w.src, client=cli, debounce_ms=25, on_event=_on_event, max_reloads=2)
        assert rc == 0
        assert edit_done.is_set()
        assert any(ev == "reloaded" for ev, _ in seen_events)

        monkeypatch.setattr("src.plugins.cli.dev_runner.RENEW_INTERVAL_S", 0.05)
        orig_req = cli.request
        renew_attempts = [0]

        def _flaky_request(method: str, path: str, *, json_body=None, timeout: float = 30.0):
            if method == "PUT" and path.startswith("/api/v1/cplug-owner/dev/lease/"):
                renew_attempts[0] += 1
                if renew_attempts[0] == 1:
                    raise urllib.error.URLError("transient")
            return orig_req(method, path, json_body=json_body, timeout=timeout)

        monkeypatch.setattr(cli, "request", _flaky_request)

        def _widener() -> None:
            time.sleep(0.25)
            (w.src / "carnivore.toml").write_text(
                (w.src / "carnivore.toml").read_text(encoding="utf-8").replace('write = ["notify"]', 'read = ["sessions"]\nwrite = ["notify"]'),
                encoding="utf-8",
            )

        threading.Thread(target=_widener, daemon=True).start()
        rc_wide = run_dev(w.src, client=cli, debounce_ms=25)
        assert rc_wide == 1
        assert renew_attempts[0] >= 1
        cli.request("PUT", "/api/v1/cplug-owner/sideload/switch", json_body={"enabled": False})
    finally:
        server.should_exit = True
        srv_thread.join(timeout=5.0)


def test_dev_runner_off_main_thread_has_no_signal_error_or_thread_leak(
    dev_world: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = dev_world
    if sys.platform == "darwin":
        try:
            sandbox.find_interpreter()
        except sandbox.SandboxUnavailable:
            pytest.skip("darwin interpreter not present")
    _install_and_consent(w)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(w.app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    srv_thread = threading.Thread(target=server.run, daemon=True)
    srv_thread.start()
    try:
        deadline = time.monotonic() + 10.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn test server failed to start"

        token = w.owner["Authorization"].split(" ", 1)[1]
        cli = CliHttpClient(state_dir=w.state, base_url=f"http://127.0.0.1:{port}", token=token)
        monkeypatch.setattr("src.plugins.cli.dev_runner.RENEW_INTERVAL_S", 0.05)

        renew_calls = [0]
        orig_req = cli.request

        def _counting_request(method: str, path: str, *, json_body=None, timeout: float = 30.0):
            if method == "PUT" and path.startswith("/api/v1/cplug-owner/dev/lease/"):
                renew_calls[0] += 1
            return orig_req(method, path, json_body=json_body, timeout=timeout)

        monkeypatch.setattr(cli, "request", _counting_request)

        result: dict[str, Any] = {}

        def _worker() -> None:
            try:
                result["rc"] = run_dev(w.src, client=cli, debounce_ms=25, max_reloads=1)
            except BaseException as exc:  # noqa: BLE001
                result["exc"] = exc

        worker_thread = threading.Thread(target=_worker, daemon=True)
        worker_thread.start()
        time.sleep(0.25)
        _write_v2_widget(w.src, title="Worker Thread Edit")
        worker_thread.join(timeout=15.0)
        assert not worker_thread.is_alive()
        assert "exc" not in result, f"off-main-thread run_dev raised {result.get('exc')!r}"
        assert result.get("rc") == 0
        assert dev_lease.store_for(w.state).get(NAME) is None

        count_at_exit = renew_calls[0]
        time.sleep(0.2)
        assert renew_calls[0] == count_at_exit, "renew_thread leaked PUT /lease calls after run_dev exited"
        cli.request("PUT", "/api/v1/cplug-owner/sideload/switch", json_body={"enabled": False})
    finally:
        server.should_exit = True
        srv_thread.join(timeout=5.0)


def test_dev_cli_subprocess_door_auth_hot_reload_under_300ms_and_widening_reprompt(
    dev_world: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = dev_world
    if sys.platform == "darwin":
        try:
            sandbox.find_interpreter()
        except sandbox.SandboxUnavailable:
            pytest.skip("darwin interpreter not present")
    _install_and_consent(w)
    monkeypatch.setattr(membership, "first_run_state", lambda: "unpaired")

    token = w.owner["Authorization"].split(" ", 1)[1]
    sock_dir = Path(tempfile.mkdtemp(prefix="d", dir="/tmp"))
    os.chmod(sock_dir, 0o700)
    door_sock = sock_dir / "d.sock"
    door_calls = {"n": 0}

    async def _fake_totp(_code: str) -> bool:
        return False

    async def _fake_login(_store: Any) -> dict[str, Any]:
        door_calls["n"] += 1
        return {"access_token": token, "refresh_token": "ref-cli-door", "expires_in": 900}

    door_loop = asyncio.new_event_loop()
    door = Door(str(door_sock), totp_ok=_fake_totp, login=_fake_login, setup_status=lambda: "pending")
    door_ready = threading.Event()
    door_stop: list[asyncio.Event] = []

    def _run_door() -> None:
        asyncio.set_event_loop(door_loop)
        ev = asyncio.Event()
        door_stop.append(ev)

        async def _main() -> None:
            await door.start()
            door_ready.set()
            await ev.wait()
            await door.stop()

        door_loop.run_until_complete(_main())

    door_thread = threading.Thread(target=_run_door, daemon=True)
    door_thread.start()
    assert door_ready.wait(timeout=5.0)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(uvicorn.Config(w.app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    srv_thread = threading.Thread(target=server.run, daemon=True)
    srv_thread.start()
    proc: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 10.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn test server failed to start"

        cli_service.write_runtime_info(w.state, port, door_sock=str(door_sock))
        repo_root = Path(__file__).resolve().parents[3]
        sub_env = {k: v for k, v in os.environ.items() if k not in ("CARNIVORE_API_TOKEN", "CARNIVORE_URL")}
        sub_env["CARNIVORE_STATE_DIR"] = str(w.state)
        sub_env["PYTHONPATH"] = str(repo_root)
        sub_env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-m", "src.tui", "plugin", "dev", str(w.src), "--debounce-ms", "25"],
            cwd=str(repo_root),
            env=sub_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None and proc.stderr is not None

        out_q: queue.Queue[str] = queue.Queue()
        err_lines: list[str] = []

        def _pump_out() -> None:
            assert proc is not None and proc.stdout is not None
            for line in proc.stdout:
                out_q.put(line.rstrip("\n"))

        def _pump_err() -> None:
            assert proc is not None and proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line.rstrip("\n"))

        t_out = threading.Thread(target=_pump_out, daemon=True)
        t_err = threading.Thread(target=_pump_err, daemon=True)
        t_out.start()
        t_err.start()

        def _wait_stdout(substring: str, timeout_s: float = 15.0) -> str:
            end = time.monotonic() + timeout_s
            seen: list[str] = []
            while time.monotonic() < end:
                rem = max(0.05, end - time.monotonic())
                try:
                    ln = out_q.get(timeout=min(0.25, rem))
                    seen.append(ln)
                    if substring in ln:
                        return ln
                except queue.Empty:
                    if proc.poll() is not None:
                        break
            raise AssertionError(f"Did not see {substring!r}; stdout={seen!r}, stderr={err_lines!r}")

        _wait_stdout(f"dev lease acquired for {NAME}")
        assert door_calls["n"] >= 1
        assert (w.state / "tui_auth.json").is_file()

        _write_v2_widget(w.src, title="Subprocess Warm Beat")
        _wait_stdout(f"reloaded {NAME}: status=reloaded total_ms=")

        w.published.clear()
        _write_v2_widget(w.src, title="Subprocess Steady Beat")
        reload_line = _wait_stdout(f"reloaded {NAME}: status=reloaded total_ms=")
        m_ms = re.search(r"total_ms=([0-9]+(?:\.[0-9]+)?)", reload_line)
        assert m_ms is not None, reload_line
        assert float(m_ms.group(1)) < 300.0, reload_line

        w.loop.run_until_complete(asyncio.sleep(0))
        assert "cplugs" in w.published
        assert any(t.startswith("cplug_ui:") for t in w.published)

        req_get = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/cplugs/{NAME}", headers=w.owner, method="GET")
        with urllib.request.urlopen(req_get, timeout=5.0) as resp:
            row_active = json.loads(resp.read().decode("utf-8"))
        assert row_active["enabled"] is True
        assert row_active["state"] == "active"

        (w.src / "carnivore.toml").write_text(
            (w.src / "carnivore.toml").read_text(encoding="utf-8").replace('write = ["notify"]', 'read = ["sessions"]\nwrite = ["notify"]'),
            encoding="utf-8",
        )
        rc = proc.wait(timeout=15.0)
        t_err.join(timeout=2.0)
        t_out.join(timeout=2.0)
        stderr_all = "\n".join(err_lines)
        assert rc == 1, f"expected rc=1, got {rc}; stderr={stderr_all!r}"
        assert "permission_widened" in stderr_all
        assert dev_lease.store_for(w.state).get(NAME) is None

        with urllib.request.urlopen(req_get, timeout=5.0) as resp2:
            row_wide = json.loads(resp2.read().decode("utf-8"))
        assert row_wide["state"] == "needs_approval"

        cli = CliHttpClient(state_dir=w.state, base_url=f"http://127.0.0.1:{port}", token=token)
        sc_after, body_after = cli.request("POST", "/api/v1/cplug-owner/dev/reload", json_body={"path": str(w.src), "probe_ui": True})
        assert sc_after == 409
        assert body_after["detail"]["code"] == "needs_approval"
        cli.request("PUT", "/api/v1/cplug-owner/sideload/switch", json_body={"enabled": False})
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        server.should_exit = True
        srv_thread.join(timeout=5.0)
        if door_stop:
            door_loop.call_soon_threadsafe(door_stop[0].set)
        door_thread.join(timeout=5.0)
        door_loop.close()
        shutil.rmtree(sock_dir, ignore_errors=True)
