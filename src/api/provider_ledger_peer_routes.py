
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api import peer_auth
from src.api.auth import require_auth
from src.core.federation import peer_fanout, peer_ledger
from src.core.provider_ledger import poller

router = APIRouter(tags=["provider-ledger"])


@router.get("/provider-ledger/summary", response_model=peer_ledger.LedgerSummary,
            dependencies=[Depends(peer_auth.require_peer_sessions)])
async def get_ledger_summary() -> peer_ledger.LedgerSummary:
    return peer_ledger.summary_of(poller.snapshot())


@router.get("/provider-ledger/peers", response_model=peer_ledger.PeersLedger, dependencies=[Depends(require_auth)])
async def get_peers_ledger() -> peer_ledger.PeersLedger:
    answers = await peer_fanout.ask_peers("/provider-ledger/summary", peer_auth.open_db)
    return peer_ledger.merge(poller.snapshot(), answers)
