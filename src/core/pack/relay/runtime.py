
from __future__ import annotations

import sqlite3
from typing import Callable, List, Optional

from src.core import resource_push
from src.core.computers import direction
from src.core.federation import peer_links
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.machines.exchange import post_via
from src.core.pack.relay.owner_side import PeerFn, Relay
from src.core.provider_ledger import refresh_poke
from src.core.resource_push import topics

RELAY: Optional[Relay] = None


def candidate_ids() -> List[str]:
    wired = machines_runtime.wiring()
    if wired is None:
        return []
    return [p.install_id for p in wired.peers()
            if p.install_id != wired.runtime.install_id and not direction.contained(p.install_id)]


def start(open_db: Callable[[], sqlite3.Connection], links_getter: Callable[[], Optional[peer_links.PeerLinks]]) -> Relay:
    global RELAY

    def peer(install_id: str):
        links = links_getter()
        client = links.client(install_id) if links is not None else None
        return None if client is None else (post_via(client, 10.0), links.capabilities(install_id))

    def allows(install_id: str) -> Optional[bool]:
        return machines_runtime.peer_restriction(install_id, "may_receive_credentials")

    wired = machines_runtime.wiring()
    if wired is None:
        raise RuntimeError("the Pack machine layer must start before the credential relay")
    lookup: PeerFn = peer
    RELAY = Relay(open_db=open_db, peer=lookup, notify=lambda: resource_push.notify(topics.PACK_RELAY),
                  self_id=wired.runtime.install_id, allows=allows, candidates=candidate_ids,
                  accepts=lambda iid, account: machines_runtime.peer_relay_accepts(iid, account, wired.runtime.install_id))
    refresh_poke.add_credential_listener(RELAY.on_credential)
    return RELAY
