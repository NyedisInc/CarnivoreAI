
from __future__ import annotations

import asyncio
import functools
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.config import settings
from src.core import resource_push
from src.core.computers import direction
from src.core.federation import peer_links
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.machines.exchange import post_via
from src.core.pack.relay import approval, ledger_sync_store, login_gate, member_reach, retire
from src.core.pack.relay.ledger_sync_push import LedgerSync
from src.core.pack.relay.owner_side import PeerFn, Relay
from src.core.account_switch import store as account_store
from src.core.account_switch.active import effective_active
from src.core.provider_ledger import accounts_store, poller, poller_core, poller_scan, refresh_poke
from src.core.resource_push import topics

RELAY: Optional[Relay] = None
SYNC: Optional[LedgerSync] = None
_RETIRE: Optional[Callable[[str], Any]] = None


async def retire_removed(sender: str) -> Optional[Dict[str, str]]:
    return None if _RETIRE is None else await _RETIRE(sender)


def candidate_ids() -> List[str]:
    wired = machines_runtime.wiring()
    if wired is None:
        return []
    return [p.install_id for p in wired.peers()
            if p.install_id != wired.runtime.install_id and not direction.contained(p.install_id)]


def active_account(provider: str) -> Optional[str]:
    path = Path(settings.auth_config_file).expanduser()
    try:
        accounts = poller_scan.with_auto_default(accounts_store.list_accounts(path))
        return effective_active(accounts, account_store.read_switch(path), provider).account_id
    except (OSError, ValueError):
        return None


def poll_owned_soon(_install_id: str) -> None:
    for account in poller.snapshot().accounts:
        if not account.relayed and account.provider in ("claude", "codex"):
            poller.poll_soon(account.id)


async def sweep_orphans() -> int:
    if RELAY is None:
        return 0

    def existing() -> Optional[List[str]]:
        try:
            path = Path(settings.auth_config_file).expanduser()
            return [a.id for a in poller_scan.with_auto_default(accounts_store.list_accounts(path), include_relay=False)]
        except (OSError, ValueError):
            return None

    keys = await asyncio.to_thread(existing)
    return 0 if keys is None else await RELAY.sweep_orphans(keys)


def sweep_soon(_install_id: str) -> None:
    try:
        asyncio.get_running_loop().create_task(sweep_orphans(), name="pack-relay-sweep")
    except RuntimeError:
        return


def start(open_db: Callable[[], sqlite3.Connection], links_getter: Callable[[], Optional[peer_links.PeerLinks]],
          manager_getter: Callable[[], Any] = lambda: None) -> Relay:
    global RELAY, SYNC, _RETIRE

    def peer(install_id: str):
        links = links_getter()
        client = links.client(install_id) if links is not None else None
        return None if client is None else (post_via(client, 10.0), links.capabilities(install_id))

    def allows(install_id: str) -> Optional[bool]:
        return machines_runtime.peer_restriction(install_id, "may_receive_credentials")

    wired = machines_runtime.wiring()
    if wired is None:
        raise RuntimeError("the Pack machine layer must start before the credential relay")
    with closing(open_db()) as conn:
        approval.ensure(conn)
    lookup: PeerFn = peer
    ledger_sync_store.PATH = lambda: Path(settings.get_state_dir()) / "ledger_sync.db"
    SYNC = LedgerSync(open_db=open_db, peer=lookup, snapshot=poller.snapshot, self_id=wired.runtime.install_id,
                      self_label=wired.runtime.label, allows=allows)
    poller_core.add_snapshot_listener(SYNC.on_snapshot)
    links = links_getter()
    if links is not None:
        links.add_connect_listener(SYNC.on_connect)
        links.add_connect_listener(poll_owned_soon)
        links.add_connect_listener(sweep_soon)
    caps_of = member_reach.caps_of(links_getter)

    def relay_candidates() -> List[str]:
        return list(dict.fromkeys(candidate_ids() + member_reach.member_ids()))

    relay_accepts = lambda iid, account: machines_runtime.peer_relay_accepts(iid, account, wired.runtime.install_id)  # noqa: E731
    RELAY = Relay(open_db=open_db, peer=member_reach.lookup(links_getter), notify=lambda: resource_push.notify(topics.PACK_RELAY),
                  self_id=wired.runtime.install_id, allows=member_reach.allows, candidates=relay_candidates, on_pushed=SYNC.on_credential_pushed,
                  active=active_account, reach=functools.partial(member_reach.dial_due, open_db, links_getter, accepts=relay_accepts),
                  via_member=member_reach.via_member(links_getter),
                  approved=login_gate.gate(open_db, caps_of=caps_of), accepts=relay_accepts)
    refresh_poke.add_credential_listener(RELAY.on_credential)

    async def reconcile(sender: str, offered: List[str]) -> None:
        await retire.reconcile(manager_getter(), sender, offered)

    wired.runtime.offers_reconcile = reconcile
    _RETIRE = lambda sender: retire.reconcile(manager_getter(), sender, [])  # noqa: E731
    return RELAY
