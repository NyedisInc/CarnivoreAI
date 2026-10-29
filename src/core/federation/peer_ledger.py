
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.federation.peer_fanout import PeerAnswer, unavailable_marker
from src.models.provider_ledger import LedgerSnapshot, ProviderKind, UsageWindow


class SummaryAccount(BaseModel):
    """One account as a paired Mac may see it. NOTHING here is a credential or a pointer to one."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderKind
    name: str = Field(max_length=200)
    short_name: Optional[str] = Field(default=None, max_length=200)
    plan: Optional[str] = Field(default=None, max_length=100)
    credential_state: str = Field(max_length=32)
    fetched_at: Optional[datetime] = None
    windows: List[UsageWindow] = Field(default_factory=list, max_length=20)
    identity_key: Optional[str] = Field(default=None, max_length=64, description="One-way key of provider and identity")


class LedgerSummary(BaseModel):

    model_config = ConfigDict(extra="forbid")

    accounts: List[SummaryAccount] = Field(default_factory=list, max_length=100)


class PeerLedgerAccount(SummaryAccount):

    shared: bool = False


class PeerLedger(BaseModel):

    host_key: str
    host_label: str
    accounts: List[PeerLedgerAccount] = Field(default_factory=list)


class PeersLedger(BaseModel):
    """`GET /provider-ledger/peers`: every paired Mac that answered, and the ones that did not."""

    peers: List[PeerLedger] = Field(default_factory=list)
    peer_unavailable: List[Dict[str, str]] = Field(default_factory=list)


def identity_key(provider: str, identity: Optional[str]) -> Optional[str]:
    cleaned = (identity or "").strip().lower()
    return hashlib.sha256(f"{provider}\0{cleaned}".encode()).hexdigest()[:32] if cleaned else None


def summary_of(snapshot: LedgerSnapshot) -> LedgerSummary:
    return LedgerSummary(accounts=[
        SummaryAccount(provider=a.provider, name=a.name, short_name=a.short_name, plan=a.plan,
                       credential_state=a.credential_state, fetched_at=a.fetched_at, windows=a.windows,
                       identity_key=identity_key(a.provider, a.identity))
        for a in snapshot.accounts])


def merge(local: LedgerSnapshot, answers: List[PeerAnswer]) -> PeersLedger:
    mine = {k for k in (identity_key(a.provider, a.identity) for a in local.accounts) if k}
    peers: List[PeerLedger] = []
    failed: List[PeerAnswer] = []
    for a in answers:
        if a.data is None:
            failed.append(a)
            continue
        try:
            summary = LedgerSummary.model_validate(a.data)
        except ValidationError:
            failed.append(PeerAnswer(a.host_key, a.label, None, "bad_answer"))
            continue
        peers.append(PeerLedger(host_key=a.host_key, host_label=a.label, accounts=[
            PeerLedgerAccount(**acct.model_dump(), shared=acct.identity_key in mine if acct.identity_key else False)
            for acct in summary.accounts]))
    return PeersLedger(peers=peers, peer_unavailable=unavailable_marker(failed))
