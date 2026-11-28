
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.parked_work_listing import background_open_for, background_processes_for
from src.api.session_background_work_routes import router as bg_router
from src.core.attention.evidence import (
    ACTIVITY_HINT_BACKGROUND, REASON_SUBAGENTS, STATE_BUSY, STATE_DONE_IDLE, Evidence,
)
from src.core.attention.listing_marks import marks_stamp
from src.core.attention.manifest_reader import ManifestReading, read_manifest
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_NO_RECORD, TranscriptFacts
from src.core.background_work import guard as bw_guard
from src.core.background_work.listing import is_agy_tool_shell, list_processes
from src.core.background_work.measured import (
    STATE_NONE, STATE_RUNNING, BackgroundMeasure, ProcessSnapshot, measure_background,
)
from src.core.background_work.tree import PaneTree, find_agent, is_agent_command, is_agy_command
from src.core.conversation_writers import Proc, ProcessTable
from src.core.session_status import LIVENESS_LIVE

NOW = datetime(2026, 11, 23, 23, 15, tzinfo=timezone.utc)
START = "Mon Nov 23 18:11:07 2026"


def _agy_table(*, include_shell: bool = True) -> ProcessTable:
    rows = {
        7349: Proc(pid=7349, ppid=9594, lstart=START, command="zsh -c source antigravity.zsh"),
        7936: Proc(pid=7936, ppid=7349, lstart=START, command="agy --model gemini-4-neon-high"),
        8045: Proc(pid=8045, ppid=7936, lstart=START, command="/opt/homebrew/bin/python3 /s/stdio_bridge.py"),
        8046: Proc(pid=8046, ppid=7936, lstart=START,
                   command="sh -c '/s/venv/bin/python3 -I -S /s/bin/agy_statusline.py /s/agy-state 7936'"),
    }
    if include_shell:
        rows[4349] = Proc(pid=4349, ppid=7936, lstart=START,
                          command="zsh -c set -euo pipefail\\012scripts/dist-at-merge.sh")
        rows[4357] = Proc(pid=4357, ppid=4349, lstart=START, command="bash scripts/dist-at-merge.sh")
    children: dict[int, list[int]] = {}
    for row in rows.values():
        children.setdefault(row.ppid, []).append(row.pid)
    return ProcessTable(rows=rows, children=children)


def test_agy_command_recognition_listing_and_guard():
    assert is_agy_command("agy --model gemini-4-neon-high")
    assert is_agy_command("/Users/demo/.local/bin/agy --conversation x")
    assert is_agent_command("agy --model m")
    assert not is_agy_command("zsh -c agy")

    assert is_agy_tool_shell("zsh -c scripts/dist-at-merge.sh")
    assert is_agy_tool_shell("/bin/bash -lc 'pytest -q'")
    assert not is_agy_tool_shell("sh -c '/s/venv/bin/python3 -I -S /s/bin/agy_statusline.py /s/agy-state 7936'")
    assert not is_agy_tool_shell("/opt/homebrew/bin/python3 /s/stdio_bridge.py")

    table = _agy_table(include_shell=True)
    agent_pid = find_agent(table, (7349,))
    assert agent_pid == 7936
    tree = PaneTree(tmux_name="carnivore_cloudecode-5", socket="cloude", pane_pids=(7349,),
                    table=table, agent_pid=agent_pid)
    listed = list_processes(tree, stdout_of=lambda _pid: None)
    assert len(listed) == 1
    assert listed[0].pid == 4349
    assert listed[0].children == 1
    assert "dist-at-merge.sh" in (listed[0].summary or "")

    assert bw_guard.check(tree, 7936, START).code == bw_guard.REFUSE_AGENT_PROCESS
    verdict = bw_guard.check(tree, 4349, START)
    assert verdict.allowed is True
    assert [pid for pid, _ in verdict.subtree] == [4349, 4357]


def test_measure_background_for_agy_counts_tool_shells_and_respects_servers():
    snap = ProcessSnapshot(
        parents={7349: 9594, 7936: 7349, 8045: 7936, 8046: 7936, 4349: 7936, 4357: 4349},
        commands={
            7349: "zsh -c source antigravity.zsh",
            7936: "agy --model gemini-4-neon-high",
            8045: "python3 /s/stdio_bridge.py",
            8046: "sh -c 'python3 /s/bin/agy_statusline.py /s/agy-state 7936'",
            4349: "zsh -c scripts/dist-at-merge.sh",
            4357: "bash scripts/dist-at-merge.sh",
        },
    )
    measure = measure_background(7936, snap, stdout_of=lambda _pid: None, agent_kind="agy")
    assert (measure.state, measure.count, measure.servers) == (STATE_RUNNING, 1, 0)

    server_measure = measure_background(
        7936, snap, stdout_of=lambda _pid: None,
        is_server=lambda pid, _cmd, _pids: pid == 4349, agent_kind="agy",
    )
    assert (server_measure.state, server_measure.count, server_measure.servers) == (STATE_RUNNING, 1, 1)

    idle_snap = ProcessSnapshot(
        parents={7349: 9594, 7936: 7349, 8045: 7936},
        commands={7349: "zsh", 7936: "agy", 8045: "python3 stdio_bridge.py"},
    )
    none_measure = measure_background(7936, idle_snap, stdout_of=lambda _pid: None, agent_kind="agy")
    assert (none_measure.state, none_measure.count) == (STATE_NONE, 0)


