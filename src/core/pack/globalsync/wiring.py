
from __future__ import annotations

import asyncio
import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Set

import structlog

from src.config import settings as app_settings
from src.core import resource_push
from src.core import config_writer
from src.core.attention import fs_trigger
from src.core.computers import direction
from src.core.federation import peer_links
from src.core.federation.peer_links import CONNECTED
from src.core.pack.globalsync import collect, panel_merge, rules
from src.core.pack.globalsync.sender import (NOT_APPROVED, OFFLINE, RECEIVER_OFF, GlobalSync, PeerView)
from src.core.pack.globalsync.store import Status, clean_settings
from src.core.pack.machines import capabilities, runtime as machines_runtime
from src.core.pack.relay import approval
from src.core.pack.transport import blobs
from src.core.provider_ledger import accounts_store
from src.core.ui_preferences import read_block
from src.core.resource_push import topics

logger = structlog.get_logger()

SYNC: Optional[GlobalSync] = None
WATCH: Optional["AutoWatch"] = None
KICK: Optional["PanelKick"] = None
MAX_WATCH_DIRS = 256
WATCH_QUIET_SECONDS = 5.0
PANEL_QUIET_SECONDS = 2.0
RETRYABLE = (NOT_APPROVED, RECEIVER_OFF, OFFLINE)
_TASKS: Set[asyncio.Task] = set()


def spawn(coro: Any) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def plan_dirs(slots: Sequence[collect.Slot], limit: int = MAX_WATCH_DIRS) -> List[str]:
    found: List[str] = []
    for slot in slots:
        found.append(str(slot.root))
        for top, real in collect._entries(slot):
            if real.is_dir():
                for here, dirs, _files in os.walk(real, followlinks=False):
                    dirs[:] = [d for d in dirs if not rules.is_machine_local(d) and not os.path.islink(os.path.join(here, d))]
                    found.append(here)
                    if len(found) >= limit:
                        return found
    return found


class AutoWatch:

    def __init__(self, sync: GlobalSync, on_change: Callable[[], None]) -> None:
        self._sync = sync
        self._trigger = fs_trigger.FsTrigger(lambda _keys: self._fired(on_change), quiet_seconds=WATCH_QUIET_SECONDS, max_paths=MAX_WATCH_DIRS)

    def start(self) -> bool:
        return self._trigger.start()

    def _fired(self, on_change: Callable[[], None]) -> None:
        on_change()
        spawn(self.rearm())

    async def rearm(self) -> None:
        wanted = self._sync.settings().get("enabled") and self._sync.settings().get("auto") and self._sync.is_main()
        slots = await asyncio.to_thread(collect.slots_for, Path.home(), list(self._sync.accounts()), self._sync.harnesses()) if wanted else []
        dirs = await asyncio.to_thread(plan_dirs, slots) if wanted else []
        self._trigger.rearm({d: ["global"] for d in dirs})

    def close(self) -> None:
        self._trigger.close()


