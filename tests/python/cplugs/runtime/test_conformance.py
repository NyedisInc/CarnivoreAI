
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import replace
from typing import Any, Dict

import pytest

from src.cplugs.runtime import conformance as kit
from src.cplugs.runtime import guards, watchdog


class _Anything:

    def parse(self, line: bytes) -> None:
        return None

    def feed(self, chunk: bytes) -> list:
        return []

    def verify(self, *a: Any) -> bytes:
        return b""


def _permissive(h: kit.Harness) -> Dict[str, Any]:
    async def handle(ctx, method, params):
        if method == "sessions.list":
            return {"sessions": h.rows}
        if method == "notify.alert":
            h.alerts.append((ctx.plugin_id, str(params.get("key")), "info", "t"))
        return {}

    async def revoke(plugin_id):
        return {"alerts": [], "cancelled": [], "state": "running", "respawn_refusal": None}

    return {
        "handle": handle, "mint": lambda ctx, ref: "tok", "pin_tools": lambda manifest, runtime: None,
        "new_guard": _Anything, "new_splitter": _Anything, "open_nofollow": lambda root, rel: os.open(os.path.join(root, rel), os.O_RDONLY),
        "git_argv": lambda repo, op: ["git", str(op)], "git_env": lambda: {},
        "git_read": lambda repo, op: subprocess.run(["/usr/bin/git", "-C", str(repo), "status"], capture_output=True, check=False),
        "git_snapshot": lambda repo, turn: subprocess.run(["/usr/bin/git", "-C", str(repo), "stash", "create"], capture_output=True, check=False), "new_verifier": lambda clock: _Anything(),
        "index_may_run": lambda index, override: True, "check_memory": lambda *a, **k: watchdog.Verdict(True),
        "check_disk": lambda *a, **k: watchdog.Verdict(True),
        "render_profile": lambda layout: f'(version 1)\n(allow file-read* (subpath "{layout.data_dir.parents[2]}"))\n',
        "revoke": revoke, "safe_mode_admit": lambda: None,
    }


def test_real_host_passes_every_probe(tmp_path):
    results = asyncio.run(kit.run_all(kit.real_harness(tmp_path)))
    assert {rule: bad for rule, bad in results.items() if bad} == {}
    assert len(results) == len(kit.RULES) == 15


@pytest.mark.parametrize("rule,finding,probe", kit.RULES, ids=[r[0] for r in kit.RULES])
def test_each_probe_goes_red_against_a_host_without_the_rule(tmp_path, rule, finding, probe):
    real = kit.real_harness(tmp_path)
    weak = replace(real, **_permissive(real))
    assert asyncio.run(probe(weak)), f"{finding}: the probe stayed green against a host with no guard"


def test_a_host_that_refuses_everything_fails_the_positive_controls(tmp_path):
    real = kit.real_harness(tmp_path)

    async def deny(ctx, method, params):
        raise guards.Refused("permission_denied", "no")

    results = asyncio.run(kit.run_all(replace(real, handle=deny)))
    for rule in ("c1_ai_call", "c2_owner_token_and_control_lines", "m6_remote_refs", "h4_session_fields", "m1_notify"):
        assert any(line.startswith("positive") for line in results[rule]), rule


