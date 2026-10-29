
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from contextlib import nullcontext
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.byoai.contracts import (
    MAX_TIMEOUT_S,
    CAP_AGENT, CAP_CHAT, EXTRA_LIST_MODELS, EXTRA_TEST, FLAG_JSON, PROTO_CODEX_CLI,
    AgentRequest, AgentResult, ByoaiError, ChatMessage, ChatRequest, ChatResult, Connection,
    ModelInfo, NotConfigured, Target, TestResult, Unsupported, Usage,
)
from src.core.byoai.native import cli_run
from src.core.provider_ledger import refresh_poke
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS

logger = structlog.get_logger()

PROTOCOL = PROTO_CODEX_CLI
CAPABILITIES: frozenset = frozenset({CAP_CHAT, CAP_AGENT})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

CHAT_TIMEOUT_S = 180.0
AGENT_TIMEOUT_S = 900.0
SANDBOXES = ("read-only", "workspace-write", "danger-full-access")

CODEX_INSTALL_CANDIDATES = ("~/.local/bin/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex")


def build_args(*, model: Optional[str], sandbox: str, cwd: str, isolate: bool,
               schema_file: Optional[str] = None) -> List[str]:
    cli_run.check_choice(sandbox, SANDBOXES, "sandbox")
    cli_run.check_model(model)
    cli_run.check_cwd(cwd)
    args = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--color", "never",
            "-s", sandbox, "-C", cwd]
    if model:
        args += ["-m", model]
    if isolate:
        args += ["--ignore-user-config", "--ignore-rules"]
    if schema_file:
        args += ["--output-schema", schema_file]
    return args + ["-"]


def build_env(codex_home: Optional[str]) -> Dict[str, str]:
    env = {k: os.environ[k] for k in refresh_poke.ENV_ALLOW_LIST if k in os.environ}
    if codex_home is not None:
        env[PROFILE_ENV_VARS["codex"]] = codex_home
    return env


def parse_events(stdout: bytes) -> Tuple[str, Usage, Optional[str]]:
    text, usage, failed = "", Usage(), None
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or "")
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            u = event["usage"]
            usage = Usage(input_tokens=u.get("input_tokens"), output_tokens=u.get("output_tokens"))
        elif kind in ("turn.failed", "error"):
            failed = kind
    return text, usage, failed


async def _binary_and_home(connection: Connection) -> Tuple[str, Optional[str]]:
    home = await asyncio.to_thread(cli_run.profile_dir, "codex", str(connection.options.get("account") or ""))
    binary = refresh_poke.resolve_binary("codex", CODEX_INSTALL_CANDIDATES)
    if binary is None:
        raise NotConfigured("the codex binary was not found on this computer")
    return binary, home


async def _exec(connection: Connection, model: Optional[str], sandbox: str, prompt: str,
                cwd: Optional[str], schema: Optional[Mapping[str, Any]], timeout: float) -> Tuple[str, Usage, Dict[str, Any]]:
    binary, home = await _binary_and_home(connection)
    scratch = tempfile.mkdtemp(prefix="byoai-codex-") if cwd is None else None
    try:
        schema_ctx = cli_run.private_file(json.dumps(schema), ".json") if schema is not None else nullcontext(None)
        with schema_ctx as schema_file:
            args = build_args(model=model, sandbox=sandbox, cwd=cwd or scratch or "",
                              isolate=cli_run.isolated(connection), schema_file=schema_file)
            result = await cli_run.spawn([binary, *args], build_env(home), stdin=prompt.encode("utf-8"),
                                         cwd=cwd or scratch, timeout=timeout, what="codex")
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    text, usage, failed = parse_events(result.stdout)
    if result.exit_code or failed:
        raise cli_run.failure("codex", result)
    return text, usage, {"events_bytes": len(result.stdout)}


async def chat(target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    if request.tools:
        raise Unsupported("codex_cli chat takes no client-side tools")
    prompt = cli_run.render_prompt(request.messages)
    if request.system:
        prompt = f"{request.system}\n\n{prompt}"
    text, usage, raw = await _exec(target.connection, target.model, "read-only", prompt, None,
                                   request.json_schema, min(request.timeout_s or CHAT_TIMEOUT_S, MAX_TIMEOUT_S))
    return ChatResult(text=text, usage=usage, raw=raw)


async def run_agent(target: Target, key: Optional[str], request: AgentRequest) -> AgentResult:
    if request.mcp_config or request.allowed_tools:
        raise Unsupported("codex_cli agent runs take a sandbox, not tools or an MCP config")
    prompt = f"{request.system}\n\n{request.prompt}" if request.system else request.prompt
    text, usage, raw = await _exec(target.connection, target.model, request.permission_mode or "read-only",
                                   prompt, request.cwd, None, request.timeout_s or AGENT_TIMEOUT_S)
    return AgentResult(text=text, usage=usage, raw=raw)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    binary, home = await _binary_and_home(connection)
    result = await cli_run.spawn([binary, "debug", "models"], build_env(home), stdin=b"", cwd=None,
                                 timeout=30.0, what="codex")
    try:
        catalog = json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise ByoaiError("codex did not list its models") from None
    rows = catalog.get("models", []) if isinstance(catalog, dict) else []
    return [ModelInfo(id=m["slug"], capabilities=(CAP_CHAT, CAP_AGENT), flags=(FLAG_JSON,),
                      label=str(m.get("display_name") or m["slug"]))
            for m in rows if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    started = asyncio.get_running_loop().time()
    try:
        if capability == CAP_AGENT:
            answer = (await run_agent(target, None, AgentRequest(prompt="say ok", timeout_s=120.0))).text
        elif capability == CAP_CHAT:
            answer = (await chat(target, None, ChatRequest(messages=(ChatMessage("user", "say ok"),)))).text
        else:
            raise Unsupported(f"codex_cli has no {capability} test")
    except ByoaiError as exc:
        return TestResult(ok=False, capability=capability, model=target.model, detail=f"{type(exc).__name__}: {exc}")
    ms = int((asyncio.get_running_loop().time() - started) * 1000)
    return TestResult(ok=bool(answer.strip()), capability=capability, latency_ms=ms, model=target.model,
                      detail=answer.strip()[:80])
