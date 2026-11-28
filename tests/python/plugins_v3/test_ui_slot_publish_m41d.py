
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.resource_push import topics
from src.plugins.host import owner_switch, runtime as host_runtime, sidecar_boot, sidecar_registry, state as owner_state, ui_slots
from src.plugins.host.runtime import Host
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_services import build_services
from src.plugins.runtime import guards, sock_cli
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.socket_server import PluginSocketServer, socket_path_for
from src.plugins.sdk_py.plugin import HostError, Plugin
from src.plugins.sdk_py.testing import attach


def _write_sidecar(code_dir: Path, plugin_id: str) -> None:
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "carnivore.toml").write_text(
        "\n".join(
            [
                "schema = 2",
                f'id = "{plugin_id}"',
                f'name = "Plugin {plugin_id}"',
                'version = "1.0.0"',
                'kind = "plugin"',
                'description = "M4.1d slot publish test plugin"',
                'author = "Tester"',
                "",
                "[run]",
                'cmd = ["python3", "main.py"]',
                'mode = "rpc"',
                "",
                "[permissions]",
                "[permissions.reasons]",
                '"ui.slot:session.badges" = "Publish CI badges on session rows"',
                "",
                "[ui]",
                'routes = ["open_ci"]',
                "",
                '[[ui.contribute."session.badges"]]',
                'id = "init"',
                'badge = "Init"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (code_dir / "main.py").write_text("import time\ntime.sleep(0.01)\n", encoding="utf-8")


def _register_and_enable(
    state_dir: Path,
    code_dir: Path,
    plugin_id: str,
    install_key: str,
    *,
    grants: tuple[str, ...] | None = None,
) -> SidecarDefinition:
    manifest = load_sidecar_manifest(code_dir, plugin_id)
    data_dir = state_dir / "cplugs" / install_key
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(
        manifest=manifest,
        item_id=f"acme/{plugin_id}",
        install_key=install_key,
        code_root=code_dir,
        folder=data_dir,
    )
    owner_state.update(
        state_dir,
        manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=tuple(manifest.permissions) if grants is None else grants,
            ui_slot_grants=("session.badges",) if grants is None else (),
            digest=manifest.code_digest,
        ),
    )
    return defn


def _install_registry(monkeypatch: pytest.MonkeyPatch, defs: List[SidecarDefinition]) -> None:
    by_id = {d.id: d for d in defs}
    fake_reg = SimpleNamespace(listed=lambda: list(defs), find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: by_id.get(pid))
    monkeypatch.setattr(host_runtime, "find", lambda pid: by_id.get(pid))


@pytest.mark.asyncio
async def test_ui_slot_publish_dispatcher_socket_sdk_py_and_sock_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    published_topics: List[str] = []
    owner_switch.write(state_dir, True)
    host = Host(state_dir, publish=lambda topic: published_topics.append(topic))

    _write_sidecar(tmp_path / "plug_a", "alpha")
    def_a = _register_and_enable(state_dir, tmp_path / "plug_a", "alpha", "inst-alpha")

    _write_sidecar(tmp_path / "plug_b", "beta")
    def_b = _register_and_enable(state_dir, tmp_path / "plug_b", "beta", "inst-beta", grants=())
    _install_registry(monkeypatch, [def_a, def_b])

    fake_sup = SimpleNamespace(
        state=lambda pid: "running" if pid == "alpha" else "stopped",
        is_paused=lambda _pid: False,
    )
    services_map = build_services(
        host=host,
        app=SimpleNamespace(state=SimpleNamespace()),
        state_dir=lambda: state_dir,
        supervisor_getter=lambda: fake_sup,
    )
    dispatcher = HostDispatcher(
        HostServices(
            activity=lambda _entry: None,
            ui_slot_publish=services_map["ui_slot_publish"],
        ),
        OwnerTokens(),
    )
    ctx_a = PluginContext(
        plugin_id="alpha",
        install_key="inst-alpha",
        data_dir=def_a.folder,
        granted=frozenset((*def_a.manifest.permissions, "ui.slot:session.badges")),
    )
    ctx_b = PluginContext(
        plugin_id="beta",
        install_key="inst-beta",
        data_dir=def_b.folder,
        granted=frozenset(),
    )

    with pytest.raises(guards.Refused) as exc_consent:
        await dispatcher.handle(
            ctx_b,
            "ui.slot.publish",
            {"slot": "session.badges", "items": [{"id": "b1", "badge": "OK"}]},
        )
    assert exc_consent.value.code == "not_granted"

    with pytest.raises(guards.Refused) as exc_bad:
        await dispatcher.handle(
            ctx_a,
            "ui.slot.publish",
            {"slot": "session.badges", "items": [{"id": "bad", "badge": "Bad", "href": "javascript:alert(1)"}]},
        )
    assert exc_bad.value.code == "invalid_params"

    async def _dispatch_call(method: str, params: Dict[str, Any]) -> Any:
        try:
            return await dispatcher.handle(ctx_a, method, params)
        except guards.Refused as exc:
            raise HostError(exc.code, str(exc), exc.data) from exc

    plugin = Plugin()
    attach(plugin, _dispatch_call)  # type: ignore[arg-type]
    out = await plugin.host.ui.slot_publish(
        "session.badges",
        [{"id": "ci", "badge": "CI green", "tone": "accent", "route": "open_ci", "when": {"session_ref": "uuid-1"}}],
    )
    assert out["slot"] == "session.badges"
    assert len(out["items"]) == 1
    assert topics.CPLUG_SLOTS in published_topics

    listed = ui_slots.registry_for(state_dir).resolve(host=host, definitions=[def_a, def_b], supervisor=fake_sup)
    assert "ci" in [x["item"]["id"] for x in listed["slots"]["session.badges"]]

    sock_path = socket_path_for(state_dir, "alpha")
    server = PluginSocketServer(ctx_a, dispatcher, sock_path)
    bound_sock = await server.start()
    try:
        monkeypatch.setenv("CARNIVORE_PLUGIN_SOCK", str(bound_sock))
        capsys.readouterr()
        rc = await asyncio.to_thread(
            sock_cli.main,
            [
                "--json",
                "ui",
                "slot-publish",
                "session.badges",
                "--items",
                json.dumps([{"id": "cli_badge", "badge": "CLI OK", "tone": "warn"}]),
            ],
        )
        assert rc == 0
        cli_out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert cli_out["slot"] == "session.badges"
        assert cli_out["items"][0]["id"] == "cli_badge"

        with pytest.raises(HostError) as exc_info:
            for idx in range(25):
                await plugin.host.ui.slot_publish("session.badges", [{"id": f"r_{idx}", "badge": "Rate"}])
        assert exc_info.value.code == "rate_limited"
        assert "rate_limited" in exc_info.value.reason
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_on_stopped_clears_dynamic_slots_and_switch_sidecar_keeps_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    published_topics: List[str] = []
    owner_switch.write(state_dir, True)
    host = Host(state_dir, publish=lambda topic: published_topics.append(topic))

    _write_sidecar(tmp_path / "plug_a", "alpha")
    _write_sidecar(tmp_path / "plug_b", "beta")
    def_a = _register_and_enable(state_dir, tmp_path / "plug_a", "alpha", "inst-alpha")
    def_b = _register_and_enable(state_dir, tmp_path / "plug_b", "beta", "inst-beta")
    _install_registry(monkeypatch, [def_a, def_b])

    rt = sidecar_boot.SidecarRuntime(
        host,
        SimpleNamespace(state=SimpleNamespace()),
        asyncio.get_running_loop(),
        env_safe=lambda: False,
    )
    monkeypatch.setattr(host, "sidecar_runtime", lambda: rt)

    monkeypatch.setattr(rt.supervisor, "state", lambda pid: "running" if pid in ("alpha", "beta") else "stopped")
    monkeypatch.setattr(rt.supervisor, "is_paused", lambda _pid: False)
    reg = ui_slots.registry_for(state_dir)
    reg.publish("alpha", "session.badges", [{"id": "a_badge", "badge": "Alpha"}], host=host, definitions=[def_a, def_b], supervisor=rt.supervisor)
    reg.publish("beta", "session.badges", [{"id": "b_badge", "badge": "Beta"}], host=host, definitions=[def_a, def_b], supervisor=rt.supervisor)
    published_topics.clear()

    monkeypatch.setattr(rt.supervisor, "state", lambda pid: "running" if pid == "beta" else "stopped")
    await rt._on_stopped("alpha")
    await asyncio.sleep(0)
    assert topics.CPLUG_SLOTS in published_topics
    snap = reg.resolve(host=host, definitions=[def_a, def_b], supervisor=rt.supervisor)
    pairs = [(e["plugin_id"], e["item"]["id"]) for e in snap["slots"].get("session.badges", [])]
    assert ("alpha", "a_badge") not in pairs
    assert ("beta", "b_badge") in pairs

    monkeypatch.setattr(rt.supervisor, "activate", lambda _spec: asyncio.sleep(0))
    monkeypatch.setattr(rt.supervisor, "disable", lambda _pid: asyncio.sleep(0))
    await host.switched("alpha", True)
    snap_after = reg.resolve(host=host, definitions=[def_a, def_b], supervisor=rt.supervisor)
    pairs_after = [(e["plugin_id"], e["item"]["id"]) for e in snap_after["slots"].get("session.badges", [])]
    assert ("beta", "b_badge") in pairs_after


def test_ui_slot_alias_canonicalization_publish_and_resolve(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    code_dir = tmp_path / "plug_alias"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "carnivore.toml").write_text(
        "\n".join(
            [
                "schema = 2",
                'id = "gamma"',
                'name = "Gamma"',
                'version = "1.0.0"',
                'kind = "plugin"',
                'description = "Alias test"',
                'author = "Tester"',
                "",
                "[run]",
                'cmd = ["python3", "main.py"]',
                'mode = "rpc"',
                "",
                "[permissions.reasons]",
                '"ui.slot:session_badges" = "Show session badges"',
                "",
                '[[ui.contribute."session_badges"]]',
                'id = "static_init"',
                'badge = "Static"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (code_dir / "main.py").write_text("import time\ntime.sleep(0.01)\n", encoding="utf-8")
    manifest = load_sidecar_manifest(code_dir, "gamma")
    data_dir = state_dir / "cplugs" / "inst-gamma"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="acme/gamma",
        install_key="inst-gamma",
        code_root=code_dir,
        folder=data_dir,
    )
    owner_state.update(
        state_dir,
        manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=tuple(manifest.permissions),
            ui_slot_grants=("session_badges",),
            digest=manifest.code_digest,
        ),
    )

    published_topics: List[str] = []
    host = Host(state_dir, publish=lambda topic: published_topics.append(topic))
    sup = SimpleNamespace(state=lambda _pid: "running", is_paused=lambda _pid: False)
    reg = ui_slots.UiSlotRegistry(state_dir)

    out = reg.publish(
        "gamma",
        "session.badges",
        [{"id": "live_badge", "badge": "Live"}],
        host=host,
        definitions=[defn],
        supervisor=sup,
    )
    assert [x["id"] for x in out] == ["live_badge"]

    snap = reg.resolve(host=host, definitions=[defn], supervisor=sup)
    badges = snap["slots"].get("session.badges", [])
    assert [b["item"]["id"] for b in badges] == ["live_badge"]
    assert badges[0]["slot"] == "session.badges"
