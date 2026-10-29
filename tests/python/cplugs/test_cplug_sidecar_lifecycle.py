
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import httpx
import pytest
from fastapi import FastAPI

from src.api.auth import require_auth
from src.cplugs.host import activity_log, egress_log, identity, owner_switch, routes as host_routes, runtime, secret_store, sidecar_boot, sidecar_registry
from src.cplugs.host import state as owner_state
from src.cplugs.runtime import sandbox

try:
    sandbox.find_interpreter()
    AVAILABLE = os.path.exists("/usr/bin/sandbox-exec") and sys.platform == "darwin"
except sandbox.SandboxUnavailable:
    AVAILABLE = False
if os.environ.get("CARNIVORE_REQUIRE_SANDBOX") == "1" and not AVAILABLE:
    raise RuntimeError("CARNIVORE_REQUIRE_SANDBOX=1 but this machine cannot run the sandbox (needs macOS sandbox-exec and a framework Python)")
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="needs macOS sandbox-exec and the framework Python")

NAME, ITEM = "clock", "acme/clock"
TOOL = {"name": "clock_now", "description": "The time.", "gate": "read", "inputSchema": {"type": "object"}}
CPLUG = {"schema": 1, "id": NAME, "name": "Clock", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
         "permissions": {"app": ["notify", "network_hosts:api.example.com"]}, "tools": [TOOL],
         "network_hosts": [{"host": "api.example.com", "reason": "time source", "methods": ["GET"],
                            "auth": {"secret": "token", "header": "Authorization", "scheme": "Bearer"}}],
         "secrets": [{"name": "token", "label": "API token", "help": "From the provider."}]}
SIDE = {"kind": "cplug", "id": ITEM, "name": "Clock", "version": "1.0.0", "api_version": 1, "min_app_version": "1.12.20", "author": "acme",
        "license": "MIT", "tier": "catalog", "scope": ["global"], "icon": "plug", "default_enabled": False,
        "permissions": [{"name": "notify", "reason": "tells you when the time is up"}], "owns": {}, "data": []}
PLUGIN = (
    "from cplug_sdk import Plugin\n\nplugin = Plugin()\n\n\n"
    "@plugin.tool('clock_now', 'The time.', {'type': 'object'}, gate='read')\n"
    "async def clock_now(arguments, caller):\n    return 'tick'\n")
KEYCHAIN: Dict[Any, str] = {}


class FakeKeychain:

    def read(self, service, account):
        return KEYCHAIN.get((service, account))

    def write(self, service, account, secret):
        KEYCHAIN[(service, account)] = secret

    def delete(self, service, account):
        return KEYCHAIN.pop((service, account), None) is not None


def alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def children(state: Path) -> Dict[str, Any]:
    try:
        return json.loads((state / "cplugs" / "children.json").read_text())["children"]
    except FileNotFoundError:
        return {}


def lay_code(state: Path) -> None:
    root = state / "cplug-code" / NAME
    root.mkdir(parents=True)
    (root / "cplug.json").write_text(json.dumps(CPLUG))
    (root / "carnivore.json").write_text(json.dumps(SIDE))
    (root / "main.py").write_text(PLUGIN)


