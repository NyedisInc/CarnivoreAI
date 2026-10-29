from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from pydantic import ValidationError

from src.core.automations import attachments, lifecycle, recipes
from src.core.automations import models as m
from src.core.automations.targets import agent_def
from src.core.automations.targets.recipe import _tell, _wants
from src.core.app_alerts import constants as alert_const
from src.core.project_writes import list_projects_ordered
from src.models.automations import UNATTENDED_PHRASE

logger = structlog.get_logger()
FINAL_TEXT_CAP = 64 << 10
_TERMINAL = {"budget_exhausted": "budget_exhausted", "max_turns": "turn_cap", "api_error": "cli_error"}
_SUBTYPE = {"error_max_budget_usd": "budget_exhausted", "error_max_turns": "turn_cap"}


def folder_problem(folder: str) -> Optional[str]:
    try:
        real = Path(folder).resolve(strict=True)
    except (OSError, RuntimeError):
        return "folder_missing"
    if not real.is_dir():
        return "folder_missing"
    if real == Path.home().resolve():
        return "home_folder"
    try:
        with closing(recipes._open_db()) as conn:
            rows = list_projects_ordered(conn, include_archived=True)
    except (OSError, sqlite3.Error):
        return "not_a_project"
    mine = [r for r in rows if _same(r.get("root"), real)]
    if not mine:
        return "not_a_project"
    return None if any(not r.get("archived_at") for r in mine) else "project_archived"


def _same(root: Any, real: Path) -> bool:
    try:
        return bool(root) and Path(str(root)).resolve() == real
    except (OSError, RuntimeError):
        return False


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    return folder_problem(str(target.get("folder") or ""))


class _Stream:

    def __init__(self, max_turns: int) -> None:
        self.max_turns, self.capped, self.unparsed, self.events = max_turns, False, 0, 0
        self._messages: set = set()
        self.result: Optional[Dict[str, Any]] = None

    @property
    def turns(self) -> int:
        return len(self._messages)

    def on_line(self, raw: bytes) -> bool:
        try:
            event = json.loads(raw)
        except (ValueError, RecursionError):
            self.unparsed += 1
            return False
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "assistant":
            self.events += 1
            message = event.get("message")
            mid = message.get("id") if isinstance(message, dict) else None
            self._messages.add(mid if isinstance(mid, str) else f"event-{self.events}")
            if self.turns > self.max_turns:
                self.capped = True
                return True
        elif kind == "result":
            self.result = event
        return False


def _failure_reason(result: Dict[str, Any]) -> Optional[str]:
    reason = _TERMINAL.get(str(result.get("terminal_reason") or "")) or _SUBTYPE.get(str(result.get("subtype") or ""))
    if reason is not None:
        return reason
    if result.get("is_error") or str(result.get("subtype") or "").startswith("error"):
        return "cli_error"
    ok = result.get("is_error") is False and (result.get("subtype") == "success" or result.get("terminal_reason") == "completed")
    return None if ok else "result_unclear"


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _usage(result: Dict[str, Any]) -> Optional[Dict[str, int]]:
    block = result.get("usage")
    if not isinstance(block, dict):
        return None
    count = lambda key: block.get(key) if isinstance(block.get(key), int) and not isinstance(block.get(key), bool) else None  # noqa: E731
    tokens_in, tokens_out = count("input_tokens"), count("output_tokens")
    if tokens_in is None or tokens_out is None:
        return None
    cache = (count("cache_read_input_tokens") or 0) + (count("cache_creation_input_tokens") or 0)
    return {"input": tokens_in, "output": tokens_out, "cache": cache, "total": tokens_in + tokens_out + cache}


async def _api_key(connection_id: str) -> Optional[str]:
    from src.core.byoai import gateway as gateway_module  # noqa: PLC0415
    from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415

    gw = gateway_module.get_gateway()
    try:
        connection = await asyncio.to_thread(gw.connection, connection_id)
    except ByoaiError:
        return None
    if connection.preset != "anthropic" or not connection.enabled:
        return None
    return await asyncio.to_thread(gw.keys.get, connection_id)


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    outcome = await _run(ctx, automation, run_row)
    failed = outcome.status != m.SUCCEEDED
    delivery = {**automation["delivery"], "notify_on": automation["delivery"].get("notify_on") or "always"}
    if _wants({**automation, "delivery": delivery}, failed):
        _tell("automation_failed" if failed else "automation_report", automation, run_row["run_id"],
              alert_const.SEV_WARN if failed else alert_const.SEV_INFO, ctx.store)
    return outcome


