
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.config import settings as app_settings
from src.core.argent import health, notices, outage, rollout, row_state, rollout_store, store as argent_store
from src.core.argent.device_login import DeviceLogin
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.session_resume_target import CONVERSATION_RESUMED, ResumeTarget
from src.core.session_transcript_presence import CONVERSATION_PRESENT, ConversationPresence
from src.plugins.sdk import ports, turn_events

NOW = 2_000_000.0
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
    def __init__(self, infos: List[Any]) -> None:
        self.infos = {i.tmux_session: i for i in infos}
        self.calls: List[Dict[str, Any]] = []
        self._attention_watcher = SimpleNamespace(observation_for=lambda sid: SimpleNamespace(stale=False, evidence=None))

    def tmux_socket_name(self) -> str: return "test-sock"
    async def list_session_infos(self) -> List[Any]: return list(self.infos.values())
    async def get_session_info(self, sid: str) -> Any: return next((i for i in self.infos.values() if i.session.id == sid), None)
    def _resume_target_for_tmux_name(self, name: str, socket: str) -> ResumeTarget: return ResumeTarget(outcome=CONVERSATION_RESUMED, claude_session_uuid=f"uuid-{name}")

    async def respawn_session(self, name: str, **kw: Any) -> Dict[str, Any]:
        self.calls.append({"name": name, **kw})
        return {"ok": True, "kind": "agent", "conversation": CONVERSATION_RESUMED, "identity_status": "unchanged"}


class Quiet:
    def __init__(self, manager: Any) -> None: ...
    async def quiet_seconds(self, name: str) -> float: return 600.0


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    box: Dict[str, Any] = {"enabled": True, "tmp": tmp_path, "state": state, "seen": []}
    cfg = lambda path=None: SimpleNamespace(enabled=box["enabled"], server_url="https://cp.test", gateway_url="https://gw.test", ca_path="")
    monkeypatch.setattr(outage.settings_module, "read", cfg)
    monkeypatch.setattr(rollout.settings_module, "read", cfg)
    astore, tokens = ArgentStore(state), TokenStore(Keychain())
    astore.set_login(TENANT, "id_1", "Fixture Person", 3600)
    set_runtime(Runtime(store=astore, tokens=tokens, login=DeviceLogin(astore, tokens)))
    ports.register(PORT_NAME, {"on": True})
    for name in ("outage", "outage_resolved", "key_expiring", "key_expiring_resolved"):
        monkeypatch.setattr(notices, name, lambda *a, _n=name: box["seen"].append((_n, a)))
    monkeypatch.setattr(outage.time, "time", lambda: box["now"] if "now" in box else NOW)
    box["now"] = NOW
    monkeypatch.setattr(rollout, "SessionEvidence", Quiet)
    monkeypatch.setattr(rollout, "family_conversation_presence",
                        lambda family, uuid, working_dir=None, **kw: _present(tmp_path, uuid))
    monkeypatch.setattr(outage, "_state", outage._State())
    yield box
    outage.stop()
    ports.unregister(PORT_NAME)
    set_runtime(None)
    run(rollout.stop())


def _present(tmp: Path, uuid: str) -> ConversationPresence:
    path = tmp / f"{uuid}.jsonl"
    path.write_bytes(b"x" * 100)
    return ConversationPresence(CONVERSATION_PRESENT, path=path)


def tether(*names: str, minted_at: float = NOW) -> None:
    for n in names:
        row_state.record_launch(TENANT, n, working_dir="/w", tethered=True, reason="", key_id=f"key_{n}", clock=lambda: minted_at)
        row_state.confirm(TENANT, n)


def poll(state: str, *, enabled: bool = True, **kw: Any) -> None:
    run(outage.on_report(health.HealthReport(state=state, mints_accepted=True, checked_at=NOW, **kw), enabled))


def names(box: Dict[str, Any]) -> List[str]:
    return [n for n, _ in box["seen"]]


def err(sid: str, status: int, at: float = NOW) -> None:
    outage._state.errors.append((at, sid, status))



def test_three_failed_polls_make_the_gateway_down_and_two_do_not(env):
    tether("a", "b")
    poll(health.DOWN)
    poll(health.DOWN)
    assert not outage.is_active() and names(env) == []
    poll(health.DOWN)
    assert outage.is_active() and outage.view_sync(TENANT)["reason"] == "gateway down"
    assert env["seen"] == [("outage", (2, "gateway down"))]
    poll(health.DOWN)
    assert names(env) == ["outage"]
    outage.reset()
    poll(health.DOWN), poll(health.UP), poll(health.DOWN), poll(health.DOWN)
    assert not outage.is_active()


