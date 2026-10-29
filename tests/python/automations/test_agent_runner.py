from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import src.config  # noqa: F401
from src.core.automations import gates, models as m
from src.core.automations.scheduler import Scheduler
from src.core.automations.targets import agent_def
from src.core.automations.targets import agent
from src.core.provider_ledger import refresh_poke

PARENT_VAL, CONN_VAL = "PARENT-KEY-SENTINEL-1", "CONNECTION-KEY-SENTINEL-2"
PROMPT_MARK = "prompt-marker-only"

FAKE = r'''import json, os, subprocess, sys, time
prompt = sys.stdin.read()
sysfile = sys.argv[sys.argv.index("--append-system-prompt-file") + 1] if "--append-system-prompt-file" in sys.argv else None
rec = {{"argv": sys.argv[1:], "stdin": prompt, "sysfile": sysfile, "sysfile_text": open(sysfile).read() if sysfile else None,
        "sysfile_mode": oct(os.stat(sysfile).st_mode & 0o777) if sysfile else None, "key": os.environ.get("ANTHROPIC_API_KEY"), "pid": os.getpid(),
        "pgid": os.getpgrp(), "env_keys": sorted(os.environ)}}
def say(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
if "MODE:turns" in prompt:
    child = subprocess.Popen(["sleep", "60"])
    rec["grandchild"] = child.pid
    json.dump(rec, open({rec_path!r}, "w"))
    for i in range(5):
        say({{"type": "assistant", "message": {{"id": "m%d" % i, "content": [{{"type": "text", "text": "turn %d" % i}}]}}}})
    time.sleep(60)
json.dump(rec, open({rec_path!r}, "w"))
say({{"type": "assistant", "message": {{"id": "only"}}}})
if "MODE:unclear" in prompt:
    say({{"type": "result", "result": "no verdict fields"}})
elif "MODE:budget" in prompt:
    say({{"type": "result", "subtype": "success", "is_error": True, "terminal_reason": "budget_exhausted",
          "num_turns": 1, "total_cost_usd": 1.02, "session_id": "s", "result": "stopped"}})
else:
    say({{"type": "result", "subtype": "success", "is_error": False, "terminal_reason": "completed",
          "num_turns": 1, "total_cost_usd": 0.25, "session_id": "sess", "result": "all done"}})
'''


class Store:

    attachments_root = Path(tempfile.mkdtemp(prefix="cc_agent_att_"))

    def __init__(self) -> None:
        self.updates: List[Dict[str, Any]] = []

    def update_run(self, run_id: str, **fields: Any) -> Dict[str, Any]:
        self.updates.append(fields)
        return {"run_id": run_id}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rec_path = tmp_path / "rec.json"
    binary = tmp_path / "claude"
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE.format(rec_path=str(rec_path)))
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
    binary.chmod(0o755)
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.setattr(refresh_poke, "resolve_claude_binary", lambda: str(binary))
    monkeypatch.setattr(gates, "login_of", lambda target: (None, None))
    monkeypatch.setenv("ANTHROPIC_API_KEY", PARENT_VAL)
    store = Store()

    def go(mode: str, **target: Any) -> m.RunOutcome:
        body = {"kind": "agent", "folder": str(folder), "prompt": f"{mode} {PROMPT_MARK}", "max_turns": 3, **target}
        automation = {"target": body, "delivery": {"notify": False}}
        out = asyncio.run(agent.run(SimpleNamespace(store=store), automation, {"run_id": "r1"}))
        rig.last = (out.status, out.reason, out.error)
        return out

    def rec() -> Dict[str, Any]:
        assert rec_path.exists(), f"population check: the fake claude never ran ({rig.last})"
        return json.loads(rec_path.read_text())

    rig = SimpleNamespace(go=go, rec=rec, store=store, folder=folder, last=None)
    return rig


REAL_FOLDER_PROBLEM = agent.folder_problem


@pytest.fixture(autouse=True)
def project_folder(monkeypatch):
    monkeypatch.setattr(agent, "folder_problem", lambda folder: None)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return "Z" not in os.popen(f"ps -o stat= -p {pid}").read()