async def _run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    from src.core.automations import gates  # noqa: PLC0415
    from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415
    from src.core.byoai.native import claude_cli, cli_run  # noqa: PLC0415
    from src.core.provider_ledger import refresh_poke  # noqa: PLC0415

    def failed(reason: str, **extra: Any) -> m.RunOutcome:
        return m.RunOutcome(status=m.FAILED, reason=reason, **extra)

    try:
        d = agent_def.AgentDef.model_validate(automation["target"])
    except ValidationError:
        return failed("target_invalid")
    if d.permission == "unattended" and d.acknowledge_unattended != UNATTENDED_PHRASE:
        return failed("unattended_not_acknowledged")
    problem = await asyncio.to_thread(folder_problem, d.folder)
    if problem:
        return failed(problem)
    folder = str(Path(d.folder).resolve())
    binary = refresh_poke.resolve_claude_binary()
    if binary is None:
        return failed("cli_not_found")
    key: Optional[str] = None
    if d.api_key_connection_id:
        key = await _api_key(d.api_key_connection_id)
        if not key:
            return failed("api_key_unusable")
    try:
        _, profile = await asyncio.to_thread(gates.login_of, automation["target"])
    except ByoaiError:
        return failed("target_invalid")
    session_id = str(uuid.uuid4())
    files = await asyncio.to_thread(attachments.prepare, ctx.store.attachments_root, run_row["run_id"])
    mode, restricted = d.mode()
    stream = _Stream(d.max_turns)

    async def record_child(pid: int) -> None:
        child = await asyncio.to_thread(lifecycle.describe_child, pid)
        if child:
            await asyncio.to_thread(ctx.store.update_run, run_row["run_id"], child=child)

    extra = cli_run.private_file(d.system_prompt_append, ".txt") if d.system_prompt_append else nullcontext(None)
    try:
        with extra as system_file:
            args = claude_cli.build_agent_run_args(
                session_id=session_id, model=d.model, effort=d.effort, tools=tuple(d.tools), permission_mode=mode,
                max_budget_usd=d.max_budget_usd, max_turns=d.max_turns, system_file=system_file, isolate=d.isolated(),
                restricted=restricted)
            argv, env = refresh_poke.build_claude_command(profile, binary, *args, "--add-dir", str(files))
            env[attachments.ENV_VAR] = str(files)
            if d.isolated():
                env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
            if key:
                env["ANTHROPIC_API_KEY"] = key
            res = await refresh_poke.run_child_streaming(
                argv, env, on_line=stream.on_line, timeout=d.timeout_s, stdin=d.prompt.encode("utf-8"), cwd=folder,
                on_started=record_child)
    except ByoaiError:
        return failed("target_invalid")
    await asyncio.to_thread(ctx.store.update_run, run_row["run_id"], child=None)
    result = stream.result or {}
    report = {
        "final_text": result["result"].encode("utf-8")[:FINAL_TEXT_CAP].decode("utf-8", "ignore") if isinstance(result.get("result"), str) else "",
        "num_turns": result.get("num_turns") if isinstance(result.get("num_turns"), int) else None, "events_seen": stream.events,
        "cost_usd": _number(result.get("total_cost_usd")), "terminal_reason": result.get("terminal_reason"),
        "subtype": result.get("subtype"), "conversation_uuid": result.get("session_id") or session_id, "folder": folder}
    cost = report["cost_usd"]
    usage = _usage(result)
    if not res.ran:
        return failed("cli_not_started", error=res.spawn_error)
    if res.timed_out:
        return failed("timeout", report=report, cost_usd=cost, usage=usage)
    if stream.capped:
        return failed("turn_cap", report=report, cost_usd=cost, usage=usage)
    if result:
        reason = _failure_reason(result)
    elif b"max-turns" in res.stderr_tail.lower() and res.exit_code:
        reason = "max_turns_flag_rejected"
    else:
        reason = "cli_error" if res.exit_code else "no_result"
    if reason == "cli_error" and cli_run.LOGIN_LABELS.intersection(refresh_poke.classify_output(res.stderr_tail)):
        reason = m.R_LOGIN
    if reason:
        return failed(reason, report=report, cost_usd=cost, usage=usage)
    return m.RunOutcome(status=m.SUCCEEDED, report=report, cost_usd=cost, usage=usage)
