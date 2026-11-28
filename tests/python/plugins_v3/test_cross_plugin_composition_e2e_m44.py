
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
import textwrap
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Tuple

import httpx
import pytest
from fastapi import FastAPI

from src.api.auth import require_auth
from src.core.cli_command import service as cli_service
from src.core.db_migration import ensure_db_migrated
from src.core.resource_push import topics
from src.plugins.host import (
    consent as consent_mod,
    developer_mode,
    owner_switch,
    routes as host_routes,
    runtime as host_runtime,
    sidecar_boot,
    sidecar_registry,
)
from src.plugins.runtime import sandbox

DARWIN_SANDBOX = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _has_node() -> bool:
    try:
        sandbox._find_node()
        return True
    except sandbox.SandboxUnavailable:
        return False


def _write_files(folder: Path, files: Dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return folder


def _provcomp_files() -> Dict[str, str]:
    return {
        "carnivore.toml": """
            schema = 2
            id = "provcomp"
            name = "Provider Comp"
            version = "1.0.0"
            kind = "plugin"
            description = "Cross-plugin math provider, event emitter, and slot owner"
            author = "Tester"

            [run]
            cmd = ["python3", "main.py"]
            mode = "rpc"

            [permissions]
            events = ["provcomp:computed"]

            [permissions.reasons]
            "events:provcomp:computed" = "Emit computation completion events"

            [[services.provides]]
            name = "comp.math"
            methods = ["mul"]

            [services.provides.schemas.mul]
            type = "object"
            required = ["x", "y"]
            additionalProperties = false
            [services.provides.schemas.mul.properties]
            x = { type = "integer" }
            y = { type = "integer" }

            [events]
            emit = ["provcomp:computed"]

            [ui]
            slots = ["provcomp.board"]
            routes = ["cli_emit"]

            [[mcp.tools]]
            name = "provcomp_emit"
            description = "Emit provcomp:computed via stdio host SDK"
            gate = "read"
            inputSchema = { type = "object", properties = { value = { type = "integer" } } }
        """,
        "main.py": """
            import json
            import os
            import subprocess
            from cplug_sdk import Plugin

            plugin = Plugin()

            @plugin.service("comp.math", "mul")
            async def mul(args, _meta):
                return {"product": int(args["x"]) * int(args["y"])}

            @plugin.tool(
                "provcomp_emit",
                "Emit provcomp:computed via stdio host SDK",
                input_schema={"type": "object", "properties": {"value": {"type": "integer"}}},
            )
            async def provcomp_emit(args, _caller):
                return await plugin.host.events.emit(
                    "provcomp:computed",
                    {"value": int(args.get("value", 42)), "via": "stdio"},
                )

            @plugin.route("cli_emit")
            async def cli_emit(req):
                val = int(((req.get("body") or {}) if isinstance(req, dict) else {}).get("value", 99))
                proc = subprocess.run(
                    [
                        os.environ["CARNIVORE_BIN"],
                        "event",
                        "emit",
                        "provcomp:computed",
                        json.dumps({"value": val, "via": "cli"}),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return {
                    "status": 200 if proc.returncode == 0 else 500,
                    "body": {
                        "rc": proc.returncode,
                        "out": json.loads(proc.stdout) if proc.returncode == 0 else None,
                        "err": proc.stderr.strip(),
                    },
                }
        """,
    }


def _conscomp_files() -> Dict[str, str]:
    return {
        "carnivore.toml": """
            schema = 2
            id = "conscomp"
            name = "Consumer Comp"
            version = "1.0.0"
            kind = "plugin"
            description = "Node TS SDK consumer composing provcomp via stdio and $CARNIVORE_BIN"
            author = "Tester"

            [run]
            cmd = ["node", "main.mjs"]
            mode = "rpc"

            [permissions]
            services = ["comp.math"]
            events = ["provcomp:computed", "conscomp:synced"]

            [permissions.reasons]
            "services:comp.math" = "Call comp.math multiplication service"
            "events:provcomp:computed" = "Listen to provcomp computed events"
            "events:conscomp:synced" = "Emit conscomp sync event"
            "ui.slot:provcomp.board" = "Publish cards into provcomp.board"
            "ui.slot:terminal.toolbar" = "Contribute compose shortcut to terminal toolbar"

            [services]
            consumes = ["comp.math"]

            [events]
            on = ["provcomp:computed"]
            emit = ["conscomp:synced"]

            [ui]
            routes = ["compose", "cli_compose", "events", "burst"]

            [[ui.contribute."provcomp.board"]]
            id = "init-board"
            label = "Init Board"
            route = "compose"

            [[ui.contribute."terminal.toolbar"]]
            id = "tb-compose"
            label = "Compose"
            route = "compose"
        """,
        "main.mjs": """
            import { execFileSync } from "node:child_process";
            import { HostError, Plugin } from "@carnivore/plugin-sdk";

            const plugin = new Plugin();
            const seenEvents = [];

            plugin.on("provcomp:computed", async (seq, payload) => {
              seenEvents.push({ seq, payload });
            });

            plugin.route("compose", async (req) => {
              const body = (req && typeof req.body === "object" && req.body) || {};
              const x = Number(body.x ?? 6);
              const y = Number(body.y ?? 7);
              let svcOk = null;
              let svcErr = null;
              try {
                svcOk = await plugin.host.service.call("comp.math", "mul", { x, y });
              } catch (err) {
                svcErr = err instanceof HostError
                  ? { code: err.code, reason: err.reason, data: err.data }
                  : { message: String(err) };
              }
              let invalidErr = null;
              if (body.check_invalid) {
                try {
                  await plugin.host.service.call("comp.math", "mul", { x: "bad", y: 7 });
                } catch (err) {
                  invalidErr = err instanceof HostError
                    ? { code: err.code, reason: err.reason, data: err.data }
                    : { message: String(err) };
                }
              }
              let slotPub = null;
              if (body.publish_slot) {
                slotPub = await plugin.host.ui.slotPublish("provcomp.board", [
                  { id: "stdio-card", label: "Stdio Mul 42", route: "compose" },
                ]);
              }
              return { status: 200, body: { svc_ok: svcOk, svc_err: svcErr, invalid_err: invalidErr, slot_pub: slotPub } };
            });

            plugin.route("cli_compose", async () => {
              const bin = process.env.CARNIVORE_BIN;
              const runCli = (args) => JSON.parse(execFileSync(bin, args, { encoding: "utf8" }).trim());
              const svc = runCli(["service", "call", "comp.math", "mul", "--args", JSON.stringify({ x: 8, y: 9 })]);
              const slot = runCli([
                "ui",
                "slot-publish",
                "provcomp.board",
                "--items",
                JSON.stringify([{ id: "cli-card", label: "CLI Mul 72", route: "cli_compose" }]),
              ]);
              const ev = runCli(["event", "emit", "conscomp:synced", JSON.stringify({ via: "cli", product: svc.product })]);
              return { status: 200, body: { svc, slot, ev } };
            });

            plugin.route("events", async () => ({ status: 200, body: { events: seenEvents } }));

            plugin.route("burst", async () => {
              let rateErr = null;
              let calls = 0;
              for (let i = 0; i < 30; i += 1) {
                try {
                  await plugin.host.service.call("comp.math", "mul", { x: 1, y: i });
                  calls += 1;
                } catch (err) {
                  if (err instanceof HostError) {
                    rateErr = { code: err.code, reason: err.reason, data: err.data };
                    break;
                  }
                  throw err;
                }
              }
              return { status: 200, body: { calls, rate_err: rateErr } };
            });

            await plugin.serve();
        """,
    }


def _unauthcomp_files() -> Dict[str, str]:
    return {
        "carnivore.toml": """
            schema = 2
            id = "unauthcomp"
            name = "Unauthorized Comp"
            version = "1.0.0"
            kind = "plugin"
            description = "Enabled without bus or slot grants to verify denials"
            author = "Tester"

            [run]
            cmd = ["python3", "main.py"]
            mode = "rpc"

            [permissions]
            services = ["comp.math"]
            events = ["provcomp:computed", "unauthcomp:poke"]

            [permissions.reasons]
            "services:comp.math" = "Attempt ungranted service call"
            "events:provcomp:computed" = "Attempt ungranted event listen"
            "events:unauthcomp:poke" = "Attempt ungranted event emit"
            "ui.slot:provcomp.board" = "Attempt ungranted slot publish"

            [services]
            consumes = ["comp.math"]

            [events]
            on = ["provcomp:computed"]
            emit = ["unauthcomp:poke"]

            [ui]
            routes = ["probe_stdio", "probe_cli", "events"]

            [[ui.contribute."provcomp.board"]]
            id = "unauth-card"
            label = "Should Not Appear"
            route = "probe_stdio"
        """,
        "main.py": """
            import json
            import os
            import subprocess
            from cplug_sdk import HostError, Plugin

            plugin = Plugin()
            seen_events = []

            @plugin.on("provcomp:computed")
            async def on_computed(seq, payload):
                seen_events.append({"seq": seq, "payload": payload})

            async def _capture(coro):
                try:
                    await coro
                    return {"allowed": True}
                except HostError as exc:
                    return {"allowed": False, "code": exc.code, "reason": exc.reason, "data": exc.data}

            @plugin.route("probe_stdio")
            async def probe_stdio(_req):
                return {
                    "status": 200,
                    "body": {
                        "service": await _capture(plugin.host.service.call("comp.math", "mul", {"x": 2, "y": 3})),
                        "emit_own": await _capture(plugin.host.events.emit("unauthcomp:poke", {"n": 1})),
                        "emit_foreign": await _capture(plugin.host.events.emit("provcomp:computed", {"n": 1})),
                        "emit_core": await _capture(plugin.host.events.emit("session.started", {"n": 1})),
                        "slot_pub": await _capture(plugin.host.ui.slot_publish("provcomp.board", [{"id": "x", "label": "X"}])),
                    },
                }

            @plugin.route("probe_cli")
            async def probe_cli(_req):
                bin_path = os.environ["CARNIVORE_BIN"]
                cmds = {
                    "service": [bin_path, "service", "call", "comp.math", "mul", "--args", json.dumps({"x": 2, "y": 3})],
                    "event": [bin_path, "event", "emit", "unauthcomp:poke", json.dumps({"n": 1})],
                    "slot": [bin_path, "ui", "slot-publish", "provcomp.board", "--items", json.dumps([{"id": "x", "label": "X"}])],
                }
                out = {}
                for name, argv in cmds.items():
                    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
                    out[name] = {"rc": proc.returncode, "stderr": proc.stderr.strip()}
                return {"status": 200, "body": out}

            @plugin.route("events")
            async def get_events(_req):
                return {"status": 200, "body": {"events": seen_events}}
        """,
    }


@contextlib.asynccontextmanager
async def _real_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Tuple[httpx.AsyncClient, host_runtime.Host, sidecar_boot.SidecarRuntime, List[str]]]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    ensure_db_migrated(state_dir, 4, "0.8.2")
    cli_service.write_shim(state_dir)
    owner_switch.write(state_dir, True)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)

    published: List[str] = []
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    app.include_router(host_routes.router, prefix="/api/v1")

    host = host_runtime.Host(state_dir, app=app, publish=published.append)
    app.state.cplugs_host = host
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False)
    app.state.sidecar_runtime = rt
    await rt.start()
    await rt.supervisor.set_index(None)
    rt.supervisor.set_safe_mode(False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        sw = await client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True})
        assert sw.status_code == 200 and sw.json()["enabled"] is True
        try:
            yield client, host, rt, published
        finally:
            await rt.stop()
            sidecar_registry.install(None)


