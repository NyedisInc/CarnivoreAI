
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.api.peer_auth import open_db
from src.api.error_response import api_error
from src.core import resource_push
from src.core.computers import direction
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.globalsync import wiring as global_wiring
from src.core.pack.relay import approval, login_gate, member_reach, runtime as relay_runtime
from src.core.resource_push import topics

logger = structlog.get_logger()
router = APIRouter(prefix="/pack/relay-approval", tags=["pack-relay"], dependencies=[Depends(require_auth)])


class ApprovalBody(BaseModel):
    """The owner's answer for one computer: ``yes`` or ``no``."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(max_length=3)


def _mesh_candidates() -> List[str]:
    return list(dict.fromkeys(relay_runtime.candidate_ids() + [i for i in member_reach.member_ids() if not direction.contained(i)]))


def _read() -> Dict[str, Any]:
    wired = machines_runtime.wiring()
    if wired is None:
        return {"computers": []}
    if caps_mod.mesh_on():
        with closing(open_db()) as conn:
            return login_gate.card_rows(wired, approval.answers(conn), _mesh_candidates())
    candidates = set(relay_runtime.candidate_ids())
    with closing(open_db()) as conn:
        recorded = approval.answers(conn)
    return {"computers": [{"install_id": p.install_id, "label": p.label, "answer": recorded.get(p.install_id),
                           "pending": p.install_id not in recorded}
                          for p in wired.peers() if p.install_id in candidates]}


def _decided_by_alpha(conn: Any, install_id: str) -> Optional[bool]:
    wired = machines_runtime.wiring()
    if wired is None:
        return False
    readable, master, context = login_gate.list_state(wired)
    if not readable:
        return None if install_id != master else False
    rows = login_gate.card_rows(wired, approval.answers(conn), [install_id], context)["computers"]
    return not rows or rows[0]["decided_by"] == "alpha"


@router.get("")
async def get_approval() -> Dict[str, Any]:
    """Each computer this one could copy accounts to, with the owner's answer (null until answered)."""
    return await asyncio.to_thread(_read)


@router.put("/{install_id}")
async def put_approval(install_id: str, body: ApprovalBody) -> Dict[str, Any]:
    """Record yes or no for one paired computer. 422 for another word, 404 for a computer that is not a candidate."""
    if body.answer not in (approval.YES, approval.NO):
        raise HTTPException(422, {"code": "bad_answer", "detail": "the answer is yes or no"})

    def write() -> Dict[str, Any]:
        mesh = caps_mod.mesh_on()
        if install_id not in (_mesh_candidates() if mesh else relay_runtime.candidate_ids()):
            raise HTTPException(404, {"code": "machine_unknown", "detail": "no paired computer here has that id"})
        with closing(open_db()) as conn:
            decided = _decided_by_alpha(conn, install_id) if mesh else False
            if decided is not False and body.answer == approval.YES:
                if decided is None:
                    raise api_error(409, "relay_list_unreadable")
                approval.forget(conn, install_id)
            else:
                approval.record(conn, install_id, body.answer)
        logger.info("pack_relay_approval_set", target=install_id, answer=body.answer)
        return _read()

    out = await asyncio.to_thread(write)
    if body.answer == approval.YES:
        await asyncio.to_thread(relay_runtime.poll_owned_soon, install_id)
        global_wiring.kick(install_id)
    resource_push.notify(topics.PACK_RELAY_OFFER)
    resource_push.notify(topics.PACK_RELAY)
    return out
