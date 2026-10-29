
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.federation_routes import _db, _error, refuse_tls_pairing
from src.core.federation import grants, pair_sas, pairing, peer_links, peer_sockets
from src.core.federation.grants import GrantError

logger = structlog.get_logger()

router = APIRouter(prefix="/federation", tags=["federation"])


class FinishRequest(BaseModel):
    nonce: str = Field(max_length=64)
    accept: bool
    signature: str = Field(max_length=128)


def _pending_json(p: pair_sas.Pending) -> Dict[str, Any]:
    return {"nonce": p.nonce, "sas": p.sas, "label": p.label, "fid": p.fid, "proof": p.proof,
            "initiator_accepted": bool(p.data["accepted"]), "owner_confirmed": bool(p.data["owner_ok"]),
            "expires_in": pair_sas.ACCEPTING.seconds_left(p)}


def _ready(p: pair_sas.Pending) -> bool:
    return bool(p.data["accepted"]) and (bool(p.data["owner_ok"]) or p.proof == pairing.PROOF_SSH_FILE)


async def _activate(p: pair_sas.Pending) -> None:
    d = p.data
    refuse_tls_pairing(d["install_id"])

    def run(conn: sqlite3.Connection):
        old = grants.live_for_peer(conn, d["install_id"])
        if old is not None and old.public_key != d["public_key"]:
            raise _error(409, "peer_identity_changed", "a live grant for that install id holds a different key")
        if old is not None:
            grants.revoke(conn, old.grant_id)
        grants.create_grant(conn, peer_install_id=d["install_id"], public_key=d["public_key"], label=p.label,
                            remote_grant_id=d["remote_grant_id"], grant_id=d["grant_id"])
        return old

    try:
        old = await _db(run)
    except GrantError as exc:
        raise _error(400, exc.code, str(exc)) from None
    pair_sas.ACCEPTING.pop(p.nonce)
    if old is not None:
        await peer_sockets.close_grant(old.grant_id)
        if peer_links.LINKS is not None:
            await peer_links.LINKS.remove(old.peer_install_id)
    logger.info("federation_paired", grant=d["grant_id"][:8], fid=p.fid, proof=p.proof)


def _find(nonce: str) -> pair_sas.Pending:
    p = pair_sas.ACCEPTING.get(nonce)
    if p is None:
        raise _error(404, "pair_pending_gone", "no pairing is waiting with that id")
    return p


@router.get("/pending-pairs", dependencies=[Depends(require_auth)])
async def list_pending() -> List[Dict[str, Any]]:
    return [_pending_json(p) for p in pair_sas.ACCEPTING.all()]


@router.post("/pending-pairs/{nonce}/confirm", dependencies=[Depends(require_auth)])
async def confirm_pending(nonce: str) -> Dict[str, Any]:
    p = _find(nonce)
    p.data["owner_ok"] = True
    if _ready(p):
        await _activate(p)
        return {"state": "active"}
    return {"state": "awaiting_initiator"}


@router.post("/pending-pairs/{nonce}/cancel", dependencies=[Depends(require_auth)])
async def cancel_pending(nonce: str) -> Dict[str, bool]:
    _find(nonce)
    pair_sas.ACCEPTING.pop(nonce)
    logger.info("federation_pair_cancelled", side="acceptor")
    return {"cancelled": True}


@router.post("/pair/finish")
async def pair_finish(body: FinishRequest) -> Dict[str, str]:
    """The initiator's accept or cancel, signed with the key it paired with. An unknown pairing and a bad
    signature answer alike, so the response is no oracle."""
    p = pair_sas.ACCEPTING.get(body.nonce)
    if p is None or not pair_sas.verify_finish(p.data["public_key"], body.nonce, body.accept, body.signature):
        raise _error(404, "pair_pending_gone", "no pairing is waiting with that id")
    if not body.accept:
        pair_sas.ACCEPTING.pop(body.nonce)
        logger.info("federation_pair_cancelled", side="initiator")
        return {"state": "cancelled"}
    p.data["accepted"] = True
    if _ready(p):
        await _activate(p)
        return {"state": "active"}
    return {"state": "awaiting_owner"}