@pytest.mark.parametrize("module,attr,value,rule", [
    (guards, "CONTROL_LEAD", frozenset(), "c2_owner_token_and_control_lines"),
    (guards, "SESSION_FIELDS", guards.SESSION_FIELDS + ("parked_summary", "working_dir"), "h4_session_fields"),
    (guards, "is_remote_row", lambda row: False, "m6_remote_refs"),
    ("src.cplugs.runtime.git_ops", "HARDENING", (), "l2_git_flags"),
    ("src.cplugs.runtime.git_ops", "UNSAFE_CONFIG", re.compile(r"^$"), "l2_git_flags"),
    ("src.cplugs.runtime.webhooks", "MAX_SKEW_SECONDS", 10 ** 9, "l4_webhooks"),
    ("src.cplugs.runtime.webhooks", "MAX_FUTURE_SECONDS", 10 ** 9, "l4_webhooks"),
    ("src.cplugs.runtime.webhooks", "_before_start", lambda ts, started: False, "l4_webhooks"),
    ("src.cplugs.runtime.watchdog", "MEMORY_LIMIT_BYTES", 10 ** 12, "m4_limits"),
], ids=["c2-control-lead", "h4-fields", "m6-remote", "l2-git", "l2-filter-config", "l4-skew", "l4-future-cap", "l4-restart-floor", "m4-memory"])
def test_removing_the_rule_in_the_real_code_turns_its_probe_red(tmp_path, monkeypatch, module, attr, value, rule):
    import importlib

    target = importlib.import_module(module) if isinstance(module, str) else module
    probe = {name: p for name, _, p in kit.RULES}[rule]
    assert asyncio.run(probe(kit.real_harness(tmp_path / "before"))) == []
    monkeypatch.setattr(target, attr, value)
    if rule == "m4_limits":
        monkeypatch.setattr(watchdog.check_memory, "__defaults__", (value,))
    assert asyncio.run(probe(kit.real_harness(tmp_path / "after")))


def test_a_changed_code_root_refuses_the_spawn_and_turns_on_safe_mode(tmp_path):
    from src.cplugs.runtime import integrity
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
    from src.cplugs.runtime.owner_tokens import OwnerTokens
    from src.cplugs.runtime.process import PluginSpec
    from src.cplugs.runtime.supervisor import Supervisor

    code = tmp_path / "code"
    code.mkdir()
    (code / "main.py").write_text("plugin = None\n")
    digest = integrity.tree_digest(code)
    alerts, log = [], []
    sup = Supervisor(tmp_path / "state", "1.0", HostDispatcher(HostServices(activity=log.append), OwnerTokens()),
                     lambda pid, key, why: alerts.append((pid, key, why)), lambda pid: {}, log.append,
                     index={"expires_at": "2999-01-01T00:00:00Z"})
    ctx = PluginContext(plugin_id="tamper", install_key="0" * 32, data_dir=tmp_path / "data", granted=frozenset())
    assert integrity.tree_digest(code) == digest
    (code / "main.py").write_text("plugin = None  # edited after consent\n")
    state = asyncio.run(sup.enable(PluginSpec(ctx=ctx, code_dir=code, entry="main", code_digest=digest)))
    assert state == "disabled (safe mode)"
    assert ("tamper", "integrity", "code_root_changed") in alerts
    assert sup.process("tamper") is None
    link = code / "ln"
    os.symlink("/etc/hosts", link)
    with pytest.raises(integrity.IntegrityError):
        integrity.tree_digest(code)


def test_pyc_in_the_code_root_is_refused_not_skipped(tmp_path):
    from src.cplugs.runtime import integrity

    code = tmp_path / "code"
    (code / "__pycache__").mkdir(parents=True)
    (code / "main.py").write_text("plugin = None\n")
    (code / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"planted")
    with pytest.raises(integrity.IntegrityError):
        integrity.tree_digest(code)
    (code / "__pycache__" / "main.cpython-312.pyc").unlink()
    (code / "__pycache__").rmdir()
    (code / "stray.pyc").write_bytes(b"x")
    with pytest.raises(integrity.IntegrityError):
        integrity.tree_digest(code)


def test_the_command_points_pycache_prefix_at_nothing(tmp_path):
    from src.cplugs.runtime import sandbox

    layout = sandbox.Layout(tmp_path / "py", tmp_path / "fw", tmp_path / "rt", tmp_path / "code", tmp_path / "data")
    argv = sandbox.build_command(layout, tmp_path / "p.sb", "main", 123)
    assert f"pycache_prefix={tmp_path / 'rt' / sandbox.NO_PYCACHE}" in argv and argv[-2:] == ["64", "123"]


