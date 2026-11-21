
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.config import settings as app_settings
from src.core.argent import health, rollout, row_state, rollout_store, settings as argent_settings
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.rebuild import CannotRebuild
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.device_login import DeviceLogin
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.budget_hold import gate
from src.core.budget_hold.store import HoldStore
from src.core.session_resume_target import CONVERSATION_NONE_RECORDED, CONVERSATION_RESUMED, ResumeTarget
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT, ConversationPresence
from src.plugins.sdk import ports

NOW = 1_000_000.0
TENANT = "ten_1"


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


class Keychain:
    def write_password(self, *a: Any, **k: Any) -> None: ...
    def read_password(self, *a: Any) -> Any: return None
    def delete_password(self, *a: Any) -> bool: return False


def info(name: str, **over: Any) -> SimpleNamespace:
    base = dict(tmux_session=name, agent_family="claude", session=SimpleNamespace(id=f"ses_{name}", working_dir="/w"), session_row_id=abs(hash(name)) % 1000 + 1,
                activity_status="idle", activity_hint=None, startup_gate="ready", subagents_running=0, background_open=0, host_key=None)
    base.update(over)
    return SimpleNamespace(**base)


class Manager:

    def __init__(self, tmp: Path, infos: List[Any]) -> None:
        self.infos = {i.tmux_session: i for i in infos}
        self.calls: List[Dict[str, Any]] = []
        self.held_during: Dict[str, bool] = {}
        self.target = lambda name: ResumeTarget(outcome=CONVERSATION_RESUMED, claude_session_uuid=f"uuid-{name}")
        self.result = lambda name: {"ok": True, "kind": "agent", "conversation": CONVERSATION_RESUMED, "identity_status": "unchanged"}
        self.raises: Dict[str, Exception] = {}
        self._attention_watcher = SimpleNamespace(observation_for=lambda sid: SimpleNamespace(stale=False, evidence=None))

    def tmux_socket_name(self) -> str: return "test-sock"
    async def list_session_infos(self) -> List[Any]: return list(self.infos.values())
    async def get_session_info(self, sid: str) -> Any: return next((i for i in self.infos.values() if i.session.id == sid), None)
    def _resume_target_for_tmux_name(self, name: str, socket: str) -> ResumeTarget: return self.target(name)

    async def respawn_session(self, name: str, **kw: Any) -> Dict[str, Any]:
        self.calls.append({"name": name, **kw})
        row = self.infos[name].session_row_id
        self.held_during[name] = gate.hold_check(row, "\r", "idle", "ready").held
        if name in self.raises:
            raise self.raises[name]
        return self.result(name)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    box: Dict[str, Any] = {"cfg": argent_settings.ArgentSettings(server_url="https://cp.test", gateway_url="https://gw.test", enabled=True), "now": NOW,
                           "quiet": 600.0, "tmp": tmp_path, "state": state, "probes": 0, "sizes": {}}
    monkeypatch.setattr(argent_settings, "read", lambda path=None: box["cfg"])
    monkeypatch.setattr(rollout.settings_module, "read", lambda path=None: box["cfg"])
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login(TENANT, "id_1", "Fixture Person", 3600)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    holds = HoldStore(state / "holds.db")
    monkeypatch.setattr(rollout, "STORE", holds)
    monkeypatch.setattr(gate, "STORE", holds)
    monkeypatch.setattr(gate, "switch_on", lambda: True)
    box["holds"] = holds
    ports.register(PORT_NAME, {"on": True})

    def presence(family, uuid, working_dir=None, **kw):
        name = uuid.removeprefix("uuid-")
        size = box["sizes"].get(name, 1000)
        if size is None:
            return ConversationPresence(CONVERSATION_ABSENT)
        path = tmp_path / f"{name}.jsonl"
        path.write_bytes(b"x" * size)
        return ConversationPresence(CONVERSATION_PRESENT, path=path)

    monkeypatch.setattr(rollout, "family_conversation_presence", presence)

    async def probe():
        box["probes"] += 1
        report = health.HealthReport(state=health.UP, mints_accepted=True, checked_at=box["now"], body_cap_bytes=box.get("cap"))
        health._poller.latest = report
        return report

    def engine(manager: Manager) -> rollout.RolloutEngine:
        evidence = SimpleNamespace(quiet_seconds=lambda name: _async(box["quiet"]))
        return rollout.RolloutEngine(manager, evidence=evidence, clock=lambda: box["now"], probe=probe)

    box["engine"] = engine
    yield box
    ports.unregister(PORT_NAME)
    set_runtime(None)
    run(rollout.stop())


