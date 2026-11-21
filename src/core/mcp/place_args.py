
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import decide as decide_mod
from src.core.pack.session_place.plan import clip, request_for
from src.core.pack.session_place.types import PlaceRequest, SessionPlacement, Starter

logger = structlog.get_logger()

PLACEMENTS = ("here", "auto")
MAX_NEEDS = 8
MAX_NEED_CHARS = 64
_POSTURES = ("ask", "accept_edits", "skip_all")
HERE_WORD = "this computer"


def read_args(args: dict, *, has_peer: bool) -> Tuple[str, List[str]]:
    placement = args.get("placement", "here")
    if placement not in PLACEMENTS:
        raise ToolError("placement is here (this computer, the default) or auto")
    needs = args.get("needs", [])
    if "needs" in args and placement != "auto":
        raise ToolError("needs works only with placement auto")
    if not isinstance(needs, list) or len(needs) > MAX_NEEDS or not all(isinstance(n, str) and 0 < len(n) <= MAX_NEED_CHARS for n in needs):
        raise ToolError(f"needs is a list of at most {MAX_NEEDS} words, each at most {MAX_NEED_CHARS} characters")
    if placement == "auto" and has_peer:
        raise ToolError("placement auto picks the computer; leave peer out (peer names one by hand)")
    return placement, list(needs)


def marked_folder(folder: str) -> bool:
    from src.core.pack.jobs import boot, policy as policy_mod

    try:
        engine = boot.engine()
        project, _why = engine._resolve_project(folder)  # noqa: SLF001
        return project is not None and policy_mod.get(engine.store, project["uid"]).auto_delegate
    except JobError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("place_default_unreadable", error_type=type(exc).__name__, error=str(exc))
        return False


async def agent_default_auto(folder: str) -> bool:
    import asyncio

    return await asyncio.to_thread(marked_folder, folder)


async def starter_for(app: Any, caller: AgentCaller, *, model: Optional[str] = None) -> Starter:
    from src.core.pack.jobs import agent_facts

    sm = getattr(getattr(app, "state", None), "session_manager", None)
    info = None if caller.external else await agent_facts.info_for_caller(sm, caller.current_session_id)
    posture = (getattr(info, "launched_with", None) or {}).get("permissions") if info is not None else None
    account: Optional[str] = None
    if info is not None:
        try:
            account = (await agent_facts.caller_launch_facts(app, caller.current_session_id)).account_key
        except JobError as exc:
            logger.info("session_place_no_caller_facts", code=exc.code)
    return Starter(kind="agent", session_id=caller.current_session_id, account_key=account,
                   posture=posture if posture in _POSTURES else "unknown", model=model)


def place_request(working_dir: str, agent: Optional[str], needs: List[str]) -> PlaceRequest:
    return request_for(agent, working_dir=working_dir, needs=needs)


async def plan_for(app: Any, req: PlaceRequest, stays: Optional[str]) -> SessionPlacement:
    if stays is not None:
        return SessionPlacement("here", clip(stays))
    try:
        plan = await decide_mod.decide(app, req)
    except JobError as exc:
        raise ToolError(f"placement refused ({exc.code}): {exc.detail}") from exc
    if plan.decision == "refused":
        raise ToolError(f"placement refused ({plan.code}): {plan.reason}")
    return plan


def dedupe_key(raw: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:32]


def card_args(plan: SessionPlacement, starter: Starter, base: Dict[str, Any]) -> Dict[str, Any]:
    shown = {**base, "placement": "auto", "computer": (plan.label or plan.install_id or HERE_WORD) if plan.decision == "remote" else HERE_WORD, "reason": plan.reason}
    if plan.decision == "remote":
        shown["account"] = starter.account_key or ""
        shown["posture"] = starter.posture
    return shown


def summary_of(plan: SessionPlacement, what: str) -> str:
    return f"{what} (auto: {plan.label or HERE_WORD}, {plan.reason})"