def test_request_flood_and_in_flight_cap_are_violations():
    from src.cplugs.runtime import frames

    line = lambda i: b'{"jsonrpc":"2.0","id":%d,"method":"log","params":{}}' % i  # noqa: E731
    guard = frames.FrameGuard(clock=lambda: 0.0)
    for i in range(1, frames.MAX_IN_FLIGHT + 1):
        guard.parse(line(i))
    with pytest.raises(frames.FrameViolation) as cap:
        guard.parse(line(frames.MAX_IN_FLIGHT + 1))
    assert cap.value.code == "request_flood"
    guard.request_done()
    guard.parse(line(frames.MAX_IN_FLIGHT + 2))
    fast = frames.FrameGuard(clock=lambda: 0.0)
    with pytest.raises(frames.FrameViolation):
        for i in range(1, frames.REQUESTS_PER_SECOND + 2):
            fast.parse(line(i))
            fast.request_done()


def test_a_refused_or_unknown_call_writes_one_activity_row_per_window(tmp_path):
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
    from src.cplugs.runtime.owner_tokens import OwnerTokens

    now, log = [0.0], []
    d = HostDispatcher(HostServices(activity=log.append), OwnerTokens(), clock=lambda: now[0], home=tmp_path)
    ctx = PluginContext(plugin_id="noisy", install_key="1" * 32, data_dir=tmp_path / "d", granted=frozenset())

    async def spam(n):
        for _ in range(n):
            with pytest.raises(guards.Refused):
                await d.handle(ctx, "no.such", {})

    asyncio.run(spam(50))
    assert len(log) == 1
    now[0] = 61.0
    asyncio.run(spam(1))
    assert len(log) == 2 and log[1]["detail"] == "repeats=49"


def test_log_fields_cannot_shadow_the_plugin_id_or_the_event(tmp_path):
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
    from src.cplugs.runtime.owner_tokens import OwnerTokens
    import structlog

    d = HostDispatcher(HostServices(activity=lambda row: None), OwnerTokens(), home=tmp_path)
    ctx = PluginContext(plugin_id="honest", install_key="2" * 32, data_dir=tmp_path / "d", granted=frozenset())
    with structlog.testing.capture_logs() as seen:
        asyncio.run(d.handle(ctx, "log", {"event": "x", "fields": {"event": "boom", "cplug": "someone-else"}}))
    assert seen[0]["cplug"] == "honest" and seen[0]["fields"]["cplug"] == "someone-else" and seen[0]["event"] == "cplug_x"


def test_storage_is_keyed_by_install_not_by_the_reusable_name(tmp_path):
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
    from src.cplugs.runtime.owner_tokens import OwnerTokens

    d = HostDispatcher(HostServices(activity=lambda row: None), OwnerTokens(), home=tmp_path)
    old = PluginContext(plugin_id="same", install_key="a" * 32, data_dir=tmp_path / "old", granted=frozenset())
    new = PluginContext(plugin_id="same", install_key="b" * 32, data_dir=tmp_path / "new", granted=frozenset())
    assert d.storage(old) is not d.storage(new) and d.storage(old) is d.storage(old)


def test_a_refused_log_line_does_not_stop_the_pump_and_events_need_a_subscription_and_a_grant(tmp_path):
    from src.cplugs.runtime import frames, sandbox
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
    from src.cplugs.runtime.owner_tokens import OwnerTokens
    from src.cplugs.runtime.process import PluginProcess, PluginSpec

    d = HostDispatcher(HostServices(activity=lambda row: None), OwnerTokens(), home=tmp_path)
    ctx = PluginContext(plugin_id="ev", install_key="3" * 32, data_dir=tmp_path / "d", granted=frozenset({"feed:meta"}))
    layout = sandbox.Layout(tmp_path / "py", tmp_path / "fw", tmp_path / "rt", tmp_path / "code", tmp_path / "d")

    async def go():
        proc = PluginProcess(PluginSpec(ctx=ctx, code_dir=tmp_path, entry="main"), layout, d, "1.0", lambda r: asyncio.sleep(0))
        proc.negotiated = {"subscriptions": ["feed.meta", "feed.raw"]}
        assert not await proc.deliver_event("session.status", 1, {})
        assert not await proc.deliver_event("feed.raw", 1, {})
        for _ in range(frames.NOTIFICATIONS_PER_SECOND):
            await proc._frame(frames.Frame("notification", None, "log", {"event": "x"}))
        await proc._frame(frames.Frame("notification", None, "log", {"event": "x"}))

    asyncio.run(go())