async def _sideload_and_enable(
    client: httpx.AsyncClient,
    code_dir: Path,
    plugin_id: str,
    rt: sidecar_boot.SidecarRuntime,
    *,
    grant_all: bool = True,
    verify_refusals: bool = False,
) -> Dict[str, Any]:
    sl = await client.post("/api/v1/cplug-owner/sideload", json={"path": str(code_dir)})
    assert sl.status_code == 200, sl.text
    assert sl.json()["id"] == plugin_id
    rt.supervisor.override_index(plugin_id, True)

    row_res = await client.get(f"/api/v1/cplugs/{plugin_id}")
    assert row_res.status_code == 200, row_res.text
    rev = row_res.json()["revision"]

    sheet_res = await client.get(f"/api/v1/cplugs/{plugin_id}/sheet")
    assert sheet_res.status_code == 200, sheet_res.text
    sheet = sheet_res.json()

    perms = [p["name"] for p in sheet["permissions"]] if grant_all else []
    ticks = [p["name"] for p in sheet["permissions"] if p["needs_tick"]] if grant_all else []
    slots = [s["slot"] for s in sheet["ui_slots"]] if grant_all else []
    slot_ticks = [s["slot"] for s in sheet["ui_slots"] if s["needs_tick"]] if grant_all else []

    if verify_refusals:
        no_consent = await client.put(f"/api/v1/cplugs/{plugin_id}", json={"revision": rev, "enabled": True})
        assert no_consent.status_code == 422
        assert no_consent.json()["detail"]["code"] == "consent_required"

        if ticks or slot_ticks:
            no_ticks = await client.put(
                f"/api/v1/cplugs/{plugin_id}",
                json={
                    "revision": rev,
                    "enabled": True,
                    "grants": {"app": perms, "ui_slots": slots},
                    "consent": {
                        "digest": sheet["digest"],
                        "body_sha": sheet["body_sha"],
                        "grants_sha": consent_mod.grants_sha(perms),
                        "ticks": [],
                        "ui_slots_sha": consent_mod.grants_sha(slots),
                        "slot_ticks": [],
                    },
                },
            )
            assert no_ticks.status_code == 422
            assert no_ticks.json()["detail"]["code"] == "tick_missing"

    en = await client.put(
        f"/api/v1/cplugs/{plugin_id}",
        json={
            "revision": rev,
            "enabled": True,
            "grants": {"app": perms, "ui_slots": slots},
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": consent_mod.grants_sha(perms),
                "ticks": ticks,
                "ui_slots_sha": consent_mod.grants_sha(slots),
                "slot_ticks": slot_ticks,
            },
        },
    )
    assert en.status_code == 200, en.text
    return en.json()