def test_two_healthy_polls_do_not_end_it_three_do_and_tethering_waits_out_the_cooldown(env):
    tether("a")
    for _ in range(3):
        poll(health.DOWN)
    assert outage.is_active()
    poll(health.UP), poll(health.UP)
    assert outage.is_active()
    poll(health.UP)
    assert not outage.is_active() and "outage_resolved" in names(env)
    assert outage._state.retether_at == NOW + outage.COOLDOWN_SECONDS
    row_state.record_launch(TENANT, "dir", working_dir="/w", tethered=False, reason="argent down at launch", key_id="")
    row_state.confirm(TENANT, "dir")
    assert rollout_store.current(TENANT) is None
    env["now"] = NOW + outage.COOLDOWN_SECONDS + 1
    poll(health.UP)
    roll = rollout_store.current(TENANT)
    assert roll is not None and roll["direction"] == "on" and roll["state"] == rollout_store.RUNNING
    assert outage._state.retether_at is None


def test_a_flap_before_the_cooldown_cancels_the_pending_retether(env):
    tether("a")
    for _ in range(3):
        poll(health.DOWN)
    for _ in range(3):
        poll(health.UP)
    assert outage._state.retether_at is not None
    for _ in range(3):
        poll(health.DOWN)
    assert outage._state.retether_at is None and outage.is_active()
    env["now"] = NOW + 5000
    poll(health.DOWN)
    assert rollout_store.current(TENANT) is None


def test_a_row_tethers_at_most_once_an_hour(env):
    tether("a")
    outage.record_retether(TENANT, "a", "rollout", clock=lambda: NOW)
    assert outage.retether_blocked(TENANT, "a", NOW + 3599)
    assert not outage.retether_blocked(TENANT, "a", NOW + 3601)
    assert not outage.retether_blocked(TENANT, "other", NOW)
    mgr = Manager([info("a")])
    roll = run(rollout.begin("on"))
    engine = rollout.RolloutEngine(mgr, evidence=Quiet(mgr), clock=lambda: NOW + 10,
                                   probe=lambda: _report())
    row_state.clear(TENANT, "a")
    run(engine.run_pass())
    assert mgr.calls == []
    assert {r["tmux_name"]: r["reason"] for r in rollout_store.rows(TENANT, roll["epoch"])}["a"] == rollout.COOLING
    mgr2 = Manager([info("a")])
    engine2 = rollout.RolloutEngine(mgr2, evidence=Quiet(mgr2), clock=lambda: NOW + 4000, probe=lambda: _report())
    run(rollout.begin("on"))
    run(engine2.run_pass())
    assert [c["name"] for c in mgr2.calls] == ["a"]
    assert outage.retether_blocked(TENANT, "a", NOW + 4001)


async def _report():
    r = health.HealthReport(state=health.UP, mints_accepted=True, checked_at=NOW + 4000)
    health._poller.latest = r
    return r



def test_five_errors_from_one_session_or_over_three_sessions_raise_the_banner_four_do_not(env):
    tether("a")
    for _ in range(4):
        err("a", 503)
    run(outage._evaluate(TENANT, NOW))
    assert not outage.is_active()
    err("a", 502)
    run(outage._evaluate(TENANT, NOW))
    assert outage.is_active() and outage.view_sync(TENANT)["reason"] == "gateway errors" and names(env) == ["outage"]
    outage.reset()
    outage._state.errors.clear()
    for sid in ("a", "a", "b", "b", "b"):
        err(sid, 500)
    run(outage._evaluate(TENANT, NOW))
    assert not outage.is_active()
    err("c", 500)
    run(outage._evaluate(TENANT, NOW))
    assert outage.is_active()
    run(outage._evaluate(TENANT, NOW + outage.ERRORS_WINDOW + 1))
    assert not outage.is_active() and "outage_resolved" in names(env)


