
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import ipaddress
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from src.core import config_writer, setup_state
from src.core.computers import commit, forget, join_job, link_rotate, membership, mesh, roster_source, store
from src.core.computers.door import Door
from src.core.computers.invites import Invites
from src.core.computers.join_server import JoinServer
from src.core.computers.knock import KnockDesk
from src.core.computers.link_addresses import learned_listen, local_addresses
from src.core.computers.beacon import BeaconListener, BeaconSender, subnet_of
from src.core.computers.link_dialer import LinkDialer
from src.core.computers.link_listener import DEFAULT_LINK_PORT, LinkListener, Member
from src.core.computers.link_transport import TlsInitiatorTransport, tls_transport_factory
from src.core.computers.member_listener import LISTENING, MemberListener, Rendezvous
from src.core.computers.member_relay_dial import MemberRelayDialer
from src.core.computers.takeover_driver import TakeoverDriver
from src.core.computers.tls_identity import LinkIdentity, ensure_link_identity, link_stem, pinned_certs
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.federation import fed_key, peer_hosts, peer_listing
from src.core.federation.peer_links import PeerLinks
from src.core.notifications.sources import computers as owner_notices
from src.config.relay import DEFAULT_LINK_DOMAIN
from src.core.pack.machines import capabilities as pack_caps, roster_doc, settings_doc
from src.core.pack.reconnect import config as reconnect_config
from src.core.phone_link.pack_relay import PackRelay
from src.core.relay_identity.device_key import DeviceKey, DeviceKeyUnavailable
from src.core.resource_push import topics

log = structlog.get_logger(__name__)

INVITE_TICK_SECONDS = 15.0
LOOPBACK_BIND = "127.0.0.1"
ALL_BIND = "0.0.0.0"
OFF_LOOPBACK = "off_loopback"
_WILDCARD_HOSTS = ("0.0.0.0", "::", "*")

_ACTIVE: Optional["ComputersRuntime"] = None

CAP_RELAY_V1 = "pack.relay_v1"
pack_caps.register(CAP_RELAY_V1)


def active() -> Optional["ComputersRuntime"]:
    return _ACTIVE


def advertised_link_port() -> Optional[int]:
    rt = _ACTIVE
    return rt.advertised_port() if rt is not None else None


def advertised_members() -> Tuple[Tuple[str, str], ...]:
    rt = _ACTIVE
    return rt.pack_members if rt is not None else ()


def advertised_fid() -> Optional[str]:
    rt = _ACTIVE
    key = rt.fed_key if rt is not None else None
    return key.device_id if key is not None else None


def read_link_port(config_path: Path) -> int:
    try:
        value = config_writer.read_config(config_path).get("computers", {}).get("link_port")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_LINK_PORT
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65534 else DEFAULT_LINK_PORT


def is_loopback_host(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def bind_host(host: str) -> str:
    if is_loopback_host(host):
        return LOOPBACK_BIND
    return ALL_BIND if host in _WILDCARD_HOSTS else host


def _stored_cert_sha(fed_dir: Path, iid: str) -> Optional[str]:
    try:
        pem = (fed_dir / (link_stem(iid) + "-cert.pem")).read_bytes()
        return hashlib.sha256(x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)).hexdigest()
    except (OSError, ValueError):
        return None


