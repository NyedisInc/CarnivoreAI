
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import httpx
import pytest
from fastapi import FastAPI

from src.api import catalog_cplug_gates
from src.api.auth import require_auth
from src.cplugs.host import identity, owner_switch, routes as host_routes, runtime, sidecar_boot, sidecar_index, sidecar_registry
from src.cplugs.host import state as owner_state
from src.cplugs.runtime import index_expiry, sandbox

try:
    sandbox.find_interpreter()
    AVAILABLE = os.path.exists("/usr/bin/sandbox-exec") and sys.platform == "darwin"
except sandbox.SandboxUnavailable:
    AVAILABLE = False
if os.environ.get("CARNIVORE_REQUIRE_SANDBOX") == "1" and not AVAILABLE:
    raise RuntimeError("CARNIVORE_REQUIRE_SANDBOX=1 but this machine cannot run the sandbox (needs macOS sandbox-exec and a framework Python)")
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="needs macOS sandbox-exec and the framework Python")

NAME, ITEM, KEY_ID = "clock", "acme/clock", "5F522AB084F4E697"
TOOL = {"name": "clock_now", "description": "The time.", "gate": "read", "inputSchema": {"type": "object"}}


def cplug_json(version: str) -> dict:
    return {"schema": 1, "id": NAME, "name": "Clock", "description": "Tells the time.", "version": version, "entry": "main.py",
            "permissions": {"app": ["notify"]}, "tools": [TOOL]}


SIDE = {"kind": "cplug", "id": ITEM, "name": "Clock", "version": "1.0.0", "api_version": 1, "min_app_version": "1.12.20", "author": "acme",
        "license": "MIT", "tier": "catalog", "scope": ["global"], "icon": "plug", "default_enabled": False,
        "permissions": [{"name": "notify", "reason": "tells you when the time is up"}], "owns": {}, "data": []}


def plugin_source(answer: str) -> str:
    return ("from cplug_sdk import Plugin\n\nplugin = Plugin()\n\n\n"
            "@plugin.tool('clock_now', 'The time.', {'type': 'object'}, gate='read')\n"
            f"async def clock_now(arguments, caller):\n    return {answer!r}\n")


def alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lay_code(state: Path, version: str, answer: str) -> None:
    root = state / "cplug-code" / NAME
    root.mkdir(parents=True, exist_ok=True)
    (root / "cplug.json").write_text(json.dumps(cplug_json(version)))
    (root / "carnivore.json").write_text(json.dumps({**SIDE, "version": version}))
    (root / "main.py").write_text(plugin_source(answer))