def test_a_413_pauses_a_running_rollout_and_raises_the_banner_a_plain_500_does_not(env):
    tether("a")
    run(rollout.begin("on"))
    err("a", 500)
    run(outage._evaluate(TENANT, NOW))
    assert rollout_store.current(TENANT)["state"] == rollout_store.RUNNING and not outage.is_active()
    err("a", 413)
    run(outage._evaluate(TENANT, NOW))
    roll = rollout_store.current(TENANT)
    assert roll["state"] == rollout_store.PAUSED and roll["reason"] == "gateway errors" and outage.is_active()
    assert outage.view_sync(TENANT)["rollout_paused"] is True
    run(outage._evaluate(TENANT, NOW + outage.ERRORS_WINDOW + 1))
    assert rollout_store.current(TENANT)["state"] == rollout_store.RUNNING


def test_transcript_scan_reads_only_new_gateway_errors(env, tmp_path):
    def rec(status: Any, at: float = NOW, flag: bool = True) -> str:
        from datetime import datetime, timezone
        return json.dumps({"type": "assistant", "isApiErrorMessage": flag, "apiErrorStatus": status, "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat()}) + "\n"
    path = tmp_path / "t.jsonl"
    path.write_text(rec(413) + rec(503) + rec(400) + rec(500, flag=False) + rec(502, at=NOW - 600) + "not json\n")
    assert sorted(s for _, s in outage.scan_transcript(path, "k", NOW)) == [413, 503]
    assert outage.scan_transcript(path, "k", NOW) == []
    with open(path, "a") as f:
        f.write(rec(504))
    assert [s for _, s in outage.scan_transcript(path, "k", NOW)] == [504]



def test_restart_direct_restarts_idle_tethered_rows_only_and_needs_an_outage(env):
    tether("idle", "busy", "direct")
    row_state.record_launch(TENANT, "direct", working_dir="/w", tethered=False, reason="argent down at launch", key_id="")
    row_state.confirm(TENANT, "direct")
    mgr = Manager([info("idle"), info("busy", activity_status="working"), info("direct")])
    with pytest.raises(LookupError):
        run(outage.restart_direct(mgr))
    for _ in range(3):
        poll(health.DOWN)
    result = run(outage.restart_direct(mgr))
    assert result == {"restarted": 1, "waiting": {"busy": 1}}
    assert [c["name"] for c in mgr.calls] == ["idle"]
    call = mgr.calls[0]
    assert call["argent_rebuild"] is False and call["require_agent_resume"] is True and call["live_restart_confirmed"] is True



def test_a_key_near_expiry_warns_once_and_its_row_becomes_a_restart_candidate(env):
    old = NOW - (outage.KEY_TTL_SECONDS - outage.KEY_WARN_LEAD_SECONDS) - 1
    tether("old", minted_at=old)
    tether("fresh")
    assert outage.expiring_refs(TENANT, NOW) == {"old"}
    poll(health.UP)
    poll(health.UP)
    assert names(env).count("key_expiring") == 1 and env["seen"][0] == ("key_expiring", (1,))
    roll = rollout_store.current(TENANT)
    assert roll is not None and roll["direction"] == "on"
    mgr = Manager([info("old"), info("fresh")])
    run(rollout.RolloutEngine(mgr, evidence=Quiet(mgr), clock=lambda: NOW, probe=lambda: _report()).run_pass())
    assert [c["name"] for c in mgr.calls] == ["old"]



def test_the_switch_off_and_the_feature_off_do_nothing(env):
    tether("a")
    env["enabled"] = False
    for _ in range(5):
        poll(health.DOWN, enabled=False)
    assert not outage.is_active() and outage._state.failures == 0 and env["seen"] == [] and rollout_store.current(TENANT) is None
    with pytest.raises(AssertionError):
        for _ in range(5):
            poll(health.DOWN)
        assert not outage.is_active()
    outage.reset()
    seen_before = len(turn_events._listeners)
    outage.stop()
    assert len(turn_events._listeners) == seen_before and not outage.is_running()

    async def go() -> None:
        outage.start()
        outage.start()
        assert outage.is_running() and len(turn_events._listeners) == seen_before + 1
        outage.stop()
        assert len(turn_events._listeners) == seen_before
    run(go())


def test_a_turn_end_with_the_switch_off_reads_no_transcript(env, monkeypatch):
    env["enabled"] = False
    from src.core.argent import fallback_spend
    mgr = Manager([info("a")])
    monkeypatch.setattr(fallback_spend, "_manager", mgr)
    tether("a")
    monkeypatch.setattr(outage, "scan_transcript", lambda *a: pytest.fail("a transcript was read with the switch off"))
    assert run(outage.handle_turn_end("ses_a")) == 0
