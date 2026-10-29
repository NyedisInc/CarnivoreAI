
import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from src.core.byoai import adapters
from src.core.byoai.contracts import (
    AgentRequest, ByoaiError, ChatMessage, ChatRequest, Connection, DecideRequest, LoginExpired, Target,
)
from src.core.byoai.native import claude_cli, cli_run, codex_cli, jev
from src.core.provider_ledger import refresh_poke

PROMPT = "ZEBRA-PROMPT-TEXT"
FAKE_KEY = "q" * 20 + "ABCD"


class Recorder:

    def __init__(self, stdout: bytes, exit_code: int = 0):
        self.calls = []
        self.stdout, self.exit_code = stdout, exit_code
        self.seen_files = {}

    async def __call__(self, argv, env, *, stdin, cwd, timeout, what):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": cwd})
        for arg in argv:
            if arg.startswith(os.sep) and os.path.isfile(arg):
                self.seen_files[arg] = (Path(arg).read_text(), oct(os.stat(arg).st_mode & 0o777))
        return refresh_poke.ChildResult(ran=True, exit_code=self.exit_code, timed_out=False,
                                        duration_seconds=0.0, stdout=self.stdout)


@pytest.fixture
def hostile_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_SESSION_ID",
                 "OPENAI_API_KEY", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "inherited-not-a-real-value")
    monkeypatch.setenv("HOME", "/Users/nobody")


def claude_conn(**options):
    return Connection(id="c1", preset="claude_cli", options=options)


def run(coro):
    return asyncio.run(coro)


def patch_claude(monkeypatch, stdout=b'{"result":"ok","total_cost_usd":0.001,"usage":{"input_tokens":3,"output_tokens":2}}',
                 expired=False):
    rec = Recorder(stdout)
    monkeypatch.setattr(cli_run, "spawn", rec)
    monkeypatch.setattr(cli_run, "profile_dir", lambda provider, account: "/profiles/work" if account else None)
    monkeypatch.setattr(claude_cli, "_login_unusable", lambda profile, account: expired)
    monkeypatch.setattr(refresh_poke, "resolve_claude_binary", lambda: "/abs/claude")
    return rec


def test_claude_chat_argv_env_and_stdin(monkeypatch, hostile_env):
    rec = patch_claude(monkeypatch)
    target = Target(claude_conn(account="work"), "haiku")
    result = run(claude_cli.chat(target, None, ChatRequest(messages=(ChatMessage("user", PROMPT),), system="SYS")))
    call = rec.calls[0]
    argv, env = call["argv"], call["env"]
    assert argv[0] == "/abs/claude" and isinstance(argv, list)
    assert "--no-session-persistence" in argv and "--safe-mode" in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--model") + 1] == "haiku"
    assert all(PROMPT not in a and "SYS" != a for a in argv) and call["stdin"] == PROMPT.encode()
    assert "claude doctor" not in " ".join(argv) and "doctor" not in argv
    assert set(env) <= set(refresh_poke.ENV_ALLOW_LIST) | {"CLAUDE_CONFIG_DIR"}
    assert env["CLAUDE_CONFIG_DIR"] == "/profiles/work" and env["HOME"] == "/Users/nobody"
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDE_CODE_SESSION_ID" not in env
    system_path = argv[argv.index("--system-prompt-file") + 1]
    assert rec.seen_files[system_path] == ("SYS", "0o600") and not os.path.exists(system_path)
    assert result.text == "ok" and result.usage.output_tokens == 2 and result.usage.cost_usd == 0.001


def test_claude_default_account_leaves_the_profile_variable_out(monkeypatch, hostile_env):
    rec = patch_claude(monkeypatch)
    run(claude_cli.chat(Target(claude_conn(), None), None, ChatRequest(messages=(ChatMessage("user", "x"),))))
    assert "CLAUDE_CONFIG_DIR" not in rec.calls[0]["env"]
    assert rec.calls[0]["argv"][rec.calls[0]["argv"].index("--model") + 1] == "haiku"


def test_claude_isolation_flags_default_on_and_off_with_the_switch(monkeypatch):
    on = claude_cli.build_args(model="haiku", isolate=True, tools_off=True)
    assert "--safe-mode" in on and "--no-session-persistence" in on
    with_mcp = claude_cli.build_args(model="haiku", isolate=True, tools_off=False, mcp_file="/tmp/m.json")
    assert "--safe-mode" not in with_mcp
    assert with_mcp[with_mcp.index("--setting-sources") + 1] == ""
    settings = json.loads(with_mcp[with_mcp.index("--settings") + 1])
    assert settings["disableAllHooks"] is True and "**/CLAUDE.md" in settings["claudeMdExcludes"]
    assert "--strict-mcp-config" in with_mcp and with_mcp[with_mcp.index("--mcp-config") + 1] == "/tmp/m.json"
    off = claude_cli.build_args(model="haiku", isolate=False, tools_off=True)
    assert not {"--safe-mode", "--setting-sources", "--settings"} & set(off) and "--no-session-persistence" in off
    assert cli_run.isolated(claude_conn()) and not cli_run.isolated(claude_conn(load_user_config=True))


