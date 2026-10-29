
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from src.cplugs.crate import import_store, imports, service
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError, conflict, not_found
from src.cplugs.crate.jobs import runner
from src.cplugs.sdk import crate_import as ci

STATE_UNDONE = "undone"
_NOTHING = ("noop", STATE_UNDONE)


def _receipt(env: CrateEnv, import_id: str) -> Dict[str, Any]:
    try:
        receipt = import_store.read_receipt(env.work, import_id)
    except KeyError as exc:
        raise not_found("import_not_found", f"no finished import {import_id}") from exc
    except ValueError as exc:
        raise CrateApiError(500, "receipt_unreadable", str(exc)) from exc
    if receipt.get("state") == STATE_UNDONE:
        raise conflict("already_undone", "this restore was already undone")
    if receipt.get("state") == "noop":
        raise conflict("nothing_to_undo", "this restore changed nothing, so there is nothing to take back")
    return receipt


def preview_blocking(env: CrateEnv, import_id: str) -> Dict[str, Any]:
    _receipt(env, import_id)
    log = import_store.read_undo(env.work, import_id)
    plan = ci.plan_undo(imports.import_env_of(env), import_id, log)
    running = runner.running_request()
    answer = plan.as_json()
    if running:
        answer["blockers"].append({"code": "job_busy", "detail": "a crate job is running; wait for it or cancel it first"})
        answer["ok"] = False
    return {**answer, **ci.undo_log_counts(log)}


def undo_blocking(env: CrateEnv, import_id: str) -> Dict[str, Any]:
    receipt = _receipt(env, import_id)
    if runner.running_request():
        raise conflict("job_busy", "a crate job is running; wait for it or cancel it first")
    log = import_store.read_undo(env.work, import_id)
    try:
        report = ci.run_undo(imports.import_env_of(env), import_id, log)
    except ci.UndoRefused as exc:
        raise conflict("undo_blocked", exc.blockers) from exc
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    undone = {**receipt, "state": STATE_UNDONE, "undone_at": stamp, "undo": report.as_json()}
    import_store.write_receipt(env.work, import_id, undone)
    return {"import_id": import_id, "state": STATE_UNDONE, "undone_at": stamp, "undo": report.as_json()}


async def preview(ctx: Any, import_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(lambda: preview_blocking(service.env_of(ctx), import_id))


async def undo(ctx: Any, import_id: str) -> Dict[str, Any]:
    if not ctx.has("imports.write"):
        raise CrateApiError(403, "permission_missing", "undoing a restore needs the imports.write permission, which the owner has not granted")
    answer = await asyncio.to_thread(lambda: undo_blocking(service.env_of(ctx), import_id))
    ctx.notify("jobs", None)
    return answer