def test_argv_stdin_env_and_success(rig):
    out = rig.go("MODE:ok", system_prompt_append="append-text-marker")
    rec = rig.rec()
    argv = rec["argv"]
    assert rec["sysfile_text"] == "append-text-marker" and rec["sysfile_mode"] == "0o600"
    assert not any("append-text-marker" in a for a in argv) and not os.path.exists(rec["sysfile"])
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in rec["env_keys"]
    assert out.status == m.SUCCEEDED and out.report["final_text"] == "all done" and out.cost_usd == 0.25
    for flag in ("-p", "--verbose", "--session-id", "--max-budget-usd", "--tools", "--permission-prompts"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch"
    assert argv[argv.index("--max-budget-usd") + 1] == "1"
    assert "--no-session-persistence" not in argv and "default" not in argv and "--restricted" not in argv
    assert argv[argv.index("--max-turns") + 1] == "3"
    assert argv[argv.index("--setting-sources") + 1] == "" and "--strict-mcp-config" in argv and "--restricted" not in argv
    assert not any(PROMPT_MARK in a for a in argv)
    assert PROMPT_MARK in rec["stdin"]
    assert rec["key"] is None and "ANTHROPIC_API_KEY" not in rec["env_keys"]
    assert rec["pgid"] == rec["pid"] != os.getpgrp()
    assert any("child" in u and u["child"] and u["child"]["pid"] == rec["pid"] for u in rig.store.updates)


def test_connection_key_only_in_child_env(rig, monkeypatch):
    async def key(connection_id: str):
        return CONN_VAL

    monkeypatch.setattr(agent, "_api_key", key)
    out = rig.go("MODE:ok", api_key_connection_id="anthropic-1")
    rec = rig.rec()
    assert out.status == m.SUCCEEDED
    assert rec["key"] == CONN_VAL
    assert not any(CONN_VAL in a or PARENT_VAL in a for a in rec["argv"])


def test_turn_cap_stops_the_group(rig):
    started = time.monotonic()
    out = rig.go("MODE:turns")
    elapsed = time.monotonic() - started
    rec = rig.rec()
    assert out.status == m.FAILED and out.reason == "turn_cap"
    assert elapsed < 3, elapsed
    assert not _alive(rec["pid"]) and not _alive(rec["grandchild"])


def test_budget_exhausted_is_mapped(rig):
    out = rig.go("MODE:budget")
    rig.rec()
    assert out.status == m.FAILED and out.reason == "budget_exhausted" and out.cost_usd == 1.02


def test_a_result_without_verdict_fields_is_not_success(rig):
    out = rig.go("MODE:unclear")
    rig.rec()
    assert out.status == m.FAILED and out.reason == "result_unclear" and out.report["num_turns"] is None


def test_tool_list_cannot_smuggle_a_write_tool_into_read_only():
    for tools in (["Read", "Grep(x),Bash(rm)"], ["Grep(x) Edit"], ["Write"], ["Bash"]):
        with pytest.raises(ValueError):
            agent_def.AgentDef(folder="/x", prompt="p", tools=tools)
    assert agent_def.AgentDef(folder="/x", prompt="p", permission="edits_in_folder", tools=["Read", "Edit", "Bash(git:*)"])


def test_unknown_login_is_a_named_skip_and_one_bad_run_never_stops_the_pass(monkeypatch):
    target = agent_def.AgentDef(folder="/x", prompt="p", login_account_id="no-such-login").model_dump(mode="json")
    verdict, _ = gates.evaluate({"enabled": True, "automation_id": "a", "target": target}, {"run_id": "r"}, [])
    assert verdict == gates.Verdict(m.SKIPPED, m.R_LOGIN)

    updates, dispatched = [], []

    class FakeStore:
        on_change = None

        def claim_due(self, now, boot_id):
            return [{"run_id": "bad", "automation_id": "a"}, {"run_id": "good", "automation_id": "b"}]

        def update_run(self, run_id, **fields):
            updates.append((run_id, fields))

        def active_run_sessions(self):
            return []

        def settle_retry(self, automation_id, failed, now):
            return None

        def get(self, automation_id):
            return {"automation_id": automation_id, "delivery": {"notify": False}}

    scheduler = Scheduler(SimpleNamespace(), FakeStore())

    async def dispatch(run):
        if run["run_id"] == "bad":
            raise RuntimeError("boom")
        dispatched.append(run["run_id"])

    monkeypatch.setattr(scheduler, "_dispatch", dispatch)
    assert asyncio.run(scheduler.pass_once()) == 2
    assert dispatched == ["good"] and updates[0][0] == "bad" and updates[0][1]["reason"] == "dispatch_error"


@pytest.mark.parametrize("which", ["on_started", "on_line"])
def test_a_raising_callback_leaves_no_child_running(rig, tmp_path, which):
    pids = []

    async def boom(pid):
        pids.append(pid)
        raise RuntimeError("store write failed")

    def boom_line(raw):
        raise RecursionError

    argv = [str(tmp_path / "claude"), "-p"]
    kwargs = {"on_started": boom, "on_line": lambda raw: False} if which == "on_started" else {"on_line": boom_line}
    with pytest.raises((RuntimeError, RecursionError)):
        asyncio.run(refresh_poke.run_child_streaming(argv, {"PATH": os.environ["PATH"]}, timeout=30, stdin=b"MODE:turns", **kwargs))
    if which == "on_started":
        assert pids and not _alive(pids[0])
    else:
        rec = rig.rec()
        assert not _alive(rec["pid"]) and not _alive(rec["grandchild"])


def test_folder_must_be_a_registered_unarchived_project(tmp_path, monkeypatch):
    import sqlite3

    live, archived, stranger = tmp_path / "live", tmp_path / "old", tmp_path / "stranger"
    for d in (live, archived, stranger):
        d.mkdir()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, root TEXT, archived_at TEXT, company_id INTEGER)")
    conn.executemany("INSERT INTO projects (display_name, root, archived_at) VALUES (?, ?, ?)",
                     [("live", str(live), None), ("old", str(archived), "2026-01-01")])
    monkeypatch.setattr(agent.recipes, "_open_db", lambda: conn)
    monkeypatch.setattr(agent, "closing", lambda c: __import__("contextlib").nullcontext(c))
    got = {name: REAL_FOLDER_PROBLEM(str(d)) for name, d in (("live", live), ("old", archived), ("stranger", stranger))}
    assert got == {"live": None, "old": "project_archived", "stranger": "not_a_project"}
    assert REAL_FOLDER_PROBLEM(str(tmp_path / "gone")) == "folder_missing"
    assert REAL_FOLDER_PROBLEM(os.path.expanduser("~")) == "home_folder"
