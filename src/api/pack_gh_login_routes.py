
from __future__ import annotations

import asyncio
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api import project_replica_routes as replica_routes
from src.api.auth import require_auth
from src.core.federation import peer_links
from src.core.pack.machines import capabilities as pack_capabilities, runtime as machines_runtime
from src.core.pack.transport import github_account

logger = structlog.get_logger()
router = APIRouter(tags=["pack-transport"], dependencies=[Depends(require_auth)])

CAP_GH_LOGIN = "pack.gh_login"
GH_LOGIN_PATH = "/federation/pack/gh-login"
pack_capabilities.register(CAP_GH_LOGIN)


class GhLoginBody(BaseModel):
    """Which machine and which gh account. The token is never a field."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=200)
    account: str = Field(min_length=1, max_length=64)


@router.post("/pack/gh-login")
async def gh_login(body: GhLoginBody) -> Dict[str, Any]:
    """Log a paired machine's gh into one of this computer's gh accounts (the token crosses once, never stored or echoed).

    Inputs: body (GhLoginBody). Output: {machine, account, ok: true}.
    Raises: HTTPException 404 unknown machine, 409 ``peer_refuses_credentials`` / ``account_not_logged_in`` / ``gh_missing`` /
      ``runs_older_carnivore``, 422 ``bad_account``, 502 the machine is unreachable or refused (its own code, such as
      ``gh_insecure_storage`` or ``account_mismatch``, is passed through).
    Example: POST /api/v1/pack/gh-login {"machine": "studio", "account": "example-owner"}
    """
    if not github_account.valid_account(body.account):
        raise HTTPException(422, {"code": "bad_account", "detail": "that is not a GitHub account name"})
    peer = await asyncio.to_thread(replica_routes.find_peer, body.machine)
    links = peer_links.LINKS
    if links is not None and CAP_GH_LOGIN not in links.capabilities(peer.peer_install_id):
        raise HTTPException(409, {"code": "runs_older_carnivore", "detail": f"{peer.label} runs an older Carnivore"})
    if machines_runtime.peer_restriction(peer.peer_install_id, "may_receive_credentials") is not True:
        raise HTTPException(409, {"code": "peer_refuses_credentials",
                                  "detail": f"{peer.label} has not allowed receiving credentials (set on that computer)"})
    try:
        token = (await asyncio.to_thread(github_account.token_env, body.account))["GH_TOKEN"]
    except github_account.AccountError as exc:
        raise HTTPException(409, {"code": exc.code, "detail": exc.detail}) from exc
    answer = await replica_routes.call_peer(peer, "POST", GH_LOGIN_PATH, {"account": body.account, "token": token})
    del token
    logger.info("pack_gh_login_carried", machine=peer.key, account=body.account)
    return {"machine": str(peer.label), "account": body.account, "ok": bool(answer.get("ok"))}
