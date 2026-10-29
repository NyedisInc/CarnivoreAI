
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

from src.cplugs.host import mcp_health_port, runtime, sidecar_boot
from src.cplugs.host.sidecar_boot import MCP_HEALTH_ID
from src.cplugs.sdk import ports
from src.cplugs.sdk.mcp_health import PORT_NAME


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
        d = SimpleNamespace(id=MCP_HEALTH_ID)
        await rt.mcp_health_switched(MCP_HEALTH_ID, True)
        assert ports.get(PORT_NAME) is not None
        await rt.supervisor.disable(MCP_HEALTH_ID, "updated")
        assert ports.get(PORT_NAME) is None
        await host.restart_sidecar(d)
        await host.restart_sidecar(d)
        registered = ports.get(PORT_NAME) is not None
        assert len(restarts) == 2
        await rt.mcp_health_switched(MCP_HEALTH_ID, False)
        return registered

    assert asyncio.run(go()) is True


def test_restart_leaves_the_port_absent_in_safe_mode_and_for_other_plugins(tmp_path: Any, monkeypatch: Any) -> None:
    async def go() -> List[bool]:
        host, rt, _ = _wire(tmp_path, monkeypatch, {"env": False, "owner": True, "off": False})
        await host.restart_sidecar(SimpleNamespace(id=MCP_HEALTH_ID))
        in_safe_mode = ports.get(PORT_NAME) is not None
        rt.safe_mode = lambda: {"env": False, "owner": False, "off": False}  # type: ignore[method-assign]
        await host.restart_sidecar(SimpleNamespace(id="some-other-plugin"))
        other = ports.get(PORT_NAME) is not None
        return [in_safe_mode, other]

    assert asyncio.run(go()) == [False, False]
