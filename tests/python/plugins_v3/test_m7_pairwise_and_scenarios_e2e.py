
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from hosted.catalog_index.tools.index_builder import review as ib_review
from scripts.warez_gates import jobs, materialize as mat_mod, review as gate_review, static as gate_static
from scripts.warez_gates.item import load_item
from scripts.warez_gates.models import ADVISORY, PASS
from scripts.warez_gates.policy import load_policy
from src.api import catalog_publish_routes, plugin_studio_routes
from src.core import session_change_notice
from src.core.catalog import publish_github
from src.core.catalog.publish_github import build_hosted_github_payload, prepare_github_publish
from src.core.notifications import kind_specs
from src.core.skills.digest import digest_directory
from src.plugins.cli.install_publish import run_publish
from src.plugins.host import dev_lease, egress_log, plugin_channels, secret_store, webhook_routes
from src.plugins.host.fetch_transport import StdlibTransport
from src.plugins.runtime import webhooks
from tests.helpers import submissions_harness as sh
from tests.helpers.catalog_app import ledger_rows
from tests.helpers.minisign_keys import minisign_binary
from tests.helpers.plugins_v3_e2e_world import (
    DARWIN_SANDBOX,
    MemKeychain,
    PluginsV3E2EWorld,
    build_plugins_v3_world,
    init_bare_git_repo,
    serve_http_probe,
    wire_bare_github,
)
from tests.helpers.plugins_v3_polyglot_fixtures import (
    DEFAULT_MIT_LICENSE,
    build_bash_plugin,
    build_node_plugin,
    build_python_plugin,
    build_tier0_declarative_plugin,
    has_node,
    write_plugin_files,
)
from tests.helpers.warez_slice5_e2e_fixtures import (
    build_12_gate_report,
    build_and_publish_checkout_index,
    create_signed_git_plugin_repo,
    make_runner_for_review_json,
    open_e2e_bridge,
    publish_cplug_to_checkout,
)
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401


def _enable_sideload_switch(w: PluginsV3E2EWorld) -> None:
    r = w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers)
    assert r.status_code == 200 and r.json()["enabled"] is True, r.text


def _install_cplug_consent(
    client: Any, item_id: str, plugin_id: str, headers: Dict[str, str], *, acknowledge_flagged: bool = False, secrets: Optional[Dict[str, str]] = None
) -> Tuple[Any, Dict[str, Any]]:
    preview = client.post("/api/v1/catalog/install/preview", json={"item_id": item_id, "scope": "global"}, headers=headers)
    assert preview.status_code in (200, 409), preview.text
    pbody = preview.json()
    sheet_p = pbody["detail"] if isinstance(pbody.get("detail"), dict) else pbody
    consent: Dict[str, Any] = {
        "digest": sheet_p["digest"],
        "body_sha": sheet_p["body_sha"],
        "scripts": True,
        "cplug_accepted": True,
        "cplug_facts_sha": sheet_p["cplug_facts_sha"],
    }
    if acknowledge_flagged:
        consent["acknowledge_flagged"] = True
    r_inst = client.post(
        "/api/v1/catalog/install",
        json={"item_id": item_id, "scope": "global", "plan_token": sheet_p.get("plan_token"), "consent": consent},
        headers=headers,
    )
    if r_inst.status_code != 200:
        return r_inst, {}
    install_id = r_inst.json().get("install_id")
    sheet = client.get(f"/api/v1/cplugs/{plugin_id}/sheet", headers=headers).json()
    row = client.get(f"/api/v1/cplugs/{plugin_id}", headers=headers).json()
    put_body: Dict[str, Any] = {
        "revision": row["revision"],
        "enabled": True,
        "activate_runtime": True,
        "grants": {"app": [p["name"] for p in sheet.get("permissions", [])], "ui_slots": [s["slot"] for s in sheet.get("ui_slots", [])]},
        "consent": {
            "digest": sheet["digest"],
            "body_sha": sheet["body_sha"],
            "grants_sha": sheet["grants_sha"],
            "ticks": [p["name"] for p in sheet.get("permissions", []) if p.get("needs_tick")],
            "ui_slots_sha": sheet.get("ui_slots_sha"),
            "slot_ticks": [s["slot"] for s in sheet.get("ui_slots", []) if s.get("needs_tick")],
        },
    }
    if secrets:
        put_body["secrets"] = dict(secrets)
    r_en = client.put(f"/api/v1/cplugs/{plugin_id}", json=put_body, headers=headers)
    return r_en, {"install_id": install_id, "row": (r_en.json() if r_en.status_code == 200 else {})}


