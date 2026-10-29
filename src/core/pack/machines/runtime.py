
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.config import settings
from src.core import resource_push
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.federation import fed_key, grants, peer_hosts, peer_links
from src.core.pack.load import agents as agents_mod
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import exchange, restrictions as restrictions_mod, roster as roster_mod, settings_sign
from src.core.pack.machines.config_state import ConfigState, default as default_state
from src.core.pack.machines.snapshot import SnapshotCollector
from src.core.pack.relay import consent as consent_mod, offers as offers_mod
from src.core.pack.rollup_import.puller import BULK_MAX_BODY, RollupImporter
from src.core.resource_push import topics

logger = structlog.get_logger()


def default_master_id(conn: sqlite3.Connection, self_id: str) -> str:
    live = [g for g in grants.list_grants(conn) if not g.revoked]
    if not live:
        return self_id
    oldest = min(live, key=lambda g: g.created_at)
    row = peer_hosts.get(conn, oldest.peer_install_id)
    return self_id if (row is None or row.initiator) else oldest.peer_install_id


def peer_infos(open_db: Callable[[], sqlite3.Connection], links: Optional[peer_links.PeerLinks]) -> List[roster_mod.PeerInfo]:
    with closing(open_db()) as conn:
        rows = peer_hosts.list_peers(conn)
    return [roster_mod.PeerInfo(r.peer_install_id, r.label, r.key,
                                links.state(r.peer_install_id) if links is not None else "disconnected",
                                links.capabilities(r.peer_install_id) if links is not None else [])
            for r in rows]


def apply_scopes(conn: sqlite3.Connection, peer_install_id: str, peer_capabilities: List[str],
                 restrictions: restrictions_mod.Restrictions, tracks_master: bool) -> bool:
    grant = grants.live_for_peer(conn, peer_install_id)
    if grant is None:
        return False
    wanted = set(restrictions_mod.scopes_for(restrictions, tracks_master=tracks_master))
    if caps_mod.has(peer_capabilities, caps_mod.CAP_MACHINE):
        wanted.add("machine")
    if caps_mod.has(peer_capabilities, caps_mod.CAP_SKILLS):
        wanted.add("skills")
    if conn.execute("SELECT 1 FROM project_replicas WHERE install_id = ? LIMIT 1", (peer_install_id,)).fetchone():
        wanted.add("swarm-proxy")
    scopes = (set(grant.scopes) - restrictions_mod.MANAGED_SCOPES) | wanted
    return grants.set_scopes(conn, grant.grant_id, tuple(scopes))


def pinned_key(open_db: Callable[[], sqlite3.Connection], install_id: str) -> Optional[str]:
    try:
        with closing(open_db()) as conn:
            grant = grants.live_for_peer(conn, install_id)
    except (sqlite3.Error, grants.GrantError) as exc:
        logger.warning("pack_settings_pin_read_failed", error_type=type(exc).__name__)
        return None
    return grant.public_key if grant is not None else None


def any_live_grant(open_db: Callable[[], sqlite3.Connection]) -> bool:
    try:
        with closing(open_db()) as conn:
            return any(not g.revoked for g in grants.list_grants(conn))
    except (sqlite3.Error, grants.GrantError) as exc:
        logger.warning("pack_settings_pairing_read_failed", error_type=type(exc).__name__)
        return False


class Wiring:

    def __init__(self, runtime: exchange.PackMachines, open_db: Callable[[], sqlite3.Connection],
                 links: Callable[[], Optional[peer_links.PeerLinks]], state: ConfigState) -> None:
        self.runtime, self._open_db, self._links, self.state = runtime, open_db, links, state

    def open_db(self) -> sqlite3.Connection:
        return self._open_db()

    def peers(self) -> List[roster_mod.PeerInfo]:
        return peer_infos(self._open_db, self._links())

    def sync_scopes(self, peer_install_id: Optional[str] = None) -> None:
        try:
            _, restrictions, _, tracks = self.state.read_all()
            links = self._links()
            with closing(self._open_db()) as conn:
                for peer in ([peer_install_id] if peer_install_id else [r.peer_install_id for r in peer_hosts.list_peers(conn)]):
                    apply_scopes(conn, peer, links.capabilities(peer) if links is not None else [], restrictions, tracks)
        except (sqlite3.Error, OSError, grants.GrantError) as exc:
            logger.warning("pack_scope_sync_failed", error=type(exc).__name__)


