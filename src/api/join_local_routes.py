
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.api import enrollment_gate as gate
from src.api.auth import limiter
from src.core.computers import join_job, membership, terminal_helper

logger = structlog.get_logger()

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_BAD_REQUEST_CODES = {"bad_request", "bad_link"}


class JoinBody(BaseModel):
    """Body of ``POST /auth/join``: exactly one of ``code`` and ``link``; ``candidate_fid`` picks among several packs."""

    code: Optional[str] = Field(default=None, max_length=16, repr=False)
    link: Optional[str] = Field(default=None, max_length=512, repr=False)
    candidate_fid: Optional[str] = Field(default=None, max_length=64)


def _check(request: Request, *, allow_joined: bool = False) -> None:
    if not gate.is_local_transport(request):
        logger.info("join_local_refused", reason="join_local_only")
        raise HTTPException(403, detail={"reason": "join_local_only"}, headers=_NO_STORE)
    allowed = ("unpaired", "join_pending", "joined") if allow_joined else ("unpaired", "join_pending")
    if membership.first_run_state() not in allowed:
        raise HTTPException(409, detail={"reason": "not_joinable"}, headers=_NO_STORE)


@router.get("/auth/join/candidates")
@limiter.limit("30/minute")
async def get_join_candidates(request: Request, response: Response) -> Dict[str, Any]:
    """The packs this computer found on the network: ``{"candidates": [{name, fid, fid_short, pack_name, label}]}``."""
    _check(request)
    response.headers["Cache-Control"] = "no-store"
    return {"candidates": join_job.candidate_view()}


@router.post("/auth/join", status_code=202)
@limiter.limit("6/minute")
async def post_join(request: Request, response: Response, body: JoinBody) -> Dict[str, Any]:
    """Start the join (or return the running one). Output: ``JoinStatus``. 422 ``bad_request``/``bad_link``; 503 ``unavailable``."""
    _check(request)
    response.headers["Cache-Control"] = "no-store"
    before = join_job.current_job()
    try:
        job = membership.start_join(body.code, body.link, body.candidate_fid, origin="local", totp_ok=False)
    except join_job.JoinNotAllowed as exc:
        if exc.code in _BAD_REQUEST_CODES:
            raise HTTPException(422, detail={"reason": exc.code}, headers=_NO_STORE) from None
        status = 503 if exc.code == "unavailable" else 409
        raise HTTPException(status, detail={"reason": "not_joinable" if status == 409 else exc.code}, headers=_NO_STORE) from None
    await terminal_helper.open_attach(job, created=job is not before)
    return job.status()


@router.post("/auth/join/look", status_code=202)
@limiter.limit("6/minute")
async def post_join_look(request: Request, response: Response) -> Dict[str, Any]:
    """Look for a pack (#1622): the Terminal helper browses Bonjour once and reports who answered. Output: ``JoinStatus``.

    Carries no code or link and starts no join. The window polls ``GET /auth/join/status``: ``finding`` with ``candidates``
    (``{name, fid, fid_short, pack_name, label}``), or ``failed`` ``no_pack`` / ``local_network_blocked`` / ``helper_not_started``.
    409 ``not_joinable``; 503 ``unavailable``.
    """
    _check(request)
    response.headers["Cache-Control"] = "no-store"
    before = join_job.current_job()
    try:
        job = join_job.start_look(origin="local")
    except join_job.JoinNotAllowed as exc:
        raise HTTPException(503 if exc.code == "unavailable" else 409, detail={"reason": "unavailable" if exc.code == "unavailable" else "not_joinable"},
                            headers=_NO_STORE) from None
    await terminal_helper.open_attach(job, created=job is not before)
    return job.status()


@router.get("/auth/join/status")
@limiter.limit("120/minute")
async def get_join_status(request: Request, response: Response) -> Dict[str, Any]:
    """The latest join job's ``JoinStatus``, or ``idle``. Polled once a second while the join phase shows.

    Answers once joined too (read only, local transport): the window reads ``linking`` until main's first link lands and then
    ``joined`` (#1530 B9), so a 409 there would leave it on ``linking`` forever.
    """
    _check(request, allow_joined=True)
    response.headers["Cache-Control"] = "no-store"
    return join_job.window_status()
