
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import pytest

from src.cplugs.runtime import process as process_mod
from src.cplugs.runtime import supervisor as sup_mod
from src.cplugs.runtime import watchdog
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.runtime.process import PluginSpec

PID = "acme-clock"


class Clock:

    def __init__(self) -> None:
        self.now = 0.0
        self.timers: List[Any] = []

    def __call__(self) -> float:
        return self.now

    def call_later(self, delay: float, fn: Callable[..., Any], *args: Any) -> Any:
        timer = SimpleNamespace(at=self.now + delay, fn=fn, args=args, cancelled=False)
        timer.cancel = lambda: setattr(timer, "cancelled", True)
        self.timers.append(timer)
        return timer

    async def advance(self, seconds: float) -> None:
        end = self.now + seconds
        while True:
            due = [t for t in self.timers if not t.cancelled and t.at <= end]
            if not due:
                break
            timer = min(due, key=lambda t: t.at)
            self.now = max(self.now, timer.at)
            self.timers.remove(timer)
            timer.fn(*timer.args)
            for _ in range(10):
                await asyncio.sleep(0)
        self.now = end


class FakeProc:

    spawned: List["FakeProc"] = []

    def __init__(self, spec, layout, dispatcher, app_version, on_exit, sampler) -> None:
        self.spec, self._on_exit = spec, on_exit
        self.ended = None
        self.busy = 0
        self.started = False
        self.pid = 4000 + len(FakeProc.spawned)
        self.stops: List[str] = []
        FakeProc.spawned.append(self)

    async def start(self) -> None:
        await asyncio.sleep(0)
        self.started = True

    async def stop(self, reason: str = "disabled") -> None:
        self.stops.append(reason)
        await self.crash(reason)

    async def kill(self, reason: str = "killed") -> None:
        await self.crash(reason)

    async def crash(self, reason: str) -> None:
        if not self.ended:
            self.ended = reason
            await self._on_exit(reason)


