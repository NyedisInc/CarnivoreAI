
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, List

import pytest
import structlog

from src.cplugs.host import runtime
from src.cplugs.registry import CPLUGS


def _boom(_ctx: Any) -> None:
    raise TypeError("unexpected plugin bug")


async def _fine(_ctx: Any) -> None:
    pass


def _definitions() -> List[Any]:
    bad, good = CPLUGS[0], CPLUGS[1]
    return [replace(bad, on_start=_boom), replace(good, on_start=_fine)]


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> runtime.Host:
    defs = _definitions()
    monkeypatch.setattr(runtime, "definitions", lambda: tuple(defs))
    monkeypatch.setattr(runtime.Host, "enabled", lambda self, cplug_id: True)
    monkeypatch.setattr(runtime.Host, "context", lambda self, cplug_id, **kw: object())
    monkeypatch.setattr(runtime.default_roots, "fill", lambda *a, **k: None)
    return runtime.Host(tmp_path)


@pytest.mark.asyncio
async def test_a_hook_raising_type_error_is_held_unavailable_and_boot_completes(host: runtime.Host) -> None:
    bad_id, good_id = _definitions()[0].id, _definitions()[1].id
    with structlog.testing.capture_logs() as logs:
        await host.start()
    assert host.unavailable[bad_id].startswith("start hook failed: TypeError")
    assert good_id not in host.unavailable
    assert good_id in host._started
    failed = [e for e in logs if e["event"] == "cplug_hook_failed"]
    assert failed and failed[0]["cplug"] == bad_id and failed[0]["hook"] == "start" and failed[0]["error_type"] == "TypeError"


@pytest.mark.asyncio
async def test_a_stop_hook_raising_does_not_stop_the_other_plugins_stopping(host: runtime.Host, monkeypatch: pytest.MonkeyPatch) -> None:
    defs = _definitions()
    monkeypatch.setattr(runtime, "definitions", lambda: (replace(defs[0], on_start=_fine, on_stop=_boom), replace(defs[1], on_start=_fine, on_stop=_fine)))
    await host.start()
    await host.stop()
    assert not host._started


def test_a_revoked_grant_counts_on_the_next_call_not_at_context_build(tmp_path: Path) -> None:
    from src.cplugs.host import state as owner_state

    manifest = CPLUGS[0].manifest
    perm = next(iter(manifest.permissions))
    owner_state.update(tmp_path, manifest, None, lambda st: replace(st, enabled=True, grants=(perm,)))
    ctx = runtime.Host(tmp_path).context(CPLUGS[0].id)
    assert ctx.has(perm)
    owner_state.update(tmp_path, manifest, None, lambda st: replace(st, grants=()))
    assert not ctx.has(perm) and perm not in ctx.grants


@pytest.mark.parametrize("name", ["CLAUDE.local.md", "Agent.md", "QWEN.md", "copilot-instructions.md", "SKILL.md", "WARP.md", "CONVENTIONS.md", "CRUSH.md"])
def test_exports_refuse_the_other_agents_instruction_names(name: str) -> None:
    from src.cplugs.runtime import fsguard

    with pytest.raises(fsguard.UnsafePath):
        fsguard.check_export_name(name)


@pytest.mark.asyncio
async def test_a_revoked_grant_refuses_the_capability_objects_built_before_the_revoke(tmp_path: Path) -> None:
    from src.cplugs.host import state as owner_state
    from src.cplugs.sdk.context import GrantRevoked

    d = next(x for x in CPLUGS if "sessions.read" in x.manifest.permissions)
    owner_state.update(tmp_path, d.manifest, None, lambda st: replace(st, enabled=True, grants=("sessions.read",)))

    async def infos() -> List[Any]:
        return []

    ctx = runtime.Host(tmp_path).context(d.id, infos=infos)
    assert await ctx.sessions.list() == []
    owner_state.update(tmp_path, d.manifest, None, lambda st: replace(st, grants=()))
    with pytest.raises(GrantRevoked) as raised:
        await ctx.sessions.list()
    assert raised.value.permission == "sessions.read"


def test_grant_revoked_is_a_runtime_error_so_a_plugin_catch_degrades() -> None:
    from src.cplugs.sdk.context import GrantRevoked

    assert issubclass(GrantRevoked, RuntimeError)


@pytest.mark.asyncio
async def test_a_task_manager_shaped_grant_set_may_still_call_asleep_and_the_method_map_follows_the_plugin_shape(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from src.cplugs.host import audit, state as owner_state
    from src.cplugs.sdk.context import GrantRevoked

    d = next(x for x in CPLUGS if x.id == "huddle")
    owner_state.update(tmp_path, d.manifest, None, lambda st: replace(st, enabled=True, grants=("sessions.read", "sessions.message")))

    async def infos() -> List[Any]:
        return []

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    ctx = runtime.Host(tmp_path).context(d.id, infos=infos, request=request)
    assert hasattr(ctx.sessions, "asleep"), "first-party message grant brings asleep"
    try:
        await ctx.sessions.asleep()
    except GrantRevoked:
        pytest.fail("asleep must not be charged to sessions.control for a first-party plugin")
    except Exception:  # noqa: BLE001
        pass
    assert audit.sessions_permission_for(False)("asleep") == "sessions.message"
    assert audit.sessions_permission_for(True)("asleep") == "sessions.control"
    assert audit.sessions_permission_for(False)("resume") == "sessions.create"