def test_read_manifest_prefers_agy_statusline_over_osc_3008_idle(monkeypatch):
    from src.core.attention import manifest_reader

    monkeypatch.setattr(manifest_reader, "_agy_code", lambda _pane, _parents, _cmds: "busy")
    snap = ProcessSnapshot(
        parents={7349: 9594, 7936: 7349},
        commands={7349: "zsh", 7936: "agy --model gemini-4-neon-high"},
    )
    reading = read_manifest(7349, snap, lambda: "", status_code="idle")
    assert reading is not None
    assert reading.cli == "agy" and reading.version == "statusline" and reading.code == "busy"


def test_manifest_verdict_stays_busy_while_non_server_background_shells_run():
    def _ev(bg: BackgroundMeasure | None) -> Evidence:
        return Evidence(
            tmux_liveness=LIVENESS_LIVE, agent_family="custom",
            registry=registry_for_session(tmux_name="carnivore_cloudecode-5", index={}),
            transcript=TranscriptFacts(verdict=FACTS_NO_RECORD), pane=None, now=NOW,
            manifest=ManifestReading("agy", "statusline", code="idle"),
            background_process=bg,
            background_open=bg.count if bg and bg.state in (STATE_RUNNING, STATE_NONE) else None,
        )

    busy = resolve_attention(_ev(BackgroundMeasure(STATE_RUNNING, 1, servers=0)))
    assert (busy.state, busy.reason, busy.activity_hint) == (STATE_BUSY, REASON_SUBAGENTS, ACTIVITY_HINT_BACKGROUND)

    server_only = resolve_attention(_ev(BackgroundMeasure(STATE_RUNNING, 1, servers=1)))
    assert server_only.state == STATE_DONE_IDLE

    idle = resolve_attention(_ev(BackgroundMeasure(STATE_NONE, 0)))
    assert idle.state == STATE_DONE_IDLE

    assert marks_stamp(_ev(BackgroundMeasure(STATE_NONE, 0))) != marks_stamp(_ev(BackgroundMeasure(STATE_RUNNING, 1)))


def test_listing_projects_agy_background_work_and_keeps_codex_null():
    agy_ev = Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family="custom",
        registry=registry_for_session(tmux_name="carnivore_cloudecode-5", index={}),
        transcript=TranscriptFacts(verdict=FACTS_NO_RECORD), pane=None, now=NOW,
        background_open=1, background_process=BackgroundMeasure(STATE_RUNNING, 1),
    )
    watcher = SimpleNamespace(observation_for=lambda _sid, now=None: SimpleNamespace(evidence=agy_ev, stale=False))
    agy_info = SimpleNamespace(agent_family="custom", agent_type="antigravity", session=SimpleNamespace(id="ses_agy"))
    assert background_open_for(watcher, agy_info, NOW) == 1
    proj = background_processes_for(watcher, agy_info, NOW)
    assert proj is not None and (proj.state, proj.count) == ("running", 1)

    codex_ev = Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family="codex",
        registry=registry_for_session(tmux_name="carnivore_cx", index={}),
        transcript=TranscriptFacts(verdict=FACTS_NO_RECORD), pane=None, now=NOW,
    )
    codex_watcher = SimpleNamespace(observation_for=lambda _sid, now=None: SimpleNamespace(evidence=codex_ev, stale=False))
    codex_info = SimpleNamespace(agent_family="codex", session=SimpleNamespace(id="ses_cx"))
    assert background_open_for(codex_watcher, codex_info, NOW) is None
    assert background_processes_for(codex_watcher, codex_info, NOW) is None


def test_background_work_route_lists_agy_tool_shells_and_refuses_codex(monkeypatch):
    from src.api import session_background_work_routes as route_mod

    table = _agy_table(include_shell=True)
    tree = PaneTree(tmux_name="carnivore_cloudecode-5", socket="cloude", pane_pids=(7349,),
                    table=table, agent_pid=7936)
    other_tree = PaneTree(tmux_name="carnivore_other", socket="cloude", pane_pids=(10,),
                          table=ProcessTable(rows={10: Proc(10, 1, START, "zsh")}, children={1: [10]}),
                          agent_pid=None)
    monkeypatch.setattr(
        route_mod.bw_tree, "measure",
        lambda name, *a, **kw: tree if name == "carnivore_cloudecode-5" else other_tree,
    )
    monkeypatch.setattr(route_mod, "row_is_agy", lambda _row, *a, **kw: False)

    class _Manager:
        def tmux_socket_name(self):
            return "cloude"

        async def resolve_session_ref(self, session_id: str):
            if session_id == "ses_agy":
                return {"tmux_session": "carnivore_cloudecode-5", "agent_family": "custom", "agent_type": "antigravity"}
            if session_id == "ses_other_custom":
                return {"tmux_session": "carnivore_other", "agent_family": "custom", "agent_type": "vim"}
            if session_id == "ses_cx":
                return {"tmux_session": "carnivore_cx", "agent_family": "codex", "agent_type": "codex"}
            return None

    app = FastAPI()
    app.state.session_manager = _Manager()
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(username="alice")
    app.include_router(bg_router, prefix="/api/v1")
    client = TestClient(app)

    agy_resp = client.get("/api/v1/sessions/ses_agy/background-work")
    assert agy_resp.status_code == 200
    body = agy_resp.json()
    assert body["state"] == "ok" and body["owners"] == "absent"
    assert len(body["processes"]) == 1 and body["processes"][0]["pid"] == 4349

    other_resp = client.get("/api/v1/sessions/ses_other_custom/background-work")
    assert other_resp.status_code == 200 and other_resp.json()["state"] == "not_applicable"

    cx_resp = client.get("/api/v1/sessions/ses_cx/background-work")
    assert cx_resp.status_code == 200 and cx_resp.json()["state"] == "not_applicable"