class _TestClientCliAdapter:
    def __init__(self, client: Any, headers: Dict[str, str]) -> None:
        self._client, self._headers = client, headers

    def request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        resp = self._client.request(method, path, json=json_body, headers=self._headers)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier3_pairwise_github_unverified_webhook_timer_http_events_and_view_e2e(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    api_secret = "sk-gh-" + "pairwise-secret-554433"
    wh_secret = "whsec-gh-pairwise-hmac-778899"
    with serve_http_probe() as probe, build_plugins_v3_world(
        tmp_path, owner_jwt, key_store, monkeypatch, dev_mode=False, enable_sideload=False, with_http_probe=False
    ) as w:
        probe_ip, probe_port = probe.host_port
        probe.set_route(
            "/ping",
            status=200,
            body=json.dumps({"echo": api_secret, "ok": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Leak": f"Bearer {api_secret}"},
        )
        orig_gai, orig_send = socket.getaddrinfo, StdlibTransport.send
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", int(port or 443)))] if host == "api.github-plug.example" else orig_gai(host, port, *a, **kw),
        )
        monkeypatch.setattr(
            StdlibTransport,
            "send",
            lambda st, **kw: orig_send(st, **{**kw, "ip": probe_ip, "port": probe_port, "tls": False}) if (kw["ip"] == "93.184.216.34" and kw["host"] == "api.github-plug.example") else orig_send(st, **kw),
        )

        gh_files: Dict[str, str | bytes] = {
            "carnivore.toml": textwrap.dedent("""
                schema = 2
                id = "ghwatcher"
                name = "GH Watcher"
                version = "1.0.0"
                kind = "plugin"
                description = "Direct GitHub pairwise integration fixture"
                author = "Acme"
                license = "MIT"
                tier = "catalog"

                [run]
                cmd = ["python3", "main.py"]
                mode = "rpc"

                [permissions]
                network = [{ host = "api.github-plug.example", methods = ["GET", "POST"], paths = ["/"] }]
                secrets = [{ key = "wh_secret", label = "Webhook HMAC" }, { key = "api_token", label = "API Token" }]
                events = ["ghwatcher:hooked", "ghwatcher:ticked"]

                [permissions.reasons]
                "network:api.github-plug.example" = "Post heartbeat to remote API"
                "hooks.inbound:ingest" = "Accept signed webhooks"
                "events:ghwatcher:hooked" = "Publish inbound webhook event"
                "events:ghwatcher:ticked" = "Publish timer fetch event"

                [timers]
                beat = { every_seconds = 5 }

                [webhooks.ingest]
                hmac_secret = "wh_secret"

                [events]
                emit = ["ghwatcher:hooked", "ghwatcher:ticked"]

                [ui]
                routes = ["state"]

                [[ui.views]]
                name = "dash"
                surfaces = ["panel"]
                files = ["index.html"]
            """).lstrip("\n"),
            "main.py": textwrap.dedent("""
                import json
                from cplug_sdk import Plugin

                plugin = Plugin()
                _state = {"hooks": 0, "ticks": 0, "fetch": None}

                @plugin.ui("widget")
                async def render_widget(_params):
                    return {"schema": 2, "root": {"type": "column", "children": [{"type": "text", "value": f"hooks={_state['hooks']} ticks={_state['ticks']}"}]}}

                @plugin.on("webhook.ingest")
                async def on_hook(_seq, body):
                    _state["hooks"] += 1
                    await plugin.host.events.emit("ghwatcher:hooked", {"count": _state["hooks"], "body": body})

                @plugin.timer("beat")
                async def on_beat(_scheduled_for):
                    res = await plugin.host.http_fetch("https://api.github-plug.example/ping", method="POST", headers={"Authorization": "Bearer $SECRET:api_token"}, body=json.dumps({"beat": _state["ticks"] + 1}))
                    _state["ticks"] += 1
                    _state["fetch"] = res
                    await plugin.host.events.emit("ghwatcher:ticked", {"tick": _state["ticks"], "status": res.get("status")})

                @plugin.route("state")
                async def get_state(_req):
                    return {"status": 200, "body": _state}
            """).lstrip("\n"),
            "views/dash/index.html": "<!doctype html><html><head></head><body><h1>GH Watcher</h1></body></html>\n",
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        }
        bare_repo, _, _ = init_bare_git_repo(tmp_path / "bare_gh", gh_files, tag="v1.0.0")
        wire_bare_github(monkeypatch, bare_repo, owner="acme", repo="ghwatcher")

        r_prev = w.client.post("/api/v1/cplug-owner/github/preview", json={"source": "acme/ghwatcher"}, headers=w.owner_headers)
        assert r_prev.status_code == 200, r_prev.text
        prev = r_prev.json()
        assert prev["trust_tier"] == "unverified_github" and prev["trust_badge"] == "Unverified GitHub Repo" and prev["unverified"] is True

        sheet = prev["consent_sheet"]
        r_inst = w.client.post(
            "/api/v1/cplug-owner/github/install",
            json={
                "source": "acme/ghwatcher",
                "enable": True,
                "activate_runtime": True,
                "secrets": {"wh_secret": wh_secret, "api_token": api_secret},
                "consent": {
                    "digest": sheet["digest"],
                    "body_sha": sheet["body_sha"],
                    "grants_sha": sheet["grants_sha"],
                    "ticks": [p["name"] for p in sheet["permissions"] if p["needs_tick"]],
                    "ui_slots_sha": sheet.get("ui_slots_sha"),
                    "slot_ticks": [s["slot"] for s in sheet.get("ui_slots", []) if s.get("needs_tick")],
                },
            },
            headers=w.owner_headers,
        )
        assert r_inst.status_code == 200 and r_inst.json()["enabled"] is True, r_inst.text
        insp_text = w.client.get("/api/v1/cplugs/ghwatcher/inspector", headers=w.owner_headers).text
        assert api_secret not in insp_text and wh_secret not in insp_text

        r_tkt = w.client.post("/api/v1/cplugs/ghwatcher/view/dash/ticket", headers=w.owner_headers)
        r_view = w.client.get(r_tkt.json()["path"])
        assert r_view.status_code == 200 and "carnivore-frame.css" in r_view.text and "Content-Security-Policy" in r_view.headers
        assert w.client.get("/api/v1/cplugs/ghwatcher/ui/widget", headers=w.owner_headers).json()["document"]["schema"] == 2

        sub_files: Dict[str, str | bytes] = {
            "carnivore.toml": textwrap.dedent("""
                schema = 2
                id = "ghsub"
                name = "GH Sub"
                version = "1.0.0"
                kind = "plugin"
                description = "Subscriber plugin"
                author = "Acme"
                license = "MIT"
                tier = "catalog"

                [run]
                cmd = ["python3", "main.py"]
                mode = "rpc"

                [permissions]
                events = ["ghwatcher:hooked", "ghwatcher:ticked"]

                [permissions.reasons]
                "events:ghwatcher:hooked" = "Consume webhook events"
                "events:ghwatcher:ticked" = "Consume timer events"

                [events]
                on = ["ghwatcher:hooked", "ghwatcher:ticked"]

                [ui]
                routes = ["seen"]
            """).lstrip("\n"),
            "main.py": textwrap.dedent("""
                from cplug_sdk import Plugin

                plugin = Plugin()
                _seen = []

                @plugin.on("ghwatcher:hooked")
                async def on_hooked(seq, payload):
                    _seen.append({"family": "ghwatcher:hooked", "seq": seq, "payload": payload})

                @plugin.on("ghwatcher:ticked")
                async def on_ticked(seq, payload):
                    _seen.append({"family": "ghwatcher:ticked", "seq": seq, "payload": payload})

                @plugin.route("seen")
                async def get_seen(_req):
                    return {"status": 200, "body": {"events": _seen}}
            """).lstrip("\n"),
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        }
        bare_sub, _, _ = init_bare_git_repo(tmp_path / "bare_sub", sub_files, tag="v1.0.0")
        wire_bare_github(monkeypatch, bare_sub, owner="acme", repo="ghsub")
        sub_prev = w.client.post("/api/v1/cplug-owner/github/preview", json={"source": "acme/ghsub"}, headers=w.owner_headers).json()
        sub_sh = sub_prev["consent_sheet"]
        r_sub_inst = w.client.post(
            "/api/v1/cplug-owner/github/install",
            json={
                "source": "acme/ghsub",
                "enable": True,
                "activate_runtime": True,
                "consent": {
                    "digest": sub_sh["digest"],
                    "body_sha": sub_sh["body_sha"],
                    "grants_sha": sub_sh["grants_sha"],
                    "ticks": [p["name"] for p in sub_sh["permissions"] if p["needs_tick"]],
                    "ui_slots_sha": sub_sh.get("ui_slots_sha"),
                    "slot_ticks": [s["slot"] for s in sub_sh.get("ui_slots", []) if s.get("needs_tick")],
                },
            },
            headers=w.owner_headers,
        )
        assert r_sub_inst.status_code == 200 and r_sub_inst.json()["enabled"] is True, r_sub_inst.text

        payload_bytes = b'{"event":"push","ref":"refs/heads/main"}'
        assert w.client.post("/api/v1/cplugs/ghwatcher/webhook/ingest", content=payload_bytes).status_code == 401
        assert w.client.post(
            "/api/v1/cplugs/ghwatcher/webhook/ingest",
            content=payload_bytes,
            headers={"X-Signature": "sha256=deadbeef", "X-Timestamp": str(int(time.time())), "X-Nonce": "n1"},
        ).status_code == 401
        gh_key = w.host.install_key("ghwatcher")
        webhook_routes._verifiers[gh_key]._started -= 40
        now_ts = int(time.time())
        sig = webhooks.sign(wh_secret.encode("utf-8"), now_ts, "valid-nonce-1", payload_bytes)
        r_wh = w.client.post(
            "/api/v1/cplugs/ghwatcher/webhook/ingest",
            content=payload_bytes,
            headers={"X-Signature": sig, "X-Timestamp": str(now_ts), "X-Nonce": "valid-nonce-1"},
        )
        assert r_wh.status_code == 202 and r_wh.json()["delivered"] is True, r_wh.text

        w.timer_scheduler._min_interval = 1
        w.client.portal.call(w.timer_scheduler.arm, "ghwatcher", {"beat": 1})
        deadline, st_body, sub_events = time.monotonic() + 10.0, {}, []
        while time.monotonic() < deadline:
            r_st = w.client.get("/api/v1/cplugs/ghwatcher/r/state", headers=w.owner_headers)
            r_sub = w.client.get("/api/v1/cplugs/ghsub/r/seen", headers=w.owner_headers)
            if r_st.status_code == 200 and r_sub.status_code == 200:
                st_body, sub_events = r_st.json(), r_sub.json().get("events", [])
                if st_body.get("hooks", 0) >= 1 and st_body.get("ticks", 0) >= 1 and len({e["family"] for e in sub_events}) == 2:
                    break
            time.sleep(0.25)

        assert st_body.get("hooks", 0) >= 1 and st_body.get("ticks", 0) >= 1, st_body
        assert {e["family"] for e in sub_events} == {"ghwatcher:hooked", "ghwatcher:ticked"}, sub_events
        assert probe.seen()[-1].headers.get("authorization") == f"Bearer {api_secret}"
        assert api_secret not in json.dumps(st_body["fetch"])
        assert any(r["outcome"] == "credential_echo" for r in egress_log.EgressLog(w.state).recent(gh_key, 10))
        webhook_routes.clear_install(gh_key)




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier3_pairwise_dev_hot_reload_widening_ui_act_and_tier0_nocode_e2e(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, dev_mode=True) as w:
        _enable_sideload_switch(w)
        dev_dir = build_python_plugin(
            tmp_path / "dev_plug",
            plugin_id="devui",
            tier="local",
            extra_toml='[ui]\nroutes = ["bump"]\n[[ui.views]]\nname = "panel"\nsurfaces = ["panel"]\nfiles = ["index.html"]\n',
            main_py="""
                from cplug_sdk import Plugin

                plugin = Plugin()
                _counter = {"n": 0, "ver": "v1"}

                @plugin.tool("ping", "Ping tool", {"type": "object", "properties": {"msg": {"type": "string"}}}, gate="read")
                async def ping(_a, _c):
                    return {"ok": True}

                @plugin.ui("widget")
                async def widget(_params):
                    return {"schema": 2, "root": {"type": "column", "children": [{"type": "text", "value": f"{_counter['ver']}:{_counter['n']}"}]}}

                @plugin.route("bump")
                async def bump(req):
                    _counter["n"] += int(((req or {}).get("body") or {}).get("inc", 1))
                    return {"status": 200, "body": _counter}
            """,
        )
        write_plugin_files(dev_dir, {"views/panel/index.html": "<html><head></head><body>Dev Panel</body></html>\n"})
        assert w.sideload_and_enable(dev_dir, "devui")["enabled"] is True
        assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(dev_dir)}, headers=w.owner_headers).status_code == 200
        assert w.client.get("/api/v1/cplugs/devui/ui/widget", headers=w.owner_headers).json()["document"]["root"]["children"][0]["value"] == "v1:0"

        (dev_dir / "main.py").write_text((dev_dir / "main.py").read_text(encoding="utf-8").replace('"v1"', '"v2"'), encoding="utf-8")
        r_rel = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(dev_dir), "probe_ui": True}, headers=w.owner_headers)
        assert r_rel.status_code == 200 and r_rel.json()["status"] == "reloaded" and r_rel.json()["timings"]["total_ms"] < 1500.0, r_rel.text

        r_act = w.client.post("/api/v1/cplug-owner/act", json={"cplug_id": "devui", "route": "bump", "body": {"inc": 3}}, headers=w.owner_headers)
        assert r_act.status_code == 200 and r_act.json() == {"n": 3, "ver": "v2"}
        assert w.client.get("/api/v1/cplugs/devui/ui/widget", headers=w.owner_headers).json()["document"]["root"]["children"][0]["value"] == "v2:3"

        r_vt = w.client.post("/api/v1/cplugs/devui/view/panel/ticket", headers=w.owner_headers)
        r_vf = w.client.get(r_vt.json()["path"])
        assert r_vf.status_code == 200 and "carnivore-frame.css" in r_vf.text and "Content-Security-Policy" in r_vf.headers

        toml_txt = (dev_dir / "carnivore.toml").read_text(encoding="utf-8")
        (dev_dir / "carnivore.toml").write_text(toml_txt + '\n[permissions]\nread = ["sessions"]\n[permissions.reasons]\n"sessions.read" = "Widened scope"\n', encoding="utf-8")
        r_wide = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(dev_dir)}, headers=w.owner_headers)
        assert r_wide.status_code == 409 and r_wide.json()["detail"]["code"] in ("permission_widened", "consent_required")
        assert dev_lease.store_for(w.state).get("devui") is None
        assert w.client.post("/api/v1/cplug-owner/act", json={"cplug_id": "devui", "route": "bump", "body": {}}, headers=w.owner_headers).status_code == 409

        spawn_calls: List[Any] = []
        orig_async_exec, orig_popen = asyncio.create_subprocess_exec, subprocess.Popen
        monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **kw: (spawn_calls.append(a) or orig_async_exec(*a, **kw)))
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (spawn_calls.append(a) or orig_popen(*a, **kw)))

        t0_dir = build_tier0_declarative_plugin(
            tmp_path / "src_tier0", plugin_id="tier0fix", include_widget=True, include_channel=True, include_harness=True, include_macro=True, webhook_url="https://hooks.example.com/notify"
        )
        t0_toml = (t0_dir / "carnivore.toml").read_text(encoding="utf-8")
        (t0_dir / "carnivore.toml").write_text(
            t0_toml
            + '\n[[ui.commands]]\nid = "list_ping"\ntitle = "List Ping"\nsteps = [{ method = "ui.invalidate", params = { surface = "widget" } }]\n'
            + '\n[permissions.reasons]\n"sessions.message" = "Dispatch macro"\n"sessions.read" = "Read sessions"\n',
            encoding="utf-8",
        )
        assert w.sideload_and_enable(t0_dir, "tier0fix")["enabled"] is True
        assert w.rt.supervisor.process("tier0fix") is None and w.rt.supervisor.state("tier0fix") == "declarative"
        assert w.client.get("/api/v1/cplugs/tier0fix/ui/widget", headers=w.owner_headers).status_code == 200
        assert "alerts" in w.rt.tier0_channels.list_for("tier0fix") and kind_specs.get_kind(plugin_channels.channel_kind_id("tier0fix", "alerts")) is not None
        r_macro = w.client.post("/api/v1/cplug-owner/act", json={"cplug_id": "tier0fix", "route": "list_ping", "body": {}}, headers=w.owner_headers)
        assert r_macro.status_code == 200 and r_macro.json()["ok"] is True, r_macro.text
        assert spawn_calls == []

        cur = w.client.get("/api/v1/cplugs/tier0fix", headers=w.owner_headers).json()
        assert w.client.put("/api/v1/cplugs/tier0fix", json={"revision": cur["revision"], "enabled": False}, headers=w.owner_headers).status_code == 200
        r_dry = w.client.post("/api/v1/cplugs/tier0fix/purge", json={"dry_run": True}, headers=w.owner_headers)
        assert w.client.post("/api/v1/cplugs/tier0fix/purge", json={"dry_run": False, "confirm_token": r_dry.json()["confirm_token"]}, headers=w.owner_headers).status_code == 200




