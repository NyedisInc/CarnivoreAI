
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core import session_change_notice
from src.core import session_journal_store as store
from src.core import session_restore_startup_check as startup_check
from src.core.db import db_path_for
from src.core.session_journal_measure import measure
from src.core.session_journal_task import mutate_journal
from src.core.session_restore_eval import evaluate_offer
from src.core.session_startup_gate import GATE_AWAITING
from src.core.session_restore_offer import OFFER_OPEN, decline, settle_accept
from src.core.swarm import switch as swarm_switch
from src.models.websocket import WSMessageType

logger = structlog.get_logger()
router = APIRouter()

OUTCOME_REOPENED: str = "reopened"
OUTCOME_REFUSED: str = "refused"
OUTCOME_FAILED: str = "failed"

REOPEN_CONCURRENCY: int = 4

PHASE_RESTORING: str = "restoring"
PHASE_DONE: str = "done"

ProgressSink = Callable[[Dict[str, Any]], None]


def progress_sink(app_state: Any, offer_id: str) -> ProgressSink:
    def emit(fields: Dict[str, Any]) -> None:
        session_change_notice.publish(app_state, {
            "type": WSMessageType.RESTORE_OFFER_PROGRESS.value, "offer_id": offer_id, **fields,
        })

    return emit


def _progress_done(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"session_uuid": result.get("session_uuid"), "phase": PHASE_DONE,
            "outcome": result.get("outcome"), "detail": result.get("detail")}


class OfferChoice(BaseModel):
    """One ticked row: which session, under which wrapper."""

    session_uuid: str = Field(..., description="sessions.session_uuid")
    agent_type: str = Field(..., description="a configured wrapper id")


class AcceptRequest(BaseModel):
    """The ticked rows of one offer."""

    offer_id: str
    sessions: List[OfferChoice] = Field(default_factory=list)


class DeclineRequest(BaseModel):
    """Say no to one offer."""

    offer_id: str


def _context() -> Dict[str, Any]:
    from src.config import settings
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME

    state_dir = Path(settings.get_state_dir())
    try:
        sock = settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError):
        sock = DEFAULT_SOCKET_NAME
    return {"settings": settings, "state_dir": state_dir, "socket": sock,
            "db_path": db_path_for(state_dir)}


def _open_offer(state_dir: Path) -> Optional[Dict[str, Any]]:
    loaded = store.load_journal(state_dir)
    offer = loaded.journal.get("offer") if loaded.outcome == store.LOAD_OK else None
    return offer if offer and offer.get("state") == OFFER_OPEN else None


def _evaluated(ctx: Dict[str, Any]) -> Dict[str, Any]:
    offer = _open_offer(ctx["state_dir"])
    if offer is None:
        return {"offer": None, "sessions": []}
    m = measure(ctx["settings"], ctx["socket"], ctx["db_path"])
    return {"offer": offer, "sessions": evaluate_offer(offer, m)}


@router.get("/sessions/restore-offer", dependencies=[Depends(require_auth)])
async def get_restore_offer() -> Dict[str, Any]:
    """The open offer, or ``{"offer": null}``.

    Output: dict - ``offer`` (id, reason, created_at, boot_epoch,
      previous_boot_epoch) and ``sessions`` (one verdict per session still
      closed). An offer whose every session is running again comes back with
      ``sessions: []``, which the page renders as nothing.
    """
    ctx = _context()
    result = await run_in_threadpool(_evaluated, ctx)
    offer = result["offer"]
    if offer is None:
        return {"offer": None, "sessions": []}
    head = {k: offer.get(k) for k in ("id", "reason", "created_at", "boot_epoch", "previous_boot_epoch")}
    return {"offer": head, "sessions": result["sessions"]}


@router.post("/sessions/restore-offer/decline", dependencies=[Depends(require_auth)])
async def decline_restore_offer(body: DeclineRequest) -> Dict[str, Any]:
    """Remember "no" for every session in this offer.

    Raises: HTTPException 409 when the offer is not the open one.
    """
    ctx = _context()
    now = store.now_iso()

    def fn(journal):
        ok = decline(journal, body.offer_id, now)
        return ok, ok

    ok = await run_in_threadpool(mutate_journal, ctx["state_dir"], fn)
    if not ok:
        raise HTTPException(status_code=409, detail="that offer is no longer open")
    store.append_human_log(ctx["state_dir"], "restore_declined", f"offer={body.offer_id}")
    logger.info("session_restore_declined", offer_id=body.offer_id)
    return {"ok": True}


async def _reopen_one(manager: Any, item: Dict[str, Any], agent_type: str) -> Dict[str, Any]:
    from src.api.recreate_action import recreate_by_uuid

    base = {"session_uuid": item["session_uuid"], "title": item.get("title"), "kind": item["kind"],
            "agent_type": agent_type, "conversation": item.get("conversation")}
    try:
        overrides = {"working_dir": item.get("folder")}
        if item.get("conversation_source") == "measured":
            overrides["claude_session_uuid"] = item.get("conversation")
        res = await recreate_by_uuid(item["session_uuid"], agent_type, get_manager=lambda: manager,
                                     row_overrides=overrides)
        started = res.status == "started"
        return {**base, "outcome": OUTCOME_REOPENED if started else OUTCOME_REFUSED,
                "detail": res.detail, "tmux_session": res.tmux_session}
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") == swarm_switch.CODE:
            return {**base, "outcome": OUTCOME_REFUSED, "detail": detail.get("message"), "tmux_session": None}
        return {**base, "outcome": OUTCOME_FAILED, "detail": str(exc.detail), "tmux_session": None}
    except (OSError, ValueError, RuntimeError) as exc:
        logger.error("session_restore_reopen_failed", session_uuid=item["session_uuid"],
                     error=f"{type(exc).__name__}: {exc}")
        return {**base, "outcome": OUTCOME_FAILED, "detail": str(exc), "tmux_session": None}


