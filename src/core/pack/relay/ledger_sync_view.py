
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.core.federation.peer_ledger import identity_key
from src.core.hosts.identity import remote_session_id
from src.core.pack.relay import ledger_sync_store as store
from src.core.pack.relay.ledger_sync_wire import WireSession
from src.models.provider_ledger import AccountUsage, ElsewhereSession

Directory = Tuple[Dict[str, Tuple[str, str]], str]


def directory() -> Directory:
    from src.core.pack.machines import runtime as machines_runtime

    wired = machines_runtime.wiring()
    if wired is None:
        return {}, ""
    return {p.install_id: (p.label, p.host_key) for p in wired.peers()}, wired.runtime.install_id


def elsewhere(sessions: List[WireSession], names: Directory, sender: str) -> List[ElsewhereSession]:
    peers, self_id = names
    out: List[ElsewhereSession] = []
    for s in sessions:
        owner = s.computer_id or sender
        if owner == self_id:
            continue
        label, host_key = peers.get(owner, (s.computer or "", ""))
        session_id = None
        if s.tmux and host_key and ":" not in s.tmux:
            session_id = remote_session_id(host_key, s.tmux)
        out.append(ElsewhereSession(computer=label or s.computer or "another computer", name=s.name, session_id=session_id))
    return out


def fill_relayed(row: AccountUsage, stored: Optional[store.StoredStatus], names: Directory) -> AccountUsage:
    if stored is None:
        return row
    b = stored.body
    from src.core.provider_ledger.relay_accounts import NAME_SUFFIX

    state = row.credential_state if row.credential_state != "ok" else b.credential_state
    return row.model_copy(update={
        "name": b.name + NAME_SUFFIX if b.name else row.name, "identity": b.identity or row.identity, "plan": b.plan or row.plan, "credential_state": state, "fetched_at": _not_after(b.fetched_at, stored.received_at), "error": b.error,
        "windows": list(b.windows), "poke": b.poke, "login_expires_at": b.login_expires_at,
        "synced_at": datetime.fromtimestamp(stored.received_at, timezone.utc),
        "sessions_elsewhere": elsewhere(b.sessions, names, stored.sender)})


def _not_after(fetched_at: Optional[datetime], received_at: float) -> Optional[datetime]:
    if fetched_at is None:
        return None
    return min(fetched_at, datetime.fromtimestamp(received_at, timezone.utc))


def decorate_local(rows: List[AccountUsage]) -> List[AccountUsage]:
    names = directory()
    out: List[AccountUsage] = []
    for row in rows:
        found = [e for r in store.sessions_reports(row.provider, row.id) for e in elsewhere(r.body.sessions, names, r.sender)]
        out.append(row.model_copy(update={"sessions_elsewhere": found}) if found else row)
    return out


def identity_keys(rows: List[AccountUsage]) -> Dict[str, Optional[str]]:
    pushed = store.statuses_by_profile()
    return {r.id: (pushed[r.id].body.identity_key if r.relayed and r.id in pushed else identity_key(r.provider, r.identity))
            for r in rows}
