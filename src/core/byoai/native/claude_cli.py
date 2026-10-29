
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, ContextManager, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.byoai.contracts import (
    MAX_TIMEOUT_S,
    CAP_AGENT, CAP_CHAT, EXTRA_LIST_MODELS, EXTRA_TEST, FLAG_JSON, PROTO_CLAUDE_CLI,
    AgentRequest, AgentResult, ByoaiError, ChatMessage, ChatRequest, ChatResult, Connection,
    LoginExpired, ModelInfo, NotConfigured, Target, TestResult, Unsupported, Usage,
)
from src.core.byoai.native import cli_run
from src.core.byoai.presets import CLAUDE_ALIASES
from src.core.provider_ledger import refresh_poke

logger = structlog.get_logger()

PROTOCOL = PROTO_CLAUDE_CLI
CAPABILITIES: frozenset = frozenset({CAP_CHAT, CAP_AGENT})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

CHAT_TIMEOUT_S = 120.0
AGENT_TIMEOUT_S = 600.0

PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk")

DEFAULT_MODEL = "haiku"

_ISOLATED_SETTINGS = json.dumps(
    {"disableAllHooks": True, "claudeMdExcludes": ["**/CLAUDE.md", "**/CLAUDE.local.md"]},
    separators=(",", ":"),
)


def build_args(*, model: Optional[str], isolate: bool, tools_off: bool,
               json_schema: Optional[Mapping[str, Any]] = None,
               system_file: Optional[str] = None, mcp_file: Optional[str] = None,
               strict_mcp: bool = True, allowed_tools: Tuple[str, ...] = (),
               permission_mode: Optional[str] = None, max_budget_usd: Optional[float] = None) -> List[str]:
    cli_run.check_model(model)
    cli_run.check_tool_names(allowed_tools)
    cli_run.check_choice(permission_mode, PERMISSION_MODES, "permission mode")
    cli_run.check_budget(max_budget_usd)
    args = ["-p", "--output-format", "json", "--no-session-persistence"]
    if model:
        args += ["--model", model]
    if isolate:
        if mcp_file:
            args += ["--setting-sources", "", "--settings", _ISOLATED_SETTINGS]
        else:
            args.append("--safe-mode")
    if mcp_file:
        args += ["--mcp-config", mcp_file]
    if strict_mcp or mcp_file:
        args.append("--strict-mcp-config")
    if tools_off:
        args += ["--tools", ""]
    if allowed_tools:
        args += ["--allowed-tools", *allowed_tools]
    if permission_mode:
        args += ["--permission-mode", permission_mode]
    if max_budget_usd is not None:
        args += ["--max-budget-usd", f"{max_budget_usd:g}"]
    if json_schema is not None:
        args += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    if system_file:
        args += ["--system-prompt-file", system_file]
    return args


AGENT_PERMISSION_MODES = ("acceptEdits", "bypassPermissions", "dontAsk", "plan")


def build_agent_run_args(*, session_id: str, model: Optional[str], effort: Optional[str],
                         tools: Tuple[str, ...], permission_mode: str, max_budget_usd: float, max_turns: int,
                         system_file: Optional[str] = None, isolate: bool = True, restricted: bool = False) -> List[str]:
    cli_run.check_model(model)
    cli_run.check_tool_names(tools)
    cli_run.check_choice(permission_mode, AGENT_PERMISSION_MODES, "permission mode")
    cli_run.check_budget(max_budget_usd)
    args = ["-p", "--output-format", "stream-json", "--verbose", "--session-id", session_id]
    if model:
        args += ["--model", model]
    if effort:
        args += ["--effort", effort]
    if system_file:
        args += ["--append-system-prompt-file", system_file]
    args += ["--tools", ",".join(tools), "--permission-mode", permission_mode, "--permission-prompts", "none",
             "--max-budget-usd", f"{max_budget_usd:g}", "--max-turns", str(int(max_turns))]
    if isolate:
        args += ["--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--strict-mcp-config"]
    if restricted:
        args.append("--restricted")
    return args


def _login_unusable(profile: Optional[str], account_id: str) -> bool:
    from src.core.provider_ledger import credentials as cred
    from src.core.provider_ledger import poller

    try:
        state = cred.credential_state_for(
            cred.read_claude_credential(profile or cred.DEFAULT_CLAUDE_CONFIG_DIR),
            datetime.now(timezone.utc))
    except (OSError, ValueError) as exc:
        logger.warning("byoai_claude_login_unreadable", error=type(exc).__name__)
        return False
    if state == "expired":
        return True
    if account_id:
        for row in poller.snapshot().accounts:
            if row.id == account_id and row.poke is not None and row.poke.state == "needs_login":
                return True
    return False


