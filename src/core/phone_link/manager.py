
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog
from cryptography.hazmat.primitives.asymmetric import ec

from src.core import resource_push, setup_state
from src.core.phone_link import acme, certs, dns01, link_status
from src.core.phone_link.custom_domain.repair import RepairGate
from src.core.phone_link.custom_domain.service import CustomDomainService
from src.core.phone_link.gate import LinkGate, StreamTable
from src.core.phone_link.listener import LoopbackListener
from src.core.phone_link.pack_relay import PackRelay
from src.core.phone_link.pairing import PENDING_SECONDS, WINDOW_SECONDS, PairingStore, Window
from src.core.phone_link.tunnel_client import TunnelClient
from src.core.catalog import catalog_auth
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.account import RelayAccount
from src.core.relay_identity.session import SIGNIN_REQUIRED, DeviceSession, RelayAuthError
from src.core.resource_push import topics

logger = structlog.get_logger()

RETRY_SECONDS = 300.0
HEARTBEAT_SECONDS = 300.0
NONE, PACK, PHONE = "none", "pack", "phone"


class PhoneLinkManager:

    def __init__(self, *, app: Any, config: Any, state_dir: Path, db_path: Path, version: str,
                 pairing: Optional[PairingStore] = None,
                 account: Optional[RelayAccount] = None) -> None:
        self._account = account
        self._account_task: Optional["asyncio.Task[None]"] = None
        self._beat_task: Optional["asyncio.Task[None]"] = None
        self._app, self._config, self._version = app, config, version
        self._state_dir, self._db_path = Path(state_dir), Path(db_path)
        self.pairing = pairing or PairingStore(path=self._state_dir / "phone_link.db")
        self._lock = asyncio.Lock()
        self._retry_timer: Optional["asyncio.TimerHandle"] = None
        self._expiry_timer: Optional["asyncio.TimerHandle"] = None
        self._boot_task: Optional["asyncio.Task[None]"] = None
        self._reconcile_task: Optional["asyncio.Task[None]"] = None
        self._session: Optional[DeviceSession] = None
        self._certs: Optional[certs.CertManager] = None
        self._listener: Optional[LoopbackListener] = None
        self._tunnel: Optional[TunnelClient] = None
        self.stream_table = StreamTable()
        self._pack: Optional[PackRelay] = None
        self._pack_up = False
        self._running: Optional[str] = None
        self._hostname = ""
        self._error = ""
        self.pairing.on_revoke.append(self._close_device_streams)
        self.pairing.on_change.append(self.announce)
        self._repair = RepairGate(pairing=self.pairing, revoke_device=self._revoke_everywhere,
                                  link_host=lambda: self.hostname,
                                  on_done=lambda: self._reconcile_later(0.0))
        self.custom = CustomDomainService(
            pairing=self.pairing, state_dir=self._state_dir, directory_url=config.link_acme_directory,
            control_url=config.control_url, get_session=self._session_for, reconcile=self.reconcile,
            repair=self._repair, sync_on=lambda: self.pairing.enabled)

    async def _session_for(self) -> DeviceSession:
        if self._session is None:
            self._session = DeviceSession(
                db_path=self._db_path, control_url=self._config.control_url, version=self._version,
                key_loader=dk.key_loader_for(self._config.device_key_file),
                account=self._account, on_repair=self._repair.enforce,
                on_token=self.custom.refresh_soon)
        return self._session

    async def device_session(self) -> DeviceSession:
        return await self._session_for()

    @property
    def control_url(self) -> str:
        return self._config.control_url

    async def _revoke_everywhere(self, device_id: str) -> None:
        from src.core.native_push import wiring as native_wiring  # noqa: PLC0415
        from src.core.web_push.wiring import sender_for  # noqa: PLC0415

        self.pairing.revoke(device_id)
        await asyncio.to_thread(sender_for(self._app.state).store.remove_for_device, device_id)
        await native_wiring.remove_for_device(self._app.state, device_id)

    def _close_device_streams(self, device_id: str) -> None:
        if self._tunnel is not None:
            self._tunnel.close_device(device_id)

    def announce(self) -> None:
        resource_push.notify(topics.PHONE_LINK)

    @property
    def hostname(self) -> str:
        return self._hostname

    @hostname.setter
    def hostname(self, value: str) -> None:
        changed = value != self._hostname
        self._hostname = value
        if changed:
            self.announce()

    @property
    def error(self) -> str:
        return self._error

    @error.setter
    def error(self, value: str) -> None:
        changed = value != self._error
        self._error = value
        if changed:
            self.announce()

    @property
    def available(self) -> bool:
        return bool(self._config.enabled)

    def public_host(self) -> str:
        return self.custom.live_host() or self.hostname

    def mode(self) -> str:
        if not self.available:
            return NONE
        if self.pairing.enabled and (self.pairing.device_count() > 0 or self.pairing.window_open() or self.pairing.pending_open()
                                     or self.custom.needs_tunnel()):
            return PHONE
        return PACK if self._pack is not None and self._pack.wanted() else NONE

    def wanted(self) -> bool:
        return self.mode() != NONE

    def set_pack(self, pack: Optional[PackRelay]) -> None:
        self._pack = pack
        if pack is not None:
            pack.use_table(self.stream_table)

    def device_id(self) -> Optional[str]:
        return self._session.device_id if self._session is not None else None

    def is_pack_member(self) -> bool:
        try:
            return (self._state_dir / setup_state.JOINED_MARKER_NAME).exists()
        except OSError:
            return False

    def status(self) -> Dict[str, Any]:
        return {"available": self.available, "enabled": self.pairing.enabled,
                "pack_member": self.is_pack_member(),
                "running": self._tunnel is not None,
                "tunnel": self._tunnel.status if self._tunnel is not None else "stopped",
                "hostname": self.hostname, "devices": self.pairing.device_count(),
                "window_open": self.pairing.window_open(), "pairing": self.pairing.pairing_view(),
                "error": self.error}

    def cert_info(self) -> Optional[Dict[str, str]]:
        return certs.describe_cert(self._state_dir / "phone_link")

    async def reconcile(self) -> None:
        async with self._lock:
            mode = self.mode()
            if mode != NONE and self._tunnel is None:
                await self._start()
            elif mode == NONE and (self._tunnel is not None or self._listener is not None):
                await self._stop()
            elif self._tunnel is not None and self._running is not None and self._running != mode:
                await self._switch(mode)
            await self._sync_pack()

    def _reconcile_later(self, delay: float, *, expiry: bool = False) -> None:
        attr = "_expiry_timer" if expiry else "_retry_timer"
        previous = getattr(self, attr)
        if previous is not None:
            previous.cancel()
        loop = asyncio.get_running_loop()

        def fire() -> None:
            self._reconcile_task = loop.create_task(self.reconcile(), name="phone-link-reconcile")

        setattr(self, attr, loop.call_later(delay, fire))

    def start_in_background(self) -> None:
        if self._account is not None:
            catalog_auth.subscribe(self.on_account_event)
        self._boot_task = asyncio.create_task(self._boot(), name="phone-link-boot")
        self.custom.start()

    def on_account_event(self, event: Dict[str, Any]) -> None:
        try:
            self._account_task = asyncio.get_running_loop().create_task(
                self._account_changed(bool(event.get("signed_in"))), name="phone-link-account")
        except RuntimeError:
            logger.warning("phone_link_account_event_without_loop")

    async def _account_changed(self, signed_in: bool) -> None:
        if self._session is not None:
            await self.report_link_status("up" if signed_in else "signed_out")
            if not signed_in:
                self._session.drop_token()
                return
            if self._tunnel is not None and self._tunnel.status == SIGNIN_REQUIRED:
                self._tunnel.start()
        if signed_in:
            if self._retry_timer is not None:
                self._retry_timer.cancel()
            await self.reconcile()

    async def report_link_status(self, status: Optional[str] = None) -> None:
        if self._session is None:
            return
        word = status or ("up" if catalog_auth.device_session(self._state_dir) is not None else "signed_out")
        try:
            await link_status.report(self._session, word)
        except (RelayAuthError, ValueError) as exc:
            logger.info("link_status_report_failed", error_type=type(exc).__name__)

    async def _heartbeat(self) -> None:
        while True:
            try:
                await self.report_link_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("link_status_heartbeat_failed", error_type=type(exc).__name__)
            await asyncio.sleep(HEARTBEAT_SECONDS)

    async def issue_status_key(self) -> str:
        return await link_status.issue_key(await self._session_for())

    async def _boot(self) -> None:
        try:
            await self.reconcile()
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}"[:200]
            logger.warning("phone_link_boot_failed", error_type=type(exc).__name__)

    async def _obtain(self, hostname: str, cert_key: ec.EllipticCurvePrivateKey) -> str:
        assert self._session is not None and self._certs is not None
        account = await asyncio.to_thread(self._certs.load_or_create_key, self._certs.account_key_path)
        client = acme.AcmeClient(
            directory_url=self._config.link_acme_directory, account_key=account,
            dns=dns01.AcmeTxtClient(session=self._session, control_url=self._config.control_url))
        try:
            return await client.obtain(hostname, cert_key)
        finally:
            await client.aclose()

    async def _start(self) -> None:
        try:
            mode = self.mode()
            self._session = await self._session_for()
            device_id = await self._session.ensure_registered()
            self.hostname = certs.link_hostname(device_id, self._config.link_domain)
            tunnel = TunnelClient(url=self._config.link_tunnel_url, session=self._session,
                                  local_port=lambda: self._listener.port if self._listener is not None else None,
                                  streams=self.stream_table, custom=self.custom, on_status=self.announce)
            self._tunnel = tunnel
            self.announce()
            if mode == PHONE:
                await self._attach_phone(tunnel)
            tunnel.start()
            self._running = mode
            if self._beat_task is None:
                self._beat_task = asyncio.get_running_loop().create_task(self._heartbeat(), name="phone-link-heartbeat")
            self.error = ""
            logger.info("phone_link_started", mode=mode)
        except (RelayAuthError, acme.AcmeError, dns01.Dns01Error, RuntimeError, OSError, ValueError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("phone_link_start_failed", error=self.error)
            await self._stop()
            self._reconcile_later(RETRY_SECONDS)

    async def _attach_phone(self, tunnel: TunnelClient) -> None:
        self._certs = certs.CertManager(
            directory=self._state_dir / "phone_link",
            directory_url=self._config.link_acme_directory, obtain=self._obtain)
        context = await self._certs.ensure(self.hostname)
        self._certs.start_renewals()
        gate = LinkGate(self._app, hostname=self.hostname, streams=self.stream_table, pairing=self.pairing,
                        send_trust=lambda sid: tunnel.trust(sid), custom_host=self.custom.live_host)
        listener = LoopbackListener(gate, context)
        await listener.start()
        self._listener = listener
        await self.custom.attach(context, tunnel)

    async def _drop_phone(self) -> None:
        await self.custom.detach()
        if self._listener is not None:
            await self._listener.stop()
            self._listener = None
        if self._certs is not None:
            await self._certs.stop()
            self._certs = None

    async def _switch(self, mode: str) -> None:
        assert self._tunnel is not None
        try:
            if mode == PHONE:
                await self._attach_phone(self._tunnel)
            else:
                await self._drop_phone()
            self._running = mode
            self.error = ""
        except (RelayAuthError, acme.AcmeError, dns01.Dns01Error, RuntimeError, OSError, ValueError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("phone_link_switch_failed", error=self.error)
            await self._drop_phone()
            self._running = PACK if self._pack_up else None
            self._reconcile_later(RETRY_SECONDS)

    async def _sync_pack(self) -> None:
        pack, tunnel = self._pack, self._tunnel
        want = pack is not None and tunnel is not None and pack.wanted()
        if want and not self._pack_up:
            try:
                await pack.acceptor.start()
            except OSError as exc:
                logger.warning("pack_relay_acceptor_failed", error_type=type(exc).__name__)
                self._reconcile_later(RETRY_SECONDS)
                return
            tunnel.attach_pack(pack)
            self._pack_up = True
        elif not want and self._pack_up:
            await self._detach_pack()

    async def _detach_pack(self) -> None:
        self._pack_up = False
        if self._tunnel is not None:
            self._tunnel.detach_pack()
        if self._pack is not None:
            await self._pack.stop()

    async def _stop(self) -> None:
        await self._detach_pack()
        await self.custom.detach()
        if self._tunnel is not None:
            await self._tunnel.stop()
            self._tunnel = None
            self.announce()
        await self._drop_phone()
        if self._beat_task is not None:
            self._beat_task.cancel()
            self._beat_task = None
        self._running = None
        logger.info("phone_link_stopped")

    async def set_enabled(self, value: bool) -> None:
        self.pairing.set_enabled(value)
        self.custom.set_sync(value)
        await self.reconcile()

    async def open_window(self) -> Window:
        window = self.pairing.open_window()
        self._reconcile_later(WINDOW_SECONDS + 1, expiry=True)
        await self.reconcile()
        return window

    async def pending_started(self) -> None:
        self._reconcile_later(PENDING_SECONDS + 1, expiry=True)
        await self.reconcile()

    async def close_window(self) -> None:
        self.pairing.close_window()
        await self.reconcile()

    def rotate_qr(self) -> Optional[Tuple[str, float]]:
        return self.pairing.rotate_secret()

    async def revoke(self, device_id: str) -> bool:
        removed = self.pairing.revoke(device_id)
        await self.reconcile()
        return removed

    async def aclose(self) -> None:
        catalog_auth.unsubscribe(self.on_account_event)
        if self._account_task is not None:
            self._account_task.cancel()
        for timer in (self._retry_timer, self._expiry_timer):
            if timer is not None:
                timer.cancel()
        if self._boot_task is not None:
            self._boot_task.cancel()
            await asyncio.gather(self._boot_task, return_exceptions=True)
        await self.custom.aclose()
        async with self._lock:
            with contextlib.suppress(OSError):
                await self._stop()
        self.pairing.close()
