
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, List

import pytest

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import (
    RigSlot, binary_missing, claude_script, codex_script, seed_claude_config, seed_codex_home)

TOOL = "mcp__carnivore__whoami"


def _need(*names: str) -> None:
    for name in names:
        if binary_missing(name):
            pytest.skip(binary_missing(name))


def _tool_results(requests: List[Any]) -> str:
    dumps = [json.dumps(r) for r in requests]
    return "\n".join(d for d in dumps if "tool_result" in d or "function_call_output" in d)


def _wait_result(model: ScriptedModel, path: str, needle: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    seen = ""
    while time.monotonic() < deadline:
        seen = _tool_results(model.requests_to(path))
        if needle in seen:
            return
        time.sleep(1.0)
    raise AssertionError(f"{needle!r} never came back as a tool result; last: {seen[-1500:]}")


def _session_id(slot: RigSlot, tmux_name: str) -> str:
    for row in slot.slot.api("GET", "/api/v1/sessions/list"):
        if row.get("tmux_session") == tmux_name:
            return row["session"]["id"]
    raise AssertionError(f"{tmux_name} not in the listing")


def _enter(slot: RigSlot, name: str) -> None:
    slot._tmux("send-keys", "-t", f"={name}:", "Enter")


def _dirs(tmp_path, tag: str):
    work = tmp_path / f"work-{tag}"
    work.mkdir()
    return tmp_path / f"cfg-{tag}", work


class _Slow(ThreadingHTTPServer):

    def __init__(self, delay: float) -> None:
        self.hits = 0

        class H(BaseHTTPRequestHandler):
            def do_POST(h) -> None:  # noqa: N805
                h.rfile.read(int(h.headers.get("Content-Length") or 0))
                self.hits += 1
                time.sleep(delay)
                body = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "stub"}}).encode()
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(len(body)))
                h.end_headers()
                h.wfile.write(body)

            def log_message(h, *a: Any) -> None:  # noqa: N805
                pass

        super().__init__(("127.0.0.1", 0), H)
        threading.Thread(target=self.serve_forever, daemon=True).start()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_claude_calls_carnivore_whoami(rig_slot: RigSlot, tmp_path) -> None:
    _need("claude")
    with ScriptedModel([Step("RIG:who", TOOL, {})]) as model:
        cdir, work = _dirs(tmp_path, "c")
        seed_claude_config(cdir, work)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        cl = rig_slot.create_session("rigc", "rigclaude", work)
        rig_slot.wait_for(cl, "❯")
        rig_slot.type_line(cl, "RIG:who please")
        rig_slot.wait_for(cl, "Do you want to proceed?")
        _enter(rig_slot, cl)
        _wait_result(model, "/v1/messages", _session_id(rig_slot, cl))
        assert TOOL in json.dumps([r.get("tools") for r in model.requests_to("/v1/messages")])


def test_real_codex_calls_carnivore_whoami(rig_slot: RigSlot, tmp_path) -> None:
    _need("codex")
    with ScriptedModel([Step("RIG:who", TOOL, {})]) as model:
        home, work = _dirs(tmp_path, "x")
        seed_codex_home(home, model.url, work)
        rig_slot.register_wrapper("rigcodex", "codex", codex_script(home))
        cx = rig_slot.create_session("rigx", "rigcodex", work)
        rig_slot.wait_for(cx, "Ask Codex to do anything")
        rig_slot.type_line(cx, "RIG:who please")
        rig_slot.wait_for(cx, 'Allow the carnivore MCP server to run tool "whoami"?')
        _enter(rig_slot, cx)
        _wait_result(model, "/v1/responses", _session_id(rig_slot, cx))


def _still_answers(slot: RigSlot, model: ScriptedModel, name: str) -> None:
    slot.wait_for(name, "❯")
    slot.type_line(name, "hello there")
    slot.wait_for(name, "rig: ok", timeout=45.0)
    assert model.requests_to("/v1/messages")


def test_claude_survives_a_missing_slow_dead_or_disabled_mcp(rig_slot: RigSlot, tmp_path) -> None:
    _need("claude")
    slow, dead = _Slow(6.0), _closed_port()
    try:
        with ScriptedModel([]) as model:
            cases = {
                "unset": "-u CARNIVORE_MCP_URL",
                "slow": f"CARNIVORE_MCP_URL=http://127.0.0.1:{slow.server_address[1]}/mcp",
                "dead": f"CARNIVORE_MCP_URL=http://127.0.0.1:{dead}/mcp",
            }
            for tag, words in cases.items():
                cdir, work = _dirs(tmp_path, tag)
                seed_claude_config(cdir, work)
                script = (claude_script(model.url, cdir).replace("-u ANTHROPIC_API_KEY ", f"-u ANTHROPIC_API_KEY {words} ", 1)
                          .replace("rigclaude()", f"rig{tag}()", 1))
                rig_slot.register_wrapper(f"rig{tag}", "claude", script)
                _still_answers(rig_slot, model, rig_slot.create_session(f"rig{tag}", f"rig{tag}", work))
            assert slow.hits, "claude never reached the slow /mcp, so the control proved nothing"
            rig_slot.slot.configure({"mcp": {"enabled": False}})
            cdir, work = _dirs(tmp_path, "off")
            seed_claude_config(cdir, work)
            rig_slot.register_wrapper("rigoff", "claude", claude_script(model.url, cdir).replace("rigclaude()", "rigoff()", 1))
            _still_answers(rig_slot, model, rig_slot.create_session("rigoff", "rigoff", work))
            assert "carnivore" not in json.dumps([r.get("tools") for r in model.requests_to("/v1/messages")[-3:]])
    finally:
        slow.shutdown()
