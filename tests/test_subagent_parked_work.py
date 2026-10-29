
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

import pytest

from src.core.attention import output_holders
from src.core.attention.display import activity_hint_for, to_display
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    FAMILY_CODEX,
    REASON_NO_EVIDENCE,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    TIER_TRANSCRIPT,
    AttentionVerdict,
    Evidence,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.attention.watcher import AttentionWatcher, WatchTarget
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.claude_resume_argv import list_process_table
from src.core.session_status import (
    LIVENESS_LIVE,
    STATUS_UNKNOWN,
    STATUS_WORKING_SUBAGENT,
)
from src.core.subagents import parked_work
from src.core.subagents.parked_work import (
    PARKED_LIVE,
    PARKED_NONE,
    PARKED_UNMEASURED,
    ParkedWorkReader,
    describe_entry,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "parked_subagent_shapes.json").read_text()
)
FEATURELIST = FIXTURE["featurelist"]
ARGENT = FIXTURE["argent"]
AGENT = "ef46830a20a635dd3"
SHELL = "bcw5srws5"
MONITORS = ("bbspnbm6q", "bidpmkfge")
CLAUDE_PID = 4242


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (at.microsecond // 1000)


def _clone(record: Dict[str, Any], when: str) -> Dict[str, Any]:
    moved = copy.deepcopy(record)
    moved["timestamp"] = when
    return moved


def _parent_record(case: Dict[str, Any], predicate: Callable[[dict], bool]) -> dict:
    return next(r for r in case["parent"] if predicate(r))


def _prompt() -> dict:
    return _parent_record(FEATURELIST, lambda r: (r.get("origin") or {}).get("kind") == "human")


def _assistant() -> dict:
    return _parent_record(
        FEATURELIST,
        lambda r: r["type"] == "assistant" and r["message"]["content"][:1] == [
            {"type": "text", "text": "redacted"}],
    )


def _turn_end() -> dict:
    return _parent_record(
        FEATURELIST, lambda r: r.get("subtype") == "turn_duration"
        and "pendingBackgroundAgentCount" not in r)


def _is_task(record: dict, task_ids: Iterable[str]) -> bool:
    result = record.get("toolUseResult")
    if not isinstance(result, dict):
        return False
    return (result.get("backgroundTaskId") or result.get("taskId")) in set(task_ids)


def _write(root: Path, case: Dict[str, Any], *, until: str,
           extra_parent: Iterable[dict] = (), extra_agent: Iterable[dict] = (),
           drop_agent: Callable[[dict], bool] = lambda r: False,
           drop_parent: Callable[[dict], bool] = lambda r: False) -> Path:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    session = case["session"]

    def dump(records: Iterable[dict]) -> str:
        kept = sorted((r for r in records if r["timestamp"] <= until),
                      key=lambda r: r["timestamp"])
        text = "".join(json.dumps(r) + "\n" for r in kept)
        return text.replace("{TASKS}", str(tasks)).replace("{SESSION}", session)

    parent = root / ("%s.jsonl" % session)
    parent.write_text(dump([r for r in case["parent"] if not drop_parent(r)]
                           + list(extra_parent)))
    directory = root / session / "subagents"
    directory.mkdir(parents=True, exist_ok=True)
    for agent_id, agent in case["agents"].items():
        (directory / ("agent-%s.meta.json" % agent_id)).write_text(json.dumps(agent["meta"]))
        lines = [r for r in agent["lines"] if not drop_agent(r)] + list(extra_agent)
        (directory / ("agent-%s.jsonl" % agent_id)).write_text(dump(lines))
    (tasks / ("%s.output" % SHELL)).write_text("")
    return parent


def _registry(started: str, status_at: str, *, status: str = "idle", session: str = ""):
    return parse_registry_record({
        "pid": CLAUDE_PID, "sessionId": session, "cwd": "/work/project",
        "startedAt": int(_at(started).timestamp() * 1000), "version": "2.1.283",
        "kind": "interactive", "entrypoint": "cli", "status": status,
        "updatedAt": int(_at(status_at).timestamp() * 1000),
        "statusUpdatedAt": int(_at(status_at).timestamp() * 1000),
    }, path_pid=CLAUDE_PID)


class _Probe:

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.asked: List[List[str]] = []

    def __call__(self, paths, *, root_pid, process_parents, budget_seconds=None):
        self.asked.append(list(paths))
        assert root_pid == CLAUDE_PID
        return {path: self.answer for path in paths}


def _read(parent: Path, now: datetime, registry, *, reader=None) -> tuple:
    records = [json.loads(line) for line in parent.read_text().splitlines()]
    facts = classify_transcript_records(records, now=now, window_is_whole_file=True)
    parked = (reader or ParkedWorkReader()).read(
        FAMILY_CLAUDE, parent, registry, facts, now,
        process_started_at=registry.started_at, process_parents=lambda: {1: 0},
    )
    return facts, parked


def _evidence(registry, facts, now: datetime, parked) -> Evidence:
    return Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=registry, transcript=facts, pane=None, now=now,
        parked_work=parked,
    )