def test_enable_restart_kill_disable_uninstall_purge_leave_no_residue(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store, "_Login", FakeKeychain)
    KEYCHAIN.clear()
    state = tmp_path / "state"
    state.mkdir()
    lay_code(state)
    record = identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    rows = [SimpleNamespace(item_id=ITEM, kind="cplug", source_index_url="https://index.example/v1", publisher_key_id="K")]
    sidecar_registry.install(sidecar_registry.SidecarRegistry(state, lambda: rows))
    sidecar_registry.current().reload()
    owner_switch.write(state, True)

    async def go() -> None:
        app = FastAPI()
        host = runtime.install(app, state)
        published = []
        host.publish = published.append
        resolved = []
        rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False, app_version="9.9.9",
                                         raise_alert=lambda *a, **k: None, resolve_alert=resolved.append)
        app.state.sidecar_runtime = rt
        app.include_router(host_routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        await rt._apply()
        await rt.supervisor.set_index({"expires_at": "2999-01-01T00:00:00Z"})
        base = f"/api/v1/cplugs/{NAME}"
        data = identity.data_dir(state, record.uuid)
        key = record.uuid
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
                row = (await http.get(base)).json()
                assert row["runtime"] == "sidecar" and row["name"] == "Clock" and row["description"] == "Tells the time."
                assert row["publisher"] == "acme" and row["trust"] == "catalog"
                assert row["state"] == "disabled" and row["enabled"] is False and row["tools"] == []
                assert rt.supervisor.process(NAME) is None and not children(state)

                sheet = (await http.get(f"{base}/sheet")).json()
                names = [p["name"] for p in sheet["permissions"]]
                assert names == ["notify", "network_hosts:api.example.com"] and all(p["reason"] for p in sheet["permissions"])
                body = {"revision": row["revision"], "enabled": True, "grants": {"app": names},
                        "consent": {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": sheet["grants_sha"], "ticks": names}}
                on = await http.put(base, json=body)
                assert on.status_code == 200, on.text
                row = on.json()
                assert row["state"] == "active" and row["process"] == "idle" and row["tools"] == ["clock_now"]
                assert rt.supervisor.process(NAME) is None and not children(state)
                first = await rt.supervisor.ensure(NAME)
                assert first is not None and alive(first.pid)
                assert children(state)[NAME]["pid"] == first.pid and children(state)[NAME]["pgid"] == first.pid
                assert "cplugs" in published
                listed = await first.request("tools/list", {})
                assert [t["name"] for t in listed["tools"]] == ["clock_now"]

                secret_store.SecretStore(state).set(key, sidecar_registry.find(NAME).manifest, "token", "abc123")
                egress_log.EgressLog(state).record(key, host="api.example.com", method="GET", permission="network_hosts:api.example.com",
                                                   status=200, bytes_out=1, bytes_in=2, ms=3, outcome="ok")
                assert (data / "files").is_dir() and (data / "profile.sb").is_file()

                restarted = await http.post(f"{base}/restart")
                assert restarted.status_code == 200 and restarted.json()["process"] == "running"
                second = rt.supervisor.process(NAME)
                assert second.pid != first.pid and alive(second.pid) and not alive(first.pid)

                killed = await http.post(f"{base}/kill")
                assert killed.status_code == 200 and not alive(second.pid)
                after = killed.json()
                assert after["enabled"] is True and after["grants"]["app"] == names and after["state"] == "unavailable"
                assert after["detail"] == "killed" and after["tools"] == [] and NAME not in children(state)
                back = await http.post(f"{base}/restart")
                assert back.json()["process"] == "running"
                third = rt.supervisor.process(NAME)
                assert alive(third.pid) and children(state)[NAME]["pid"] == third.pid

                assert (await http.post("/api/v1/cplugs/huddle/kill")).status_code == 409

                refused = await http.post(f"{base}/purge", json={"dry_run": True})
                assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_enabled" and data.is_dir()

                seen = len(published)
                row = (await http.get(base)).json()
                off = await http.put(base, json={"revision": row["revision"], "enabled": False})
                assert off.status_code == 200, off.text
                assert not alive(third.pid) and rt.supervisor.process(NAME) is None and NAME not in children(state)
                gone = off.json()
                assert gone["enabled"] is False and gone["tools"] == [] and gone["state"] == "disabled"
                assert "cplugs" in published[seen:] and f"cplug.{NAME}.crash_loop" in resolved
                assert gone["grants"]["app"] == names and data.is_dir() and owner_state.stored_entry(state, NAME) is not None
                assert activity_log.ActivityLog(state).recent(key, 50)
                assert egress_log.EgressLog(state).recent(key, 50) and KEYCHAIN

                rows.clear()
                sidecar_registry.current().reload()
                listing = (await http.get("/api/v1/cplugs")).json()["cplugs"]
                removed = [r for r in listing if r["id"] == NAME]
                assert len(removed) == 1 and removed[0]["state"] == "removed"
                assert identity.lookup(state, NAME).uuid == key and data.is_dir()

                price = (await http.post(f"{base}/purge", json={"dry_run": True})).json()
                assert price["dry_run"] is True and price["files"] >= 1 and price["bytes"] > 0
                stale = await http.post(f"{base}/purge", json={"dry_run": False, "confirm_token": "x"})
                assert stale.status_code == 409 and stale.json()["detail"]["code"] == "purge_stale" and data.is_dir()
                done = await http.post(f"{base}/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
                assert done.status_code == 200, done.text

            assert not data.exists()
            assert owner_state.stored_entry(state, NAME) is None
            assert not KEYCHAIN
            assert egress_log.EgressLog(state).recent(key, 50) == [] and activity_log.ActivityLog(state).recent(key, 50) == []
            assert identity.lookup(state, NAME) is None
            assert rt.supervisor.state(NAME) == "unknown" and NAME not in rt.supervisor._strikes
            fresh = identity.register_install(state, NAME, "other/clock", {d.id for d in runtime.definitions()})
            assert fresh.uuid != key
        finally:
            await rt.supervisor.shutdown()

    try:
        asyncio.run(asyncio.wait_for(go(), 180))
    finally:
        sidecar_registry.install(None)