async def _async(value: Any) -> Any:
    return value


def start(direction: str = "on") -> int:
    return run(rollout.begin(direction))["epoch"]


def states(epoch: int | None = None) -> Dict[str, Any]:
    roll = rollout_store.current(TENANT)
    return {r["tmux_name"]: (r["state"], r["reason"]) for r in rollout_store.rows(TENANT, epoch or roll["epoch"])}


def test_only_an_idle_quiet_row_with_nothing_open_restarts(env):
    rows = [info("a"), info("working", activity_status="working"), info("sub", subagents_running=1), info("bg", background_open=2),
            info("unmeasured", subagents_running=None), info("dialog", startup_gate="trust"), info("hint", activity_hint="shell")]
    mgr = Manager(env["tmp"], rows)
    start()
    assert run(env["engine"](mgr).run_pass()) == rollout.RAN
    assert [c["name"] for c in mgr.calls] == ["a"]
    call = mgr.calls[0]
    assert call["live_restart_confirmed"] is True and call["require_agent_resume"] is True and call["argent_rebuild"] is True
    assert call["live_restart_reason"] == "argent_rollout"
    got = states()
    assert got["a"][0] == "restarted" and got["working"] == ("pending", "busy") and got["sub"] == ("pending", "busy") and got["bg"] == ("pending", "busy")
    assert got["unmeasured"] == ("pending", "busy") and got["dialog"] == ("pending", "startup dialog") and got["hint"] == ("pending", "busy")
    with pytest.raises(AssertionError):
        assert "working" in [c["name"] for c in mgr.calls]


def test_a_row_quiet_under_120_seconds_waits_and_a_dead_pane_respawns_without_the_kill_flag(env):
    mgr = Manager(env["tmp"], [info("a")])
    env["quiet"] = 119.0
    start()
    run(env["engine"](mgr).run_pass())
    assert mgr.calls == [] and states()["a"] == ("pending", "busy")
    mgr2 = Manager(env["tmp"], [info("husk", activity_status="dead")])
    env["quiet"] = 0.0
    start()
    run(env["engine"](mgr2).run_pass())
    assert len(mgr2.calls) == 1 and mgr2.calls[0]["live_restart_confirmed"] is False and mgr2.calls[0]["live_restart_reason"] is None


def test_three_rows_per_pass_and_a_finished_row_never_restarts_again_after_a_server_restart(env):
    mgr = Manager(env["tmp"], [info(n) for n in "abcde"])
    start()
    run(env["engine"](mgr).run_pass())
    assert len(mgr.calls) == 3
    run(env["engine"](mgr).run_pass())
    assert sorted(c["name"] for c in mgr.calls) == list("abcde") and len(mgr.calls) == 5
    assert rollout_store.current(TENANT)["state"] == "done"
    run(env["engine"](mgr).run_pass())
    assert len(mgr.calls) == 5
    with pytest.raises(AssertionError):
        assert len(Manager(env["tmp"], []).calls) == 3


def test_the_pass_holds_the_prompt_gate_while_it_restarts_and_leaves_no_hold_behind(env):
    mgr = Manager(env["tmp"], [info("a"), info("b")])
    mgr.raises["b"] = RuntimeError("pane died")
    start()
    run(env["engine"](mgr).run_pass())
    assert mgr.held_during == {"a": True, "b": True}
    assert not env["holds"].any_hold()
    assert gate.hold_check(mgr.infos["a"].session_row_id, "\r", "idle", "ready").held is False
    assert states()["b"][0] == "failed"
    with pytest.raises(AssertionError):
        assert mgr.held_during == {"a": False, "b": False}