@pytest.mark.asyncio
@pytest.mark.skipif(not (DARWIN_SANDBOX and _has_node()), reason="needs macOS sandbox-exec and node")
async def test_cross_plugin_composition_http_consent_py_ts_stdio_and_carnivore_bin_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prov_dir = _write_files(tmp_path / "src_provcomp", _provcomp_files())
    cons_dir = _write_files(tmp_path / "src_conscomp", _conscomp_files())

    async with _real_world(tmp_path, monkeypatch) as (client, _host, rt, published):
        row_a = await _sideload_and_enable(client, prov_dir, "provcomp", rt, grant_all=True, verify_refusals=True)
        row_b = await _sideload_and_enable(client, cons_dir, "conscomp", rt, grant_all=True, verify_refusals=True)
        assert row_a["enabled"] is True and row_b["enabled"] is True
        assert set(row_b["grants"]["ui_slots"]) == {"provcomp.board", "terminal.toolbar"}

        comp = await client.post(
            "/api/v1/cplugs/conscomp/r/compose",
            json={"x": 6, "y": 7, "check_invalid": True, "publish_slot": True},
        )
        assert comp.status_code == 200, comp.text
        cbody = comp.json()
        assert cbody["svc_ok"] == {"product": 42}
        assert cbody["invalid_err"]["reason"] == "invalid_params"
        assert cbody["slot_pub"]["slot"] == "provcomp.board"
        assert cbody["slot_pub"]["items"][0]["id"] == "stdio-card"

        tool_res = await client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "provcomp", "tool": "provcomp_emit", "args": {"value": 42}},
        )
        assert tool_res.status_code == 200, tool_res.text
        assert json.loads(tool_res.json()["result"]["content"][0]["text"]) == {"event": "provcomp:computed", "delivered": 1}

        cli_emit = await client.post("/api/v1/cplugs/provcomp/r/cli_emit", json={"value": 99})
        assert cli_emit.status_code == 200, cli_emit.text
        assert cli_emit.json()["out"] == {"event": "provcomp:computed", "delivered": 1}

        cli_comp = await client.post("/api/v1/cplugs/conscomp/r/cli_compose")
        assert cli_comp.status_code == 200, cli_comp.text
        clibody = cli_comp.json()
        assert clibody["svc"] == {"product": 72}
        assert clibody["slot"]["slot"] == "provcomp.board"
        assert clibody["slot"]["items"][0]["id"] == "cli-card"
        assert clibody["ev"] == {"event": "conscomp:synced", "delivered": 0}

        evs = await client.get("/api/v1/cplugs/conscomp/r/events")
        assert evs.status_code == 200
        seen = [e["payload"] for e in evs.json()["events"]]
        assert seen == [
            {"event": "provcomp:computed", "source": "provcomp", "data": {"value": 42, "via": "stdio"}},
            {"event": "provcomp:computed", "source": "provcomp", "data": {"value": 99, "via": "cli"}},
        ]

        slots_res = await client.get("/api/v1/cplugs/slots")
        assert slots_res.status_code == 200
        sbody = slots_res.json()
        assert sbody["owners"] == {"provcomp.board": "provcomp"}
        assert sbody["slots"]["provcomp.board"][0]["plugin_id"] == "conscomp"
        assert sbody["slots"]["provcomp.board"][0]["item"]["id"] == "cli-card"
        assert sbody["slots"]["terminal.toolbar"][0]["plugin_id"] == "conscomp"
        assert topics.CPLUG_SLOTS in published

        insp = await client.get("/api/v1/cplugs/conscomp/inspector")
        assert insp.status_code == 200
        ibody = insp.json()
        sources = {t["source"] for t in ibody["rpc_trace"]}
        assert {"rpc", "cli_sock"} <= sources
        assert any(t["method"] == "ui.slot.publish" and t["target"] == "provcomp.board" for t in ibody["rpc_trace"])
        perms_checked = {c["permission"] for c in ibody["capability_checks"] if c["allowed"]}
        assert {"services:comp.math", "ui.slot:provcomp.board", "events:conscomp:synced"} <= perms_checked

        act = await client.get("/api/v1/cplugs/conscomp/activity")
        assert act.status_code == 200
        act_methods = {r["method"] for r in act.json()["activity"]}
        assert {"service.call", "ui.slot.publish", "events.emit"} <= act_methods

        burst = await client.post("/api/v1/cplugs/conscomp/r/burst")
        assert burst.status_code == 200
        assert burst.json()["rate_err"]["reason"] == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_cross_plugin_unapproved_permission_denials_across_stdio_and_cli_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prov_dir = _write_files(tmp_path / "src_provcomp", _provcomp_files())
    unauth_dir = _write_files(tmp_path / "src_unauthcomp", _unauthcomp_files())

    async with _real_world(tmp_path, monkeypatch) as (client, _host, rt, _published):
        await _sideload_and_enable(client, prov_dir, "provcomp", rt, grant_all=True)
        row_c = await _sideload_and_enable(client, unauth_dir, "unauthcomp", rt, grant_all=False)
        assert row_c["enabled"] is True
        assert row_c["grants"] == {"app": [], "ui_slots": []}

        stdio_res = await client.post("/api/v1/cplugs/unauthcomp/r/probe_stdio")
        assert stdio_res.status_code == 200, stdio_res.text
        sb = stdio_res.json()
        assert sb["service"]["allowed"] is False and sb["service"]["reason"] == "not_granted"
        assert sb["emit_own"]["allowed"] is False and sb["emit_own"]["reason"] == "not_granted"
        assert sb["emit_foreign"]["allowed"] is False and sb["emit_foreign"]["reason"] == "permission_denied"
        assert sb["emit_core"]["allowed"] is False and sb["emit_core"]["reason"] == "permission_denied"
        assert sb["slot_pub"]["allowed"] is False and sb["slot_pub"]["reason"] == "not_granted"

        cli_res = await client.post("/api/v1/cplugs/unauthcomp/r/probe_cli")
        assert cli_res.status_code == 200, cli_res.text
        cb = cli_res.json()
        for key in ("service", "event", "slot"):
            assert cb[key]["rc"] == 1
            assert "not_granted" in cb[key]["stderr"]

        emit_res = await client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "provcomp", "tool": "provcomp_emit", "args": {"value": 11}},
        )
        assert emit_res.status_code == 200
        assert json.loads(emit_res.json()["result"]["content"][0]["text"])["delivered"] == 0
        evs = await client.get("/api/v1/cplugs/unauthcomp/r/events")
        assert evs.status_code == 200 and evs.json()["events"] == []

        slots_res = await client.get("/api/v1/cplugs/slots")
        assert slots_res.json()["slots"] == {}
        insp = await client.get("/api/v1/cplugs/unauthcomp/inspector")
        assert insp.status_code == 200
        denied = [c for c in insp.json()["capability_checks"] if not c["allowed"]]
        assert {c["permission"] for c in denied} >= {"services:comp.math", "events:unauthcomp:poke", "ui.slot:provcomp.board"}


