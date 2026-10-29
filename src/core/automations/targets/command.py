
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import structlog

from src.core.automations import attachments, command_allowlist, contract, lifecycle
from src.core.automations import models as m

logger = structlog.get_logger()

TAIL_BYTES = 64 * 1024
R_NOT_ALLOWED, R_NO_FOLDER, R_TIMED_OUT, R_SPAWN = "command_not_allowed", "project_missing", "timed_out", "spawn_failed"


TIMEOUT_S = 300.0


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    if not command_allowlist.allows(target.get("command")):
        return R_NOT_ALLOWED
    if target.get("project_id") is not None:
        return contract.project_problem(target["project_id"])
    return None


def _env() -> Dict[str, str]:
    from src.core.provider_ledger.refresh_poke import ENV_ALLOW_LIST  # noqa: PLC0415

    return {k: os.environ[k] for k in ENV_ALLOW_LIST if k in os.environ}


def _tail(chunks: List[bytes]) -> str:
    from src.core.timers.redact import redact  # noqa: PLC0415

    return redact(b"".join(chunks)[-TAIL_BYTES:].decode("utf-8", "replace"))


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    from src.core.automations.targets.recipe import tell_failure  # noqa: PLC0415

    outcome = await _run(ctx, automation, run_row)
    if outcome.status == m.FAILED:
        tell_failure(automation, run_row["run_id"], ctx.store)
    return outcome


async def _run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    from src.core.provider_ledger import refresh_poke  # noqa: PLC0415

    target = automation["target"]
    if not await asyncio.to_thread(command_allowlist.allows, target.get("command")):
        return m.RunOutcome(status=m.FAILED, reason=R_NOT_ALLOWED)
    argv = command_allowlist.argv_of(target["command"])
    cwd = os.path.expanduser("~")
    if target.get("project_id") is not None:
        cwd = await asyncio.to_thread(contract.project_root, int(target["project_id"]))
        if not cwd or not os.path.isdir(cwd):
            return m.RunOutcome(status=m.FAILED, reason=R_NO_FOLDER)
    timeout = min(TIMEOUT_S, float(automation.get("max_runtime_s") or TIMEOUT_S))
    out: List[bytes] = []
    kept = [0]

    def on_line(line: bytes) -> bool:
        out.append(line)
        kept[0] += len(line)
        while kept[0] > TAIL_BYTES and len(out) > 1:
            kept[0] -= len(out.pop(0))
        return False

    async def record_child(pid: int) -> None:
        child = await asyncio.to_thread(lifecycle.describe_child, pid)
        if child:
            await asyncio.to_thread(ctx.store.update_run, run_row["run_id"], child=child)

    folder = await asyncio.to_thread(attachments.prepare, ctx.store.attachments_root, run_row["run_id"])
    res = await refresh_poke.run_child_streaming(argv, {**_env(), attachments.ENV_VAR: str(folder)}, on_line=on_line, timeout=timeout, cwd=cwd,
                                                 on_started=record_child)
    await asyncio.to_thread(ctx.store.update_run, run_row["run_id"], child=None)
    report = {"command": target["command"], "exit_code": res.exit_code, "duration_s": round(res.duration_seconds, 1),
              "stdout_tail": _tail(out), "stderr_tail": _tail([res.stderr_tail])}
    logger.info("automation_command_ended", run_id=run_row["run_id"], exit_code=res.exit_code,
                timed_out=res.timed_out)
    if not res.ran:
        return m.RunOutcome(status=m.FAILED, reason=R_SPAWN, error=res.spawn_error, report=report)
    if res.timed_out:
        return m.RunOutcome(status=m.FAILED, reason=R_TIMED_OUT, report=report)
    if res.exit_code != 0:
        return m.RunOutcome(status=m.FAILED, reason=f"exit_{res.exit_code}", report=report)
    return m.RunOutcome(status=m.SUCCEEDED, report=report)