def test_a_stale_hold_from_a_crashed_pass_is_swept_at_the_next_pass(env):
    env["holds"].set_hold("rollout:7", "the gateway rollout", ["7"], TENANT)
    env["holds"].set_hold("wi_1", "a budget item", ["7"], TENANT)
    start()
    run(env["engine"](Manager(env["tmp"], [])).run_pass())
    assert [h["item_id"] for h in env["holds"].snapshot()] == ["wi_1"]


def test_a_missing_or_empty_transcript_fails_only_that_row(env):
    mgr = Manager(env["tmp"], [info("gone"), info("empty"), info("ok")])
    env["sizes"].update(gone=None, empty=0)
    start()
    run(env["engine"](mgr).run_pass())
    assert [c["name"] for c in mgr.calls] == ["ok"]
    assert states()["gone"] == ("failed", "conversation not resumed") and states()["empty"] == ("failed", "conversation not resumed")
    assert states()["ok"][0] == "restarted"
    mgr.target = lambda name: ResumeTarget(outcome=CONVERSATION_NONE_RECORDED)
    mgr2 = Manager(env["tmp"], [info("new")])
    mgr2.target = mgr.target
    start()
    run(env["engine"](mgr2).run_pass())
    assert mgr2.calls == [] and states()["new"] == ("pending", "no conversation yet")


def test_a_restart_that_did_not_resume_fails_the_row_not_the_pass(env):
    mgr = Manager(env["tmp"], [info("a"), info("b")])
    mgr.result = lambda name: {"ok": True, "kind": "agent", "conversation": "none_recorded"} if name == "a" else {
        "ok": True, "kind": "agent", "conversation": CONVERSATION_RESUMED, "identity_status": "unchanged"}
    start()
    run(env["engine"](mgr).run_pass())
    assert states()["a"] == ("failed", "conversation not resumed") and states()["b"][0] == "restarted"
    mgr.result = lambda name: {"ok": True, "kind": "agent", "conversation": CONVERSATION_RESUMED, "identity_status": "cannot_determine"}
    mgr2 = Manager(env["tmp"], [info("c")])
    mgr2.result = mgr.result
    start()
    run(env["engine"](mgr2).run_pass())
    assert states()["c"] == ("failed", "conversation not resumed")


def test_a_transcript_over_80_percent_of_the_cap_waits_until_the_cap_is_raised(env):
    env["cap"] = 1000
    env["now"] = NOW + 100
    env["sizes"].update(big=801, fits=800)
    mgr = Manager(env["tmp"], [info("big"), info("fits")])
    start()
    run(env["engine"](mgr).run_pass())
    assert env["probes"] == 1
    assert [c["name"] for c in mgr.calls] == ["fits"] and states()["big"] == ("pending", "too large for gateway cap")
    env["cap"] = None
    health._poller.latest = health.HealthReport(state=health.UP, mints_accepted=True, checked_at=env["now"], body_cap_bytes=None)
    run(env["engine"](mgr).run_pass())
    assert [c["name"] for c in mgr.calls] == ["fits", "big"]


def test_a_stale_or_unready_probe_restarts_nothing_and_each_row_says_why(env):
    health._poller.latest = health.HealthReport(state=health.DOWN, checked_at=NOW)

    async def down():
        return health.HealthReport(state=health.DOWN, checked_at=env["now"])

    mgr = Manager(env["tmp"], [info("a")])
    start()
    engine = rollout.RolloutEngine(mgr, evidence=SimpleNamespace(quiet_seconds=lambda n: _async(600.0)), clock=lambda: env["now"], probe=down)
    run(engine.run_pass())
    assert mgr.calls == [] and states()["a"] == ("pending", "argent down at launch")
    assert rollout.gate_reason(health.HealthReport(state=health.UP, mints_accepted=False, checked_at=NOW), NOW) == "argent down at launch"
    assert rollout.gate_reason(health.HealthReport(state=health.UP, mints_accepted=True, checked_at=NOW - 61), NOW) == "argent down at launch"
    assert rollout.gate_reason(health.HealthReport(state=health.UP, mints_accepted=True, checked_at=NOW), NOW) == ""


