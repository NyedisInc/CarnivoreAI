
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.api import sleep_hold_listing
from src.core import session_sleep
from src.core.agy import identity as agy_identity
from src.core.agy import transcripts as agy_transcripts
from src.core.auto_sleep.idle_seed import SOURCE_AGY_STORE, SOURCE_AGY_TRANSCRIPT
from src.core.auto_sleep.idle_seed_paths import resolve_agy_seed
from src.core.auto_sleep.live_work import hold_for
from src.core.conversation_writers import Proc
from src.models import SessionInfo
from tests.test_auto_sleep_sleeper import _add, _run, clean_evidence, world  # noqa: F401

AGY_UUID = "00000000-0000-4000-8000-000000000001"


def _stub_agy_profiles(monkeypatch):
    profiles = [
        SimpleNamespace(id="antigravity", agent=SimpleNamespace(process="agy", rules="agy")),
        SimpleNamespace(id="opencode", agent=SimpleNamespace(process="opencode", rules="opencode")),
    ]
    real = agy_identity.row_is_agy
    monkeypatch.setattr(agy_identity, "row_is_agy", lambda row, profiles_=None: real(row, profiles))


def _make_agy(world, monkeypatch, *, n=1, direct_pane=False, agy_listening=True, child_listening=False, agent_type="antigravity"):
    _stub_agy_profiles(monkeypatch)
    sid, uuid = _add(world, n=n, family="custom", conv=AGY_UUID)
    info = world.manager.infos[sid]
    info.agent_type = agent_type
    info.session.agent_type = agent_type
    pane_pid = 1000 + n
    world.procs = [p for p in world.procs if p.pid not in (pane_pid, pane_pid + 100, pane_pid + 200)]
    if direct_pane:
        agy_pid = pane_pid
        child_pid = pane_pid + 100
        world.procs.extend([
            Proc(agy_pid, 1, "t", f"agy --model m --conversation {AGY_UUID}"),
            Proc(child_pid, agy_pid, "t", "node server.js"),
        ])
    else:
        agy_pid = pane_pid + 100
        child_pid = pane_pid + 200
        world.procs.extend([
            Proc(pane_pid, 1, "t", "zsh -c 'agy'"),
            Proc(agy_pid, pane_pid, "t", "/Users/x/.local/bin/agy --model m"),
            Proc(child_pid, agy_pid, "t", "node server.js"),
        ])
    if agy_listening:
        world.listening.add(agy_pid)
    if child_listening:
        world.listening.add(child_pid)
    agy_ev = clean_evidence(agent_family="custom", timers=None, subagents=None, background_process=None)
    world.manager._attention_watcher.evidence = agy_ev
    world.manager.fresh = agy_ev
    return sid, uuid


def test_idle_agy_under_shell_with_own_listener_auto_sleeps(world, monkeypatch):
    sid, uuid = _make_agy(world, monkeypatch, direct_pane=False, agy_listening=True, child_listening=False)
    assert _run(world) == [uuid]
    assert world.sleeper.verdict_for(sid).code == "due"


def test_idle_agy_as_direct_pane_root_with_own_listener_auto_sleeps(world, monkeypatch):
    sid, uuid = _make_agy(world, monkeypatch, direct_pane=True, agy_listening=True, child_listening=False)
    assert _run(world) == [uuid]
    assert world.sleeper.verdict_for(sid).code == "due"


def test_agy_child_dev_server_listener_still_blocks_auto_sleep(world, monkeypatch):
    sid, _ = _make_agy(world, monkeypatch, direct_pane=False, agy_listening=True, child_listening=True)
    assert _run(world) == []
    verdict = world.sleeper.verdict_for(sid)
    assert verdict.code == "listening" and "node" in (verdict.detail or "")


def test_non_agy_custom_cli_is_never_auto_slept_or_stamped(world, monkeypatch):
    sid, _ = _make_agy(world, monkeypatch, agent_type="opencode", agy_listening=False)
    assert _run(world) == []
    assert world.sleeper.verdict_for(sid).code == "not_agent"
    info = SessionInfo.model_construct(
        session=SimpleNamespace(id=sid, agent_type="opencode"),
        agent_family="custom",
        sleep_hold=None,
        sleep_verdict=None,
    )
    sleep_hold_listing.mark_sleep_hold(world.manager, [info], world.sleeper)
    assert info.sleep_verdict is None


def test_listing_stamp_exposes_sleep_verdict_for_agy(world, monkeypatch):
    sid, _ = _make_agy(world, monkeypatch, agy_listening=True, child_listening=True)
    _run(world)
    info = SessionInfo.model_construct(
        session=SimpleNamespace(id=sid, agent_type="antigravity"),
        agent_family="custom",
        sleep_hold=None,
        sleep_verdict=None,
    )
    sleep_hold_listing.mark_sleep_hold(world.manager, [info], world.sleeper)
    assert info.sleep_verdict is not None and info.sleep_verdict.code == "listening"


def test_live_work_hold_for_skips_claude_only_checks_for_custom_family():
    ev = clean_evidence(agent_family="custom", timers=None, subagents=None, background_process=None)
    assert hold_for(ev, require_measured=False) is None
    assert hold_for(ev, require_measured=True) is None


def test_resolve_agy_seed_reads_transcript_and_store_mtimes(tmp_path):
    tdir = tmp_path / "brain" / AGY_UUID / ".system_generated" / "logs"
    tdir.mkdir(parents=True)
    (tdir / "transcript.jsonl").write_text("{}\n")
    sdir = tmp_path / "conversations"
    sdir.mkdir(parents=True)
    (sdir / f"{AGY_UUID}.db").write_bytes(b"db")

    candidates, floor = resolve_agy_seed(
        conversation_uuid=AGY_UUID,
        session_started_epoch=1758800000,
        agy_home=tmp_path,
    )
    by_source = {src: when for when, src in candidates}
    assert by_source[SOURCE_AGY_TRANSCRIPT] is not None
    assert by_source[SOURCE_AGY_STORE] is not None
    assert floor == datetime.fromtimestamp(1758800000, tz=timezone.utc)


def test_dead_pane_agy_transcript_absent_checks_agy_store(tmp_path, monkeypatch):
    _stub_agy_profiles(monkeypatch)
    monkeypatch.setattr(agy_transcripts, "AGY_HOME", tmp_path)
    row = {"agent_family": "custom", "agent_type": "antigravity"}
    assert session_sleep._transcript_absent(row, AGY_UUID) is True
    (tmp_path / "conversations").mkdir()
    (tmp_path / "conversations" / f"{AGY_UUID}.db").write_bytes(b"db")
    assert session_sleep._transcript_absent(row, AGY_UUID) is False
