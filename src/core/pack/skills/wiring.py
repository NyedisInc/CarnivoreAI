
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import structlog

from src.core import resource_push
from src.core.computers import membership
from src.core.federation import peer_links
from src.core.federation.peer_link import CONNECTED
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.machines.config_state import ConfigState
from src.core.pack.skills import alerts
from src.core.pack.skills.doc import Choices
from src.core.pack.skills.runtime import PeerView, SkillsSync
from src.core.pack.skills.watch import SkillsWatcher
from src.core.pack.transport import blobs
from src.core.resource_push import topics

logger = structlog.get_logger()
NOTIFY_EVERY_SECONDS = 1.0

SYNC: Optional[SkillsSync] = None
WATCHER: Optional[SkillsWatcher] = None


class ConfigChoices:

    def __init__(self, state: ConfigState) -> None:
        self._state = state

    def read(self) -> Choices:
        raw = self._state.skills_sync()
        mode = raw.get("mode") if raw.get("mode") in ("off", "some", "all") else "off"

        def pairs(key: str) -> frozenset:
            rows = raw.get(key)
            return frozenset((r[0], r[1]) for r in rows if isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(x, str) for x in r)) \
                if isinstance(rows, list) else frozenset()

        return Choices(mode=mode, include=pairs("include"), exclude=pairs("exclude"))

    def write(self, choices: Choices) -> None:
        self._state.save_skills_sync({"mode": choices.mode, "include": sorted([list(p) for p in choices.include]),
                                      "exclude": sorted([list(p) for p in choices.exclude])})


def start(links_getter: Callable[[], Optional[peer_links.PeerLinks]], services: Any = None) -> SkillsSync:
    global SYNC, WATCHER
    from src.api import federation_pack_skills_routes as receiving

    wired = machines_runtime.wiring()
    if wired is None:
        raise RuntimeError("the Pack machine layer must start before skill sync")
    runtime = wired.runtime

    def peers() -> Sequence[PeerView]:
        links = links_getter()
        return [PeerView(iid, entry.label, links is not None and links.state(iid) == CONNECTED, entry.snapshot)
                for iid, entry in list(runtime.roster.entries.items()) if iid != runtime.install_id]

    def request_for(peer_id: str) -> Optional[blobs.Request]:
        links = links_getter()
        client = links.client(peer_id) if links is not None else None
        return blobs.request_via(client) if client is not None else None

    home = Path.home()
    roots = {"claude": home / ".claude" / "skills", "codex": home / ".agents" / "skills"}
    sync = SkillsSync(
        install_id=runtime.install_id, state=receiving.receiver_state(), alpha_id=lambda: runtime.settings().master_install_id,
        choices=ConfigChoices(wired.state), family_roots=lambda: roots,
        receiver_roots=receiving.roots_now, peers=peers, request_for=request_for,
        notify=lambda: resource_push.notify_coalesced(topics.PACK_SKILLS, "skills", NOTIFY_EVERY_SECONDS),
        outbox=receiving.state_dir() / "pack" / "skills-outbox", services=lambda: services)
    from src.core.pack.skills import take_export

    take_export.purge(receiving.export_dir())
    take_export.purge(sync.state.path.parent / "skills-take")
    sync.bind_loop(asyncio.get_running_loop())
    runtime.skills_block = sync.skills_block
    runtime.skills_seen = sync.seen

    def synced_now() -> set[tuple[str, str]]:
        doc = sync.published() if sync.is_alpha() else None
        return {(f, n) for f, n, *_ in [*doc["skills"], *doc["held"], *doc.get("warez", [])]} if doc else set()

    watcher = SkillsWatcher(lambda: roots if sync.is_alpha() else {}, synced_now, sync.kick)
    if watcher.start():
        WATCHER, sync.after_pass = watcher, watcher.rearm
        asyncio.get_running_loop().create_task(watcher.rearm(), name="pack-skills-watch-arm")

    def settings_changed(source: str, from_install_id: str) -> None:
        sync.refresh_alpha()
        alerts.check_alpha(sync.state, source, from_install_id)
        sync.kick()

    def settings_now() -> alerts.Settings:
        doc = runtime.settings()
        return doc.master_install_id, str(doc.rev[1]), int(doc.rev[0])

    def label_of(install_id: str) -> str:
        return next((v.label for v in peers() if v.peer_id == install_id), "")

    def grant_live(install_id: str) -> bool:
        from src.api import peer_auth
        from src.core.federation import grants

        try:
            with closing(peer_auth.open_db()) as conn:
                return grants.live_for_peer(conn, install_id) is not None
        except sqlite3.Error as exc:
            logger.warning("pack_skills_grant_read_failed", error_type=type(exc).__name__)
            return True

    alerts.configure(alerts.Seams(runtime.install_id, settings_now, label_of, grant_live))
    runtime.custody.refused = alerts.settings_refused_hook

    def peer_removed(install_id: str) -> None:
        from src.core.pack.skills import warez_receiver

        warez_receiver.clear_hold_if_alpha(sync.state, install_id)
        alerts.check_placers(sync.state)

    membership.add_removed_listener(peer_removed)
    runtime.skills_settings_changed = settings_changed
    links = links_getter()
    if links is not None:
        links.add_connect_listener(lambda peer_id: sync.spawn(sync.on_connect(peer_id)))
    SYNC = sync
    resource_push.add_topic_listener(topics.CATALOG, sync.kick)
    sync.kick()
    return sync


async def after_index_refresh() -> None:
    if SYNC is not None:
        from src.core.pack.skills import warez_receiver

        if warez_receiver.running():
            return
        await asyncio.to_thread(warez_receiver.reset_transient, SYNC.state)
        await asyncio.to_thread(SYNC.retry_refs)