def test_a_row_busy_over_24_hours_is_parked_and_a_paused_or_cancelled_rollout_does_nothing(env):
    mgr = Manager(env["tmp"], [info("a", activity_status="working")])
    start()
    run(env["engine"](mgr).run_pass())
    env["now"] += rollout.PARK_AFTER_SECONDS + 1
    health._poller.latest = health.HealthReport(state=health.UP, mints_accepted=True, checked_at=env["now"])
    run(env["engine"](mgr).run_pass())
    assert states()["a"] == ("parked", "busy")
    assert rollout.view_sync(TENANT)["rows"] == [{"tmux_name": "a", "state": "pending", "reason": "busy"}]
    mgr.infos["a"].activity_status = "idle"
    run(env["engine"](mgr).run_pass())
    assert mgr.calls == []
    start()
    assert run(rollout.pause("paused: gateway errors")) is True
    run(env["engine"](mgr).run_pass())
    assert mgr.calls == [] and rollout_store.current(TENANT)["state"] == "paused"
    assert run(rollout.resume()) is True
    run(env["engine"](mgr).run_pass())
    assert len(mgr.calls) == 1
    start()
    assert run(rollout.cancel()) is True
    mgr.infos["a"].session_row_id += 1
    run(env["engine"](mgr).run_pass())
    assert len(mgr.calls) == 1


def test_the_switch_turned_off_mid_rollout_cancels_it(env):
    mgr = Manager(env["tmp"], [info("a")])
    start("on")
    env["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.test", gateway_url="https://gw.test", enabled=False)
    assert run(env["engine"](mgr).run_pass()) == rollout.CANCELLED_BY_SWITCH
    assert mgr.calls == [] and rollout_store.current(TENANT)["state"] == "cancelled"


def test_off_direction_resets_tethered_rows_with_argent_down_and_leaves_direct_rows_alone(env):
    env["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.test", gateway_url="https://gw.test", enabled=False)
    health._poller.latest = health.HealthReport(state=health.DOWN, checked_at=0.0)
    row_state.record_launch(TENANT, "tethered", working_dir="/w", tethered=True, reason="", key_id="k1")
    row_state.confirm(TENANT, "tethered")
    mgr = Manager(env["tmp"], [info("tethered"), info("direct")])
    start("off")
    run(env["engine"](mgr).run_pass())
    assert [c["name"] for c in mgr.calls] == ["tethered"] and mgr.calls[0]["argent_rebuild"] is False
    assert states()["tethered"] == ("restarted", "direct") and states()["direct"] == ("restarted", "direct")
    assert env["probes"] == 0
    assert row_state.lookup(TENANT, "tethered")["state"] == ""


def test_rows_already_tethered_or_with_a_reason_no_restart_changes_are_not_restarted(env):
    row_state.record_launch(TENANT, "ok", working_dir="/w", tethered=True, reason="", key_id="k1")
    row_state.confirm(TENANT, "ok")
    row_state.record_launch(TENANT, "ovr", working_dir="/w", tethered=False, reason="settings override", key_id="")
    row_state.confirm(TENANT, "ovr")
    row_state.record_launch(TENANT, "late", working_dir="/w", tethered=False, reason="argent down at launch", key_id="")
    row_state.confirm(TENANT, "late")
    mgr = Manager(env["tmp"], [info("ok"), info("ovr"), info("late")])
    start()
    run(env["engine"](mgr).run_pass())
    assert [c["name"] for c in mgr.calls] == ["late"]
    assert states()["ok"] == ("restarted", "pending first traffic") and states()["ovr"] == ("excluded", "settings override")


def test_an_unrebuildable_row_is_listed_never_killed_and_a_codex_or_remote_row_is_scoped(env):
    mgr = Manager(env["tmp"], [info("adopted"), info("far", host_key="peer-1"), info("shell", agent_family=None), info("cx", agent_family="codex")])
    mgr.raises["adopted"] = CannotRebuild("unknown flag --weird")
    start()
    run(env["engine"](mgr).run_pass())
    assert states()["adopted"] == ("excluded", "cannot rebuild launch command: unknown flag --weird")
    assert set(states()) == {"adopted", "cx"} and [c["name"] for c in mgr.calls] == ["adopted", "cx"]