@pytest.mark.asyncio
@pytest.mark.skipif(not (DARWIN_SANDBOX and _has_node()), reason="needs macOS sandbox-exec and node")
async def test_provider_stop_pause_crash_service_unavailable_and_recovery_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prov_dir = _write_files(tmp_path / "src_provcomp", _provcomp_files())
    cons_dir = _write_files(tmp_path / "src_conscomp", _conscomp_files())

    async with _real_world(tmp_path, monkeypatch) as (client, _host, rt, _published):
        await _sideload_and_enable(client, prov_dir, "provcomp", rt, grant_all=True)
        await _sideload_and_enable(client, cons_dir, "conscomp", rt, grant_all=True)

        base = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert base.status_code == 200 and base.json()["svc_ok"] == {"product": 42}

        killed = await client.post("/api/v1/cplugs/provcomp/kill")
        assert killed.status_code == 200
        after_kill = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert after_kill.json()["svc_err"]["reason"] == "service_unavailable"
        assert after_kill.json()["svc_err"]["data"]["reason"] == "provider_killed"

        restarted = await client.post("/api/v1/cplugs/provcomp/restart")
        assert restarted.status_code == 200
        after_restart = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert after_restart.json()["svc_ok"] == {"product": 42}

        paused = await client.post("/api/v1/cplugs/provcomp/pause")
        assert paused.status_code == 200 and paused.json()["paused"] is True
        after_pause = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert after_pause.json()["svc_err"]["reason"] == "service_unavailable"
        assert after_pause.json()["svc_err"]["data"]["reason"] == "provider_paused"
        slots_paused = await client.get("/api/v1/cplugs/slots")
        assert "provcomp.board" not in slots_paused.json()["owners"]
        assert "provcomp.board" not in slots_paused.json()["slots"]

        resumed = await client.post("/api/v1/cplugs/provcomp/resume")
        assert resumed.status_code == 200 and resumed.json()["paused"] is False
        slots_resumed = await client.get("/api/v1/cplugs/slots")
        assert slots_resumed.json()["owners"] == {"provcomp.board": "provcomp"}
        assert slots_resumed.json()["slots"]["provcomp.board"][0]["plugin_id"] == "conscomp"
        after_resume = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert after_resume.json()["svc_ok"] == {"product": 42}

        proc_a = rt.supervisor.process("provcomp")
        assert proc_a is not None and proc_a.pid is not None
        entered_backoff = asyncio.Event()
        release_backoff = asyncio.Event()
        orig_sleep = rt.supervisor._sleep

        async def gated_sleep(delay: float) -> None:
            if rt.supervisor.state("provcomp") == "backing_off" and not entered_backoff.is_set():
                entered_backoff.set()
                await release_backoff.wait()
            else:
                await orig_sleep(delay)

        rt.supervisor._sleep = gated_sleep
        os.kill(proc_a.pid, signal.SIGKILL)
        await asyncio.wait_for(entered_backoff.wait(), timeout=5.0)
        assert rt.supervisor.state("provcomp") == "backing_off"

        during_backoff = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert during_backoff.json()["svc_err"]["reason"] == "service_unavailable"
        assert during_backoff.json()["svc_err"]["data"]["reason"] == "provider_restarting"

        release_backoff.set()
        for _ in range(100):
            if rt.supervisor.state("provcomp") == "running":
                break
            await asyncio.sleep(0.05)
        assert rt.supervisor.state("provcomp") == "running"

        recovered = await client.post("/api/v1/cplugs/conscomp/r/compose", json={"x": 6, "y": 7})
        assert recovered.json()["svc_ok"] == {"product": 42}
