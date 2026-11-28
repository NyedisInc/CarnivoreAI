
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from src.plugins.host import mcp_health_port, runtime, sidecar_boot, sidecar_registry
from src.plugins.sdk import ports
from src.plugins.sdk.mcp_health import PORT_NAME

PLUGIN_ID = "healthmon"


def _health_def(plugin_id: str = PLUGIN_ID, *, permissions: tuple[str, ...] = ("mcp.health.read",), subscriptions: tuple[str, ...] = ()) -> Any:
    return SimpleNamespace(id=plugin_id, manifest=SimpleNamespace(permissions=permissions, subscriptions=subscriptions))


class _StubMonitor:

    async def run(self, *_args: Any) -> None:
        await asyncio.sleep(3600)

    def close(self) -> None:
        return None


def _wire(tmp_path: Any, monkeypatch: Any, safe: Dict[str, bool]) -> Tuple[Any, Any, List[Any]]:
    monkeypatch.setattr(mcp_health_port, "McpMonitor", _StubMonitor)
    ports.unregister(PORT_NAME)
    shell = SimpleNamespace(state_dir=tmp_path, install_key=lambda plugin_id: plugin_id)
    rt = sidecar_boot.SidecarRuntime(shell, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(),
                                     env_safe=lambda: False, app_version="9.9.9")
    restarts: List[Any] = []

    async def restart(spec: Any) -> str:
        restarts.append(spec)
        return "idle"

    async def ensure() -> None:
        return None

    rt.supervisor.restart = restart  # type: ignore[method-assign]
    rt.index = SimpleNamespace(ensure=ensure)
    rt.safe_mode = lambda: safe  # type: ignore[method-assign]
    host = runtime.Host.__new__(runtime.Host)
    host.app = SimpleNamespace(state=SimpleNamespace(sidecar_runtime=rt))
    host.sidecar_spec = lambda d: d.id  # type: ignore[method-assign]
    return host, rt, restarts


def test_consent_restart_after_an_update_stop_registers_the_port(tmp_path: Any, monkeypatch: Any) -> None:
    async def go() -> bool:
        host, rt, restarts = _wire(tmp_path, monkeypatch, {"env": False, "owner": False, "off": False})
        d = _health_def()
        monkeypatch.setattr(sidecar_registry, "find", lambda pid: d if pid == d.id else None)
        await rt.mcp_health_switched(d.id, True)
        assert ports.get(PORT_NAME) is not None
        assert rt._mcp_health_owner == d.id
        await rt.supervisor.disable(d.id, "updated")
        assert ports.get(PORT_NAME) is None
        assert rt._mcp_health_owner is None
        await host.restart_sidecar(d)
        await host.restart_sidecar(d)
        registered = ports.get(PORT_NAME) is not None
        assert len(restarts) == 2
        await rt.stop()
        assert ports.get(PORT_NAME) is None and rt._mcp_health_owner is None
        return registered

    assert asyncio.run(go()) is True


def test_capability_discovery_by_subscription_and_ignores_unrelated_plugins(tmp_path: Any, monkeypatch: Any) -> None:
    async def go() -> Tuple[bool, Optional[str], bool]:
        _host, rt, _ = _wire(tmp_path, monkeypatch, {"env": False, "owner": False, "off": False})
        sub_def = _health_def("subhealth", permissions=(), subscriptions=(mcp_health_port.EVENT_FAMILY,))
        other_def = _health_def("unrelated", permissions=("notify",), subscriptions=())
        defs = {sub_def.id: sub_def, other_def.id: other_def}
        monkeypatch.setattr(sidecar_registry, "find", lambda pid: defs.get(pid))
        await rt.mcp_health_switched(other_def.id, True)
        unrelated_started = ports.get(PORT_NAME) is not None
        await rt.mcp_health_switched(sub_def.id, True)
        sub_started = ports.get(PORT_NAME) is not None
        owner = rt._mcp_health_owner
        await rt.mcp_health_switched(sub_def.id, False)
        return unrelated_started, owner, sub_started

    assert asyncio.run(go()) == (False, "subhealth", True)


def test_restart_leaves_the_port_absent_in_safe_mode_and_for_other_plugins(tmp_path: Any, monkeypatch: Any) -> None:
    async def go() -> List[bool]:
        host, rt, _ = _wire(tmp_path, monkeypatch, {"env": False, "owner": True, "off": False})
        d = _health_def()
        other_def = _health_def("some-other-plugin", permissions=("notify",), subscriptions=())
        defs = {d.id: d, other_def.id: other_def}
        monkeypatch.setattr(sidecar_registry, "find", lambda pid: defs.get(pid))
        await host.restart_sidecar(d)
        in_safe_mode = ports.get(PORT_NAME) is not None
        rt.safe_mode = lambda: {"env": False, "owner": False, "off": False}  # type: ignore[method-assign]
        await host.restart_sidecar(other_def)
        other = ports.get(PORT_NAME) is not None
        return [in_safe_mode, other]

    assert asyncio.run(go()) == [False, False]
