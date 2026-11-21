
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.core.machine_stats.cpu_busy import CpuMeter
from src.core.beast_prompts import launch_hooks
from src.core.pack.jobs import launch_line, precheck, precheck_hook, precheck_learn
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import PlaceAnswer
from src.core.pack.reserve import pressure

HOOK = str(launch_line.HOOK_SCRIPT)


class _Route(BaseHTTPRequestHandler):

    answer = {"decision": "block", "computer": "tower", "reason": "over"}
    seen: list = []

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Route.seen.append((self.path, self.headers.get("Authorization"), self.headers.get("X-Carnivore-Session"), body))
        payload = json.dumps(_Route.answer).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def _run(command: str, port: int | None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin"}
    if port is not None:
        env.update({"CARNIVORE_HOOK_URL": f"http://127.0.0.1:{port}/api/v1/hooks/claude-event", "CARNIVORE_HOOK_TOKEN": "tok",
                    "CARNIVORE_SESSION_ID": "ses_1"})
    env.update(env_extra or {})
    stdin = json.dumps({"tool_input": {"command": command}, "cwd": "/work/app", "session_id": "x"})
    return subprocess.run([sys.executable, "-I", HOOK], input=stdin, env=env, capture_output=True, text=True, timeout=10)


def test_hook_blocks_remote_lets_exempt_unmarked_and_down_through():
    server = HTTPServer(("127.0.0.1", 0), _Route)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        _Route.seen.clear()
        _Route.answer = {"decision": "block", "computer": "tower", "reason": "over"}
        blocked = _run("pytest -q", port)
        out = json.loads(blocked.stdout)
        assert blocked.returncode == 0 and blocked.stderr == "" and out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse" and "tower" in out["systemMessage"] and "delegate" in out["systemMessage"]
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith("/// this computer is full") and "\x1b" not in reason
        assert out["systemMessage"].startswith("\x1b[31m///\x1b[0m this computer is full") and out["systemMessage"].count("\x1b") == 2
        assert "again" not in blocked.stdout and "python" not in blocked.stdout
        path, auth, session, body = _Route.seen[0]
        assert (path, auth, session, body) == ("/api/v1/pack/jobs/precheck", "Bearer tok", "ses_1", {"command": "pytest -q", "folder": "/work/app", "tool_use_id": "", "background": False, "timeout_ms": None})
        _Route.seen.clear()
        for exempt in ("git status && ls -la", "grep -rn x src | head", "curl -s http://localhost:5001/x", "FOO=1 git log"):
            assert _run(exempt, port).returncode == 0
        assert _Route.seen == []
        assert "deny" in _run("curl https://example.com", port).stdout
        _Route.seen.clear()
        assert _run("cd /elsewhere/llm && make", port).returncode == 0
        assert _Route.seen[0][3]["folder"] == "/elsewhere/llm"
        _Route.seen.clear()
        done = json.dumps({"hook_event_name": "PostToolUse", "tool_input": {"command": "make"}, "cwd": "/work/app", "tool_use_id": "tu_9"})
        finished = subprocess.run([sys.executable, "-I", HOOK], input=done, env={"PATH": "/usr/bin:/bin", "CARNIVORE_HOOK_URL": f"http://127.0.0.1:{port}/api/v1/hooks/x",
                                  "CARNIVORE_HOOK_TOKEN": "tok", "CARNIVORE_SESSION_ID": "ses_1"}, capture_output=True, text=True, timeout=10)
        assert finished.stdout == "" and _Route.seen[0][0] == "/api/v1/pack/jobs/precheck/finished" and _Route.seen[0][3] == {"tool_use_id": "tu_9"}
        _Route.answer = {"decision": "run", "computer": None, "reason": ""}
        assert _run("pytest -q", port).stdout == ""
    finally:
        server.shutdown()
    assert _run("pytest -q", port).stdout == "" and _run("pytest -q", port).returncode == 0
    assert _run("pytest -q", None).stdout == ""


class _Engine:

    def __init__(self, store=None):
        self.store = store

    def _resolve_project(self, folder):
        return ({"uid": "u", "root": "/w"}, "") if folder.startswith("/w") else (None, "not in a project")

    def _view_for(self, root, uid):
        return None


def _marked(monkeypatch, decision="remote"):
    monkeypatch.setattr(precheck.policy_mod, "get", lambda store, uid: type("P", (), {"auto_delegate": True})())
    monkeypatch.setattr(precheck.place, "place", lambda *a, **k: PlaceAnswer(decision, "i", "tower", "over"))


def test_light_commands_always_run_and_heavy_by_program_or_expectation_block(monkeypatch, tmp_path):
    _marked(monkeypatch)
    eng, mem = _Engine(JobStore(tmp_path)), precheck.Memory()
    for light in ("python3 x.py", "npm install", "curl https://example.com", "timeout 60 ./run.sh", "cargo fmt"):
        assert precheck.decide(eng, "s", light, "/w", memory=mem).decision == "run"
    for heavy in ("cd web && npm run build", "pytest -q", "cargo test", "node scripts/build-all.mjs"):
        assert precheck.decide(eng, "s", heavy, "/w", memory=mem).decision == "block"
    assert precheck.decide(eng, "s", "./run.sh", "/w", background=True, memory=mem).decision == "block"
    assert precheck.decide(eng, "s", "./run.sh", "/w", timeout_ms=600000, memory=mem).decision == "block"
    assert precheck.decide(eng, "s", "./run.sh", "/w", timeout_ms=120000, memory=mem).decision == "run"
    assert precheck.decide(eng, "s", "timeout 300 ./run.sh", "/w", memory=mem).decision == "block"
    assert precheck.decide(eng, "s", "gtimeout 10m ./run.sh", "/w", memory=mem).decision == "block"
    assert precheck.decide(eng, "s", "gtimeout 90 ./run.sh", "/w", memory=mem).decision == "run"
    assert precheck.decide(eng, "s", "pytest -q", "/elsewhere/scratch", memory=mem).decision == "run"
    mem.note_here("s")
    assert precheck.decide(eng, "s", "pytest -q", "/w", memory=mem).decision == "run"
    assert precheck.decide(eng, "t", "pytest -q", "/w", memory=mem).decision == "block" and "again" not in precheck_hook.message("x")[0]


def test_heavy_with_nowhere_to_send_it_runs_here(monkeypatch, tmp_path):
    for decision in ("here", "refused"):
        _marked(monkeypatch, decision)
        assert precheck.decide(_Engine(JobStore(tmp_path)), "s", "npm run build", "/w", memory=precheck.Memory()).decision == "run"


def test_a_slow_run_makes_its_shape_heavy_next_time_and_the_table_is_bounded(monkeypatch, tmp_path):
    _marked(monkeypatch)
    store = JobStore(tmp_path)
    eng, now = _Engine(store), [0.0]
    mem = precheck.Memory(clock=lambda: now[0])
    assert precheck_learn.shape("cd /w && ./deploy.sh --env=prod /Users/a/secret 42") == "deploy.sh <path> --env"
    assert precheck_learn.shape("git status") is None and precheck_learn.shape("npm run build /p") == "npm run build"
    assert precheck.decide(eng, "s", "./deploy.sh 1", "/w", tool_use_id="t1", memory=mem).decision == "run"
    now[0] = 75.0
    precheck.finished(eng, "s", "t1", memory=mem)
    assert precheck.decide(eng, "s", "./deploy.sh 2", "/w", tool_use_id="t2", memory=mem).decision == "block"
    assert precheck.decide(eng, "other", "./deploy.sh 2", "/other", memory=mem).decision == "run"
    precheck.finished(eng, "s", "never-started", memory=mem)
    with store._borrow() as conn:
        assert [r[0] for r in conn.execute("SELECT shape FROM command_runs")] == ["deploy.sh N"]
        for i in range(30):
            precheck_learn.record(store, "u", "deploy.sh N", 1.0, now=1000.0 + i)
        assert conn.execute("SELECT COUNT(*) FROM command_runs").fetchone()[0] == precheck_learn.LAST_RUNS
    assert not precheck_learn.learned_heavy(store, "u", "deploy.sh N")


def test_launch_settings_carry_pre_and_post_hooks_beside_the_deny_list_and_beast_hook():
    deny = json.dumps({"permissions": {"deny": ["Bash(rm -rf:*)"]}, "hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "mine"}]}]}})
    out = launch_hooks.add_hooks(["--settings", deny], delegate=True, permission=True)
    doc = json.loads(out[out.index("--settings") + 1])
    assert doc["permissions"]["deny"] == ["Bash(rm -rf:*)"] and "PermissionRequest" in doc["hooks"]
    assert [b["matcher"] for b in doc["hooks"]["PreToolUse"]] == ["Bash", "Agent|Task"] and len(doc["hooks"]["PostToolUse"]) == 2
    assert doc["hooks"]["PermissionRequest"] and doc["hooks"]["PostToolUse"][1]["matcher"] == "Bash"
    assert "precheck_hook.py" in doc["hooks"]["PostToolUse"][1]["hooks"][0]["command"]
    assert "heavy work" in launch_line.LAUNCH_LINE and "everything else runs here" in launch_line.LAUNCH_LINE


def test_busy_cores_come_from_two_tick_samples_and_macos_has_no_run_queue():
    now = [0.0]
    meter = CpuMeter(read=lambda: (100, 1000) if now[0] == 0.0 else (700, 2000), clock=lambda: now[0])
    meter.sample()
    now[0] = 30.0
    assert meter.busy_cores(10)["busy_1"] == 6.0
    assert pressure.read_run_queue(10, "Darwin") is None


def _agent(port: int | None, tool_input: dict, event: str = "PreToolUse") -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin"}
    if port is not None:
        env.update({"CARNIVORE_HOOK_URL": f"http://127.0.0.1:{port}/api/v1/hooks/claude-event", "CARNIVORE_HOOK_TOKEN": "tok", "CARNIVORE_SESSION_ID": "ses_1"})
    stdin = json.dumps({"tool_name": "Agent", "hook_event_name": event, "tool_input": tool_input, "cwd": "/work/app"})
    return subprocess.run([sys.executable, "-I", HOOK], input=stdin, env=env, capture_output=True, text=True, timeout=10)


def test_agent_hook_denies_over_reserve_names_the_computer_and_the_delegate_task_and_fails_open():
    server = HTTPServer(("127.0.0.1", 0), _Route)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        _Route.seen.clear()
        _Route.answer = {"decision": "block", "computer": "tower", "reason": "over"}
        tool = {"description": "d", "prompt": "review it", "subagent_type": "code-reviewer", "run_in_background": True}
        blocked = _agent(port, tool)
        out = json.loads(blocked.stdout)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert blocked.returncode == 0 and out["hookSpecificOutput"]["permissionDecision"] == "deny" and out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert reason.startswith("/// ") and "\x1b" not in reason and out["systemMessage"].startswith("\x1b[31m///\x1b[0m ")
        assert "tower" in reason and "delegate" in reason and "task = the subagent's prompt" in reason and "agent_type = code-reviewer" in reason
        assert _Route.seen[0][0] == "/api/v1/pack/jobs/precheck/agent" and _Route.seen[0][3] == {"folder": "/work/app"}
        assert "agent_type" not in json.loads(_agent(port, {"prompt": "x", "subagent_type": "Explore"}).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        _Route.seen.clear()
        assert _agent(port, tool, "PostToolUse").stdout == "" and _Route.seen == []
        _Route.answer = {"decision": "run", "computer": None, "reason": ""}
        assert _agent(port, tool).stdout == ""
    finally:
        server.shutdown()
    assert _agent(port, {"prompt": "x"}).stdout == "" and _agent(None, {"prompt": "x"}).stdout == ""


def test_agent_check_blocks_only_a_marked_project_over_reserve_and_never_leaves_nowhere_to_run(monkeypatch, tmp_path):
    eng, mem = _Engine(JobStore(tmp_path)), precheck.Memory()
    _marked(monkeypatch)
    assert precheck.decide_agent(eng, "s", "/w", memory=mem) == precheck.Verdict("block", "over", "tower")
    assert precheck.decide_agent(eng, "s", "/elsewhere", memory=mem).decision == "run"
    mem.note_here("s")
    assert precheck.decide_agent(eng, "s", "/w", memory=mem).decision == "run"
    for decision in ("here", "refused"):
        _marked(monkeypatch, decision)
        assert precheck.decide_agent(eng, "t", "/w", memory=precheck.Memory()).decision == "run"
    monkeypatch.setattr(precheck.policy_mod, "get", lambda store, uid: type("P", (), {"auto_delegate": False})())
    assert precheck.decide_agent(eng, "t", "/w", memory=precheck.Memory()).decision == "run"

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(precheck.policy_mod, "get", boom)
    assert precheck.decide_agent(eng, "t", "/w", memory=precheck.Memory()).decision == "run"
