
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import Field, field_validator

from src.api.auth import require_auth, security
from src.api.error_response import api_error, refusal_error
from src.api.session_crud_routes import create_session_with_extra
from src.core.api_keys.store import is_api_key
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import create as create_mod, decide as decide_mod
from src.core.pack.session_place.plan import clip, owner_posture, request_for
from src.core.pack.session_place.types import PlaceRequest, SessionPlacement, Starter
from src.core.pack.session_place.wire import HEX32
from src.models import CreateSessionRequest

router = APIRouter(tags=["pack-session-place"], dependencies=[Depends(require_auth)])

_OWN_FIELDS = {"needs", "request_id"}


class AutoCreateBody(CreateSessionRequest):

    needs: List[str] = Field(default_factory=list, max_length=8)
    request_id: Optional[str] = Field(default=None, pattern=HEX32)

    @field_validator("needs")
    @classmethod
    def _short_words(cls, words: List[str]) -> List[str]:
        if any(len(w) > 64 for w in words):
            raise ValueError("a need is at most 64 characters")
        return words


async def _owner_only(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "auto_owner_only")


def place_request(body: AutoCreateBody) -> PlaceRequest:
    return request_for(body.agent_type, working_dir=os.path.expanduser(body.working_dir) if body.working_dir else None, needs=body.needs)


@router.post("/pack/session-placement/explain")
async def explain(body: AutoCreateBody) -> Dict[str, Any]:
    """Where a session with this body would start, with the one-line reason. Writes nothing.

    Body: the POST /sessions fields plus ``needs``. Output: {placement: {decision "here"|"remote"|"refused", computer (install id or null),
    label (name or null), reason (one line, at most 160 characters), code ("requirement_unmet" | "requirement_busy" | null)}}.
    Raises: 422 bad_request or bad_needs, 404 project_unknown, 409 project_ambiguous, 503 jobs_not_ready.
    """
    try:
        stays = create_mod.local_only_reason(CreateSessionRequest(**body.model_dump(exclude=_OWN_FIELDS, by_alias=True)))
        placed = SessionPlacement("here", clip(stays)) if stays else await decide_mod.decide(None, place_request(body))
    except JobError as exc:
        raise refusal_error(exc) from exc
    return {"placement": placed.wire()}


@router.post("/sessions/auto", status_code=201, dependencies=[Depends(_owner_only)])
async def create_auto(request: Request, body: AutoCreateBody) -> Dict[str, Any]:
    """Start a session of a marked project by auto: here (the ordinary local create) or on another computer's copy at this computer's last commit.

    Body: the POST /sessions fields plus ``needs`` and ``request_id``. Output: {session, placement}; ``session`` is what POST /sessions answers
    (here) or the far session (id ``remote:<peer key>:<tmux name>``, session_uuid, tmux_session, working_dir, host_key, host_label); ``placement``
    is {decision, computer, label, reason, code, request_id, reasons, left_behind, work_lives, ...}. Raises: 409 requirement_unmet (nothing created),
    422, 404, 409, 503 as the explain route, and whatever POST /sessions raises for a local start.
    """
    plain = CreateSessionRequest(**body.model_dump(exclude=_OWN_FIELDS, by_alias=True))

    async def local(create_body: CreateSessionRequest) -> Any:
        return await create_session_with_extra(request, create_body)

    try:
        placed = await create_mod.create_placed(request.app, place_request(body), Starter(kind="owner", model=body.model, posture=owner_posture(body.agent_type)), plain, local_create=local,
                                                request_id=body.request_id)
    except create_mod.PlacementRefused as exc:
        raise refusal_error(exc, extra={"placement": exc.placement.wire()}) from exc
    except JobError as exc:
        if exc.code != "jobs_not_ready":
            raise refusal_error(exc) from exc
        session = await local(plain)
        return {"session": session, "placement": {"decision": "here", "computer": None, "label": None, "reason": clip(exc.detail), "code": None,
                                                  "request_id": body.request_id, "reasons": [clip(exc.detail)], "left_behind": None, "work_lives": None,
                                                  "replayed": False}}
    return {"session": placed.session, "placement": placed.placement}
