
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.mcp import pending
from src.plugins.host import sidecar_boot, sidecar_registry, sidecar_spec
from src.plugins.host.runtime import Host
from src.plugins.host.plugin_manifest import SidecarManifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.dispatch import HostDispatcher, PluginContext
from src.plugins.runtime.guards import Refused
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.sdk.ai_features import AiFeature
from src.plugins.sdk.network import NetworkDecl


def _make_runtime(tmp_path: Path, app: Any) -> sidecar_boot.SidecarRuntime:
    loop = asyncio.new_event_loop()
    try:
        host = Host(tmp_path, app=app)
        return sidecar_boot.SidecarRuntime(host, app, loop)
    finally:
        loop.close()


def test_sidecar_boot_wires_all_host_services_and_capabilities(tmp_path: Path) -> None:
    assert sidecar_spec.CAPABILITIES == frozenset({"tools", "events", "routes", "timers", "services"})

    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    rt = sidecar_boot.SidecarRuntime(Host(tmp_path, app=app), app, asyncio.new_event_loop())
    try:
        svc = rt._services()
        for field_name in (
            "activity",
            "list_sessions",
            "get_session",
            "session_output",
            "permission_mode",
            "paste_line",
            "create_session",
            "control_session",
            "list_projects",
            "project_path",
            "ledger",
            "http_fetch",
            "ai_for",
            "toast",
            "alert",
            "publish_topic",
            "invalidate_ui",
            "process_snapshot",
            "mcp_config",
            "mcp_links",
            "flow_run",
            "flow_run_part",
            "flow_feed",
            "flow_tasks",
            "service_call",
            "events_emit",
        ):
            assert getattr(svc, field_name) is not None, f"HostServices.{field_name} must be wired"
    finally:
        rt.loop.close()


def test_build_spec_populates_picked_folders_excluding_defaults_and_timers(tmp_path: Path) -> None:
    manifest = SidecarManifest(
        id="exporter",
        name="Exporter",
        description="Exports reports",
        version="1.0.0",
        entry="main.py",
        tools=(),
        permissions=("exports.write",),
        network=NetworkDecl(),
        code_digest="a" * 64,
        settings_schema={
            "version": 1,
            "fields": {
                "out_dir": {"type": "folder", "default": "/default/out"},
                "extra_dir": {"type": "folder", "default": "/default/extra"},
            },
        },
        timers={"sweep": 15},
    )
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="acme/exporter",
        install_key="k-export",
        code_root=tmp_path / "code",
        folder=tmp_path / "data",
    )
    export_dir = tmp_path / "picked"
    spec = sidecar_spec.build_spec(
        defn,
        frozenset({"exports.write"}),
        settings={
            "picked_folders": [str(export_dir)],
            "out_dir": "/default/out",
            "extra_dir": str(tmp_path / "custom"),
        },
    )
    assert spec.timers == {"sweep": 15}
    assert export_dir in spec.ctx.picked_folders
    assert (tmp_path / "custom") in spec.ctx.picked_folders
    assert Path("/default/out") not in spec.ctx.picked_folders


@pytest.mark.asyncio
async def test_dispatch_session_output_and_exports_write_through_wired_services(tmp_path: Path) -> None:
    fake_secret = "sk-ant-api03-" + ("A1b2C3d4E5" * 4)

    class _FakeSM:
        async def list_session_infos(self) -> List[Any]:
            return [
                SimpleNamespace(
                    session=SimpleNamespace(id="ses_local1"),
                    tmux_session="cloude_ses_local1",
                    session_uuid="uuid-local-1",
                    host_key="local",
                    agent_family="claude",
                )
            ]

        def capture_scrollback(self, *, lines: int, session_id: str) -> bytes:
            assert session_id == "ses_local1"
            return f"\x1b[32mline one\x1b[0m\nsecret={fake_secret}\n".encode("utf-8")

    app = SimpleNamespace(state=SimpleNamespace(session_manager=_FakeSM(), services=SimpleNamespace(registry=None)))
    host = Host(tmp_path, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop())
    try:
        disp = HostDispatcher(rt._services(), OwnerTokens(), home=tmp_path)
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)
        ctx = PluginContext(
            plugin_id="reader",
            install_key="k-reader",
            data_dir=tmp_path / "data",
            granted=frozenset({"sessions.output", "exports.write"}),
            picked_folders=(export_dir,),
        )
        out = await disp.handle(ctx, "sessions.output", {"ref": "ses_local1", "lines": 10})
        joined = "\n".join(out["lines"])
        assert "line one" in joined
        assert "\x1b[" not in joined
        assert fake_secret not in joined

        res = await disp.handle(
            ctx,
            "exports.write",
            {
                "folder": str(export_dir),
                "name": "report.txt",
                "bytes": base64.b64encode(b"ok").decode("ascii"),
            },
        )
        assert Path(res["path"]).read_bytes() == b"ok"

        with pytest.raises(Refused):
            await disp.handle(
                ctx,
                "exports.write",
                {
                    "folder": str(tmp_path / "unpicked"),
                    "name": "bad.txt",
                    "bytes": base64.b64encode(b"no").decode("ascii"),
                },
            )
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_control_session_stop_parks_in_pending_and_permission_mode_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destroyed: List[str] = []

    class _FakeSM:
        async def list_session_infos(self) -> List[Any]:
            row = {
                "session": {"id": "ses_target1", "launched_with": {"permissions": "default"}},
                "tmux_session": "cloude_target1",
                "session_uuid": "uuid-target-1",
                "host_key": "local",
                "agent_family": "codex",
                "agent_wrapper_label": "codex",
            }
            return [
                SimpleNamespace(
                    session=SimpleNamespace(id="ses_target1", launched_with={"permissions": "default"}),
                    tmux_session="cloude_target1",
                    session_uuid="uuid-target-1",
                    host_key="local",
                    agent_family="codex",
                    agent_wrapper_label="codex",
                    model_dump=lambda mode=None, _r=row: dict(_r),
                )
            ]

        def capture_scrollback(self, *, lines: int, session_id: str) -> bytes:
            return b"plain prompt without mode marker"

        async def destroy_session(self, *, session_id: str) -> None:
            destroyed.append(session_id)

    app = SimpleNamespace(state=SimpleNamespace(session_manager=_FakeSM(), services=SimpleNamespace(registry=None)))
    host = Host(tmp_path, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop())
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "get_store", lambda: store)

    try:
        disp = HostDispatcher(rt._services(), rt.tokens, home=tmp_path)
        ctx = PluginContext(
            plugin_id="ctrl",
            install_key="k-ctrl",
            data_dir=tmp_path / "data",
            granted=frozenset({"sessions.control", "sessions.message"}),
        )

        tok = rt.tokens.mint("k-ctrl", "ses_target1")
        with pytest.raises(Refused) as exc_info:
            await disp.handle(ctx, "sessions.message", {"ref": "ses_target1", "line": "hello", "owner_token": tok})
        assert exc_info.value.code == "permission_denied"

        rt.supervisor._procs["ctrl"] = SimpleNamespace(ended=None, spec=SimpleNamespace(ctx=ctx))
        task = asyncio.create_task(disp.handle(ctx, "sessions.control", {"ref": "ses_target1", "action": "stop"}))
        for _ in range(50):
            if task.done():
                task.result()
            items = store.list()
            if items:
                break
            await asyncio.sleep(0.01)
        items = store.list()
        assert len(items) == 1
        assert items[0]["action"] == "plugin_session_stop"
        assert destroyed == []

        await store.approve(items[0]["id"])
        out = await task
        assert out == {"ok": True}
        assert destroyed == ["ses_target1"]
    finally:
        rt.supervisor._procs.pop("ctrl", None)
        await rt.stop()