def test_claude_agent_flags_and_private_mcp_file(monkeypatch):
    rec = patch_claude(monkeypatch)
    cfg = {"mcpServers": {"carnivore": {"type": "http", "url": "http://127.0.0.1:8000/mcp",
                                        "headers": {"Authorization": "Bearer " + FAKE_KEY}}}}
    req = AgentRequest(prompt=PROMPT, allowed_tools=("mcp__carnivore__a", "Read"), permission_mode="plan",
                       mcp_config=cfg, cwd=str(Path.cwd()), max_budget_usd=0.5)
    run(claude_cli.run_agent(Target(claude_conn(), "sonnet"), None, req))
    call = rec.calls[0]
    argv = call["argv"]
    assert FAKE_KEY not in " ".join(argv) and PROMPT not in " ".join(argv)
    mcp_path = argv[argv.index("--mcp-config") + 1]
    text, mode = rec.seen_files[mcp_path]
    assert json.loads(text) == cfg and mode == "0o600" and not os.path.exists(mcp_path)
    assert argv[argv.index("--allowed-tools") + 1:argv.index("--allowed-tools") + 3] == ["mcp__carnivore__a", "Read"]
    assert argv[argv.index("--permission-mode") + 1] == "plan" and argv[argv.index("--max-budget-usd") + 1] == "0.5"
    assert call["cwd"] == str(Path.cwd())
    run(claude_cli.run_agent(Target(claude_conn(), None), None, AgentRequest(prompt="x")))
    bare = rec.calls[1]["argv"]
    assert bare[bare.index("--tools") + 1] == "" and "--allowed-tools" not in bare