_WIRING: Optional[Wiring] = None


def wiring() -> Optional[Wiring]:
    return _WIRING


def peer_restriction(install_id: str, name: str) -> Optional[bool]:
    wired = _WIRING
    entry = wired.runtime.roster.entries.get(install_id) if wired is not None else None
    snapshot = entry.snapshot if entry is not None else None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("restrictions"), dict):
        return None
    return bool(snapshot["restrictions"].get(name))


def peer_relay_accepts(install_id: str, account_key: str, self_install_id: str) -> bool:
    wired = _WIRING
    entry = wired.runtime.roster.entries.get(install_id) if wired is not None else None
    snapshot = entry.snapshot if entry is not None else None
    return consent_mod.peer_accepts(snapshot.get("relay_accept") if isinstance(snapshot, dict) else None,
                                    self_install_id, account_key)


def set_wiring(value: Optional[Wiring]) -> None:
    global _WIRING
    _WIRING = value
    exchange.RUNTIME = value.runtime if value is not None else None


def start(open_db: Callable[[], sqlite3.Connection], links_getter: Callable[[], Optional[peer_links.PeerLinks]],
          *, label: str, app_version: str, state_dir: Callable[[], str],
          pipeline_rev: Callable[[], Dict[str, int]] = lambda: {}) -> "asyncio.Task[None]":
    with closing(open_db()) as conn:
        install_id = get_meta(conn, META_INSTALL_ID) or ""
        stored = roster_mod.load_entries(conn)

    def default_master() -> str:
        with closing(open_db()) as conn:
            return default_master_id(conn, install_id)

    def store(entry: roster_mod.Entry) -> None:
        with closing(open_db()) as conn:
            roster_mod.store_entry(conn, entry)

    def connected():
        links = links_getter()
        return [(peer, exchange.post_via(client), links.capabilities(peer))
                for peer, client in (links.connected_clients() if links is not None else [])]

    def post_for(peer_id: str):
        links = links_getter()
        client = links.client(peer_id) if links is not None else None
        return exchange.bulk_post_via(client, max_body=BULK_MAX_BODY) if client is not None else None

    def caps_for(peer_id: str) -> List[str]:
        links = links_getter()
        return links.capabilities(peer_id) if links is not None else []

    state = default_state()
    try:
        if state.migrate_relay_consent():
            logger.info("pack_relay_consent_migrated", mode=consent_mod.MODE_ALL)
    except (OSError, ValueError) as exc:
        logger.warning("pack_relay_consent_migration_failed", error=type(exc).__name__)
    signing = settings_sign.Signing(install_id=install_id, load_key=lambda: fed_key.load_key(install_id),
                                    pinned_key=lambda iid: pinned_key(open_db, iid))
    runtime = exchange.PackMachines(
        install_id=install_id, label=label, app_version=app_version, state=state, collector=SnapshotCollector(state_dir),
        default_master=default_master, connected=connected, notify=resource_push.notify_coalesced, store=store,
        agents=lambda: agents_mod.collect(open_db), importer=RollupImporter(open_db, post_for, caps_for),
        signing=signing, paired=lambda: any_live_grant(open_db))
    runtime.pipeline_rev = pipeline_rev
    for entry in stored:
        runtime.roster.entries.setdefault(entry.install_id, entry)
    runtime.member_labels = lambda: [{"install_id": install_id, "label": label},
                                     *({"install_id": p.install_id, "label": p.label}
                                       for p in peer_infos(open_db, links_getter()))]
    runtime.credential_offers = lambda: offers_mod.local_offers(open_db, settings.auth_config_file)
    runtime.offers_changed = lambda: resource_push.notify(topics.PACK_RELAY_OFFER)
    wired = Wiring(runtime, open_db, links_getter, state)
    set_wiring(wired)
    links = links_getter()
    if links is not None:
        async def hook(peer_id: str, client: Any, caps: list) -> None:
            await asyncio.to_thread(wired.sync_scopes, peer_id)
            await runtime.beat(peer_id, exchange.post_via(client), caps)

        links.set_beat_hook(hook)
        links.add_connect_listener(lambda peer_id: asyncio.get_running_loop().run_in_executor(None, wired.sync_scopes, peer_id))
    return asyncio.create_task(runtime.run_tick(), name="pack-machines-tick")