def spec() -> PluginSpec:
    ctx = PluginContext(plugin_id=PID, install_key="uuid-1", data_dir=Path("/nonexistent"), granted=frozenset(), manifest_tools=(), tier="local")
    return PluginSpec(ctx=ctx, code_dir=Path("/nonexistent"), entry="main", code_digest=None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    FakeProc.spawned = []
    monkeypatch.setattr(sup_mod, "PluginProcess", FakeProc)
    monkeypatch.setattr(sup_mod.Supervisor, "_layout", lambda self, s: None)
    clock, alerts = Clock(), []
    sup = sup_mod.Supervisor(tmp_path, "1.0", HostDispatcher(HostServices(activity=lambda e: None), OwnerTokens()),
                             lambda *a: alerts.append(a), lambda pid: {}, lambda e: None, safe_mode=False,
                             clock=clock, call_later=clock.call_later)
    return SimpleNamespace(sup=sup, clock=clock, alerts=alerts)


def strikes(sup: sup_mod.Supervisor) -> int:
    ledger = sup._strikes.get(PID)
    return 0 if ledger is None else len(ledger._times)


def test_an_enabled_plugin_without_subscriptions_has_no_process(world):
    state = asyncio.run(world.sup.activate(spec()))
    assert state == "idle" and world.sup.process(PID) is None and FakeProc.spawned == []
    assert world.sup.available(PID)
    live = PluginSpec(ctx=spec().ctx, code_dir=Path("/x"), entry="main", subscriptions=frozenset({"feed.meta"}))
    assert asyncio.run(world.sup.activate(live)) == "running" and len(FakeProc.spawned) == 1


def test_the_first_call_spawns_one_process_and_a_held_off_plugin_never_starts(world):
    async def go():
        await world.sup.activate(spec())
        proc = await world.sup.ensure(PID)
        assert proc is FakeProc.spawned[0] and world.sup.state(PID) == "running"
        assert await world.sup.ensure(PID) is proc and len(FakeProc.spawned) == 1
        await world.sup.revoke(PID)
        assert await world.sup.ensure(PID) is None and len(FakeProc.spawned) == 1

    asyncio.run(go())


def test_two_concurrent_first_calls_spawn_one_process(world):
    async def go():
        await world.sup.activate(spec())
        async def call():
            proc = await world.sup.ensure(PID)
            return proc, proc.started

        (a, ready_a), (b, ready_b) = await asyncio.gather(call(), call())
        assert a is b and len(FakeProc.spawned) == 1
        assert ready_a and ready_b

    asyncio.run(go())


def test_ten_idle_minutes_evicts_and_the_next_call_respawns(world):
    async def go():
        await world.sup.activate(spec())
        first = await world.sup.ensure(PID)
        await world.clock.advance(300)
        await world.sup.ensure(PID)
        await world.clock.advance(300)
        assert world.sup.process(PID) is first and world.sup.state(PID) == "running"
        first.busy = 1
        await world.clock.advance(400)
        assert world.sup.process(PID) is first
        first.busy = 0
        await world.clock.advance(601)
        assert world.sup.process(PID) is None and world.sup.state(PID) == "idle"
        assert first.stops == ["idle"] and strikes(world.sup) == 0 and world.alerts == []
        second = await world.sup.ensure(PID)
        assert second is not first and len(FakeProc.spawned) == 2 and strikes(world.sup) == 0
        assert len([t for t in world.clock.timers if not t.cancelled]) == 1

    asyncio.run(go())


def test_kill_minus_nine_adds_a_strike(world):
    async def go():
        await world.sup.activate(spec())
        proc = await world.sup.ensure(PID)
        await proc.crash("exited")
        assert strikes(world.sup) == 1 and world.sup.state(PID) == "backing_off"
        assert not [t for t in world.clock.timers if not t.cancelled]
        world.sup._restarts.pop(PID).cancel()

    asyncio.run(go())


def test_usage_is_read_with_one_ps_fork(monkeypatch):
    calls: List[List[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="  2048 1-02:03:04.50\n")

    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    usage = watchdog.usage_of(42)
    assert len(calls) == 1 and usage == watchdog.Usage(2048 * 1024, 86400 + 2 * 3600 + 3 * 60 + 4.5)
    monkeypatch.setattr(watchdog.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout=""))
    assert watchdog.usage_of(42) is None
    assert (watchdog.next_delay(False, 120.0), watchdog.next_delay(True, 120.0), watchdog.next_delay(False, 5.0)) == (10.0, 1.0, 1.0)


def test_the_watchdog_samples_slowly_when_quiet_and_never_without_a_process(monkeypatch, tmp_path):
    reads: List[int] = []
    monkeypatch.setattr(watchdog, "BUSY_SAMPLE_SECONDS", 0.01)
    monkeypatch.setattr(watchdog, "QUIET_SAMPLE_SECONDS", 0.2)
    monkeypatch.setattr(watchdog, "WARMUP_SECONDS", 0.0)

    def sampler(pid: int):
        reads.append(pid)
        return watchdog.Usage(1024, 0.0)

    def build() -> process_mod.PluginProcess:
        layout = SimpleNamespace(files_dir=tmp_path)
        return process_mod.PluginProcess(spec(), layout, None, "1.0", lambda reason: asyncio.sleep(0), sampler)

    async def window(proc, seconds: float) -> None:
        task = asyncio.create_task(proc._watch())
        await asyncio.sleep(seconds)
        proc.ended = "test"
        proc._busy_wake.set()
        await asyncio.wait_for(task, 2)

    async def go():
        none = build()
        await window(none, 0.1)
        assert reads == []
        quiet = build()
        quiet._proc = SimpleNamespace(pid=77)
        await window(quiet, 0.1)
        assert len(reads) <= 1
        reads.clear()
        busy = build()
        busy._proc = SimpleNamespace(pid=78)
        busy.busy = 1
        await window(busy, 0.1)
        assert len(reads) >= 4 and set(reads) == {78}

    asyncio.run(go())



def catalog_spec(subs=frozenset(), tier="catalog") -> PluginSpec:
    ctx = PluginContext(plugin_id=PID, install_key="uuid-1", data_dir=Path("/nonexistent"), granted=frozenset(), manifest_tools=(), tier=tier)
    return PluginSpec(ctx=ctx, code_dir=Path("/nonexistent"), entry="main", code_digest=None if tier == "local" else "d", subscriptions=subs, catalog_id=PID, version="1.0.0")


def test_a_burst_of_calls_samples_at_most_once_per_busy_interval(monkeypatch, tmp_path):
    reads: List[int] = []
    monkeypatch.setattr(watchdog, "BUSY_SAMPLE_SECONDS", 0.1)
    monkeypatch.setattr(watchdog, "QUIET_SAMPLE_SECONDS", 5.0)
    monkeypatch.setattr(watchdog, "WARMUP_SECONDS", 0.0)
    proc = process_mod.PluginProcess(spec(), SimpleNamespace(files_dir=tmp_path), None, "1.0", lambda r: asyncio.sleep(0),
                                     lambda pid: reads.append(pid) or watchdog.Usage(1024, 0.0))
    proc._proc = SimpleNamespace(pid=9)

    async def go():
        task = asyncio.create_task(proc._watch())
        for _ in range(100):
            proc.busy = 1
            proc._busy_wake.set()
            await asyncio.sleep(0.005)
        proc.ended = "test"
        proc._busy_wake.set()
        await asyncio.wait_for(task, 2)

    asyncio.run(go())
    assert 1 <= len(reads) <= 8, len(reads)


def test_the_manifest_declares_subscriptions_and_the_spec_carries_them():
    from src.cplugs.host import sidecar_manifest as man
    from src.cplugs.host.sidecar_spec import build_spec

    base = {"schema": 1, "id": "clock", "name": "Clock", "description": "d", "version": "1.0.0", "entry": "main.py", "tools": []}
    assert man.parse_sidecar_manifest(base, "clock", "dg").subscriptions == ()
    m = man.parse_sidecar_manifest({**base, "subscriptions": ["feed.meta"]}, "clock", "dg")
    assert m.subscriptions == ("feed.meta",)
    d = SimpleNamespace(id="clock", install_key="k", folder=Path("/x"), code_root=Path("/x"), item_id="clock", manifest=m)
    assert build_spec(d, frozenset(), {}).subscriptions == frozenset({"feed.meta"})
    for bad in (["nope"], "feed.meta", ["feed.meta", "feed.meta"]):
        with pytest.raises(man.SidecarManifestError):
            man.parse_sidecar_manifest({**base, "subscriptions": bad}, "clock", "dg")


def test_a_subscriber_is_never_idle_evicted_and_an_event_ensures_the_process(world):
    async def go():
        sub = catalog_spec(frozenset({"feed.meta"}), tier="local")
        world.sup._specs[PID] = sub
        await world.sup._spawn(sub)
        assert [t for t in world.clock.timers if not t.cancelled] == []
        await world.clock.advance(5000)
        assert world.sup.process(PID) is not None and world.sup.state(PID) == "running"
        world.sup._procs.pop(PID).ended = "gone"
        world.sup._state[PID] = "idle"
        sent = []
        FakeProc.deliver_event = lambda self, f, s, p: _async(sent.append(f) or True)
        assert await world.sup.deliver_event(PID, "feed.meta", 1, {}) is True and sent == ["feed.meta"] and len(FakeProc.spawned) == 2

    asyncio.run(go())


async def _async(value):
    return value


def revoking_index():
    return {"revoked": [{"id": PID}]}


def test_an_index_refresh_judges_an_idle_plugin(world):
    async def go():
        sp = catalog_spec()
        world.sup._state[PID] = "idle"
        world.sup._specs[PID] = sp
        fresh = {"expires_at": "2099-01-01T00:00:00Z"}
        await world.sup.set_index(fresh)
        assert world.sup.state(PID) == "idle" and world.alerts == []
        await world.sup.set_index({"expires_at": "2001-01-01T00:00:00Z"})
        assert world.sup.state(PID) == "index_expired" and (PID, "index_expired", "index_expired") in world.alerts
        world.sup._state[PID] = "idle"
        await world.sup.set_index({**fresh, **revoking_index()})
        assert world.sup.state(PID) == "revoked" and (PID, "revoked", "revoked_in_index") in world.alerts and not world.sup.available(PID)

    asyncio.run(go())


def test_safe_mode_turns_an_idle_plugin_off(world):
    async def go():
        await world.sup.activate(spec())
        assert world.sup.state(PID) == "idle" and world.sup.available(PID)
        await world.sup.enter_safe_mode()
        assert world.sup.state(PID) == "disabled (safe mode)" and not world.sup.available(PID)
        assert await world.sup.ensure(PID) is None and FakeProc.spawned == []

    asyncio.run(go())