class _FakeProc:

    def __init__(self) -> None:
        self.stopped = None

    async def stop(self, reason: str = "disabled") -> None:
        self.stopped = reason


def _sup(tmp_path, alerts, index):
    from src.cplugs.runtime.dispatch import HostDispatcher, HostServices
    from src.cplugs.runtime.owner_tokens import OwnerTokens
    from src.cplugs.runtime.supervisor import Supervisor

    log = []
    return Supervisor(tmp_path / "state", "1.0", HostDispatcher(HostServices(activity=log.append), OwnerTokens()),
                      lambda pid, key, why: alerts.append((pid, key, why)), lambda pid: {}, log.append, index=index)


def _spec(tmp_path, name="cat", tier="catalog", digest="d", **kw):
    from src.cplugs.runtime.dispatch import PluginContext
    from src.cplugs.runtime.process import PluginSpec

    ctx = PluginContext(plugin_id=name, install_key="4" * 32, data_dir=tmp_path / "data", granted=frozenset(), tier=tier)
    return PluginSpec(ctx=ctx, code_dir=tmp_path, entry="main", code_digest=digest, **kw)


def test_a_running_catalog_plugin_is_paused_when_the_index_expires_or_revokes_it(tmp_path):
    alerts = []
    sup = _sup(tmp_path, alerts, {"expires_at": "2999-01-01T00:00:00Z"})
    spec = _spec(tmp_path, catalog_id="pub/cat", version="1.0")
    fresh = {"expires_at": "2999-01-01T00:00:00Z"}

    async def go():
        sup._specs["cat"], sup._procs["cat"], sup._state["cat"] = spec, _FakeProc(), "running"
        await sup.set_index(fresh)
        assert sup.state("cat") == "running"
        await sup.set_index({"expires_at": "2000-01-01T00:00:00Z"})
        expired = sup.state("cat")
        sup._procs["cat"], sup._state["cat"] = _FakeProc(), "running"
        await sup.set_index({**fresh, "revoked": [{"id": "pub/cat", "version": "1.0"}]})
        return expired

    assert asyncio.run(go()) == "index_expired"
    assert ("cat", "index_expired", "index_expired") in alerts
    assert sup.state("cat") == "revoked" and ("cat", "revoked", "revoked_in_index") in alerts
    other = _sup(tmp_path, [], {**fresh, "revoked": [{"id": "pub/cat"}]})
    assert other.admit(spec) == "revoked"
    assert _sup(tmp_path, [], fresh).admit(spec) is None


def test_a_catalog_plugin_without_a_code_digest_is_refused_but_a_local_one_is_not(tmp_path):
    alerts = []
    sup = _sup(tmp_path, alerts, {"expires_at": "2999-01-01T00:00:00Z"})
    assert asyncio.run(sup.enable(_spec(tmp_path, digest=None))) == "integrity"
    assert ("cat", "integrity", "no_code_digest") in alerts and sup.process("cat") is None


def test_exports_refuse_agent_instruction_names_and_agent_control_folders(tmp_path):
    from src.cplugs.runtime import fsguard

    for name in ("CLAUDE.md", "agents.MD", "Gemini.md"):
        with pytest.raises(fsguard.UnsafePath):
            fsguard.check_export_name(name)
    assert fsguard.check_export_name("report.md") == "report.md"
    home = tmp_path / "home"
    for part in (".claude", ".codex", ".carnivore", ".local/bin", "bin"):
        (home / part).mkdir(parents=True)
        with pytest.raises(fsguard.UnsafePath):
            fsguard.check_export_folder(str(home / part), home, [home / part])