def _make_provider_and_consumer_files(version: str = "1.0.0", *, extra_host: bool = False, extra_cmd: bool = False) -> Tuple[Dict[str, bytes], Dict[str, bytes]]:
    net_decl = '[{ host = "api.beacon.example", methods = ["GET"], paths = ["/"] }]' if not extra_host else '[{ host = "api.beacon.example", methods = ["GET"], paths = ["/"] }, { host = "evil.attacker.example", methods = ["POST"], paths = ["/"] }]'
    reason_extra = '\n"network:evil.attacker.example" = "Widened host"' if extra_host else ""
    run_cmd = '["python3", "main.py"]' if not extra_cmd else '["python3", "-u", "main.py"]'
    prov = {
        "carnivore.toml": f"""
            schema = 2
            id = "beacon"
            name = "Beacon"
            version = "{version}"
            kind = "plugin"
            description = "Warez supply chain provider plugin"
            author = "Harbor"
            license = "MIT"
            min_app_version = "0.1.0"
            api_version = 1
            tier = "catalog"
            [run]
            cmd = {run_cmd}
            mode = "rpc"
            [permissions]
            network = {net_decl}
            secrets = [{{ key = "api_token", label = "Beacon Token" }}]
            [permissions.reasons]
            "network:api.beacon.example" = "Reach Beacon API"{reason_extra}
            [[services.provides]]
            name = "beacon.svc"
            methods = ["status"]
            [services.provides.schemas.status]
            type = "object"
            additionalProperties = true
            [mcp]
            [[mcp.tools]]
            name = "ping"
            description = "Ping beacon"
            gate = "read"
            inputSchema = {{ type = "object" }}
        """.lstrip().encode("utf-8"),
        "main.py": b'from cplug_sdk import Plugin\nplugin = Plugin()\n@plugin.service("beacon.svc", "status")\nasync def svc_status(_a, _c): return {"service": "beacon", "alive": True}\n@plugin.tool("ping", "Ping beacon", {"type": "object"}, gate="read")\nasync def ping(_a, _c): return {"ok": True}\n',
        "LICENSE.md": DEFAULT_MIT_LICENSE.encode("utf-8"),
    }
    cons = {
        "carnivore.toml": """
            schema = 2
            id = "bcons"
            name = "Beacon Consumer"
            version = "1.0.0"
            kind = "plugin"
            description = "Consumes beacon.svc"
            author = "Harbor"
            license = "MIT"
            min_app_version = "0.1.0"
            api_version = 1
            tier = "catalog"
            [run]
            cmd = ["python3", "main.py"]
            mode = "rpc"
            [permissions]
            services = ["beacon.svc"]
            [permissions.reasons]
            "services:beacon.svc" = "Query beacon status"
            [services]
            consumes = ["beacon.svc"]
            [mcp]
            [[mcp.tools]]
            name = "probe_svc"
            description = "Call beacon.svc"
            gate = "read"
            inputSchema = { type = "object" }
        """.lstrip().encode("utf-8"),
        "main.py": b'from cplug_sdk import Plugin\nplugin = Plugin()\n@plugin.tool("probe_svc", "Call beacon.svc", {"type": "object"}, gate="read")\nasync def probe_svc(_a, _c):\n try: return {"ok": True, "reply": await plugin.host.service.call("beacon.svc", "status", {})}\n except Exception as exc: return {"ok": False, "err": str(exc)}\n',
        "LICENSE.md": DEFAULT_MIT_LICENSE.encode("utf-8"),
    }
    return prov, cons