async def _reopen_all(manager: Any, jobs: List[tuple],
                      progress: Optional[ProgressSink] = None) -> List[Dict[str, Any]]:
    gate = asyncio.Semaphore(REOPEN_CONCURRENCY)
    name_locks: Dict[str, asyncio.Lock] = {}

    async def one(item: Dict[str, Any], agent_type: str) -> Dict[str, Any]:
        lock = name_locks.setdefault(str(item.get("tmux_name") or item["session_uuid"]), asyncio.Lock())
        async with lock, gate:
            if progress is not None:
                progress({"session_uuid": item["session_uuid"], "phase": PHASE_RESTORING})
            result = await _reopen_one(manager, item, agent_type)
            if progress is not None:
                progress(_progress_done(result))
            return result

    return list(await asyncio.gather(*(one(item, agent) for item, agent in jobs)))


async def _flag_startup_prompts(results: List[Dict[str, Any]], sock: str,
                                since: Optional[float] = None) -> None:
    names = [r["tmux_session"] for r in results
             if r.get("outcome") == OUTCOME_REOPENED and r.get("tmux_session")]
    if not names:
        return
    seen = await run_in_threadpool(startup_check.watch_for_startup_prompts, names, socket=sock,
                                   fresh=names, since=since)
    for r in results:
        if r.get("outcome") != OUTCOME_REOPENED or not r.get("tmux_session"):
            continue
        if seen.get(r["tmux_session"]) is True:
            r["startup_gate"] = GATE_AWAITING
            r["detail"] = startup_check.STARTUP_PROMPT_WORDS


@router.post("/sessions/restore-offer/accept", dependencies=[Depends(require_auth)])
async def accept_restore_offer(request: Request, body: AcceptRequest) -> Dict[str, Any]:
    """Reopen the ticked sessions, each re-measured first.

    Description: a ticked session that is no longer selectable (it came back
      on its own, its conversation opened elsewhere, its transcript went) is
      REFUSED with the reason, never forced. A wrapper id that is not one of
      that session's options is refused too.
    Raises: HTTPException 409 when the offer is not the open one.
    """
    ctx = _context()
    evaluated = await run_in_threadpool(_evaluated, ctx)
    offer = evaluated["offer"]
    if offer is None or offer.get("id") != body.offer_id:
        raise HTTPException(status_code=409, detail="that offer is no longer open")
    by_uuid = {s["session_uuid"]: s for s in evaluated["sessions"]}
    manager = request.app.state.session_manager
    results: List[Optional[Dict[str, Any]]] = []
    jobs: List[tuple] = []
    slots: List[int] = []
    for choice in body.sessions:
        item = by_uuid.get(choice.session_uuid)
        if item is None:
            results.append({"session_uuid": choice.session_uuid, "outcome": OUTCOME_REFUSED,
                            "detail": "not in this offer, or running again already"})
            continue
        allowed = {o["id"] for o in item.get("wrapper_options") or []}
        if not item.get("selectable"):
            results.append({"session_uuid": item["session_uuid"], "title": item.get("title"),
                            "kind": item["kind"], "agent_type": choice.agent_type,
                            "outcome": OUTCOME_REFUSED, "detail": item.get("detail")})
        elif choice.agent_type not in allowed:
            results.append({"session_uuid": item["session_uuid"], "title": item.get("title"),
                            "kind": item["kind"], "agent_type": choice.agent_type,
                            "outcome": OUTCOME_REFUSED,
                            "detail": f"{choice.agent_type} is not a configured wrapper"})
        else:
            slots.append(len(results))
            results.append(None)
            jobs.append((item, choice.agent_type))
    since = time.time()
    progress = progress_sink(request.app.state, body.offer_id)
    for r in results:
        if r is not None:
            progress(_progress_done(r))
    for slot, result in zip(slots, await _reopen_all(manager, jobs, progress)):
        results[slot] = result
    await _flag_startup_prompts(results, ctx["socket"], since=since)
    for r in results:
        store.append_human_log(ctx["state_dir"], "restore_result",
                               f"{r.get('title') or r['session_uuid']} outcome={r['outcome']} "
                               f"agent={r.get('agent_type')} tmux={r.get('tmux_session')} detail={r.get('detail')}")
    now = store.now_iso()
    await run_in_threadpool(mutate_journal, ctx["state_dir"],
                            lambda j: (settle_accept(j, body.offer_id, results, now), True))
    store.append_human_log(ctx["state_dir"], "restore_accepted",
                           f"offer={body.offer_id} chosen={len(body.sessions)} "
                           f"reopened={sum(1 for r in results if r['outcome'] == OUTCOME_REOPENED)}")
    logger.info("session_restore_accepted", offer_id=body.offer_id, chosen=len(body.sessions),
                reopened=sum(1 for r in results if r["outcome"] == OUTCOME_REOPENED))
    return {"results": results}

