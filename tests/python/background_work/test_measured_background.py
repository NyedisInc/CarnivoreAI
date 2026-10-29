
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.api.parked_work_listing import background_open_for, background_processes_for
from src.core.attention.background_claims import (
    claims_after_epoch, measurement_overrules_claims, standing_background_claims,
)
from src.core.attention.evidence import (
    FAMILY_CLAUDE, REASON_SUBAGENTS, STATE_BUSY, Evidence,
)
from src.core.attention.registry_read import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.auto_sleep.live_work import hold_for
from src.core.background_work.measured import (
    STATE_NONE, STATE_RUNNING, STATE_UNKNOWN, UNREADABLE, BackgroundMeasure,
    ProcessSnapshot, measure_background,
)
from src.core.session_status import LIVENESS_LIVE

CLAUDE = 52033
SNAP = "/Users/example/.carnivore/accounts/sam-initech/shell-snapshots/snapshot-zsh-1790808101319-5u4phq.sh"
UUID = "c8cae45c-a817-4123-86de-e1d544b2f6c7"
STARTED_MS = int(datetime(2026, 9, 30, 23, 11, 14, tzinfo=timezone.utc).timestamp() * 1000)
NOW = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)


def _table(extra: Dict[int, tuple] = None) -> ProcessSnapshot:
    rows = {
        4663: (61987, "zsh -c source ~/.zshrc; claude --resume x"),
        CLAUDE: (4663, "claude --dangerously-skip-permissions --chrome --mcp-config={...}"),
        52102: (CLAUDE, "npm exec @modelcontextprotocol/server-sequential-thinking"),
        52230: (52102, "node /u/.npm/_npx/de/node_modules/.bin/mcp-server-sequential-thinking"),
        52103: (CLAUDE, "npm exec @modelcontextprotocol/server-memory"),
        52241: (52103, "node /u/.npm/_npx/15/node_modules/.bin/mcp-server-memory"),
        76882: (CLAUDE, "caffeinate -i -t 300"),
    }
    rows.update(extra or {})
    return ProcessSnapshot(parents={p: v[0] for p, v in rows.items()},
                           commands={p: v[1] for p, v in rows.items()})


def _no_stdout(pid: int) -> Optional[str]:
    return None


def _registry(status: str, version: str = "2.1.283"):
    return parse_registry_record({
        "pid": CLAUDE, "sessionId": UUID, "cwd": "/Users/example/kitchen",
        "startedAt": STARTED_MS, "version": version, "kind": "interactive",
        "entrypoint": "cli", "status": status,
        "updatedAt": STARTED_MS + 60_000, "statusUpdatedAt": STARTED_MS + 60_000,
    }, path_pid=CLAUDE)


def _record(kind: str, ts: str, **fields: Any) -> Dict[str, Any]:
    record = {"type": kind, "isSidechain": False, "timestamp": ts, "sessionId": UUID}
    record.update(fields)
    return record


def _shell_launch(ts: str, task_id: str) -> Dict[str, Any]:
    return _record("user", ts, toolUseResult={
        "stdout": "", "stderr": "", "interrupted": False, "isImage": False,
        "noOutputExpected": False, "backgroundTaskId": task_id,
    }, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_" + task_id, "content": "x"}]})


def _window(launched: List[str]) -> List[Dict[str, Any]]:
    records = [_shell_launch(ts, "b%d" % i) for i, ts in enumerate(launched)]
    return records + [
        _record("assistant", "2026-09-30T23:20:00.000Z",
                message={"role": "assistant", "content": [{"type": "text", "text": "ok"}]}),
        _record("system", "2026-09-30T23:20:01.000Z", subtype="turn_duration", version="2.1.283"),
    ]


def _evidence(status: str, measure: Optional[BackgroundMeasure],
              launched=("2026-09-30T23:15:00.000Z", "2026-09-30T23:16:00.000Z"),
              resting: bool = False) -> Evidence:
    return Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=_registry(status), transcript=classify_transcript_records(_window(list(launched))),
        pane=None, now=NOW, resting_prompt_held=resting, background_process=measure,
    )


NONE = BackgroundMeasure(STATE_NONE, 0)
UNKNOWN = BackgroundMeasure(STATE_UNKNOWN, None)




def test_mcp_servers_and_caffeinate_are_claudes_own_machinery():
    measure = measure_background(CLAUDE, _table(), stdout_of=_no_stdout)
    assert (measure.state, measure.count) == (STATE_NONE, 0)


def test_a_real_tool_shell_child_is_running_counted_once_with_its_children():
    table = _table({
        66086: (CLAUDE, "/bin/zsh -c source %s 2>/dev/null || true && eval 'tail -f log'" % SNAP),
        66088: (66086, "tail -n +1 -f /private/tmp/log"),
        66089: (66086, "/bin/zsh -c source %s && eval 'rg x'" % SNAP),
    })
    measure = measure_background(CLAUDE, table, stdout_of=_no_stdout)
    assert (measure.state, measure.count) == (STATE_RUNNING, 1)