@pytest.mark.asyncio
async def test_ai_for_ledger_and_projects_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    host = Host(tmp_path, app=app)
    host.ai_gateway = lambda: SimpleNamespace(
        chat=lambda feat, prompt, max_tokens=100: asyncio.sleep(0, result=SimpleNamespace(text="pong", usage=None)),
    )
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop())
    try:
        manifest = SidecarManifest(
            id="helper",
            name="Helper",
            description="AI helper",
            version="1.0.0",
            entry="main.py",
            tools=(),
            permissions=("ai_features:cplug.helper.summarize", "ledger.read", "sessions.read"),
            network=NetworkDecl(),
            code_digest="b" * 64,
            ai_features={"summarize": AiFeature(name="summarize", capability="chat", calls_per_day=10, tokens_per_day=1000)},
        )
        defn = SidecarDefinition(
            manifest=manifest,
            item_id="acme/helper",
            install_key="k-helper",
            code_root=tmp_path / "code",
            folder=tmp_path / "data",
        )
        monkeypatch.setattr(sidecar_registry, "find", lambda pid: defn if pid == "helper" else None)
        monkeypatch.setattr(
            "src.api.provider_ledger_routes.get_provider_ledger",
            lambda: asyncio.sleep(
                0,
                result=SimpleNamespace(
                    accounts=[
                        SimpleNamespace(
                            id="acc-1",
                            name="Main",
                            provider="claude",
                            plan="max",
                            credential_state="ok",
                            error=None,
                            fetched_at="2026-11-23T00:00:00Z",
                            windows=[],
                        )
                    ]
                ),
            ),
        )
        svc = rt._services()
        ctx = PluginContext(
            plugin_id="helper",
            install_key="k-helper",
            data_dir=tmp_path / "data",
            granted=frozenset({"ai_features:cplug.helper.summarize", "ledger.read", "sessions.read"}),
        )
        assert svc.ai_for is not None
        ai = svc.ai_for(ctx)
        assert ai is not None
        ledger_out = await HostDispatcher(svc, rt.tokens).handle(ctx, "ledger.read", {})
        assert ledger_out["accounts"][0]["id"] == "acc-1"
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_session_output_none_scrollback_returns_empty_list(tmp_path: Path) -> None:
    class _NoneSM:
        async def list_session_infos(self) -> List[Any]:
            return [
                SimpleNamespace(
                    session=SimpleNamespace(id="ses_none"),
                    tmux_session="cloude_ses_none",
                    session_uuid="uuid-none",
                    host_key="local",
                    agent_family="claude",
                )
            ]

        def capture_scrollback(self, *, lines: int, session_id: str) -> None:
            return None

    app = SimpleNamespace(state=SimpleNamespace(session_manager=_NoneSM(), services=SimpleNamespace(registry=None)))
    host = Host(tmp_path, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop())
    try:
        disp = HostDispatcher(rt._services(), OwnerTokens(), home=tmp_path)
        ctx = PluginContext(
            plugin_id="reader",
            install_key="k-reader",
            data_dir=tmp_path / "data",
            granted=frozenset({"sessions.output"}),
        )
        out = await disp.handle(ctx, "sessions.output", {"ref": "ses_none", "lines": 10})
        assert out == {"lines": []}
    finally:
        await rt.stop()
