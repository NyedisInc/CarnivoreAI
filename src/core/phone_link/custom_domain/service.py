
from __future__ import annotations

import asyncio
import contextlib
import json
import ssl
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog
from cryptography.hazmat.primitives.asymmetric import ec

from src.core import resource_push
from src.core.phone_link import acme, certs
from src.core.phone_link.custom_domain import control, dns_gate, names
from src.core.phone_link.custom_domain.challenge import ChallengeResponder
from src.core.phone_link.custom_domain.repair import RepairGate
from src.core.phone_link.pairing import PairingStore
from src.core.relay_identity.session import DeviceSession, RelayAuthError
from src.core.resource_push import topics

logger = structlog.get_logger()

SETTING = "custom_domain"
SYNC_SETTING = "cd_sync_pending"
RENEW_BEFORE = timedelta(hours=72)
PENDING_POLLS = (30.0, 60.0, 120.0, 300.0)
PENDING_EVERY, SETTLED_EVERY = 600.0, 6 * 3600.0
MINT_EVERY = 24 * 3600.0
ORDER_RETRY = 3600.0
PIN_POLL, PIN_WAIT = 15.0, 300.0
YOUNG_FOR, YOUNG_RETRIES = 1800.0, (120.0, 300.0, 600.0)
SYNC_RETRY = 60.0
FAST_TICK, SLOW_TICK = 10.0, 600.0


