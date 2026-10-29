
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
from src.core.computers import commit, forget, join_job, link_rotate, membership, store
from src.core.computers.door import Door
from src.core.computers.invites import Invites
from src.core.computers.join_server import JoinServer
from src.core.computers.link_addresses import learned_listen, local_addresses
from src.core.computers.link_dialer import LinkDialer
from src.core.computers.link_listener import DEFAULT_LINK_PORT, LinkListener, Member
from src.core.computers.link_transport import tls_transport_factory
from src.core.computers.member_listener import LISTENING, MemberListener, Rendezvous
from src.core.computers.tls_identity import LinkIdentity, ensure_link_identity, link_stem, pinned_certs
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.federation import fed_key, peer_hosts
from src.core.federation.peer_links import PeerLinks
from src.core.notifications.sources import computers as owner_notices
from src.core.pack.machines import settings_doc
from src.core.relay_identity.device_key import DeviceKey, DeviceKeyUnavailable

log = structlog.get_logger(__name__)

INVITE_TICK_SECONDS = 15.0
LOOPBACK_BIND = "127.0.0.1"
ALL_BIND = "0.0.0.0"
OFF_LOOPBACK = "off_loopback"
_WILDCARD_HOSTS = ("0.0.0.0", "::", "*")

_ACTIVE: Optional["ComputersRuntime"] = None


def active() -> Optional["ComputersRuntime"]:
    return _ACTIVE


def advertised_link_port() -> Optional[int]:
    rt = _ACTIVE
    return rt.advertised_port() if rt is not None else None


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
        return self._wired().runtime.custody.adopt(doc, signature)


class _GatedListener:

    def __init__(self, rt: "ComputersRuntime") -> None:
        self._rt = rt

    async def set_members(self, members: Sequence[Member]) -> str:
        rt = self._rt
        await asyncio.to_thread(rt.refresh_flags)
        allowed = rt.complete and not rt.joined
        state = await rt.listener.set_members(list(members) if allowed else [])
        rt.last_pins = tuple(sorted(m.peer_install_id + m.cert.cert_sha256 for m in members)) if allowed else ()
        return state


