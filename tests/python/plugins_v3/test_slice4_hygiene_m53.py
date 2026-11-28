
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.plugins.host import activity_log, plugin_bus, state as owner_state, ui_slots
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.runtime import Host
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames, guards
from src.plugins.runtime.dispatch import PluginContext
from src.plugins.runtime.process import ProcessEnded


def _make_tier0_def(code_dir: Path, plugin_id: str, static_items: list[dict] | None = None) -> SidecarDefinition:
    code_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": 2,
        "id": plugin_id,
        "name": f"Plugin {plugin_id}",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "UI slot size test plugin",
        "author": "Tester",
        "permissions": {"reasons": {"ui.slot:session.badges": "Render badges"}},
        "ui": {"contribute": {"session.badges": static_items if static_items is not None else [{"id": "a", "badge": "ok"}]}},
    }
    (code_dir / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    manifest = load_sidecar_manifest(code_dir, plugin_id)
    return SidecarDefinition(
        manifest=manifest,
        item_id=f"test/{plugin_id}",
        install_key="inst-key",
        code_root=code_dir,
        folder=code_dir.parent / "data" / plugin_id,
    )


def test_ui_slots_publish_and_resolve_enforce_aggregate_128kib_cap(tmp_path: Path):
    assert ui_slots.MAX_SLOT_BYTES == 128 * 1024
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    host = Host(state_dir)
    defn = _make_tier0_def(tmp_path / "plugins" / "slotcap", "slotcap")
    owner_state.update(
        state_dir,
        defn.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=tuple(defn.manifest.permissions),
            ui_slot_grants=("session.badges",),
            digest=defn.manifest.code_digest,
        ),
    )

    reg = ui_slots.UiSlotRegistry(state_dir)
    big_items = [
        {
            "schema": 2,
            "root": {
                "type": "column",
                "children": [
                    {"type": "text", "value": "x" * 1900},
                    {"type": "text", "value": "y" * 1900},
                    {"type": "text", "value": "z" * 1900},
                ],
            },
        }
        for _ in range(25)
    ]
    with pytest.raises(ui_slots.UiSlotError) as exc_info:
        reg.publish("slotcap", "session.badges", big_items, host=host, definitions=[defn])
    assert exc_info.value.status == 422
    assert exc_info.value.code == "slot_payload_too_large"
    events = [
        r
        for r in activity_log.ActivityLog(state_dir).recent("slotcap", 10)
        if r.get("status") == "invalid:slot_payload_too_large"
    ]
    assert events

    small = [{"id": "ok1", "badge": "hi"}]
    out = reg.publish("slotcap", "session.badges", small, host=host, definitions=[defn])
    assert out == small
    resolved = reg.resolve(host=host, definitions=[defn], safe_mode_active=False)
    assert len(resolved["slots"]["session.badges"]) == 1

    big_static = [
        {
            "schema": 2,
            "root": {
                "type": "column",
                "children": [
                    {"type": "text", "value": "a" * 1900},
                    {"type": "text", "value": "b" * 1900},
                    {"type": "text", "value": "c" * 1900},
                ],
            },
        }
        for _ in range(25)
    ]
    defn_big = _make_tier0_def(tmp_path / "plugins" / "slotcapbig", "slotcapbig", static_items=big_static)
    owner_state.update(
        state_dir,
        defn_big.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=tuple(defn_big.manifest.permissions),
            ui_slot_grants=("session.badges",),
            digest=defn_big.manifest.code_digest,
        ),
    )
    resolved2 = reg.resolve(host=host, definitions=[defn_big], safe_mode_active=False)
    assert "session.badges" not in resolved2["slots"]


@pytest.mark.asyncio
async def test_plugin_bus_distinguishes_leaked_host_error_32601_from_method_missing(tmp_path: Path):
    class _FakeProc:
        ended = False

        def __init__(self, exc: Exception):
            self._exc = exc

        async def request(self, *_a, **_k):
            raise self._exc

    holder: dict[str, Any] = {"proc": None}

    class _FakeSup:
        def is_paused(self, _pid: str) -> bool:
            return False

        def state(self, _pid: str) -> str:
            return "running"

        async def ensure(self, _pid: str):
            return holder["proc"]

    prov_dir = tmp_path / "plugins" / "prov"
    prov_dir.mkdir(parents=True)
    (prov_dir / "carnivore.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "id": "prov",
                "name": "Provider",
                "version": "1.0.0",
                "kind": "plugin",
                "description": "Service provider",
                "author": "Tester",
                "tier": "catalog",
                "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
                "services": {"provides": [{"name": "demo.svc", "methods": ["ping"]}]},
            }
        ),
        encoding="utf-8",
    )
    (prov_dir / "main.py").write_text("pass\n", encoding="utf-8")
    prov_manifest = load_sidecar_manifest(prov_dir, "prov")
    owner_state.update(
        tmp_path,
        prov_manifest,
        None,
        lambda st: replace(st, enabled=True, digest=prov_manifest.code_digest),
    )
    defn = SidecarDefinition(
        manifest=prov_manifest,
        item_id="test/prov",
        install_key="pk1",
        code_root=prov_dir,
        folder=tmp_path / "data" / "prov",
    )
    host = SimpleNamespace(enabled=lambda _pid: True, _live_grants=lambda _m: ("service.provide:demo.svc",))
    bus = plugin_bus.PluginBus(
        host=host,
        state_dir=lambda: tmp_path,
        supervisor_getter=lambda: _FakeSup(),
        safe_mode_getter=lambda: {},
        on_loop=lambda *_a, **_k: None,
        definitions_getter=lambda: [defn],
    )
    caller_ctx = PluginContext(
        plugin_id="caller",
        install_key="ck1",
        data_dir=tmp_path / "caller_data",
        granted=frozenset({"service:demo.svc"}),
        tier="catalog",
    )

    holder["proc"] = _FakeProc(ProcessEnded("plugin_error", code=frames.METHOD_NOT_FOUND, message="HostError"))
    with pytest.raises(guards.Refused) as exc1:
        await bus.call_service(caller_ctx, "demo.svc", "ping", {})
    assert exc1.value.code == "unavailable"
    assert "provider_error" in str(exc1.value)

    for msg in ("method_not_found", "unknown service method: demo.svc.ping", "unknown method: service.call"):
        holder["proc"] = _FakeProc(ProcessEnded("plugin_error", code=frames.METHOD_NOT_FOUND, message=msg))
        with pytest.raises(guards.Refused) as exc2:
            await bus.call_service(caller_ctx, "demo.svc", "ping", {})
        assert exc2.value.code == "service_unavailable"
        assert exc2.value.data.get("reason") == "provider_method_missing"


def test_developer_sideload_feature_uses_carnivore_toml_json_prose():
    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / "features" / "catalog" / "developer-sideload.json").read_text(encoding="utf-8")
    assert "(carnivore.toml / carnivore.json)" in text
    assert "(cplug.json)" not in text