class CustomDomainService:

    def __init__(self, *, pairing: PairingStore, state_dir: Path, directory_url: str, control_url: str,
                 get_session: Callable[[], Awaitable[DeviceSession]], reconcile: Callable[[], Awaitable[None]],
                 repair: RepairGate, sync_on: Callable[[], bool],
                 clock: Callable[[], float] = time.time, call: Any = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._sleep = sleep
        self._pairing, self._get_session, self._reconcile = pairing, get_session, reconcile
        self._repair, self._sync_on, self._clock = repair, sync_on, clock
        self._control_url, self._call = control_url, call
        self._directory_url = directory_url
        self._link_dir = Path(state_dir) / "phone_link"
        self._certs = certs.CertManager(
            directory=self._link_dir / "custom", directory_url=directory_url, obtain=self._obtain,
            renew_before=RENEW_BEFORE, meta={"profile": acme.SHORTLIVED},
            account_key_path=self._link_dir / "account.key")
        self.responder = ChallengeResponder()
        self._tunnel: Any = None
        self._link_context: Optional[ssl.SSLContext] = None
        self._view: Dict[str, Any] = {}
        self._error: Optional[str] = None
        self._updated_at = 0
        self._not_after: Optional[datetime] = None
        self._ready = False
        self._claim_sent = False
        self._order_open = False
        self._live_since: Optional[float] = None
        self._order_fails = 0
        self._acct_uri: Optional[str] = None
        self._next_status = 0.0
        self._next_order = 0.0
        self._next_sync = 0.0
        self._next_mint = 0.0
        self._pending_polls = 0
        self._wake = asyncio.Event()
        self._task: Optional["asyncio.Task[None]"] = None
        self._load()


    def _load(self) -> None:
        try:
            held = json.loads(self._pairing.setting(SETTING) or "{}")
            self._view = control.clean_view(held["view"]) if isinstance(held.get("view"), dict) else {}
            self._error = held.get("error") if isinstance(held.get("error"), str) else None
            self._updated_at = int(held.get("updated_at") or 0)
        except (ValueError, TypeError, AttributeError):
            self._view, self._error, self._updated_at = {}, None, 0

    def _commit(self, view: Optional[Dict[str, Any]] = None, error: Optional[str] = None, *, keep_error: bool = False) -> None:
        if view is not None:
            self._view = view
            self._updated_at = int(self._clock())
        if not keep_error:
            self._error = error
        self._pairing.set_setting(SETTING, json.dumps(
            {"view": self._view, "error": self._error, "updated_at": self._updated_at}))
        resource_push.notify(topics.CUSTOM_DOMAIN)

    @property
    def state(self) -> str:
        return str(self._view.get("state") or "none")

    @property
    def domain(self) -> Optional[str]:
        value = self._view.get("domain")
        return value if isinstance(value, str) and self.state != "none" else None

    def cert_info(self) -> Optional[Dict[str, str]]:
        described = certs.describe_cert(self._certs.cert_path.parent)
        if described is None or "profile" not in described:
            return None
        return {key: described[key] for key in ("issuer", "not_after", "profile")}

    def snapshot(self) -> Dict[str, Any]:
        view = self._view
        domain = self.domain
        return {"domain": domain, "domain_display": names.display(domain) if domain else None,
                "state": self.state, "target": view.get("target"), "dead_reason": view.get("dead_reason"),
                "lockout_until": view.get("lockout_until"), "check": view.get("check"),
                "cert": self.cert_info() if domain else None, "error": self._error, "updated_at": self._updated_at}


    def name(self) -> Optional[str]:
        return self.domain if self.state == "live" else None

    def ready(self) -> bool:
        return self._ready and self.name() is not None

    def challenge_port(self) -> Optional[int]:
        return self.responder.port if self.responder.has_open else None

    def live_host(self) -> Optional[str]:
        return self.name() if self.ready() else None

    def custom_context(self) -> Optional[Tuple[str, ssl.SSLContext]]:
        host = self.live_host()
        return None if host is None else (host, self._certs.context_loaded())

    def needs_tunnel(self) -> bool:
        return self.state == "live" and (not self._ready or self._order_open or self._renewal_due())

    def _renewal_due(self) -> bool:
        return self._not_after is None or self._not_after - datetime.now(timezone.utc) < RENEW_BEFORE


    async def attach(self, link_context: ssl.SSLContext, tunnel: Any) -> None:
        self._tunnel, self._link_context = tunnel, link_context
        certs.install_sni_selector(link_context, self.custom_context)
        await self.responder.start()
        await self._refresh_cert_flag()
        self._wake.set()

    async def detach(self) -> None:
        self._tunnel = None
        await self.responder.stop()

    async def _refresh_cert_flag(self) -> None:
        domain = self.domain
        usable = bool(domain) and await asyncio.to_thread(self._certs.is_usable, domain)
        if usable:
            await asyncio.to_thread(self._certs.context)
            self._not_after = await asyncio.to_thread(self._certs.not_after)
        else:
            self._not_after = None
        self._ready = usable


    async def _client(self) -> control.ControlClient:
        session = await self._get_session()
        await session.ensure_registered()
        kwargs = {"call": self._call} if self._call is not None else {}
        return control.ControlClient(session=session, control_url=self._control_url, sleep=self._sleep, **kwargs)

    async def _account_uri(self) -> str:
        if self._acct_uri is None:
            self._link_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            key = await asyncio.to_thread(self._certs.load_or_create_key, self._certs.account_key_path)
            client = acme.AcmeClient(directory_url=self._directory_url, account_key=key, alpn=self.responder)
            try:
                self._acct_uri = await client.account_uri()
            finally:
                await client.aclose()
        return self._acct_uri

    async def _adopt(self, view: Dict[str, Any]) -> None:
        await self._repair.enforce(int(view.get("repair") or 0))
        was_pending = self.state == "pending"
        if view.get("state") != "live":
            self._claim_sent = False
            self._live_since, self._order_fails = None, 0
        if view.get("state") == "pending" and not was_pending:
            self._pending_polls = 0
        self._commit(view)
        self._schedule_status()
        self._wake.set()
        await self._reconcile()

    async def submit(self, raw: str) -> Dict[str, Any]:
        domain = names.normalise(raw)
        client = await self._client()
        view = await client.act("submit", domain, await self._account_uri())
        await self._adopt(view)
        return await asyncio.to_thread(self.snapshot)

    async def remove(self) -> Dict[str, Any]:
        if self.domain:
            try:
                await (await self._client()).act("remove", self.domain)
            except control.CustomDomainError as exc:
                if exc.code != "no_domain":
                    raise
            await asyncio.to_thread(self._certs.forget)
            self._ready, self._not_after = False, None
            await self._adopt(control.clean_view({}))
        return await asyncio.to_thread(self.snapshot)

    async def refresh(self) -> None:
        if self.domain is None:
            return
        try:
            view = await (await self._client()).act("status")
            self._pending_polls += 1
            await self._adopt(view)
        except control.CustomDomainError as exc:
            self._commit(error="control_unreachable" if exc.code == "unreachable" or exc.status >= 500
                         else f"control_refused:{exc.code}")
        except RelayAuthError as exc:
            self._commit(error=f"relay_{exc.kind}")
        except (OSError, ValueError) as exc:
            logger.warning("custom_domain_status_failed", error_type=type(exc).__name__)
            self._commit(error="repair_failed")
        self._schedule_status()

    def refresh_soon(self) -> None:
        if self.domain is not None:
            self._next_status = 0.0
            self._wake.set()

    def set_sync(self, enabled: bool) -> None:
        if self.domain is not None:
            self._pairing.set_setting(SYNC_SETTING, "on" if enabled else "off")
            self._next_sync = 0.0
            self._wake.set()


    async def _obtain(self, hostname: str, cert_key: ec.EllipticCurvePrivateKey) -> str:
        account = await asyncio.to_thread(self._certs.load_or_create_key, self._certs.account_key_path)
        client = acme.AcmeClient(directory_url=self._directory_url, account_key=account,
                                 alpn=self.responder, profile=acme.SHORTLIVED)
        try:
            return await client.obtain(hostname, cert_key)
        finally:
            await client.aclose()

    async def _order(self, domain: str) -> None:
        self._order_open = True
        try:
            await self._certs.renew(domain)
            await self._refresh_cert_flag()
            self._order_fails = 0
            self._commit(error=None)
        except (acme.AcmeError, OSError, ValueError) as exc:
            logger.warning("custom_domain_order_failed", error_type=type(exc).__name__, error=str(exc)[:200])
            self._next_order = self._clock() + self._retry_after()
            self._order_fails += 1
            self._commit(error="certificate_failed")
        finally:
            self._order_open = False

    def _retry_after(self) -> float:
        young = self._live_since is not None and self._clock() - self._live_since < YOUNG_FOR
        return YOUNG_RETRIES[self._order_fails] if young and self._order_fails < len(YOUNG_RETRIES) else ORDER_RETRY

    async def _pin_pending(self) -> bool:
        now = self._clock()
        if self._live_since is None:
            self._live_since = now
        node = self._view.get("target")
        if self._ready or not isinstance(node, str) or now - self._live_since >= PIN_WAIT:
            return False
        if await dns_gate.pin_visible(node, await self._account_uri()):
            return False
        self._next_order = now + PIN_POLL
        return True

    async def _claim_then_order(self, domain: str) -> None:
        tunnel = self._tunnel
        if tunnel is None or not tunnel.connected:
            return
        if not self._claim_sent:
            session = await self._get_session()
            session.drop_token()
            try:
                self._claim_sent = await tunnel.reauth_now()
            except RelayAuthError as exc:
                logger.warning("custom_domain_reauth_failed", kind=exc.kind)
                return
            if not self._claim_sent:
                return
        if await self._pin_pending():
            return
        await self._order(domain)


    def _schedule_status(self) -> None:
        if self.state == "pending":
            step = PENDING_POLLS[self._pending_polls] if self._pending_polls < len(PENDING_POLLS) else PENDING_EVERY
        else:
            step = SETTLED_EVERY
        self._next_status = self._clock() + step

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="custom-domain")

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.responder.stop()

    async def _run(self) -> None:
        while True:
            try:
                delay = await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("custom_domain_tick_failed", error_type=type(exc).__name__)
                delay = SLOW_TICK / 10
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)

    async def _tick(self) -> float:
        domain = self.domain
        if domain is None:
            return SLOW_TICK
        now = self._clock()
        pending = self._pairing.setting(SYNC_SETTING)
        if pending in ("on", "off") and now >= self._next_sync:
            action = "sync_on" if pending == "on" else "sync_off"
            try:
                await self._adopt(await (await self._client()).act(action))
                self._pairing.set_setting(SYNC_SETTING, "")
            except (control.CustomDomainError, RelayAuthError) as exc:
                logger.warning("custom_domain_sync_failed", error_type=type(exc).__name__)
                self._next_sync = now + SYNC_RETRY
        if now >= self._next_status:
            await self.refresh()
        if self._sync_on() and now >= self._next_mint:
            await self._mint()
        if self.state == "live" and self._tunnel is not None and (not self._ready or self._renewal_due()) \
                and now >= self._next_order:
            await self._claim_then_order(domain)
        return FAST_TICK if self.needs_tunnel() or self.state == "pending" else SLOW_TICK

    async def _mint(self) -> None:
        self._next_mint = self._clock() + MINT_EVERY
        if self._tunnel is not None and self._tunnel.connected:
            return
        session = await self._get_session()
        session.drop_token()
        try:
            await session.token()
        except RelayAuthError as exc:
            logger.warning("custom_domain_mint_failed", kind=exc.kind)
            return
        await self.refresh()