class ComputersRuntime:

    def __init__(self, *, open_db: commit.OpenDb, pack: commit.PackSettingsPort, fed_dir: Path, listener_path: str, config_path: Path,
                 host: str, label: str, app_version: str, door_path: str,
                 door_totp_ok: Callable[[str], Awaitable[bool]], door_login: Callable[[Any], Awaitable[Dict[str, Any]]],
                 refresh_store: Callable[[], Any] = lambda: None, discovery: Callable[[], Any] = lambda: None,
                 notify: Optional[commit.Notify] = None,
                 setup_state_fn: Callable[[], setup_state.SetupState] = setup_state.current_setup_state,
                 setup_status: Callable[[], str] = lambda: "unknown", control_dir: Optional[Path] = None) -> None:
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
        self._member_pins: Tuple[str, ...] = ()
        self._reserved = False
        self._discovery_on = False
        self.pins = _GatedListener(self)
        self.invites: Optional[Invites] = None
        self.join_server: Optional[JoinServer] = None
        self.door: Optional[Door] = None
        self._task: Optional["asyncio.Task[None]"] = None
        self._kick = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._advertised: Optional[int] = None
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
            on_rotated=self._on_rotated, control_dir=self._control_dir)

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
                                     on_member_hello=self._on_member_hello,
                                     on_members=lambda members: self.dialer.set_members(members) if self.dialer is not None else None)
        self.dialer = LinkDialer(identity=self.identity, hub=self.listener, rows=store.CACHE.get,
                                 on_change=lambda _iid: self.notify("computers"))
        self.member_listener = MemberListener(identity=self.identity, rendezvous=self.rendezvous,
                                              host=ALL_BIND if bind == LOOPBACK_BIND else bind,
                                              on_state=lambda _state: self.notify("computers"))
        self.invites = Invites(on_change=self._invites_changed, on_notice=self._on_notice, is_member=self.is_joiner)
        self.join_server = JoinServer(invites=self.invites, identity=self.identity, fed_key=self.fed_key, public_key=self.public_key,
                                      own_iid=self.iid, own_label=self._label, open_db=self._open_db, listener=self.pins, pack=self.pack,
                                      host=bind, port=self.link_port + 1, addresses=lambda: list(self.addresses),
                                      link_port=self.link_port, app_version=self._version, is_member=self.is_joiner,
                                      notify=self._notify_fn, on_member=lambda iid: self.dialer.kick(iid))
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
        for part in (self.door, self.join_server, self.dialer, self.listener, self.member_listener):
            if part is not None:
                try:
                    await part.stop()
                except OSError as exc:
                    log.warning("computers_runtime_stop_failed", error_type=type(exc).__name__)

    async def forget(self, iid: str, *, notify_peer: bool) -> bool:
        if self.links is None or self.iid is None:
            raise RuntimeError("the computers runtime is not prepared")
        return await forget.forget_computer(
            iid, notify_peer=notify_peer, open_db=self._open_db, links=self.links, pack=self.pack, own_iid=self.iid,
            config_path=self._config_path, fed_dir=self._fed_dir, repin=self.repin, notify=self._notify_fn)

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
        self.notify("computers")

    async def link_rotation_step(self) -> str:
        if self.links is None or self.iid is None or self.identity is None or self.fed_key is None:
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
        """The link identity changed: rebuild the listener context, close the join port (it reopens with the new cert), and make
        every link redial so the other side sees the new cert (an old pin is dropped by the first handshake that presents it)."""
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
        self.notify("computers")

    async def _on_rotated(self, iid: str, sha: str) -> None:
        if await asyncio.to_thread(link_rotate.promote, self._open_db, iid, sha):
            if self.listener is not None:
                await self.repin(force=True)
            self.notify("computers")

    def refresh_flags(self) -> None:
        state = self._setup_state()
        self.complete, self.joined = state.is_complete, state.joined is True

    def advertised_port(self) -> Optional[int]:
        return self.link_port if self.complete and not self.joined and not self.loopback_bind else None

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
        wanted = tuple(sorted(m.peer_install_id + m.cert.cert_sha256 for m in members)) if self.complete and not self.joined else ()
        if force or wanted != self.last_pins:
            await self.pins.set_members(members)
        await self._sync_member_listener(force)
        self._sync_discovery()
        return self.link_state

    def _main_row(self) -> Optional[store.LinkRow]:
        return next((r for r in store.CACHE.rows() if r.role == "main" and r.transport == "tls"), None)

    async def _sync_member_listener(self, force: bool) -> None:
        """Run the member listener while a tls main row exists (pinned to main's cert and its next one), stop it when none does.

        The stored port is bound as is, and a busy one is the state ``port_busy``, retried on every tick, never moved (main could not learn a
        new one). A reservation held for a join in flight (:meth:`reserve_listen_port`) is kept while no main row exists yet.
        """
        ml, main = self.member_listener, self._main_row()
        if ml is None or self.identity is None:
            return
        if main is None or main.cert_der is None:
            if not self._reserved:
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
        key = tuple(sorted(c.cert_sha256 for c in pins))
        if force or key != self._member_pins:
            await ml.set_pins(pins)
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
            self._advertised = self.advertised_port()
            if want:
                discovery.start(self._loop)
            else:
                discovery.stop()
            return
        port = self.advertised_port()
        if want and port != self._advertised:
            self._advertised = port
            discovery.refresh_link_port()

    def notify(self, topic: str) -> None:
        if self._notify_fn is not None:
            self._notify_fn(topic)

    async def _on_link(self, iid: str) -> None:
        assert self.links is not None
        await commit.main_final(self._open_db, self.links, iid, notify=self._notify_fn)
        self.notify("computers")

    async def _on_unlink(self, iid: str) -> None:
        self.notify("computers")

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
        self.notify("computers")

    def _invites_changed(self) -> None:
        self.notify("computers")
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._kick.set)

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
