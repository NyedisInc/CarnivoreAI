
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from src.core.mcp import beast_mode, common, federated, session_target
from src.core.mcp.approvals import typed_confirm
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.mcp.write_tools import _via_route, park

CONFIRMATION_ARGS = frozenset({"confirm_text", "confirm_name", "typed", "confirm", "confirmation"})


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


async def _route(manager: Any, uuid: str, apply: bool, fingerprint: Optional[str] = None,
                 typed: Optional[str] = None) -> dict:
    from src.api import session_purge_routes

    body = session_purge_routes.SessionPurgeRequest(apply=apply, plan_fingerprint=fingerprint, confirm_text=typed)
    request = SimpleNamespace(app=getattr(manager, "app", None))
    return await _via_route(session_purge_routes.purge_session(uuid, body, request))


async def _resolve_uuid(manager: Any, args: dict) -> str:
    import asyncio
    from contextlib import closing

    from src.config import settings
    from src.core.db import DatastoreUnreadableError, connect, db_path_for
    from src.core.inventory import target as purge_target

    text = session_target._target_text(args)
    try:
        info = common._resolve(await common._all_infos(manager), {"target": text})
    except ToolError:
        info = None
    if info is not None:
        if federated.is_remote(info):
            raise ToolError("that session lives on a paired computer: purge it there")
        raise ToolError("that session is live: stop it first (a purge only removes an asleep session)")

    def read() -> str:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            return purge_target.resolve_session_uuid(conn, text)

    try:
        return await asyncio.to_thread(read)
    except (purge_target.TargetNotFound, purge_target.TargetAmbiguous) as exc:
        raise ToolError(str(exc)) from exc
    except DatastoreUnreadableError as exc:
        raise ToolError(f"the datastore is unreadable: {exc}") from exc


def _summary(plan: dict) -> str:
    totals = plan["totals"]
    kept = " (INCOMPLETE: some artifacts are shared and stay)" if not plan["complete"] else ""
    name = plan["confirm_text"]
    return (f"PURGE asleep session {name} for good: its record and {totals['rows']} database rows, "
            f"{totals['files']} files ({totals['bytes']} bytes) including its transcripts{kept}. Cannot be undone. "
            f"Plan {plan['fingerprint']}. Type the session's name exactly to confirm: {name}")


async def session_purge(manager: Any, caller: AgentCaller, args: dict) -> dict:
    if set(args) & CONFIRMATION_ARGS:
        raise ToolError("the owner types the confirmation on the approval card in the app; an agent cannot supply it")
    if set(args) - {"target", "apply", "plan_fingerprint"}:
        raise ToolError("session_purge takes only target, apply and plan_fingerprint")
    apply = args.get("apply", False)
    if not isinstance(apply, bool):
        raise ToolError("apply must be true or false")
    uuid = await _resolve_uuid(manager, args)
    plan = await _route(manager, uuid, False)
    if not apply:
        return _ok(plan)
    fingerprint = args.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ToolError("apply true needs plan_fingerprint: call session_purge with apply false, read the plan, "
                        "and pass back its fingerprint")
    fingerprint = fingerprint.strip()
    if plan["fingerprint"] != fingerprint:
        raise ToolError(f"the plan changed since it was read (fingerprint {fingerprint} is now "
                        f"{plan['fingerprint']}); read the new plan and quote it")
    if not plan["ok"]:
        raise ToolError("the purge is blocked, so nothing was sent for approval: " + "; ".join(plan["blockers"]))
    if not beast_mode.beast_enabled():
        raise ToolError("Beast Mode is not armed: the owner must arm it in the app before a purge can be asked for")

    async def run(approved: bool) -> dict:
        typed = typed_confirm.typed_answer()
        if typed is None:
            return _error("session_purge needs the owner's typed confirmation from the approval card; nothing was done")
        try:
            return _ok(await _route(manager, uuid, True, fingerprint, typed))
        except ToolError as exc:
            return _error(f"session_purge refused: {exc}")

    return await park(manager, caller, uuid, "", "session_purge", _summary(plan),
                      {"target": uuid, "plan_fingerprint": fingerprint}, run,
                      dedupe_key=f"session_purge:{uuid}:{fingerprint}", beast_eligible=False,
                      confirm_text=plan["confirm_text"])


WRITE_TOOLS: dict = {
    "session_purge": (
        "PURGE a stopped session for good: its record and everything traced to it, transcripts included. target is "
        "a session_uuid, ses_ id, DB row id (row:<id> or an integer) or a tmux name one row carries. apply "
        "false returns the plan and fingerprint, no wait. apply true needs the fingerprint and Beast Mode "
        "armed; the owner TYPES the session's name on the card. Always waits for the owner's approval.",
        {"target": _TARGET_SCHEMA,
         "apply": {"type": "boolean", "description": "ask the owner to run the purge (default false: plan only)"},
         "plan_fingerprint": {"type": "string",
                              "description": "required with apply: the fingerprint of the plan you read"}},
        ["target"], session_purge,
    ),
}