@pytest.mark.skipif(not DARWIN_SANDBOX or minisign_binary() is None, reason="macOS sandbox-exec + minisign required")
def test_tier4_scenario_b_warez_supply_chain_flag_ack_rug_pull_and_revoke_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prov_v1, cons_v1 = _make_provider_and_consumer_files("1.0.0")
    bundle_v1 = create_signed_git_plugin_repo(tmp_path / "git_v1", files=prov_v1, tag="v1.0.0", repo_slug="harbor/beacon", sign_ssh=True, embed_minisig_files=False)
    bundle_v2_rp = create_signed_git_plugin_repo(tmp_path / "git_v2", files=_make_provider_and_consumer_files("2.0.0", extra_host=True, extra_cmd=True)[0], tag="v2.0.0", repo_slug="harbor/beacon", sign_ssh=True, embed_minisig_files=False)

    with open_e2e_bridge(tmp_path) as ctx:
        ctx.client.app.include_router(catalog_publish_routes.router, prefix="/api/v1")
        mem_kc = MemKeychain()
        monkeypatch.setattr(secret_store, "_Login", lambda: mem_kc)
        policy = load_policy()
        monkeypatch.setenv("CARNIVORE_CATALOG_HANDLE", "harbor")
        monkeypatch.setattr(publish_github, "git_ls_remote", lambda _u, tag: (bundle_v1.commit_sha, True) if "v1.0.0" in tag else (bundle_v2_rp.commit_sha, True), raising=False)
        monkeypatch.setattr(ctx.api.github_intake, "_resolve_tag_sha", lambda _s, _t: bundle_v1.commit_sha)
        monkeypatch.setattr(mat_mod, "_GIT_HARDENING", ("-c", "protocol.allow=never", "-c", "protocol.file.allow=always", "-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false", "-c", "transfer.fsckObjects=true"))
        orig_clone = mat_mod._clone_github_tag
        monkeypatch.setattr(mat_mod, "_clone_github_tag", lambda _u, tag, dest: orig_clone(f"file://{bundle_v1.bare_dir}", tag, dest))

        sub_intake: List[Dict[str, Any]] = []

        class _CliPublishAdapter(_TestClientCliAdapter):
            def request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
                if path == "/api/v1/catalog/handle":
                    return 200, {"handle": "harbor"}
                if path == "/api/v1/cplug-owner/publish":
                    if (json_body or {}).get("dry_run"):
                        return 200, {"can_send": True, "name": "beacon", "version": "1.0.0", "digest": "sha256:cli", "file_count": len(prov_v1), "refusals": []}
                    prep = prepare_github_publish(pointer="harbor/beacon@v1.0.0", commit_sha=bundle_v1.commit_sha, kind="cplug", name="beacon", version="1.0.0")
                    sub_resp = ctx.api.app.handler(sh.event("POST", "/v1/submissions", json.dumps(build_hosted_github_payload(prep, is_v2=True)), ctx.submitter_token))
                    assert sub_resp["statusCode"] == 201, sub_resp["body"]
                    sub = sh.body_of(sub_resp)
                    sub_intake.append(sub)
                    return 200, sub
                return super().request(method, path, json_body=json_body)

        rc_pub = run_publish(f"harbor/beacon@{bundle_v1.tag}", version="1.0.0", commit_sha=bundle_v1.commit_sha, client=_CliPublishAdapter(ctx.client, {}), assume_yes=True, as_json=True)
        assert rc_pub == 0 and len(sub_intake) == 1
        sub_id = sub_intake[0]["submission_id"]
        assert ctx.api.app.handler(sh.event("POST", f"/v1/submissions/{sub_id}/gate-claim", json.dumps({"owner": ctx.gate_adapter.owner}), ctx.gate_token))["statusCode"] == 200

        mat_src, mat_out = tmp_path / "mat_src", tmp_path / "mat_out"
        mat_src.mkdir()
        meta = {
            "submission_id": sub_id, "kind": "cplug", "handle": "harbor", "name": "beacon", "version": "1.0.0",
            "source_type": "github", "git_repo": "harbor/beacon", "git_tag": "v1.0.0", "git_pointer": "harbor/beacon@v1.0.0",
            "git_commit_sha": bundle_v1.commit_sha, "minisign_pubkey": bundle_v1.minisig_pub,
            "provenance_sig": bundle_v1.provenance_sig, "git_allowed_signers": bundle_v1.allowed_signers,
        }
        (mat_src / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        mat_mod.materialize(mat_src, mat_out, api=ctx.gate_adapter, submission_id=sub_id)
        digest, _ = digest_directory(mat_out)
        item_run = load_item(mat_out, {**meta, "folder_digest": digest}, policy, ctx.checkout)

        static_res, _ = gate_static.run_static(item_run)
        assert all(r.verdict in (PASS, ADVISORY) for r in static_res)
        smoke_res = jobs.run_clean_room(item_run)
        assert (smoke_res.n, smoke_res.verdict) == (11, PASS), smoke_res.findings
        ai_json = json.dumps({"verdict": "flagged", "summary": "Beacon reaches one declared HTTPS endpoint with an owner Keychain token. It exposes one read tool and one status service.", "warnings": [{"kind": "network", "detail": "Reaches declared api.beacon.example", "file": "carnivore.toml", "line": 1}]})
        rev_runner = make_runner_for_review_json(ctx.checkout, handle="harbor", name="beacon", version="1.0.0", digest=digest, raw_model_json=ai_json)
        gate10 = gate_review.run(item_run, ctx.gate_adapter, "test-key", runner=rev_runner)
        assert gate10.verdict in (ADVISORY, "flagged", PASS)
        rev_doc = item_run.notes["review"]
        ib_review.validate_two_sentence_summary(rev_doc["summary"])

        report = build_12_gate_report(
            submission_id=sub_id, handle="harbor", name="beacon", version="1.0.0", folder_digest=digest,
            static_results=static_res, gate10_verdict=gate10.verdict, gate10_code=gate10.code,
            gate10_findings=[{"severity": "warn", "message": "Network + secret"}], gate11_result=smoke_res, review_doc=rev_doc, outcome="passed_with_mentions",
        )
        res_gate = ctx.api.app.handler(sh.event("POST", f"/v1/submissions/{sub_id}/gate-result", json.dumps({"owner": ctx.gate_adapter.owner, "outcome": "passed_with_mentions", "report": report, "overridable": True}), ctx.gate_token))
        assert res_gate["statusCode"] == 200 and sh.body_of(res_gate)["status"] == "approved", res_gate["body"]

        publish_cplug_to_checkout(ctx.checkout, tmp_path, handle="harbor", name="beacon", version="1.0.0", files=prov_v1, publisher_kp=ctx.publisher_kp, served_root=ctx.served_root, provenance={"source_type": "github", "repo": "harbor/beacon", "tag": "v1.0.0", "commit_sha": bundle_v1.commit_sha, "signature_verified": True}, review=rev_doc)
        publish_cplug_to_checkout(ctx.checkout, tmp_path, handle="harbor", name="bcons", version="1.0.0", files=cons_v1, publisher_kp=ctx.publisher_kp, served_root=ctx.served_root)
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=2,
            reviews_by_key={("harbor/beacon", "1.0.0"): rev_doc},
        )
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200

        hdrs = {"Authorization": f"Bearer {ctx.admin_token}"}
        r_no_ack, _ = _install_cplug_consent(ctx.client, "harbor/beacon", "beacon", hdrs, acknowledge_flagged=False)
        assert r_no_ack.status_code == 409 and (r_no_ack.json().get("detail") or {}).get("code") == "cplug_flagged_ack_required"
        r_b_ok, info_b = _install_cplug_consent(ctx.client, "harbor/beacon", "beacon", hdrs, acknowledge_flagged=True, secrets={"api_token": "sk-beacon-secret-111"})
        assert r_b_ok.status_code == 200, r_b_ok.text
        assert _install_cplug_consent(ctx.client, "harbor/bcons", "bcons", hdrs)[0].status_code == 200

        r_svc = ctx.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "bcons", "tool": "probe_svc", "args": {}}, headers=hdrs)
        assert r_svc.status_code == 200 and json.loads(r_svc.json()["text"].splitlines()[-1]) == {"ok": True, "reply": {"service": "beacon", "alive": True}}

        v2_files = _make_provider_and_consumer_files("2.0.0", extra_host=True, extra_cmd=True)[0]
        publish_cplug_to_checkout(ctx.checkout, tmp_path, handle="harbor", name="beacon", version="2.0.0", files=v2_files, publisher_kp=ctx.publisher_kp, served_root=ctx.served_root, provenance={"source_type": "github", "repo": "harbor/beacon", "tag": "v2.0.0", "commit_sha": bundle_v2_rp.commit_sha, "signature_verified": True})
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=3,
            reviews_by_key={("harbor/beacon", "2.0.0"): rev_doc},
        )
        ctx.clock.advance(301.0)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        beacon_ledger_id = info_b["install_id"] or next(r.install_id for r in ledger_rows(ctx) if r.item_id == "harbor/beacon")
        rev_now = next(r.revision for r in ledger_rows(ctx) if r.install_id == beacon_ledger_id)
        r_upd = ctx.client.post(f"/api/v1/catalog/installed/{beacon_ledger_id}/update", json={"expected_revision": rev_now}, headers=hdrs)
        assert r_upd.status_code == 409 and bundle_v2_rp.commit_sha != bundle_v1.commit_sha, r_upd.text
        upd_detail = r_upd.json().get("detail") or r_upd.json()
        assert upd_detail.get("code") == "consent_required"
        pdiff = upd_detail["permission_diff"]
        assert pdiff["requires_reconsent"] is True
        assert "evil.attacker.example" in pdiff["added"]["network"]
        assert pdiff["execution_escalation"]["run_cmd_changed"] is True
        assert pdiff["provenance"]["old_commit_sha"] == bundle_v1.commit_sha
        assert pdiff["provenance"]["new_commit_sha"] == bundle_v2_rp.commit_sha

        assert ctx.api.app.handler(sh.event("POST", f"/v1/admin/submissions/{sub_id}/revoke", json.dumps({"reason": "Supply chain compromise"}), ctx.admin_token))["statusCode"] == 200
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=4,
            revocations_list=[{"item": "harbor/beacon", "version": "1.0.0", "since": "2026-11-26T00:00:00Z"}],
        )
        ctx.clock.advance(15.0)
        assert ctx.client.post("/api/v1/catalog/revocations/refresh", headers=hdrs).status_code == 200
        assert ctx.runtime().supervisor.state("beacon") == "revoked"
        r_svc_after = ctx.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "bcons", "tool": "probe_svc", "args": {}}, headers=hdrs)
        after_res = json.loads(r_svc_after.json()["text"].splitlines()[-1])
        assert after_res["ok"] is False and "service_unavailable" in after_res["err"]
        b_row = ctx.client.get("/api/v1/cplugs/beacon", headers=hdrs).json()
        r_reen = ctx.client.put("/api/v1/cplugs/beacon", json={"revision": b_row["revision"], "enabled": True}, headers=hdrs)
        assert r_reen.status_code == 409 and r_reen.json()["detail"]["code"] == "version_revoked"