def read_arrangement() -> Optional[dict]:
    try:
        config = json.loads(Path(app_settings.auth_config_file).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = read_block(config).get("values", {}).get("drawer_arrangement") if isinstance(config, dict) else None
    return value if isinstance(value, dict) else None


class PanelKick:

    def __init__(self, loop: asyncio.AbstractEventLoop, run: Callable[[], Any]) -> None:
        self._loop, self._run, self._handle = loop, run, None

    def poke(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._arm)

    def _arm(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._handle = self._loop.call_later(PANEL_QUIET_SECONDS, lambda: spawn(self._run()))


def start(open_db: Callable[[], Any], links_getter: Callable[[], Optional[peer_links.PeerLinks]], app_state: Any = None) -> GlobalSync:
    global SYNC, WATCH
    wired = machines_runtime.wiring()
    if wired is None:
        raise RuntimeError("the Pack machine layer must start before the global setup sync")
    runtime = wired.runtime
    state_dir = Path(app_settings.get_state_dir()) / "pack"

    def peers() -> List[PeerView]:
        links = links_getter()
        return [PeerView(iid, entry.label, links is not None and links.state(iid) == CONNECTED,
                         links.capabilities(iid) if links is not None else [])
                for iid, entry in list(runtime.roster.entries.items()) if iid != runtime.install_id]

    def request_for(install_id: str, timeout: float) -> Optional[blobs.Request]:
        links = links_getter()
        client = links.client(install_id) if links is not None else None
        return blobs.request_via(client, timeout) if client is not None else None

    def accounts() -> List[Any]:
        try:
            return list(accounts_store.list_accounts(Path(app_settings.auth_config_file).expanduser()))
        except (OSError, ValueError):
            return []

    stamps_path = state_dir / "panel-stamps.json"

    def panel_doc() -> dict:
        with closing(open_db()) as conn:
            return panel_merge.doc_for_send(conn, read_arrangement, runtime.install_id, stamps_path,
                                            member=runtime.settings().master_install_id != runtime.install_id)

    if capabilities.mesh_on() and app_state is not None:
        from src.core.pack.globalsync import mesh_panel, mesh_telemetry, mesh_workspace
        from src.core.pack.meshdata import gossip

        def _sync_settings() -> dict:
            return clean_settings(wired.state.global_sync())

        gossip.add_step(mesh_panel.attach(app_state, open_db, _sync_settings, stamps_path))
        gossip.add_step(mesh_workspace.attach(app_state, open_db, _sync_settings, state_dir))
        gossip.add_step(
            mesh_telemetry.attach(
                app_state,
                open_db,
                label=lambda: runtime.label,
                app_version=runtime.app_version,
                state_dir=str(app_settings.get_state_dir()),
            )
        )

        async def _telemetry_beat() -> None:
            while True:
                await asyncio.sleep(mesh_telemetry.REFRESH_SECONDS)
                links_now = links_getter()
                has_peer = links_now is not None and bool(links_now.connected_clients())
                if has_peer and wired.state.restrictions().may_receive_pack_ui:
                    gossip.wake()

        spawn(_telemetry_beat())

    sync = GlobalSync(
        settings=lambda: clean_settings(wired.state.global_sync()), is_main=lambda: runtime.content_alpha() == runtime.install_id,
        peers=peers, approved=approval.reader(open_db), allows=lambda iid: machines_runtime.peer_restriction(iid, "may_receive_global_setup"),
        contained=direction.contained, accounts=accounts, request_for=request_for, status=Status(state_dir / "global-sync-status.json"),
        outbox=state_dir / "global-outbox", home=Path.home(), notify=lambda: resource_push.notify(topics.PACK_GLOBAL_SYNC), installs=Status(state_dir / "global-install-status.json"),
        panel_doc=panel_doc, panel_status=Status(state_dir / "global-panel-status.json"),
        panel_allows=lambda iid: machines_runtime.peer_restriction(iid, "may_receive_pack_ui", default=True),
        main_id=runtime.content_alpha, one_way_toward=direction.is_one_way_toward,
        panel_pending=lambda: panel_merge.pending(stamps_path), panel_sent=lambda: panel_merge.clear_pending(stamps_path))
    SYNC = sync
    loop = asyncio.get_running_loop()
    watch = AutoWatch(sync, lambda: spawn(sync.sync()))
    if watch.start():
        WATCH = watch
        loop.create_task(watch.rearm())

    async def on_connect(install_id: str) -> None:
        chosen = sync.settings()
        if not sync.is_main():
            if chosen.get("panel") and install_id == runtime.content_alpha():
                await sync.send_changes()
            return
        last = await asyncio.to_thread(sync.status.get, install_id)
        files = bool(chosen.get("enabled")) and (chosen.get("auto") or last is None or last.get("state") not in ("synced", "unchanged"))
        if files or chosen.get("panel"):
            await sync.sync([install_id], files=files)

    async def retry_blocked() -> None:
        if not sync.is_main():
            await sync.send_changes()
            return
        if sync.settings().get("panel"):
            await sync.sync(files=False)
        if not sync.settings().get("enabled"):
            return
        records = await asyncio.to_thread(sync.status.all)
        ids = [i for i, r in records.items() if r.get("state") == "refused" and r.get("reason") in RETRYABLE]
        views = {v.install_id: v for v in sync.peers()}
        ready = await asyncio.to_thread(lambda: [i for i in ids if i in views and sync.gate(views[i]) is None])
        if ready:
            await sync.sync(ready)

    async def panel_pass() -> None:
        if capabilities.mesh_on():
            from src.core.pack.meshdata import gossip

            gossip.wake()
        if not sync.settings().get("panel"):
            return
        if sync.is_main():
            await sync.sync(files=False)
        else:
            await sync.send_changes()

    def _wake_mesh_workspace() -> None:
        if capabilities.mesh_on():
            from src.core.pack.meshdata import gossip

            gossip.wake()

    def _workspace_pref_fp(data: Any) -> str:
        values = read_block(data).get("values", {}) if isinstance(data, dict) else {}
        if not isinstance(values, dict):
            return ""
        from src.core.pack.globalsync import mesh_workspace

        return json.dumps(mesh_workspace.synced_pref_snapshot(values), sort_keys=True, separators=(",", ":"))

    def _read_workspace_pref_fp() -> str:
        try:
            config = json.loads(Path(app_settings.auth_config_file).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return _workspace_pref_fp(config)

    global KICK
    kick_panel = KICK = PanelKick(loop, panel_pass)
    resource_push.add_topic_listener(topics.PROJECTS, kick_panel.poke)
    resource_push.add_topic_listener(topics.COMPANIES, kick_panel.poke)
    resource_push.add_topic_listener(topics.ROW_LOOKS, _wake_mesh_workspace)
    resource_push.add_topic_listener(topics.ITEM_SETTINGS, _wake_mesh_workspace)
    seen = {"arrangement": json.dumps(read_arrangement(), sort_keys=True), "workspace_prefs": _read_workspace_pref_fp()}

    def on_config_commit(_path: Path, data: Any) -> None:
        value = read_block(data).get("values", {}).get("drawer_arrangement") if isinstance(data, dict) else None
        now = json.dumps(value if isinstance(value, dict) else None, sort_keys=True)
        if now != seen["arrangement"]:
            seen["arrangement"] = now
            kick_panel.poke()
        ws_now = _workspace_pref_fp(data)
        if ws_now != seen["workspace_prefs"]:
            seen["workspace_prefs"] = ws_now
            _wake_mesh_workspace()

    config_writer.on_commit(on_config_commit)
    links = links_getter()
    if links is not None:
        links.add_connect_listener(lambda iid: spawn(on_connect(iid)))
    resource_push.add_topic_listener(topics.PACK_MACHINES, lambda: spawn(retry_blocked()))
    return sync


def groups_changed() -> None:
    if KICK is not None:
        KICK.poke()


def kick(install_id: str) -> None:
    if SYNC is not None:
        spawn(SYNC.sync([install_id]))
