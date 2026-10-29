
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.peer_auth import Principal, open_db, require_peer
from src.core.computers import link_rotate, runtime

router = APIRouter(prefix="/federation", tags=["federation"])
_require_machine = require_peer("machine")


class LinkCertBody(BaseModel):
    """The new cert (standard base64 of the DER) and its signature (base64url, 64 bytes)."""

    model_config = ConfigDict(extra="forbid")

    cert_der: str = Field(max_length=4096)
    sig: str = Field(max_length=128)


@router.post("/link-cert")
async def announce_link_cert(body: LinkCertBody, principal: Principal = Depends(_require_machine)) -> Dict[str, bool]:
    """Store a linked computer's next link cert (both pinned until the new one handshakes). Peer token only."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a linked computer announces its link certificate"})
    rt = runtime.active()
    if rt is None or rt.identity is None:
        raise HTTPException(503, {"code": "computers_unavailable", "detail": "the computers link is not running"})
    grant, own_fid = principal.grant, rt.identity.cert.link_fid

    def store_it() -> None:
        with closing(open_db()) as conn:
            link_rotate.accept(conn, grant, body.cert_der, body.sig, own_link_fid=own_fid)

    try:
        await asyncio.to_thread(store_it)
    except link_rotate.LinkCertRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the link certificate was not accepted"}) from None
    except sqlite3.Error:
        raise HTTPException(503, {"code": "computers_unavailable", "detail": "the datastore could not store the certificate"}) from None
    await rt.repin(force=True)
    rt.notify("computers")
    return {"accepted": True}