def test_the_view_counts_states_and_reasons(env):
    mgr = Manager(env["tmp"], [info("a"), info("b", activity_status="working")])
    start()
    run(env["engine"](mgr).run_pass())
    view = rollout.view_sync(TENANT)
    assert view["state"] == "running" and view["direction"] == "on"
    assert view["counts"] == {"restarted": 1, "pending": 1} and view["reasons"]["busy"] == 1


def test_with_the_feature_off_no_pass_acts_no_timer_starts_and_no_rollout_runs(env):
    ports.unregister(PORT_NAME)
    mgr = Manager(env["tmp"], [info("a")])
    start()
    assert run(env["engine"](mgr).run_pass()) == rollout.FEATURE_OFF and mgr.calls == []
    assert rollout.is_running() is False

    async def go() -> bool:
        rollout.bind(SimpleNamespace(session_manager=mgr))
        await rollout.resume_at_boot()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if not rollout.is_running():
                break
        return rollout.is_running()

    assert run(go()) is False and mgr.calls == []
    ports.register(PORT_NAME, {"on": True})


def test_no_timer_exists_without_a_running_rollout(env):
    async def go() -> bool:
        rollout.bind(SimpleNamespace(session_manager=Manager(env["tmp"], [])))
        await rollout.resume_at_boot()
        return rollout.is_running()

    assert run(go()) is False


def _tether(name: str, tethered: bool, reason: str = "") -> None:
    row_state.record_launch(TENANT, name, working_dir="/w", tethered=tethered, reason=reason, key_id="")
    row_state.confirm(TENANT, name)


def test_the_preview_counts_what_a_rollout_would_do_and_sorts_like_the_engine(env):
    from src.core.argent import rollout_preview
    rows = [info("fresh"), info("busy", subagents_running=2, background_open=1), info("adopt", session=SimpleNamespace(id="adopted:adopt", working_dir="/w")),
            info("fixed"), info("on"), info("remote", host_key="peer")]
    _tether("fixed", False, "settings override")
    _tether("on", True)
    mgr = Manager(env["tmp"], rows)
    got = run(rollout_preview.preview(mgr, TENANT, "on"))
    assert (got["total"], got["pending"], got["will_restart"], got["adopted"], got["subagents"], got["background"]) == (5, 1, 3, 1, 2, 1)
    assert got["excluded"] == {"settings override": 1} and got["reasons"] == {"settings override": 1}
    off = run(rollout_preview.preview(mgr, TENANT, "off"))
    assert off["will_restart"] == 1 and off["excluded"] == {}
    assert run(rollout_preview.preview(mgr, "", "on"))["will_restart"] == 5
    assert mgr.calls == []
    with pytest.raises(AssertionError):
        assert got["will_restart"] == 4


def test_restart_now_restarts_one_busy_waiting_row_past_the_idle_gates_but_keeps_the_conversation_rules(env):
    mgr = Manager(env["tmp"], [info("busy", activity_status="working"), info("gone"), info("done")])
    env["sizes"]["gone"] = None
    start()
    run(env["engine"](mgr).run_pass())
    assert mgr.calls == [] or "busy" not in [c["name"] for c in mgr.calls]
    assert states()["busy"] == ("pending", "busy")
    engine = env["engine"](mgr)
    assert run(engine.restart_now("busy")) == "ok"
    call = next(c for c in mgr.calls if c["name"] == "busy")
    assert call["live_restart_confirmed"] is True and call["require_agent_resume"] is True and call["live_restart_reason"] == "argent_rollout"
    assert states()["busy"][0] == "restarted" and mgr.held_during["busy"] is True
    assert run(engine.restart_now("busy")) == "not_open"
    assert run(engine.restart_now("nope")) == "not_open"
    assert states()["gone"][0] == "failed"
    assert run(engine.restart_now("gone")) == "not_open"
    mgr2 = Manager(env["tmp"], [info("w", activity_status="working")])
    env["sizes"]["w"] = None
    start()
    run(env["engine"](mgr2).run_pass())
    assert run(env["engine"](mgr2).restart_now("w")) == "refused" and mgr2.calls == []
    with pytest.raises(AssertionError):
        assert mgr2.calls