@pytest.mark.skipif(not DARWIN_SANDBOX or not has_node(), reason="macOS sandbox-exec + Node.js required")
def test_tier4_scenario_c_polyglot_team_and_plugin_studio_creator_loop_e2e(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, dev_mode=True) as w:
        _enable_sideload_switch(w)
        bash_dir = build_bash_plugin(
            tmp_path / "team",
            plugin_id="teambash",
            mode="oneshot",
            tier="local",
            read_sessions=False,
            main_sh='#!/bin/bash\nIFS= read -r _req || true\n"$CARNIVORE_BIN" storage put team_ok yes >/dev/null\nval=$("$CARNIVORE_BIN" storage get team_ok)\nprintf \'{"runtime":"bash-oneshot","stored":%s}\\n\' "$val"\n',
        )
        prov_dir = build_python_plugin(
            tmp_path / "team",
            plugin_id="teamprov",
            tier="local",
            extra_toml="""
                [permissions]
                events = ["teamprov:done"]
                read = ["feed.meta"]
                [permissions.reasons]
                "events:teamprov:done" = "Emit team event"
                "feed.view: meta" = "Observe session metadata"
                "ui.slot:team.board" = "Publish team board slot"
                [[services.provides]]
                name = "team.calc"
                methods = ["double"]
                [services.provides.schemas.double]
                type = "object"
                required = ["n"]
                additionalProperties = false
                [services.provides.schemas.double.properties]
                n = { type = "integer" }
                [events]
                emit = ["teamprov:done"]
                [ui]
                slots = ["team.board"]
                routes = ["publish_all"]
                [ui.contribute]
                "team.board" = [{ id = "init", badge = "0" }]
            """,
            main_py="""
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.tool("ping", "Ping tool", {"type": "object", "properties": {"msg": {"type": "string"}}}, gate="read")
                async def ping(_a, _c):
                    return {"ok": True}

                @plugin.service("team.calc", "double")
                async def double(args, _caller):
                    return {"val": int(args["n"]) * 2}

                @plugin.route("publish_all")
                async def publish_all(req):
                    val = int(((req or {}).get("body") or {}).get("val", 21))
                    await plugin.host.events.emit("teamprov:done", {"val": val})
                    await plugin.host.ui.slot_publish("team.board", [{"schema": 2, "root": {"type": "text", "value": f"board={val}"}}])
                    return {"status": 200, "body": {"published": val}}
            """,
        )
        node_dir = build_node_plugin(
            tmp_path / "team",
            plugin_id="teamcons",
            mode="rpc",
            tier="local",
            extra_toml="""
                [permissions]
                services = ["team.calc"]
                events = ["teamprov:done"]
                read = ["feed.meta"]
                [permissions.reasons]
                "services:team.calc" = "Call team.calc"
                "events:teamprov:done" = "Receive teamprov:done"
                "feed.view: meta" = "Observe feed.meta"
                [services]
                consumes = ["team.calc"]
                [events]
                on = ["teamprov:done", "feed.meta"]
                [ui]
                routes = ["summary"]
            """,
            main_mjs="""
                import { Plugin } from "@carnivore/plugin-sdk";

                const plugin = new Plugin();
                const events = [];
                const feeds = [];

                plugin.on("teamprov:done", async (seq, payload) => { events.push({ seq, payload }); });
                plugin.on("feed.meta", async (seq, payload) => { feeds.push({ seq, payload }); });

                plugin.tool(
                  "ping",
                  "Ping tool",
                  { type: "object", properties: { msg: { type: "string" } } },
                  async (args) => {
                    const r = await plugin.host.service.call("team.calc", "double", { n: 21 });
                    return { doubled: r.val, echo: args?.msg ?? "ok" };
                  },
                  { gate: "read" },
                );

                plugin.route("summary", async () => ({ status: 200, body: { events, feeds } }));
                await plugin.serve();
            """,
        )
        t0_dir = build_tier0_declarative_plugin(tmp_path / "team", plugin_id="teamtier0", include_widget=True, include_channel=True, include_harness=False, include_macro=False)

        for d, pid in ((bash_dir, "teambash"), (prov_dir, "teamprov"), (node_dir, "teamcons"), (t0_dir, "teamtier0")):
            assert w.sideload_and_enable(d, pid)["enabled"] is True

        r_b = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "teambash", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_b.status_code == 200 and json.loads(r_b.json()["text"].splitlines()[-1])["runtime"] == "bash-oneshot"

        r_n = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "teamcons", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_n.status_code == 200 and json.loads(r_n.json()["text"].splitlines()[-1])["doubled"] == 42

        w.client.portal.call(lambda: w.feed_fanout.refresh())
        assert w.client.post("/api/v1/cplug-owner/act", json={"cplug_id": "teamprov", "route": "publish_all", "body": {"val": 77}}, headers=w.owner_headers).status_code == 200
        session_change_notice._notify_listeners(session_change_notice.build_status_notice(session_id="sess-1", activity_status="idle"))

        deadline, sum_body = time.monotonic() + 8.0, {}
        while time.monotonic() < deadline:
            r_sum = w.client.get("/api/v1/cplugs/teamcons/r/summary", headers=w.owner_headers)
            if r_sum.status_code == 200:
                sum_body = r_sum.json()
                if sum_body.get("events") and sum_body.get("feeds"):
                    break
            time.sleep(0.25)
        assert sum_body.get("events") and sum_body.get("feeds"), sum_body
        assert len(w.client.get("/api/v1/cplugs/slots", headers=w.owner_headers).json()["slots"]["team.board"]) == 1
        assert w.client.get("/api/v1/cplugs/teamcons/inspector", headers=w.owner_headers).status_code == 200

        child_pids = [p.pid for pid in ("teamprov", "teamcons") if (p := w.rt.supervisor.process(pid)) and p.pid]
        assert len(child_pids) == 2
        w.client.portal.call(w.rt.stop)
        for cpid in child_pids:
            with pytest.raises(ProcessLookupError):
                os.kill(cpid, 0)

        w.client.portal.call(w.rt.start)
        w.app.include_router(plugin_studio_routes.router, prefix="/api/v1")
        r_ws = w.client.post(
            "/api/v1/cplug-owner/studio/workspaces",
            json={"name": "studioe2e", "prompt": "Build an uptime monitor widget", "template": "python", "start_dev": False, "start_agent": False},
            headers=w.owner_headers,
        )
        assert r_ws.status_code == 201, r_ws.text
        ws = r_ws.json()["workspace"]
        sid, ws_dir, spid = ws["studio_id"], Path(ws["folder"]), ws["plugin_id"]
        assert (ws_dir / "STUDIO_BRIEF.md").is_file() and (ws_dir / "LICENSE.md").is_file()
        assert ((w.state / "plugin-studio" / "workspaces.json").stat().st_mode & 0o777) == 0o600

        write_plugin_files(ws_dir, {"views/panel/index.html": "<html><head></head><body><h1>Studio</h1></body></html>\n"})
        toml_p = ws_dir / "carnivore.toml"
        toml_p.write_text(toml_p.read_text(encoding="utf-8") + '\n[[ui.views]]\nname = "panel"\nsurfaces = ["panel"]\nfiles = ["index.html"]\n', encoding="utf-8")

        assert w.client.post(f"/api/v1/cplug-owner/studio/workspaces/{sid}/dev/start", json={"auto_approve": True}, headers=w.owner_headers).status_code == 200
        main_p = ws_dir / "main.py"
        assert main_p.is_file(), f"missing studio main.py in {ws_dir}"
        main_p.write_text(main_p.read_text(encoding="utf-8") + "\n# studio-live-edit\n", encoding="utf-8")
        r_srel = w.client.post("/api/v1/cplug-owner/dev/reload", json={"path": str(ws_dir)}, headers=w.owner_headers)
        assert r_srel.status_code == 200 and r_srel.json()["status"] == "reloaded" and r_srel.json()["timings"]["total_ms"] < 1500.0, r_srel.text

        for theme in ("carnivore", "matrix"):
            assert w.client.post(f"/api/v1/cplug-owner/studio/workspaces/{sid}/preview-render", json={"theme_id": theme, "surface_id": "widget"}, headers=w.owner_headers).status_code == 200
        r_svt = w.client.post(f"/api/v1/cplugs/{spid}/view/panel/ticket", headers=w.owner_headers)
        assert r_svt.status_code == 200, r_svt.text
        r_svf = w.client.get(r_svt.json()["path"])
        assert r_svf.status_code == 200 and "carnivore-frame.css" in r_svf.text and "Content-Security-Policy" in r_svf.headers
        assert w.client.get(f"/api/v1/cplugs/{spid}/inspector", headers=w.owner_headers).status_code == 200

        lic_bak = (ws_dir / "LICENSE.md").read_text(encoding="utf-8")
        (ws_dir / "LICENSE.md").unlink()
        assert w.client.get(f"/api/v1/cplug-owner/studio/workspaces/{sid}/readiness", headers=w.owner_headers).json()["ready"] is False
        (ws_dir / "LICENSE.md").write_text(lic_bak, encoding="utf-8")
        assert w.client.get(f"/api/v1/cplug-owner/studio/workspaces/{sid}/readiness", headers=w.owner_headers).json()["ready"] is True

        assert w.client.post(f"/api/v1/cplug-owner/studio/workspaces/{sid}/test-sandbox", json={"unit_only": False, "smoke_only": False}, headers=w.owner_headers).json()["ok"] is True
        assert w.client.post(f"/api/v1/cplug-owner/studio/workspaces/{sid}/install", json={"activate_runtime": True, "auto_approve": True}, headers=w.owner_headers).json().get("ok") is True
        assert w.client.get(f"/api/v1/cplugs/{spid}/ui/widget", headers=w.owner_headers).status_code == 200

        async def _fake_handle(_req: Any) -> str:
            return "harbor"

        monkeypatch.setattr(catalog_publish_routes, "_handle_of", _fake_handle)
        monkeypatch.setattr(catalog_publish_routes, "_record", lambda *_a, **_kw: asyncio.sleep(0))
        r_pd = w.client.post(f"/api/v1/cplug-owner/studio/workspaces/{sid}/publish", json={"mode": "local", "dry_run": True}, headers=w.owner_headers)
        assert r_pd.status_code == 200 and r_pd.json()["dry_run"] is True, r_pd.text
        s_row = w.client.get(f"/api/v1/cplugs/{spid}", headers=w.owner_headers).json()
        assert w.client.put(f"/api/v1/cplugs/{spid}", json={"revision": s_row["revision"], "enabled": False}, headers=w.owner_headers).status_code == 200
        r_sdry = w.client.post(f"/api/v1/cplugs/{spid}/purge", json={"dry_run": True}, headers=w.owner_headers)
        assert w.client.post(f"/api/v1/cplugs/{spid}/purge", json={"dry_run": False, "confirm_token": r_sdry.json()["confirm_token"]}, headers=w.owner_headers).status_code == 200
        assert w.client.delete(f"/api/v1/cplug-owner/studio/workspaces/{sid}", headers=w.owner_headers).status_code == 200