class LazyPack:

    def __init__(self, wiring: Callable[[], Any]) -> None:
        self._wiring = wiring

    def _wired(self) -> Any:
        wired = self._wiring()
        if wired is None:
            raise RuntimeError("the pack machine layer is not running")
        return wired

    def settings(self) -> settings_doc.PackSettings:
        return self._wired().runtime.settings()

    def signature(self) -> Optional[Dict[str, Any]]:
        return self._wired().runtime.custody.held_signature()

    def mint(self, changes: Dict[str, Any], base: Optional[settings_doc.PackSettings] = None) -> settings_doc.PackSettings:
        return self._wired().runtime.custody.mint(changes, base=base)

    def adopt(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, Any]] = None) -> bool:
        rt = self._wired().runtime
        changed = rt.custody.adopt_join(doc, signature)
        rt.skills_settings_changed("local_edit", "")
        return changed

    def clear_roster(self) -> bool:
        return self._wired().runtime.custody.clear_roster()

    def held_lists(self) -> Optional[Tuple[Any, Optional[Dict[str, Any]]]]:
        return self._wired().runtime.custody.held_lists()

    def roster_wire(self) -> Optional[Dict[str, Any]]:
        return self._wired().runtime.custody.roster_wire()

    def merge_roster(self, raw: Any, sender: str) -> bool:
        return self._wired().runtime.custody.merge_roster(raw, sender)

    def refresh_roster(self, inputs: List[roster_doc.RosterInput]) -> str:
        return self._wired().runtime.refresh_roster(inputs)

    def is_laptop(self, install_id: str) -> bool:
        return self._wired().runtime.is_laptop(install_id)

    def follow_hello(self) -> Optional[Dict[str, Any]]:
        rt = self._wired().runtime
        wire = rt.custody.roster_wire()
        if wire is None:
            return None
        doc, signature = rt.custody.outgoing()
        return roster_doc.fit_hello({"follows": doc["master_install_id"], "generation": doc["rev"][0], "settings": doc,
                                     "settings_sig": signature, "roster": wire, "can_claim": rt.custody.can_claim()})

    def merge_follow(self, hello: Dict[str, Any], sender: str) -> None:
        pack = self._wired().runtime
        if pack._merge_remote(hello.get("settings"), sender, hello.get("settings_sig"), hello.get("roster")):
            pack.kick()
        pack._merge_roster(hello.get("roster"), sender)

    def kick(self) -> None:
        wired = self._wiring()
        if wired is not None:
            wired.runtime.kick()


class _GatedListener:

    def __init__(self, rt: "ComputersRuntime") -> None:
        self._rt = rt

    async def set_members(self, members: Sequence[Member]) -> str:
        rt = self._rt
        await asyncio.to_thread(rt.refresh_flags)
        allowed = rt.complete and not rt.joined
        state = await rt.listener.set_members(list(members) if allowed else [])
        await rt.sync_pack_relay(list(members) if allowed else [])
        await rt.sync_beacon(allowed and bool(members))
        rt.last_pins = tuple(sorted(m.peer_install_id + m.cert.cert_sha256 for m in members)) if allowed else ()
        return state