async def _command(connection: Connection, args: List[str]) -> Tuple[List[str], Dict[str, str]]:
    account_id = str(connection.options.get("account") or "")
    profile = await asyncio.to_thread(cli_run.profile_dir, "claude", account_id)
    if await asyncio.to_thread(_login_unusable, profile, account_id):
        raise LoginExpired("this account's claude login is expired; log in again in the provider ledger")
    binary = refresh_poke.resolve_claude_binary()
    if binary is None:
        raise NotConfigured("the claude binary was not found on this computer")
    return refresh_poke.build_claude_command(profile, binary, *args)


def _usage(body: Mapping[str, Any]) -> Usage:
    raw = body.get("usage") or {}
    if not isinstance(raw, Mapping):
        return Usage(cost_usd=body.get("total_cost_usd"))
    parts = [raw.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    seen = [p for p in parts if isinstance(p, int)]
    return Usage(input_tokens=sum(seen) if seen else None, output_tokens=raw.get("output_tokens"),
                 cost_usd=body.get("total_cost_usd"))


async def _run(connection: Connection, args: List[str], prompt: str, cwd: Optional[str],
               timeout: float) -> Tuple[str, Usage, Mapping[str, Any]]:
    argv, env = await _command(connection, args)
    cwd = cli_run.check_cwd(cwd or None)
    scratch = tempfile.mkdtemp(prefix="byoai-claude-") if cwd is None else None
    try:
        result = await cli_run.spawn(argv, env, stdin=prompt.encode("utf-8"), cwd=cwd or scratch,
                                     timeout=timeout, what="claude")
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    try:
        body = json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        body = None
    if not isinstance(body, dict) or result.exit_code or body.get("is_error"):
        # authentication error
        raise cli_run.failure("claude", result)
    structured = body.get("structured_output")
    text = json.dumps(structured) if structured is not None else str(body.get("result") or "")
    return text, _usage(body), body


async def chat(target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    if request.tools:
        raise Unsupported("claude_cli chat takes no client-side tools; use run_agent with an MCP config")
    with _optional_file(request.system) as system_file:
        args = build_args(model=target.model or DEFAULT_MODEL, isolate=cli_run.isolated(target.connection),
                          tools_off=True, json_schema=request.json_schema, system_file=system_file)
        text, usage, body = await _run(target.connection, args, cli_run.render_prompt(request.messages),
                                       None, min(request.timeout_s or CHAT_TIMEOUT_S, MAX_TIMEOUT_S))
    return ChatResult(text=text, usage=usage, finish_reason=body.get("terminal_reason"), raw=body)


async def run_agent(target: Target, key: Optional[str], request: AgentRequest) -> AgentResult:
    conn = target.connection
    mcp_text = json.dumps(request.mcp_config) if request.mcp_config else None
    with _optional_file(mcp_text, ".json") as mcp_file, _optional_file(request.system) as system_file:
        args = build_args(model=target.model or DEFAULT_MODEL, isolate=cli_run.isolated(conn),
                          tools_off=not request.allowed_tools and mcp_file is None,
                          system_file=system_file, mcp_file=mcp_file, strict_mcp=mcp_file is not None,
                          allowed_tools=request.allowed_tools, permission_mode=request.permission_mode,
                          max_budget_usd=request.max_budget_usd)
        text, usage, body = await _run(conn, args, request.prompt, request.cwd,
                                       request.timeout_s or AGENT_TIMEOUT_S)
    return AgentResult(text=text, usage=usage, raw=body)


def _optional_file(text: Optional[str], suffix: str = ".txt") -> ContextManager[Optional[str]]:
    return cli_run.private_file(text, suffix) if text else nullcontext(None)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    return [ModelInfo(id=alias, capabilities=(CAP_CHAT, CAP_AGENT), flags=(FLAG_JSON,), label=alias)
            for alias in CLAUDE_ALIASES]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    started = asyncio.get_running_loop().time()
    model = target.model or DEFAULT_MODEL
    try:
        if capability == CAP_AGENT:
            answer = (await run_agent(target, None, AgentRequest(prompt="say ok", timeout_s=60.0))).text
        elif capability == CAP_CHAT:
            answer = (await chat(target, None, ChatRequest(messages=(ChatMessage("user", "say ok"),)))).text
        else:
            raise Unsupported(f"claude_cli has no {capability} test")
    except ByoaiError as exc:
        return TestResult(ok=False, capability=capability, model=model, detail=f"{type(exc).__name__}: {exc}")
    ms = int((asyncio.get_running_loop().time() - started) * 1000)
    return TestResult(ok=bool(answer.strip()), capability=capability, latency_ms=ms, model=model,
                      detail=answer.strip()[:80])
