
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api import pack_move_env
from src.api.peer_auth import Principal, require_peer
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate.receive import MigrateRefused
from src.core.pack.move import receive

router = APIRouter(prefix="/federation/pack/session", tags=["federation"])
_require_migrate = require_peer("migrate")
pack_capabilities.register("pack.session_move")
pack_capabilities.register("pack.session_send")


class FileRef(BaseModel):
    """One conversation file the target must hold byte for byte."""

    model_config = ConfigDict(extra="forbid")

    rel: str = Field(min_length=1, max_length=500)
    sha256: str = Field(min_length=64, max_length=64)


class ReceiveBody(BaseModel):
    """One session to receive. ``row`` is the durable row (``SESSION_COLUMNS`` plus ``tmux_name``); a dry run carries no blob."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=3, max_length=64)
    dry_run: bool = False
    session_uuid: str = Field(min_length=8, max_length=64)
    project_uid: str = Field(min_length=8, max_length=64)
    working_dir_rel: str = Field(max_length=1024)
    agent_family: Optional[str] = Field(default=None, max_length=40)
    account_key: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    row: Dict[str, Any]
    mode: Literal["move", "copy", "fresh"] = "move"
    transcripts_blob_id: Optional[str] = Field(default=None, max_length=64)
    files: List[FileRef] = []


async def _wake(request: Request, uuid: str, agent_type: Optional[str], launch: Dict[str, Any]) -> Dict[str, Any]:
    from src.api.session_sleep_routes import wake_by_uuid

    answer = await wake_by_uuid(request.app.state, uuid, None, account_id=launch.get("account_id"), extra_env=launch.get("extra_env"),
                                  fork=bool(launch.get("fork")), fresh=bool(launch.get("fresh")))
    return answer.model_dump()


@router.post("/receive")
async def receive_session(body: ReceiveBody, request: Request, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Check (dry run) or bring in one session and wake it. Output: {ok, working_dir} (dry run) or {moved, working_dir, status}.

    Raises: 403 ``pack_restricted`` / ``peer_token_required``; 409 ``project_not_on_target`` / ``project_moved_away`` / ``working_dir_missing`` /
      ``account_not_usable`` / ``session_live_here`` / ``transcript_clash`` / ``verify_failed`` / ``wake_refused`` (the row is undone first).
    """
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer moves a session"})
    data = body.model_dump()
    if not data["dry_run"] and data["mode"] != "fresh" and not data["transcripts_blob_id"]:
        raise HTTPException(422, {"code": "no_conversation_blob", "detail": "a move or copy carries the conversation files"})

    async def wake(uuid: str, agent_type: Optional[str], launch: Dict[str, Any]) -> Dict[str, Any]:
        return await _wake(request, uuid, agent_type, launch)

    try:
        return await receive.receive(pack_move_env.move_target(), principal.grant.peer_install_id, data, wake)
    except MigrateRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "rule": exc.rule}) from exc