class ComputersRuntime:

    def __init__(self, *, open_db: commit.OpenDb, pack: commit.PackSettingsPort, fed_dir: Path, listener_path: str, config_path: Path,
                 host: str, label: str, app_version: str, door_path: str,
                 door_totp_ok: Callable[[str], Awaitable[bool]], door_login: Callable[[Any], Awaitable[Dict[str, Any]]],
                 refresh_store: Callable[[], Any] = lambda: None, discovery: Callable[[], Any] = lambda: None,
                 notify: Optional[commit.Notify] = None,
                 setup_state_fn: Callable[[], setup_state.SetupState] = setup_state.current_setup_state,
                 setup_status: Callable[[], str] = lambda: "unknown", control_dir: Optional[Path] = None,
                 phone_link: Callable[[], Any] = lambda: None, link_domain: str = DEFAULT_LINK_DOMAIN) -> None:
        self._phone_link, self._link_domain = phone_link, link_domain
        self._roster: Optional[LazyPack] = pack if isinstance(pack, LazyPack) else None
        self._roster_cache: Optional[Tuple[Any, Optional[Dict[str, Any]]]] = None
        self._open_db, self.pack, self._fed_dir, self._listener_path = open_db, pack, fed_dir, listener_path
        self._config_path, self._host, self._label, self._version = config_path, host, label, app_version
        self.open_db, self.fed_dir, self.config_path, self.label = open_db, fed_dir, config_path, label
        self._door_path, self._door_totp, self._door_login = door_path, door_totp_ok, door_login
        self._refresh_store, self._discovery, self._notify_fn = refresh_store, discovery, notify
        self._setup_state, self._setup_status, self._control_dir = setup_state_fn, setup_status, control_dir
        self.link_port = read_link_port(config_path)
        self.loopback_bind = is_loopback_host(host)
        self.complete, self.joined = False, False
        self.addresses: List[str] = []
        self.last_pins: Tuple[str, ...] = ()
        self.links: Optional[PeerLinks] = None
        self.iid: Optional[str] = None
        self.identity: Optional[LinkIdentity] = None
        self.fed_key: Any = None
        self._join_deps: Optional[join_job.JoinDeps] = None
        self.public_key = ""
        self.listener: Optional[LinkListener] = None
        self.dialer: Optional[LinkDialer] = None
        self.rendezvous = Rendezvous()
        self.member_listener: Optional[MemberListener] = None
        self.pack_relay: Optional[PackRelay] = None
        self.member_relay: Optional[MemberRelayDialer] = None
        self.takeover: Optional[TakeoverDriver] = None
        self.beacon_listener: Optional[BeaconListener] = None
        self.beacon_sender: Optional[BeaconSender] = None
        self._beacon_alpha = False
        self._subnets: List[str] = []
        self._member_pins: Tuple[str, ...] = ()
        self._reserved = False
        self._discovery_on = False
        self.pins = _GatedListener(self)
        self.invites: Optional[Invites] = None
        self.join_server: Optional[JoinServer] = None
        self.knocks: Optional[KnockDesk] = None
        self.door: Optional[Door] = None
        self._task: Optional["asyncio.Task[None]"] = None
        self._kick = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reannounce_tasks: "set[asyncio.Task[None]]" = set()
        self._advertised: Optional[Tuple[Optional[int], Tuple[Tuple[str, str], ...]]] = None
        self.pack_member = False
        self.pack_members: Tuple[Tuple[str, str], ...] = ()
        self._rekeyed = False
        self._waiting_told: Optional[str] = None

    async def prepare(self, links: PeerLinks) -> None:
        self.links = links
        try:
            await asyncio.to_thread(self._load)
        except (OSError, sqlite3.Error, ValueError, DeviceKeyUnavailable) as exc:
            log.warning("computers_runtime_prepare_failed", error_type=type(exc).__name__)
            return
        assert self.identity is not None
        links.transport_factory = tls_transport_factory(
            install_id=self.iid or "", listener_path=self._listener_path, rendezvous=self.rendezvous,
            on_first_link=self._on_first_link, addresses=lambda: list(self.addresses),
            listen_port=lambda: self.member_listener.port if self.member_listener is not None else None,
            on_rotated=self._on_rotated, hello_extras=self._member_hello_extras, on_relay_id=self._on_relay_id,
            on_roster=self._on_roster, control_dir=self._control_dir)

    def _load(self) -> None:
        with closing(self._open_db()) as conn:
            self.iid = get_meta(conn, META_INSTALL_ID)
            store.refresh(conn)
        if not self.iid:
            raise ValueError("no install id")
        self.fed_key = fed_key.load_key(self.iid)
        self.public_key = fed_key.public_key_b64(self.fed_key)
        before = _stored_cert_sha(self._fed_dir, self.iid)
        self.identity = ensure_link_identity(self.fed_key, self.iid, self._fed_dir)
        self._rekeyed = bool(before and before != self.identity.cert.cert_sha256 and any(r.transport == "tls" for r in store.CACHE.rows()))
        if self._rekeyed:
            log.warning("computers_link_cert_changed_without_rotation", link_fid=self.identity.cert.link_fid)
        self.refresh_flags()

    async def start(self) -> None:
        global _ACTIVE
        if self.identity is None or self.links is None or self.iid is None:
            log.warning("computers_runtime_not_started")
            return
        self._loop = asyncio.get_running_loop()
        bind = bind_host(self._host)
        self.addresses = await asyncio.to_thread(local_addresses)
        self.listener = LinkListener(identity=self.identity, fed_dir=self._fed_dir, listener_path=self._listener_path,
                                     addresses=lambda: list(self.addresses), port=self.link_port,
                                     on_link=self._on_link, on_unlink=self._on_unlink, on_rotated=self._on_rotated,
                                     on_member_hello=self._on_member_hello, hello_extras=self._alpha_hello_extras,
                                     on_follow_reply=self._on_follow_reply, on_member_device_id=self._on_member_device_id,
                                     app_streams_ok=lambda: self.pack_relay is None or not self.pack_relay.budget.exhausted,
                                     on_members=lambda members: self.dialer.set_members(members) if self.dialer is not None else None)
        self.pack_relay = PackRelay(identity=self.identity, hub=self.listener, config_path=self._config_path,
                                    budget_path=self._fed_dir / "pack-relay-budget.json")
        self.member_relay = MemberRelayDialer(identity=self.identity, rendezvous=self.rendezvous, main=self._main_row,
                                              relay_host=self._relay_host, enabled=self.pack_relay.enabled, linked=self._main_linked,
                                              roster_shas=self._roster_shas)
        phone = self._phone_link()
        if phone is not None:
            phone.set_pack(self.pack_relay)
        self.links.add_connect_listener(self._on_peer_connected)
        self.dialer = LinkDialer(identity=self.identity, hub=self.listener, rows=store.CACHE.get,
                                 on_change=lambda _iid: self.notify(topics.COMPUTERS),
                                 on_candidate_win=lambda iid: self.beacon_listener.throttle.refund(iid) if self.beacon_listener else None)
        self.beacon_listener = BeaconListener(members=self.listener.members, connected=self.listener.connected,
                                              kick=lambda iid, source: self.dialer.kick(iid, source) if self.dialer is not None else None,
                                              host=bind)
        self._subnets = await asyncio.to_thread(reconnect_config.known_subnets, self._config_path)
        identity = self.identity
        self.beacon_sender = BeaconSender(cert_sha256=lambda: identity.cert.cert_sha256, addresses=lambda: list(self.addresses),
                                          subnets=lambda: list(self._subnets), linked=self._main_linked,
                                          enabled=lambda: self.pack_relay.enabled() and self._main_row() is not None)
        self.beacon_sender.start()
        self.member_listener = MemberListener(identity=self.identity, rendezvous=self.rendezvous,
                                              host=ALL_BIND if bind == LOOPBACK_BIND else bind,
                                              on_state=lambda _state: self.notify(topics.COMPUTERS), follow_hello=self._follow_hello)
        self.takeover = TakeoverDriver(self) if self._roster is not None else None
        mesh.attach(self)
        self.invites = Invites(on_change=self._invites_changed, on_notice=self._on_notice, is_member=self.is_joiner)
        self.knocks = KnockDesk(self.invites, self._label, notify=self.notify, emit=owner_notices.knock)
        self.join_server = JoinServer(invites=self.invites, identity=self.identity, fed_key=self.fed_key, public_key=self.public_key,
                                      own_iid=self.iid, own_label=self._label, open_db=self._open_db, listener=self.pins, pack=self.pack,
                                      host=bind, port=self.link_port + 1, addresses=lambda: list(self.addresses),
                                      link_port=self.link_port, app_version=self._version, is_member=self.is_joiner,
                                      notify=self._notify_fn, on_member=lambda iid: self.dialer.kick(iid),
                                      findable=self.findable, on_knock=self.knocks.handle)
        self._join_deps = join_job.JoinDeps(
            identity=self.identity, fed_key=self.fed_key, public_key=self.public_key, own_iid=self.iid, own_label=self._label,
            open_db=self._open_db, links=self.links, pack=self.pack, reserve_port=self.reserve_listen_port,
            release_port=self.release_listen_port, addresses=lambda: list(self.addresses), app_version=self._version,
            notify=self._notify_fn)
        join_job.configure_join(self._join_deps)
        self.door = Door(self._door_path, totp_ok=self._door_totp, login=self._door_login, setup_status=self._setup_status,
                         refresh_store=self._refresh_store)
        try:
            await self.door.start()
        except OSError as exc:
            log.warning("computers_door_start_failed", error_type=type(exc).__name__)
            self.door = None
        _ACTIVE = self
        await self.repin(force=True)
        if self._rekeyed:
            owner_notices.link_cert("rekeyed", self.identity.cert.cert_sha256)
        self._task = asyncio.create_task(self._run(), name="computers-runtime")
        log.info("computers_runtime_started", link_port=self.link_port, loopback_bind=self.loopback_bind)

    async def stop(self) -> None:
        global _ACTIVE
        _ACTIVE = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        join_job.configure_join(None)
        phone = self._phone_link()
        if phone is not None:
            phone.set_pack(None)
            try:
                await phone.reconcile()
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                log.warning("pack_relay_detach_failed", error_type=type(exc).__name__)
        await mesh.detach()
        for part in (self.door, self.join_server, self.beacon_sender, self.beacon_listener, self.dialer, self.listener, self.member_listener, self.member_relay, self.pack_relay):
            if part is not None:
                try:
                    await part.stop()
                except OSError as exc:
                    log.warning("computers_runtime_stop_failed", error_type=type(exc).__name__)

    async def forget(self, iid: str, *, notify_peer: bool) -> bool:
        if self.links is None or self.iid is None:
            raise RuntimeError("the computers runtime is not prepared")
        told = await forget.forget_computer(
            iid, notify_peer=notify_peer, open_db=self._open_db, links=self.links, pack=self.pack, own_iid=self.iid,
            config_path=self._config_path, fed_dir=self._fed_dir, repin=self.repin, notify=self._notify_fn)
        await self.after_roster_change()
        return told

    async def rotate_link(self, new_key: DeviceKey) -> None:
        if self.iid is None or self.identity is None:
            return
        self.fed_key, self.public_key = new_key, fed_key.public_key_b64(new_key)
        if self.join_server is not None:
            self.join_server.use_key(new_key, self.public_key)
        if self._join_deps is not None:
            self._join_deps = dataclasses.replace(self._join_deps, fed_key=new_key, public_key=self.public_key)
            join_job.configure_join(self._join_deps)
        discovery = self._discovery()
        if discovery is not None and self._discovery_on:
            discovery.refresh_link_port()
        await asyncio.to_thread(link_rotate.stage, new_key, self.iid, self._fed_dir)
        await self.link_rotation_step()
        self.notify(topics.COMPUTERS)

    async def link_rotation_step(self) -> str:
        if self.links is None or self.iid is None or self.identity is None or self.fed_key is None:
            return link_rotate.IDLE
        if self.takeover is not None and await self.takeover.rotation_paused():
            return link_rotate.IDLE
        result = await link_rotate.run_step(links=self.links, open_db=self._open_db, fed_dir=self._fed_dir, iid=self.iid,
                                            signer=self.fed_key, identity=self.identity)
        if result == link_rotate.SWAPPED:
            await self._after_link_swap()
        elif result == link_rotate.WAITING:
            await self._tell_rotation_waiting()
        return result

    async def _tell_rotation_waiting(self) -> None:
        staged = await asyncio.to_thread(link_rotate.read_staged, self._fed_dir, self.iid or "")
        if staged is not None and staged.sha != self._waiting_told and owner_notices.link_cert("rotation_waiting", staged.sha):
            self._waiting_told = staged.sha

    async def _after_link_swap(self) -> None:
        await self.repin(force=True)
        if self.join_server is not None:
            await self.join_server.stop()
        if self.listener is not None:
            await self.listener.drop_links()

        def main_host() -> Optional[Any]:
            with closing(self._open_db()) as conn:
                main = store.main_row(conn)
                return peer_hosts.get(conn, main.peer_install_id) if main is not None else None

        host = await asyncio.to_thread(main_host)
        if host is not None and self.links is not None:
            await self.links.start_initiator(host)
        self.notify(topics.COMPUTERS)

    async def _on_rotated(self, iid: str, sha: str) -> None:
        if await asyncio.to_thread(link_rotate.promote, self._open_db, iid, sha):
            if self.listener is not None:
                await self.repin(force=True)
            self.notify(topics.COMPUTERS)

    def refresh_flags(self) -> None:
        state = self._setup_state()
        self.complete, self.joined = state.is_complete, state.joined is True

    def advertised_port(self) -> Optional[int]:
        return self.link_port if self.complete and not self.joined and not self.pack_member and not self.loopback_bind else None

    def refresh_pack_view(self) -> None:
        peers = peer_listing.read_peers(self._open_db)
        try:
            master = self.pack.settings().master_install_id if peers else None
        except RuntimeError:
            master = None
        self.pack_member = master is not None and master != self.iid
        self.pack_members = tuple((r.peer_fid, r.label) for r in peers if r.peer_fid) if master is not None and master == self.iid else ()

    def findable(self) -> bool:
        discovery = self._discovery()
        return (self.advertised_port() is not None and discovery is not None and discovery.advertising_wanted
                and discovery.advertise_allowed)

    def kick(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._kick.set)

    @property
    def link_state(self) -> str:
        if self.listener is None:
            return "stopped"
        return OFF_LOOPBACK if self.loopback_bind else self.listener.state

    async def repin(self, *, force: bool = False) -> str:
        assert self.identity is not None and self.listener is not None
        link_fid = self.identity.cert.link_fid

        def build() -> List[Member]:
            with closing(self._open_db()) as conn:
                return commit.listener_members(conn, link_fid)

        members = await asyncio.to_thread(build)
        await asyncio.to_thread(self.refresh_flags)
        await asyncio.to_thread(self.refresh_pack_view)
        wanted = tuple(sorted(m.peer_install_id + m.cert.cert_sha256 for m in members)) if self.complete and not self.joined else ()
        if force or wanted != self.last_pins:
            await self.pins.set_members(members)
        await self._sync_member_listener(force)
        self._sync_discovery()
        return self.link_state

    def _main_row(self) -> Optional[store.LinkRow]:
        return next((r for r in store.CACHE.rows() if r.role == "main" and r.transport == "tls"), None)

    async def _sync_member_listener(self, force: bool) -> None:
        ml, main = self.member_listener, self._main_row()
        if ml is None or self.identity is None:
            return
        if main is None or main.cert_der is None:
            if not self._reserved and not (self.takeover is not None and await self.takeover.answer_walks(ml)):
                await ml.stop()
                self._member_pins = ()
            return
        pins = pinned_certs([d for d in (main.cert_der, main.next_cert_der) if d], own_link_fid=self.identity.cert.link_fid)
        if not pins:
            log.warning("computers_main_cert_not_pinned", iid=main.peer_install_id[:8])
            return
        if ml.state != LISTENING:
            self._reserved = False
            if not (await ml.bind(main.link_port) if main.link_port else await ml.reserve(self.link_port)):
                return
        follow = self._follow_pins(main.peer_install_id)
        key = tuple(sorted(c.cert_sha256 for c in pins)) + ("|",) + tuple(sorted(c.cert_sha256 for c in follow))
        if force or key != self._member_pins:
            await ml.set_pins(pins, follow)
            self._member_pins = key

    async def reserve_listen_port(self) -> Optional[int]:
        if self.member_listener is None:
            return None
        port = await self.member_listener.reserve(self.link_port)
        self._reserved = port is not None
        return port

    async def release_listen_port(self) -> None:
        self._reserved = False
        await self._sync_member_listener(False)

    def _sync_discovery(self) -> None:
        discovery = self._discovery()
        if discovery is None:
            return
        want = self.complete and not self.joined and self._main_row() is None
        if want != self._discovery_on and self._loop is not None:
            self._discovery_on = want
            self._advertised = (self.advertised_port(), self.pack_members)
            if want:
                discovery.start(self._loop)
            else:
                discovery.stop()
            return
        port = (self.advertised_port(), self.pack_members)
        if want and port != self._advertised:
            self._advertised = port
            discovery.refresh_link_port()

    async def sync_pack_relay(self, members: Sequence[Member]) -> None:
        if self.pack_relay is None:
            return
        try:
            changed = await self.pack_relay.set_members(members)
        except (ValueError, OSError) as exc:
            log.warning("pack_relay_pins_failed", error_type=type(exc).__name__)
            return
        phone = self._phone_link()
        if changed and phone is not None:
            try:
                await phone.reconcile()
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                log.warning("pack_relay_reconcile_failed", error_type=type(exc).__name__)

    async def sync_beacon(self, alpha: Optional[bool] = None) -> None:
        if alpha is not None:
            self._beacon_alpha = alpha
        listener = self.beacon_listener
        if listener is None:
            return
        if self._beacon_alpha and not self.loopback_bind and self.pack_relay is not None and self.pack_relay.enabled():
            await listener.start()
        else:
            await listener.stop()

    async def relay_switch_changed(self) -> None:
        await self.sync_beacon()
        phone = self._phone_link()
        if phone is not None:
            await phone.reconcile()
        if self.listener is not None:
            await self.listener.reannounce()
        self.notify(topics.COMPUTERS)
        self.notify(topics.PACK_MACHINES)

    def _on_peer_connected(self, iid: str) -> None:
        if self._loop is not None:
            task = self._loop.create_task(self._reannounce(iid), name="pack-relay-reannounce")
            self._reannounce_tasks.add(task)
            task.add_done_callback(self._reannounce_tasks.discard)
            main = self._main_row()
            if main is not None and main.peer_install_id == iid and not self.rendezvous.taken_via_relay:
                note = self._loop.create_task(self._remember_subnet(), name="pack-beacon-subnet")
                self._reannounce_tasks.add(note)
                note.add_done_callback(self._reannounce_tasks.discard)

    async def _remember_subnet(self) -> None:
        local = self.rendezvous.taken_local_address
        subnet = subnet_of(local) if local else None
        if subnet is None:
            return
        try:
            if await asyncio.to_thread(reconnect_config.remember_subnet, self._config_path, subnet):
                self._subnets = await asyncio.to_thread(reconnect_config.known_subnets, self._config_path)
        except (OSError, ValueError) as exc:
            log.warning("pack_beacon_subnet_not_saved", error_type=type(exc).__name__)

    async def _reannounce(self, iid: str) -> None:
        try:
            if self.listener is not None:
                await self.listener.reannounce(iid)
            transport = self.links.transport(iid) if self.links is not None else None
            if isinstance(transport, TlsInitiatorTransport):
                await transport.reannounce()
        except (OSError, RuntimeError) as exc:
            log.warning("pack_relay_reannounce_failed", error_type=type(exc).__name__)

    def _alpha_hello_extras(self, iid: str) -> Dict[str, Any]:
        phone, relay = self._phone_link(), self.pack_relay
        relay_id = phone.device_id() if phone is not None else None
        extras: Dict[str, Any] = {}
        if (relay_id and reconnect_config.valid_relay_id(relay_id) and relay is not None and relay.enabled()
                and self.links is not None and pack_caps.has(self.links.capabilities(iid), CAP_RELAY_V1)):
            extras["relay_id"] = relay_id
        if (self._roster_cache is not None and self._roster_cache[1] is not None and self.links is not None
                and pack_caps.has(self.links.capabilities(iid), pack_caps.CAP_ROSTER)):
            extras["roster"] = self._roster_cache[1]
        return roster_doc.fit_hello(extras)

    def _member_hello_extras(self, main_iid: str) -> Dict[str, Any]:
        phone = self._phone_link()
        device_id = phone.device_id() if phone is not None else None
        if device_id and self.links is not None and pack_caps.has(self.links.capabilities(main_iid), CAP_RELAY_V1):
            return {"device_id": device_id}
        return {}

    def _own_roster_input(self) -> roster_doc.RosterInput:
        assert self.identity is not None and self.iid is not None and self._roster is not None
        phone = self._phone_link()
        relay_id = phone.device_id() if phone is not None else None
        return roster_doc.RosterInput(
            install_id=self.iid, label=self._label, fed_public_key=self.public_key, cert=self.identity.cert.der,
            next_cert=link_rotate.staged_der(self._fed_dir, self.iid), addresses=tuple(self.addresses), link_port=self.link_port,
            relay_id=relay_id if relay_id and reconnect_config.valid_relay_id(relay_id) else None, laptop=self._roster.is_laptop(self.iid))

    def _roster_inputs_blocking(self) -> Optional[List[roster_doc.RosterInput]]:
        assert self.identity is not None and self._roster is not None
        return roster_source.build_inputs(
            self._open_db, own=self._own_roster_input(), own_link_fid=self.identity.cert.link_fid,
            relay_id_for=lambda iid: reconnect_config.learned_relay_id(self._config_path, iid), laptop_for=self._roster.is_laptop)

    async def roster_inputs(self) -> List[roster_doc.RosterInput]:
        if self._roster is None or self.identity is None:
            raise roster_source.RosterUnavailable("the roster is not available on this computer")
        inputs = await asyncio.to_thread(self._roster_inputs_blocking)
        if inputs is None:
            raise roster_source.RosterUnavailable("the Pack could not be read")
        return inputs

    async def after_roster_change(self) -> None:
        if self._roster is None:
            return
        try:
            self._roster_cache = await asyncio.to_thread(self._roster.held_lists)
            if self.member_listener is not None and self.identity is not None:
                await self._sync_member_listener(False)
            await mesh.list_changed()
        except (OSError, ValueError, RuntimeError) as exc:
            log.warning("pack_roster_reload_failed", error_type=type(exc).__name__)
            return
        self.notify(topics.COMPUTERS)
        self.notify(topics.PACK_MACHINES)

    async def _sync_roster(self) -> None:
        if self._roster is None or self.identity is None or self.listener is None:
            return
        try:
            if await asyncio.to_thread(self._roster.held_lists) != self._roster_cache:
                await self.after_roster_change()
            if not self.listener.members():
                return
            inputs = await asyncio.to_thread(self._roster_inputs_blocking)
            if inputs is None:
                return
            if await asyncio.to_thread(self._roster.refresh_roster, inputs):
                await self.after_roster_change()
                self._roster.kick()
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            log.warning("pack_roster_sync_failed", error_type=type(exc).__name__)

    def _follow_pins(self, main_iid: str) -> list:
        held = self._roster_cache[0] if self._roster_cache is not None else None
        if held is None or self.identity is None:
            return []
        ders = [d for entry in held.computers if entry.install_id not in (self.iid, main_iid) for d in entry.ders()]
        return pinned_certs(ders, own_link_fid=self.identity.cert.link_fid)

    def _roster_shas(self, iid: str) -> Optional[frozenset]:
        held = self._roster_cache[0] if self._roster_cache is not None else None
        entry = held.entry(iid) if held is not None else None
        return frozenset(entry.shas()) if entry is not None else None

    async def _follow_hello(self) -> Optional[Dict[str, Any]]:
        if self._roster is None:
            return None
        try:
            return await asyncio.to_thread(self._roster.follow_hello)
        except (OSError, ValueError, RuntimeError) as exc:
            log.warning("pack_follow_hello_failed", error_type=type(exc).__name__)
            return None

    async def _on_follow_reply(self, iid: str, hello: Dict[str, Any]) -> None:
        if self._roster is None:
            return
        await asyncio.to_thread(self._roster.merge_follow, hello, iid)
        await self.after_roster_change()

    async def _on_roster(self, main_iid: str, raw: Any) -> None:
        main = self._main_row()
        if self._roster is None or main is None or main.peer_install_id != main_iid:
            return
        if await asyncio.to_thread(self._roster.merge_roster, raw, main_iid):
            await self.after_roster_change()

    def _on_member_device_id(self, iid: str, device_id: str) -> None:
        try:
            reconnect_config.remember_relay_id(self._config_path, iid, device_id)
        except (OSError, ValueError) as exc:
            log.warning("pack_member_device_id_not_saved", error_type=type(exc).__name__)

    def _on_relay_id(self, main_iid: str, relay_id: str) -> None:
        try:
            reconnect_config.remember_relay_id(self._config_path, main_iid, relay_id)
        except (OSError, ValueError) as exc:
            log.warning("pack_relay_id_not_saved", error_type=type(exc).__name__)

    def _relay_host(self) -> Optional[str]:
        main = self._main_row()
        relay_id = reconnect_config.learned_relay_id(self._config_path, main.peer_install_id) if main is not None else None
        return f"{relay_id}.{self._link_domain}" if relay_id else None

    def _main_linked(self) -> bool:
        main = self._main_row()
        return main is not None and self.links is not None and self.links.state(main.peer_install_id) == "connected"

    def notify(self, topic: str) -> None:
        if self._notify_fn is not None:
            self._notify_fn(topic)

    async def _on_link(self, iid: str) -> None:
        assert self.links is not None
        await commit.main_final(self._open_db, self.links, iid, notify=self._notify_fn)
        self.notify(topics.COMPUTERS)

    async def _on_unlink(self, iid: str) -> None:
        self.notify(topics.COMPUTERS)

    async def _on_first_link(self, main_iid: str) -> None:
        async def revoke() -> None:
            tokens = self._refresh_store()
            if tokens is not None:
                await tokens.revoke_all()

        done = await commit.joiner_final(self._open_db, main_iid, config_path=self._config_path, revoke_refresh_tokens=revoke,
                                         notify=self._notify_fn)
        if done:
            await asyncio.to_thread(self.refresh_flags)
            self._sync_discovery()

    async def _on_member_hello(self, peer_iid: str, addresses: List[str], port: Optional[int]) -> None:
        learned = learned_listen(addresses, port, join_port=self.link_port + 1)
        row = store.CACHE.get(peer_iid)
        if learned is None or row is None:
            return
        found, found_port = learned[0], learned[1] or row.link_port
        if (row.addresses, row.link_port) == (tuple(found), found_port):
            return

        def write() -> None:
            with closing(self._open_db()) as conn:
                store.set_link_address(conn, peer_iid, tuple(found), found_port)

        await asyncio.to_thread(write)
        self.notify(topics.COMPUTERS)

    def _invites_changed(self) -> None:
        self.notify(topics.COMPUTERS)
        self.notify(topics.PACK_KNOCKS)
        self.kick()

    def _on_notice(self, event: str, addr: str) -> None:
        log.warning("computer_wrong_code", what=event, addr=addr)
        owner_notices.wrong_code(event, addr)

    def is_joiner(self) -> bool:
        return membership.is_member() or any(r.role == "main" and r.transport == "tls" for r in store.CACHE.rows())

    async def _run(self) -> None:
        last_slow = 0.0
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), INVITE_TICK_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._kick.clear()
            try:
                assert self.invites is not None and self.join_server is not None
                self.invites.sweep()
                await self.join_server.sync()
                if self.member_relay is not None:
                    self.member_relay.tick()
                await self._sync_roster()
                if self.takeover is not None:
                    await self.takeover.tick()
                if time.monotonic() - last_slow >= commit.SWEEP_EVERY_SECONDS:
                    last_slow = time.monotonic()
                    await self._slow_tick()
            except asyncio.CancelledError:
                raise
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
                log.warning("computers_runtime_tick_failed", error_type=type(exc).__name__)

    async def _slow_tick(self) -> None:
        assert self.identity is not None and self.iid is not None and self.links is not None
        before, self.addresses = self.addresses, await asyncio.to_thread(local_addresses)
        if self.dialer is not None and before != self.addresses:
            self.dialer.kick()
        await commit.sweep(self._open_db, identity=self.identity, own_iid=self.iid, pack=self.pack, links=self.links,
                           listener=self.pins, notify=self._notify_fn)
        await self.repin()
        await self.link_rotation_step()
