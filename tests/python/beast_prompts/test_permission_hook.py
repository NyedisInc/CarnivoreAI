
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import beast_permission_hook_routes
from src.api.agent_auth import require_agent
from src.core.beast_prompts import launch_hooks
from src.core.mcp import pending
from src.core.mcp.caller import AgentCaller
from tests.python.beast_mode.grid import install

SCRIPT = str(launch_hooks.PERMISSION_SCRIPT)


class _Store:

    def __init__(self) -> None:
        self.rows: list = []

    def record_beast(self, **kwargs) -> None:
        self.rows.append(kwargs)


def _client(monkeypatch, *, external: bool = False):
    store = _Store()
    monkeypatch.setattr(pending, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(beast_permission_hook_routes.router, prefix="/api/v1")
    caller = AgentCaller("ses_1", "carnivore_x", "ses_1", token_name="mcp-token:t" if external else "")
    app.dependency_overrides[require_agent] = lambda: caller
    return TestClient(app), store


def _ask(client, tool="Bash", **tool_input):
    return client.post("/api/v1/beast-mode/permission-request", json={"tool_name": tool, "tool_input": tool_input or {"command": "ls"}, "cwd": "/w"}).json()


def test_route_allows_a_plain_tool_with_beast_on_and_records_it(monkeypatch):
    install(monkeypatch, {}, armed=lambda: True, prompts=lambda: True)
    client, store = _client(monkeypatch)
    assert _ask(client, command="touch rigfile") == {"decision": "allow"}
    row = store.rows[0]
    assert row["action"] == "session_prompt" and row["args_summary"] == "Bash: touch rigfile" and row["result"]["choice"] == "yes"


def test_route_gives_no_decision_off_widening_plan_question_cell_or_external(monkeypatch):
    install(monkeypatch, {}, armed=lambda: False, prompts=lambda: False)
    client, store = _client(monkeypatch)
    assert _ask(client) == {"decision": "none"}
    install(monkeypatch, {}, armed=lambda: True, prompts=lambda: True)
    assert _ask(client, "ExitPlanMode", plan="x") == {"decision": "none"}
    assert _ask(client, "AskUserQuestion", questions=[]) == {"decision": "none"}
    install(monkeypatch, {"claudePermissionOn": False}, armed=lambda: True, prompts=lambda: True)
    assert _ask(client) == {"decision": "none"}
    install(monkeypatch, {}, armed=lambda: True, prompts=lambda: True)
    external, _ = _client(monkeypatch, external=True)
    assert _ask(external) == {"decision": "none"}
    assert store.rows == []


class _Route(BaseHTTPRequestHandler):

    answer = {"decision": "allow"}

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.dumps(_Route.answer).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def _run(port):
    env = {"PATH": "/usr/bin:/bin"}
    if port is not None:
        env.update({"CARNIVORE_HOOK_URL": f"http://127.0.0.1:{port}/api/v1/hooks/claude-event", "CARNIVORE_HOOK_TOKEN": "t", "CARNIVORE_SESSION_ID": "ses_1"})
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/w"})
    return subprocess.run([sys.executable, "-I", SCRIPT], input=stdin, env=env, capture_output=True, text=True, timeout=10)


def test_script_prints_allow_only_on_allow_and_fails_open():
    server = HTTPServer(("127.0.0.1", 0), _Route)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        out = _run(port)
        assert out.returncode == 0 and json.loads(out.stdout) == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        _Route.answer = {"decision": "none"}
        assert _run(port).stdout == ""
    finally:
        server.shutdown()
    down = _run(port)
    assert down.returncode == 0 and down.stdout == ""
    assert _run(None).stdout == ""


def test_merged_settings_carry_both_hooks_keep_the_deny_list_and_fall_back_when_invalid(tmp_path):
    out = launch_hooks.add_hooks(["--resume", "u"], delegate=True, permission=True)
    hooks = json.loads(out[out.index("--settings") + 1])["hooks"]
    assert hooks["PreToolUse"][0]["matcher"] == "Bash" and "PermissionRequest" in hooks and out.count("--settings") == 1
    swarm = tmp_path / "s.json"
    swarm.write_text(json.dumps({"permissions": {"deny": ["Edit"]}, "hooks": {"PreToolUse": [{"matcher": "X", "hooks": []}]}}))
    out = launch_hooks.add_hooks(["--settings", str(swarm)], delegate=False, permission=True)
    doc = json.loads(out[1])
    assert out.count("--settings") == 1 and doc["permissions"]["deny"] == ["Edit"] and len(doc["hooks"]["PreToolUse"]) == 1 and "PermissionRequest" in doc["hooks"]
    broken = ["--settings", str(tmp_path / "missing.json")]
    assert launch_hooks.add_hooks(broken, delegate=True, permission=True) == broken
    assert launch_hooks.add_hooks([], delegate=False, permission=False) == []