def test_a_shell_without_a_snapshot_counts_by_its_task_output_stdout():
    table = _table({70000: (CLAUDE, "/bin/bash -c sleep 100")})
    stdout = {70000: "/private/tmp/claude-1000/x/tasks/bt0wu171w.output"}
    measure = measure_background(CLAUDE, table, stdout_of=stdout.get)
    assert (measure.state, measure.count) == (STATE_RUNNING, 1)


def test_a_detached_grandchild_is_not_this_sessions_work():
    table = _table({80000: (1, "/bin/zsh -c source %s && eval 'nohup x &'" % SNAP)})
    assert measure_background(CLAUDE, table, stdout_of=_no_stdout).state == STATE_NONE


def test_unmeasurable_is_unknown_never_none():
    for pid, table in ((CLAUDE, UNREADABLE), (None, _table()), (99999, _table()), (CLAUDE, None)):
        measure = measure_background(pid, table, stdout_of=_no_stdout)
        assert (measure.state, measure.count) == (STATE_UNKNOWN, None), (pid, table)




def test_kitchen_stale_claim_no_process_record_idle_is_overruled_to_none():
    evidence = _evidence("idle", NONE)
    assert evidence.transcript.open_background_tasks == 2
    assert measurement_overrules_claims(evidence)
    assert standing_background_claims(evidence) == 0
    verdict = resolve_attention(evidence)
    assert not (verdict.state == STATE_BUSY and verdict.reason == REASON_SUBAGENTS), verdict.detail


def test_record_busy_with_no_process_keeps_the_claim_1148():
    evidence = _evidence("busy", NONE, resting=True)
    assert not measurement_overrules_claims(evidence)
    assert standing_background_claims(evidence) == 2
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)


def test_unknown_or_unmeasured_never_overrules_a_claim():
    for measure in (UNKNOWN, None):
        evidence = _evidence("idle", measure)
        assert standing_background_claims(evidence) == 2
        assert (resolve_attention(evidence).state, resolve_attention(evidence).reason) == (
            STATE_BUSY, REASON_SUBAGENTS)


def test_the_restart_epoch_retires_claims_from_before_the_new_claude():
    old = ("2026-09-29T23:04:00.000Z", "2026-09-29T23:34:00.000Z")
    evidence = _evidence("idle", UNKNOWN, launched=old)
    assert evidence.transcript.open_background_tasks == 2
    assert claims_after_epoch(evidence) == 0
    mixed = _evidence("idle", UNKNOWN, launched=(old[0], "2026-09-30T23:15:00.000Z"))
    assert claims_after_epoch(mixed) == 1




def _watcher(evidence: Evidence):
    observation = SimpleNamespace(evidence=evidence, stale=False)
    return SimpleNamespace(observation_for=lambda sid, now=None: observation)


def _info():
    return SimpleNamespace(agent_family="claude", session=SimpleNamespace(id="ses_1"))


def test_listing_projects_the_measurement_and_zeroes_an_overruled_count():
    evidence = _evidence("idle", NONE)
    projected = background_processes_for(_watcher(evidence), _info(), NOW)
    assert (projected.state, projected.count) == ("none", 0)
    assert background_open_for(_watcher(evidence), _info(), NOW) == 0
    unknown = _evidence("idle", UNKNOWN)
    projected = background_processes_for(_watcher(unknown), _info(), NOW)
    assert (projected.state, projected.count) == ("unknown", None)
    assert background_processes_for(_watcher(_evidence("idle", None)), _info(), NOW) is None


def test_auto_sleep_is_blocked_by_a_running_or_unknown_tree_not_by_a_stale_claim():
    def held(measure):
        evidence = SimpleNamespace(agent_family="claude", background_process=measure)
        return hold_for(evidence, require_measured=False) is not None

    assert held(BackgroundMeasure(STATE_RUNNING, 1))
    assert held(UNKNOWN)
    assert not held(NONE)
    assert not held(None)


def test_the_reader_takes_one_ps_snapshot_per_pass(monkeypatch):
    from src.core import claude_resume_argv
    from src.core.attention_reader import AttentionEvidenceReader

    calls = []
    rows = [SimpleNamespace(pid=CLAUDE, ppid=4663, command="claude")]
    monkeypatch.setattr(claude_resume_argv, "list_process_table",
                        lambda *a, **k: calls.append(1) or rows)
    reader = AttentionEvidenceReader(SimpleNamespace(), lambda sid: (sid, 1))
    first = reader._process_snapshot(NOW)
    assert reader._process_snapshot(NOW) is first and len(calls) == 1
    assert first.commands[CLAUDE] == "claude" and reader._process_parents(NOW) == {CLAUDE: 4663}
    monkeypatch.setattr(claude_resume_argv, "list_process_table", lambda *a, **k: None)
    reader._snapshot_taken_at -= 60
    assert reader._process_snapshot(NOW.replace(minute=31)) is UNREADABLE