class FakeClock(datetime):

    current = datetime(2030, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class FakeCache:

    def __init__(self) -> None:
        self.generated_at = FakeClock.current
        self.keys: frozenset = frozenset()
        self.versions: frozenset = frozenset()

    def snapshot(self) -> Any:
        return SimpleNamespace(verified=SimpleNamespace(generated_at=self.generated_at))

    async def get(self) -> Any:
        return self.snapshot()

    def revoked_sets(self, verified: Any) -> tuple:
        return self.keys, self.versions


def test_update_and_revocation_and_freshness_stop_the_process(tmp_path, monkeypatch):
    monkeypatch.setattr(index_expiry, "datetime", FakeClock)
    FakeClock.current = datetime(2030, 1, 1, tzinfo=timezone.utc)
    state = tmp_path / "state"
    state.mkdir()
    lay_code(state, "1.0.0", "tick")
    identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    rows = [SimpleNamespace(item_id=ITEM, kind="cplug", source_index_url="https://index.example/v1", publisher_key_id=KEY_ID)]
    owner_switch.write(state, True)
    alerts: List[str] = []

    async def go() -> None:
        app = FastAPI()
        host = runtime.install(app, state)
        host.publish = lambda *_: None
        rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False, app_version="9.9.9",
                                         raise_alert=lambda key, **_: alerts.append(key), resolve_alert=lambda *_: None)
        rt._ledger_rows = lambda: rows
        cache = FakeCache()
        rt.index = sidecar_index.IndexAdapter(rt, cache)
        app.state.sidecar_runtime = rt
        app.state.services = SimpleNamespace(settings_reader=SimpleNamespace(state_dir=lambda: state))
        rt.load_registry()
        app.include_router(host_routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        await rt._apply()
        request = SimpleNamespace(app=app)
        base = f"/api/v1/cplugs/{NAME}"
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
                async def consent_and_enable() -> dict:
                    row = (await http.get(base)).json()
                    sheet = (await http.get(f"{base}/sheet")).json()
                    names = [p["name"] for p in sheet["permissions"]]
                    body = {"revision": row["revision"], "enabled": True, "grants": {"app": names},
                            "consent": {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": sheet["grants_sha"], "ticks": names}}
                    done = await http.put(base, json=body)
                    assert done.status_code == 200, done.text
                    return done.json()

                assert rt.supervisor._index is None
                row = await consent_and_enable()
                assert row["process"] == "idle" and rt.supervisor._index["expires_at_derived"] is True
                first = await rt.supervisor.ensure(NAME)
                assert first is not None and alive(first.pid)
                FakeClock.current += timedelta(days=15)
                await rt.index.sync()
                assert rt.supervisor.state(NAME) == "running" and alive(first.pid)
                FakeClock.current += timedelta(days=2)
                await rt.index.sync()
                assert rt.supervisor.state(NAME) == "index_expired" and not alive(first.pid) and rt.supervisor.process(NAME) is None
                assert f"cplug.{NAME}.index_expired" in alerts
                cache.generated_at = FakeClock.current
                await rt.index.sync()
                assert (await http.post(f"{base}/restart")).json()["process"] == "running"

                running = rt.supervisor.process(NAME)
                assert running is not None and alive(running.pid)
                v1 = (await http.get(base)).json()
                assert v1["grants"]["app"] == ["notify"] and v1["version"] == "1.0.0"
                await catalog_cplug_gates.stop_before_update(request, SimpleNamespace(item_id=ITEM))
                assert not alive(running.pid) and rt.supervisor.process(NAME) is None
                lay_code(state, "2.0.0", "tock")
                stripped = await asyncio.to_thread(catalog_cplug_gates.strip_grant_after_update, request, SimpleNamespace(item_id=ITEM))
                assert stripped is True
                after = (await http.get(base)).json()
                assert after["version"] == "2.0.0" and after["state"] == "needs_approval" and after["enabled"] is True
                assert after["grants"]["app"] == [] and after["needs"] == ["notify"] and after["tools"] == []
                assert rt.supervisor.process(NAME) is None and rt.supervisor.state(NAME) == "disabled"
                assert not rt.supervisor._safe_mode and not any(rt.safe_mode().values())
                assert f"cplug.{NAME}.integrity" not in alerts and f"cplug.{NAME}.safe_mode" not in alerts
                again = await consent_and_enable()
                assert again["state"] == "active" and again["process"] == "running" and again["grants"]["app"] == ["notify"]
                live = rt.supervisor.process(NAME)
                cache.versions = frozenset({f"{ITEM}@2.0.0"})
                await rt.index.sync()
                assert not alive(live.pid) and rt.supervisor.state(NAME) == "revoked" and f"cplug.{NAME}.revoked" in alerts
                assert (await http.post(f"{base}/restart")).json()["process"] == "revoked"
                rt.supervisor.forget(NAME)
                cache.versions, cache.keys = frozenset(), frozenset({KEY_ID})
                await rt.index.ensure()
                assert rt.supervisor._index["revoked"] == [{"id": ITEM}]
                assert (await http.post(f"{base}/restart")).json()["process"] == "revoked"
                rt.supervisor.forget(NAME)
                cache.keys = frozenset()
                await rt.index.sync()
                assert (await http.post(f"{base}/restart")).json()["process"] == "running"

                (state / "cplug-code" / NAME / "main.py").write_text(plugin_source("hacked"))
                await http.post(f"{base}/restart")
                assert f"cplug.{NAME}.integrity" in alerts and rt.supervisor._safe_mode is True
                assert rt.supervisor.process(NAME) is None
        finally:
            await rt.supervisor.shutdown()

    try:
        asyncio.run(asyncio.wait_for(go(), 240))
    finally:
        sidecar_registry.install(None)
        owner_state._file_cache.clear()