def _axes(verdict: AttentionVerdict) -> tuple:
    return (verdict.state, verdict.reason, verdict.tier)




@pytest.mark.parametrize("turn_end, now", [
    ("2026-09-27T20:51:16.096Z", "2026-09-27T20:51:20.000Z"),
    ("2026-09-27T20:56:13.606Z", "2026-09-27T20:56:17.000Z"),
])
def test_a_parked_subagent_on_a_live_shell_reads_working_subagent(
        tmp_path, monkeypatch, turn_end, now):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _write(tmp_path, FEATURELIST, until=now)
    registry = _registry("2026-09-27T20:00:00.000Z", turn_end, session=FEATURELIST["session"])
    instant = _at(now)
    facts, parked = _read(parent, instant, registry)

    assert parked.state == PARKED_LIVE
    assert SHELL in parked.detail and AGENT in parked.detail
    assert probe.asked == [[str(tmp_path / "tasks" / ("%s.output" % SHELL))]]
    verdict = resolve_attention(_evidence(registry, facts, instant, parked))
    assert _axes(verdict) == (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == STATUS_WORKING_SUBAGENT
    before = resolve_attention(_evidence(registry, facts, instant, None))
    assert _axes(before)[:2] == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_the_parked_entry_names_the_subagent_and_never_a_command(tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    now = "2026-09-27T20:51:20.000Z"
    parent = _write(tmp_path, FEATURELIST, until=now)
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.096Z",
                          session=FEATURELIST["session"])
    instant = _at(now)
    _facts, parked = _read(parent, instant, registry)

    assert parked.state == PARKED_LIVE
    assert len(parked.entries) == 3
    assert [e.live for e in parked.entries] == [True, False, False]
    entry = parked.entries[0]
    assert entry.agent_id == AGENT
    assert entry.agent_type == "general-purpose"
    assert entry.description == "redacted"
    assert entry.task_id == SHELL
    assert entry.kind == "shell"
    assert entry.live is True
    assert entry.started_at is not None

    sentence = describe_entry(entry, now=instant)
    assert SHELL in sentence
    assert "general-purpose" not in sentence
    assert "'redacted'" in sentence
    assert "running" in sentence
    for forbidden in (".output", "/tasks/", "bash", "curl"):
        assert forbidden not in sentence




def test_a_stale_owner_is_ignored_and_the_probe_never_runs(tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    later = [_clone(_prompt(), "2026-09-27T20:52:00.000Z"),
             _clone(_assistant(), "2026-09-27T20:52:05.000Z"),
             _clone(_turn_end(), "2026-09-27T20:52:06.000Z")]
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:52:06.000Z",
                    extra_parent=later)
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:52:06.100Z")
    now = _at("2026-09-27T20:52:10.000Z")
    facts, parked = _read(parent, now, registry)

    assert parked.state == PARKED_NONE
    assert probe.asked == []
    verdict = resolve_attention(_evidence(registry, facts, now, parked))
    assert verdict.state == STATE_DONE_IDLE




def test_a_fresh_owner_with_no_live_holder_goes_idle(tmp_path, monkeypatch):
    probe = _Probe(output_holders.NOT_HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:51:20.000Z",
                    drop_agent=lambda r: _is_task(r, MONITORS))
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z")
    now = _at("2026-09-27T20:51:20.000Z")
    facts, parked = _read(parent, now, registry)

    assert len(probe.asked) == 1
    assert parked.state == PARKED_NONE
    assert resolve_attention(_evidence(registry, facts, now, parked)).state == STATE_DONE_IDLE




def _monitor_only(tmp_path: Path, until: str) -> Path:
    return _write(tmp_path, FEATURELIST, until=until,
                  drop_agent=lambda r: _is_task(r, (SHELL, "bbspnbm6q")))


def test_a_monitor_past_its_launch_plus_timeout_is_over(tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _monitor_only(tmp_path, "2026-09-27T20:56:17.000Z")
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:56:13.700Z")
    now = _at("2026-09-27T20:56:17.000Z")
    facts, parked = _read(parent, now, registry)

    assert parked.state == PARKED_NONE
    assert resolve_attention(_evidence(registry, facts, now, parked)).state == STATE_DONE_IDLE


def test_a_monitor_inside_its_deadline_is_unmeasured_not_idle_and_not_working(
        tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _monitor_only(tmp_path, "2026-09-27T20:51:20.000Z")
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z")
    now = _at("2026-09-27T20:51:20.000Z")
    facts, parked = _read(parent, now, registry)

    assert parked.state == PARKED_UNMEASURED
    assert probe.asked == []
    verdict = resolve_attention(_evidence(registry, facts, now, parked))
    assert _axes(verdict) == (STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_TRANSCRIPT)
    assert "bidpmkfge" in verdict.detail




def _argent(tmp_path: Path, *, with_lost_notice: bool) -> Path:
    parent_extra = [_clone(_prompt(), "2026-09-27T18:40:00.000Z"),
                    _clone(_assistant(), "2026-09-27T18:40:05.000Z"),
                    _clone(_turn_end(), "2026-09-27T18:40:06.000Z"),
                    _clone(_assistant(), "2026-09-27T19:01:58.000Z"),
                    _clone(_turn_end(), "2026-09-27T19:01:59.000Z")]
    agent_line = ARGENT["agents"]["42663cac05a267bf3"]["lines"][-1]
    return _write(tmp_path, ARGENT, until="2026-09-27T19:05:00.000Z",
                  extra_parent=parent_extra,
                  extra_agent=[_clone(agent_line, "2026-09-27T19:01:55.000Z")],
                  drop_parent=lambda r: not with_lost_notice)


def test_the_argent_lost_notice_shape_goes_idle_and_can_sleep(tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _argent(tmp_path, with_lost_notice=True)
    registry = _registry("2026-09-27T18:00:00.000Z", "2026-09-27T19:02:00.000Z")
    clock = IdleClock()
    for minute in (5, 10, 15):
        now = _at("2026-09-27T19:00:00.000Z") + timedelta(minutes=minute)
        facts, parked = _read(parent, now, registry)
        assert parked.state == PARKED_NONE
        verdict = resolve_attention(_evidence(registry, facts, now, parked))
        assert verdict.state == STATE_DONE_IDLE
        clock.observe("ses_argent", "cloude_argent@1",
                      to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN),
                      activity_hint_for(registry), now)
    assert clock.idle_seconds("ses_argent", now) == 600.0


def test_without_the_parent_notice_the_same_monitor_would_hold_the_session(
        tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _argent(tmp_path, with_lost_notice=False)
    registry = _registry("2026-09-27T18:00:00.000Z", "2026-09-27T19:02:00.000Z")
    now = _at("2026-09-27T19:05:00.000Z")
    facts, parked = _read(parent, now, registry)
    assert parked.state == PARKED_UNMEASURED
    assert resolve_attention(_evidence(registry, facts, now, parked)).state == STATE_UNKNOWN




def test_a_launch_older_than_the_current_claude_process_is_not_its_work(
        tmp_path, monkeypatch):
    probe = _Probe(output_holders.HELD)
    monkeypatch.setattr(parked_work, "probe_output_holders", probe)
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:51:20.000Z")
    registry = _registry("2026-09-27T20:51:14.000Z", "2026-09-27T20:51:16.100Z")
    now = _at("2026-09-27T20:51:20.000Z")
    _, parked = _read(parent, now, registry)
    assert parked.state == PARKED_NONE
    assert probe.asked == []


def test_codex_and_a_working_claude_are_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:51:20.000Z")
    now = _at("2026-09-27T20:51:20.000Z")
    reader = ParkedWorkReader()
    idle = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z")
    busy = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z", status="busy")
    common = dict(process_started_at=idle.started_at, process_parents=dict)
    assert reader.read(FAMILY_CODEX, parent, idle, None, now, **common) is None
    assert reader.read(FAMILY_CLAUDE, parent, busy, None, now, **common) is None
    assert reader.read(FAMILY_CLAUDE, parent, idle, None, now, **common).state == PARKED_LIVE




def _watch(evidence_at: Callable[[datetime], Evidence], ticks: List[datetime]) -> tuple:
    toasts: List[str] = []
    clock = IdleClock()
    target = WatchTarget(session_id="ses_featurelist", key="cloude_featurelist@1")
    ledger = AttentionLedger()
    ledger.observe(target.key, AttentionVerdict(
        state=STATE_BUSY, reason=REASON_SUBAGENTS, tier=TIER_TRANSCRIPT),
        ticks[0] - timedelta(seconds=30))
    moment = {"now": ticks[0]}

    def observe(tgt: WatchTarget, observation) -> None:
        verdict = observation.verdict
        clock.observe(tgt.session_id, tgt.key,
                      to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN),
                      verdict.activity_hint or activity_hint_for(observation.evidence.registry),
                      observation.observed_at)

    watcher = AttentionWatcher(
        list_targets=lambda: [target],
        read_evidence=lambda tgt, now: evidence_at(now),
        raise_toast=lambda tgt, kind, tr: toasts.append(kind),
        set_unread=lambda tgt: None, on_busy_edge=lambda tgt, tr: None,
        on_observation=observe, ledger=ledger, now=lambda: moment["now"],
        tick_seconds=0.0, registry_directory="/nonexistent-for-this-test",
    )
    for tick in ticks:
        moment["now"] = tick
        asyncio.run(watcher.tick_once())
    return toasts, clock.idle_seconds(target.session_id, ticks[-1])


@pytest.mark.parametrize("with_fix, toasts, idle", [(True, [], None), (False, ["Stop"], 6.0)])
def test_no_your_turn_toast_and_no_idle_run_while_the_shell_is_live(
        tmp_path, monkeypatch, with_fix, toasts, idle):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:51:20.000Z")
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z")
    reader = ParkedWorkReader()

    def evidence_at(now: datetime) -> Evidence:
        facts, parked = _read(parent, now, registry, reader=reader)
        return _evidence(registry, facts, now, parked if with_fix else None)

    start = _at("2026-09-27T20:51:20.000Z")
    ticks = [start + timedelta(seconds=2 * i) for i in range(4)]
    assert _watch(evidence_at, ticks) == (toasts, idle)




def test_a_real_child_holding_the_output_file_is_live_and_its_exit_is_not(tmp_path):
    parent = _write(tmp_path, FEATURELIST, until="2026-09-27T20:51:20.000Z",
                    drop_agent=lambda r: _is_task(r, MONITORS))
    output = tmp_path / "tasks" / ("%s.output" % SHELL)
    registry = _registry("2026-09-27T20:00:00.000Z", "2026-09-27T20:51:16.100Z")
    registry = dataclasses.replace(registry, pid=os.getpid())
    now = _at("2026-09-27T20:51:20.000Z")
    records = [json.loads(line) for line in parent.read_text().splitlines()]
    facts = classify_transcript_records(records, now=now, window_is_whole_file=True)

    def table() -> Dict[int, int]:
        return {row.pid: row.ppid for row in (list_process_table() or [])}

    def state() -> str:
        return ParkedWorkReader().read(
            FAMILY_CLAUDE, parent, registry, facts, now,
            process_started_at=registry.started_at, process_parents=table).state

    with open(output, "ab") as sink:
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=sink, stderr=sink)
    try:
        time.sleep(0.2)
        assert state() == PARKED_LIVE
    finally:
        child.kill()
        child.wait()
    assert state() == PARKED_NONE