def test_claude_decide_goes_through_json_schema_and_an_expired_login_never_spawns(monkeypatch):
    rec = patch_claude(monkeypatch, stdout=b'{"result":"{}","structured_output":{"answer":true}}')
    schema = {"type": "object", "properties": {"answer": {"type": "boolean"}}}
    out = run(claude_cli.chat(Target(claude_conn(), "haiku"), None,
                              ChatRequest(messages=(ChatMessage("user", "q"),), json_schema=schema)))
    argv = rec.calls[0]["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema and json.loads(out.text) == {"answer": True}
    expired = patch_claude(monkeypatch, expired=True)
    with pytest.raises(LoginExpired):
        run(claude_cli.chat(Target(claude_conn(), None), None, ChatRequest(messages=(ChatMessage("user", "x"),))))
    assert expired.calls == []


def test_a_failing_cli_error_carries_labels_and_never_the_output():
    result = refresh_poke.ChildResult(ran=True, exit_code=1, timed_out=False, duration_seconds=0.0,
                                      stdout=b"your refresh token zzz-SECRET-zzz is invalid_grant")
    err = cli_run.failure("claude", result)
    assert isinstance(err, LoginExpired) and "SECRET" not in str(err)
    plain = cli_run.failure("codex", refresh_poke.ChildResult(True, 2, False, 0.0, stdout=b"boom SECRET-text"))
    assert type(plain) is ByoaiError and "SECRET" not in str(plain) and "exited 2" in str(plain)


def test_codex_argv_env_schema_file_and_scratch_dir(monkeypatch, hostile_env):
    events = (b'{"type":"thread.started"}\n{"type":"item.completed","item":{"type":"agent_message","text":"{\\"a\\":1}"}}\n'
              b'{"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":4}}\n')
    rec = Recorder(events)
    monkeypatch.setattr(cli_run, "spawn", rec)
    monkeypatch.setattr(cli_run, "profile_dir", lambda provider, account: "/homes/c2" if account else None)
    monkeypatch.setattr(refresh_poke, "resolve_binary", lambda name, fallbacks=(): "/abs/codex")
    conn = Connection(id="c2", preset="codex_cli", options={"account": "acct"})
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    out = run(codex_cli.chat(Target(conn, "gpt-x"), None,
                             ChatRequest(messages=(ChatMessage("user", PROMPT),), json_schema=schema)))
    call = rec.calls[0]
    argv, env = call["argv"], call["env"]
    assert argv[:2] == ["/abs/codex", "exec"] and argv[-1] == "-" and PROMPT not in " ".join(argv)
    assert {"--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"} <= set(argv)
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "gpt-x"
    assert call["stdin"] == PROMPT.encode() and argv[argv.index("-C") + 1] == call["cwd"]
    schema_path = argv[argv.index("--output-schema") + 1]
    assert json.loads(rec.seen_files[schema_path][0]) == schema and not os.path.exists(schema_path)
    assert not os.path.exists(call["cwd"])
    assert set(env) <= set(refresh_poke.ENV_ALLOW_LIST) | {"CODEX_HOME"} and env["CODEX_HOME"] == "/homes/c2"
    assert "OPENAI_API_KEY" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert out.text == '{"a":1}' and out.usage.input_tokens == 9
    own = Connection(id="c3", preset="codex_cli", options={"load_user_config": True})
    run(codex_cli.chat(Target(own, None), None, ChatRequest(messages=(ChatMessage("user", "x"),))))
    argv2 = rec.calls[1]["argv"]
    assert "--ignore-user-config" not in argv2 and "--ignore-rules" not in argv2 and "-m" not in argv2
    assert "CODEX_HOME" not in rec.calls[1]["env"] and "--output-schema" not in argv2


def test_codex_agent_uses_the_requests_sandbox_and_refuses_tools(monkeypatch):
    rec = Recorder(b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n')
    monkeypatch.setattr(cli_run, "spawn", rec)
    monkeypatch.setattr(cli_run, "profile_dir", lambda provider, account: None)
    monkeypatch.setattr(refresh_poke, "resolve_binary", lambda name, fallbacks=(): "/abs/codex")
    target = Target(Connection(id="c", preset="codex_cli"), None)
    run(codex_cli.run_agent(target, None, AgentRequest(prompt="x", permission_mode="workspace-write", cwd=str(Path.cwd()))))
    assert rec.calls[0]["argv"][rec.calls[0]["argv"].index("-s") + 1] == "workspace-write"
    with pytest.raises(ByoaiError):
        run(codex_cli.run_agent(target, None, AgentRequest(prompt="x", allowed_tools=("a",))))
    with pytest.raises(ByoaiError):
        run(codex_cli.run_agent(target, None, AgentRequest(prompt="x", permission_mode="yolo")))


def test_jev_body_both_question_shapes_and_the_key_stays_out_of_it(monkeypatch):
    questions = {
        "page": {"type": "bool", "question": "does this need the owner?"},
        "when": {"type": "choice", "options": ["now", "later"], "question": "when?"},
        "risk": {"type": "score", "min": 0, "max": 10, "question": "how risky?"},
        "dept": {"type": "choice", "instructions": "who", "criteria": {"a": "alpha", "b": "beta"}},
        "native": {"type": "noul", "instructions": "urgent?"},
    }
    body = jev.build_body(DecideRequest(state={"event": "build failed"}, questions=questions))
    assert body["model"] == "jev-1.13.0" and json.loads(body["state"]) == {"event": "build failed"}
    q = body["questions"]
    assert q["page"] == {"type": "noul", "instructions": "does this need the owner?"}
    assert q["when"]["criteria"] == {"now": "now", "later": "later"} and q["dept"]["criteria"]["a"] == "alpha"
    assert q["risk"]["type"] == "score" and len(q["risk"]["criteria"]) == 2 and q["native"]["type"] == "noul"

    seen = {}

    async def fake_request(connection, key, method, path, **kwargs):
        seen.update(method=method, path=path, key=key, body=kwargs["json"])
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
            "page": {"type": "noul", "noul": 0.9}, "when": {"type": "choice", "choice": "now", "probabilities": {"now": 0.8, "later": 0.2}, "confidence": 0.6},
            "risk": {"type": "score", "score": 1.0, "legend": {"0": "l", "1": "h"}, "confidence": 0.5},
            "dept": {"type": "choice", "choice": "b", "probabilities": {"a": 0.1, "b": 0.9}},
            "native": {"type": "noul", "noul": 0.25}}, "usage": {"input_tokens": 7, "output_tokens": 3}})

    monkeypatch.setattr(jev.transport, "request", fake_request)
    conn = Connection(id="j", preset="jev", base_url="https://api.typesafe.ai", key_host="https://api.typesafe.ai")
    res = run(adapters.decide("jev", Target(conn, "jev-1.13.0"), FAKE_KEY, DecideRequest(state="s", questions=questions)))
    assert seen["method"] == "POST" and seen["path"] == "/v1/systemone" and FAKE_KEY not in json.dumps(seen["body"])
    a = res.answers
    assert a["page"] == {"probability": 0.9, "value": True} and a["when"]["value"] == "now" and a["when"]["probabilities"]["now"] == 0.8
    assert a["risk"]["value"] == 10.0 and a["dept"]["value"] == "b" and a["native"]["value"] == 0.25
    assert res.usage.input_tokens == 7
    assert [m.id for m in run(adapters.list_models("jev", conn, None))] == ["jev-1.13.0"]


def test_every_cli_module_is_wired_through_the_dispatcher():
    for module in (claude_cli, codex_cli):
        assert {"chat", "agent"} == set(module.CAPABILITIES) and module.PROTOCOL in adapters.ADAPTERS
    assert set(jev.CAPABILITIES) == {"decide"}
