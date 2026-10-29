
from __future__ import annotations

import asyncio
import copy
import threading
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.computers import direction
from src.core.machine_stats.sample import signature
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.machines import roster as roster_mod
from src.core.pack.machines import settings_doc, settings_sign
from src.core.pack.machines.config_state import ConfigState
from src.core.pack.machines.settings_custody import SettingsCustody
from src.core.pack.machines.roster import Entry, PeerInfo, Roster
from src.core.pack.relay import consent as consent_mod, offers as offers_mod
from src.core.pack.reserve import model as reserve_model

logger = structlog.get_logger()

EXCHANGE_PATH = "/federation/pack/exchange"
RESERVE_PATH = "/federation/pack/reserve"
TIGHTEN_PATH = "/federation/pack/restrictions/tighten"
KICK_DELAY_SECONDS = 2.0
NOTIFY_EVERY_SECONDS = 5.0
TOPIC = "pack_machines"
SNAPSHOT_TTL_SECONDS = 4.0

PostFn = Callable[[str, str, Optional[dict]], Awaitable[Tuple[int, Any]]]


def post_via(client: Any, timeout: float = 5.0) -> PostFn:
    async def post(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
        reply = await asyncio.wait_for(client.request(method, path, json=body), timeout)
        try:
            return reply.status_code, reply.json()
        except ValueError:
            return reply.status_code, None
    return post


def bulk_post_via(client: Any, *, max_body: int, timeout: float = 30.0) -> PostFn:
    async def post(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
        reply = await asyncio.wait_for(client.request(method, path, json=body, timeout=timeout, max_body=max_body), timeout + 5)
        try:
            return reply.status_code, reply.json()
        except ValueError:
            return reply.status_code, None
    return post


def agents_signature(agents: Dict[str, Any]) -> Any:
    rows = agents.get("rows") or []
    return (tuple(sorted((r.get("session_id"), int((r.get("cpu_pct") or 0) // 10), int((r.get("rss_mb") or 0) // 256)) for r in rows)),
            int(((agents.get("machine") or {}).get("cpu_pct") or 0) // 10), int(((agents.get("carnivore") or {}).get("rss_mb") or 0) // 256))


class PackMachines:

    def __init__(self, *, install_id: str, label: str, app_version: str, state: ConfigState, collector: Any,
                 default_master: Callable[[], str], connected: Callable[[], List[Tuple[str, PostFn, List[str]]]],
                 notify: Callable[[str, str, float], None], roster: Optional[Roster] = None,
                 store: Optional[Callable[[Entry], None]] = None, clock: Callable[[], float] = time.time,
                 local_now: Callable[[], datetime] = datetime.now,
                 agents: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                 importer: Optional[Any] = None, signing: Optional[settings_sign.Signing] = None,
                 paired: Callable[[], bool] = lambda: False) -> None:
        self.install_id, self.label, self.app_version = install_id, label, app_version
        self.state, self.collector, self.roster = state, collector, roster or Roster(clock)
        self._default_master, self._connected, self._notify, self._store = default_master, connected, notify, store
        self.custody = SettingsCustody(install_id=install_id, state=state, default_master=default_master, signing=signing,
                                       paired=paired)
        self._clock, self._local_now = clock, local_now
        self._signatures: Dict[str, Any] = {}
        self._stale_timers: Dict[str, threading.Timer] = {}
        self._kick_task: Optional["asyncio.Task[None]"] = None
        self._lease_until = 0.0
        self._peer_want_until = 0.0
        self._agents = agents
        self._snap_lock = threading.Lock()
        self._snap_cache: Optional[Tuple[float, bool, Dict[str, Any]]] = None
        self.importer = importer
        self._pull_tasks: set = set()
        self.pipeline_rev: Callable[[], Dict[str, int]] = lambda: {}
        self.member_labels: Callable[[], List[Dict[str, str]]] = lambda: []
        self.credential_offers: Callable[[], List[Dict[str, str]]] = lambda: []
        self.offers_changed: Callable[[], None] = lambda: None
        self.skills_block: Callable[[], Optional[Dict[str, Any]]] = lambda: None
        self.skills_seen: Callable[[str, Dict[str, Any]], Any] = lambda install_id, snapshot: None
        self.skills_settings_changed: Callable[[str, str], None] = lambda source, from_install_id: None
        self._offer_signatures: Dict[str, Any] = {}


    def settings(self) -> settings_doc.PackSettings:
        return self.custody.settings()

    def own_snapshot(self) -> Dict[str, Any]:
        with self._snap_lock:
            wants = self.wants_agents()
            cached = self._snap_cache
            if cached is None or cached[1] != wants or self._clock() - cached[0] >= SNAPSHOT_TTL_SECONDS:
                cached = (self._clock(), wants, self._build_snapshot(wants))
                self._snap_cache = cached
            return copy.deepcopy(cached[2])

    def _invalidate_snapshot(self) -> None:
        with self._snap_lock:
            self._snap_cache = None

    def _build_snapshot(self, wants_agents: bool) -> Dict[str, Any]:
        _, restrictions, reserve_cfg, _tracks = self.state.read_all()
        hid = self.collector.hid_idle_seconds(reserve_cfg.keyboard_rule.enabled)
        active = reserve_model.active(reserve_cfg, self._local_now(), hid)
        snap = self.collector.collect(
            install_id=self.install_id, label=self.label, app_version=self.app_version,
            reserve={**active, "config": reserve_cfg.model_dump()}, restrictions=restrictions.model_dump(),
            capabilities=caps_mod.names(), hid_idle=hid)
        snap["members"] = self.member_labels()
        snap["credential_offers"] = self.credential_offers()
        snap["relay_accept"] = consent_mod.published(self.state.relay_consent())
        skills = self.skills_block()
        if skills:
            snap["skills"] = skills
        revisions = self.pipeline_rev()
        if revisions:
            snap["pipeline_rev"] = revisions
        if self._agents is not None and wants_agents:
            snap["agents"] = self._agents()
        return snap


    def _announce(self, install_id: str, snapshot: Dict[str, Any], state_word: str) -> None:
        load = snapshot.get("load") or {}
        reserve = snapshot.get("reserve") or {}
        battery = snapshot.get("battery") or {}
        agents = snapshot.get("agents") or {}
        key = (signature(load), reserve.get("level"), battery.get("on_battery"), state_word,
               repr(snapshot.get("restrictions")), repr(reserve.get("config")), agents_signature(agents),
               repr(snapshot.get("relay_accept")), repr(snapshot.get("credential_offers")), repr(snapshot.get("skills")))
        if self._signatures.get(install_id) != key:
            self._signatures[install_id] = key
            self._notify(TOPIC, install_id, NOTIFY_EVERY_SECONDS)

    def _arm_stale_notice(self, install_id: str) -> None:
        old = self._stale_timers.pop(install_id, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(roster_mod.STALE_SECONDS + 1.0, self._notify, (TOPIC, install_id, NOTIFY_EVERY_SECONDS))
        timer.daemon = True
        self._stale_timers[install_id] = timer
        timer.start()

    def _merge_remote(self, raw: Any, from_install_id: str = "", raw_sig: Any = None) -> bool:
        if direction.contained(from_install_id):
            return False
        if not self.custody.merge(raw, raw_sig, from_install_id):
            return False
        self._notify(TOPIC, "settings", NOTIFY_EVERY_SECONDS)
        self.skills_settings_changed("remote_merge", from_install_id)
        return True

    def _record(self, install_id: str, label: str, snapshot: Dict[str, Any], remote_settings: Any) -> None:
        held = settings_doc.from_dict(remote_settings)
        entry = self.roster.record(install_id, label=label, snapshot=snapshot,
                                   holds_master=held.master_install_id if held else None)
        self._announce(install_id, snapshot, roster_mod.STATE_CONNECTED)
        self._arm_stale_notice(install_id)
        self.skills_seen(install_id, snapshot)
        offered = offers_mod.signature(self.roster.entries, install_id)
        if self._offer_signatures.get(install_id, ()) != offered:
            self._offer_signatures[install_id] = offered
            self.offers_changed()
        if self._store is not None and (entry.persisted_at == 0.0 or self.roster.due_for_store(entry)):
            try:
                self._store(entry)
            except Exception as exc:  # noqa: BLE001
                logger.info("pack_machines_store_failed", error=type(exc).__name__)

    def _schedule_pull(self, peer_id: str, snapshot: Dict[str, Any]) -> None:
        if self.importer is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(self.importer.maybe_pull(peer_id, snapshot), name="pack-rollup-pull")
        except RuntimeError:
            return
        self._pull_tasks.add(task)
        task.add_done_callback(self._pull_tasks.discard)

    async def serve_exchange(self, caller_id: str, caller_label: str, body: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = body.get("snapshot")
        if not roster_mod.snapshot_ok(snapshot, caller_id):
            raise ValueError("snapshot_identity")
        self._record(caller_id, caller_label, snapshot, body.get("settings"))
        self._schedule_pull(caller_id, snapshot)
        if body.get("want_agents"):
            self._peer_want_until = self._clock() + self.LEASE_SECONDS
        if await asyncio.to_thread(self._merge_remote, body.get("settings"), caller_id, body.get("settings_sig")):
            self.kick()
        mine, (doc, sig) = await asyncio.to_thread(lambda: (self.own_snapshot(), self.custody.outgoing()))
        self._announce(self.install_id, mine, roster_mod.STATE_SELF)
        return {"snapshot": mine, "settings": doc, "settings_sig": sig, "want_agents": self.viewer_live()}

    async def beat(self, peer_id: str, post: PostFn, peer_capabilities: List[str]) -> bool:
        if not caps_mod.has(peer_capabilities, caps_mod.CAP_MACHINE):
            return False
        try:
            mine, (doc, sig) = await asyncio.to_thread(lambda: (self.own_snapshot(), self.custody.outgoing()))
            self._announce(self.install_id, mine, roster_mod.STATE_SELF)
            body = {"snapshot": mine, "settings": doc, "want_agents": self.viewer_live()}
            if caps_mod.has(peer_capabilities, caps_mod.CAP_SETTINGS_SIGNED):
                body["settings_sig"] = sig
            status, data = await post("POST", EXCHANGE_PATH, body)
            if status != 200 or not isinstance(data, dict) or not roster_mod.snapshot_ok(data.get("snapshot"), peer_id):
                logger.info("pack_exchange_refused", peer=peer_id[:8], status=status)
                return False
            label = str(data["snapshot"].get("label") or "")
            if data.get("want_agents") is True:
                self._peer_want_until = self._clock() + self.LEASE_SECONDS
            self._record(peer_id, label, data["snapshot"], data.get("settings"))
            self._schedule_pull(peer_id, data["snapshot"])
            if await asyncio.to_thread(self._merge_remote, data.get("settings"), peer_id, data.get("settings_sig")):
                self.kick()
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("pack_exchange_failed", peer=peer_id[:8], error=type(exc).__name__)
            return False

    async def beat_all(self) -> None:
        for peer_id, post, caps in self._connected():
            await self.beat(peer_id, post, caps)

    def kick(self) -> None:
        if self._kick_task is not None and not self._kick_task.done():
            return
        try:
            self._kick_task = asyncio.get_running_loop().create_task(self._kick_run())
        except RuntimeError:
            self._kick_task = None

    async def _kick_run(self) -> None:
        await asyncio.sleep(KICK_DELAY_SECONDS)
        await self.beat_all()

    LEASE_SECONDS = 120.0
    TICK_SECONDS = 30.0
    KEEPALIVE_SECONDS = 60.0

    def touch(self) -> None:
        self._lease_until = self._clock() + self.LEASE_SECONDS

    def viewer_live(self) -> bool:
        return self._clock() < self._lease_until

    def wants_agents(self) -> bool:
        return self.viewer_live() or self._clock() < self._peer_want_until

    async def run_tick(self) -> None:
        last_keepalive = self._clock()
        while True:
            await asyncio.sleep(self.TICK_SECONDS)
            if self._clock() < self._lease_until:
                try:
                    self._announce(self.install_id, await asyncio.to_thread(self.own_snapshot), roster_mod.STATE_SELF)
                    if self._clock() - last_keepalive >= self.KEEPALIVE_SECONDS:
                        last_keepalive = self._clock()
                        self._notify(TOPIC, self.install_id, NOTIFY_EVERY_SECONDS)
                except Exception as exc:  # noqa: BLE001
                    logger.info("pack_tick_failed", error=type(exc).__name__)


    def resolve(self, machine: str, peers: List[PeerInfo]) -> Optional[str]:
        if machine in ("self", "local", "this"):
            return self.install_id
        ids = {self.install_id: self.label, **{p.install_id: p.label for p in peers}}
        for entry in self.roster.entries.values():
            for member in entry.members:
                ids.setdefault(member["install_id"], member["label"])
        if machine in ids:
            return machine
        wanted = [i for i, label in ids.items() if label and label.lower() == machine.lower()]
        return wanted[0] if len(wanted) == 1 else None

    def edit_settings(self, changes: Dict[str, Any]) -> settings_doc.PackSettings:
        doc = self.custody.mint(changes, strict=True)
        self._notify(TOPIC, "settings", NOTIFY_EVERY_SECONDS)
        self.skills_settings_changed("local_edit", "")
        return doc

    def set_reserve(self, patch: Dict[str, Any]) -> reserve_model.ReserveConfig:
        cfg = reserve_model.merged(self.state.reserve(), patch)
        if self.state.save_reserve(cfg):
            self._invalidate_snapshot()
            self._notify(TOPIC, self.install_id, NOTIFY_EVERY_SECONDS)
        return cfg

    def set_restrictions(self, patch: Dict[str, Any], *, from_peer: bool,
                         sync_consent: bool = True) -> restrictions_mod.Restrictions:
        current = self.state.restrictions()
        new = restrictions_mod.merged(current, patch)
        if from_peer:
            loosened = restrictions_mod.loosened_rules(current, new)
            if loosened:
                raise PermissionError(",".join(loosened))
        if self.state.save_restrictions(new):
            self._invalidate_snapshot()
            self._notify(TOPIC, self.install_id, NOTIFY_EVERY_SECONDS)
            if new.may_receive_credentials != current.may_receive_credentials:
                if sync_consent:
                    self._sync_receive_switch(new.may_receive_credentials)
                self.offers_changed()
        return new

    def _sync_receive_switch(self, on: bool) -> None:
        before = self.state.relay_consent()
        offered = [o["key"] for o in offers_mod.peer_offers(self.roster.entries)]
        after = consent_mod.Consent(consent_mod.MODE_ALL if on else consent_mod.MODE_NONE, (), tuple(offered))
        with consent_mod.WRITE_LOCK:
            self.state.save_relay_consent(after)
        offers_mod.revoke_keys(consent_mod.revoked(before, after, offered))

    def view(self, peers: List[PeerInfo]) -> Dict[str, Any]:
        return self.roster.view(self_snapshot=self.own_snapshot(), self_id=self.install_id, self_label=self.label,
                                peers=peers, settings=self.settings())


RUNTIME: Optional[PackMachines] = None
