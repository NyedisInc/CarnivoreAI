
from __future__ import annotations

import asyncio
import base64
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.api.attach_settle import read_pane_geometry
from src.api.ws_startup_paint import paint_on_attach
from src.config.relay import viewer_base_url
from src.core import relay_link_framer as framing
from src.core import relay_protocol as proto
from src.core import spectator_redaction, viewer_fanout
from src.core.bounded_stream import BoundedStream
from src.core.relay_identity import publish_auth
from src.core.relay_identity.device_key import key_loader_for
from src.core.relay_identity.session import (
    ACCOUNT_DISABLED,
    OWNED_ELSEWHERE,
    REVOKED,
    SIGNIN_REQUIRED,
    UPDATE_REQUIRED,
    DeviceSession,
    RelayAuthError,
)

logger = structlog.get_logger()

DeclarationSource = Callable[[], Awaitable[List[proto.LinkDeclaration]]]

Connector = Callable[[str, publish_auth.Dial], Any]

Credentials = Callable[[], Awaitable[publish_auth.PublishAuth]]

CLOSE_REVOKED = 4403
CLOSE_UPDATE_REQUIRED = 4426
CLOSE_QUOTA = 4402
CLOSE_TOKEN_EXPIRED = 4440

GEOMETRY_POLL_SECONDS = 1.0

MIN_PAINT_INTERVAL_SECONDS = 1.0

FRAME_RECORD = "record"

_NOT_CONNECTED = "the relay publisher is not connected"

_STATUS_TEXT = {
    REVOKED: "relay access revoked",
    UPDATE_REQUIRED: "update required",
    SIGNIN_REQUIRED: "sign in to a carnivore account to use the relay",
    ACCOUNT_DISABLED: "this carnivore account is disabled",
    OWNED_ELSEWHERE: "this computer's relay device belongs to another carnivore account",
    "keychain_unavailable": "the login keychain is unavailable",
    "control_unreachable": "the relay control plane is unreachable",
    "rate_limited": "the relay control plane is rate limiting this device",
    "refused": "the relay refused this device",
    "quota": "the daily relay quota is spent",
}

_CONNECTION_ERRORS: Tuple[type, ...] = (OSError, asyncio.TimeoutError, sqlite3.Error)
try:
    from websockets.exceptions import WebSocketException

    _CONNECTION_ERRORS += (WebSocketException,)
except ImportError:
    pass


def _default_connector(url: str, dial: publish_auth.Dial) -> Any:
    from websockets.asyncio.client import connect

    return connect(
        url,
        subprotocols=[dial.subprotocol],
        additional_headers=dict(dial.headers),
        open_timeout=10,
    )


@dataclass
class _Pump:

    task: asyncio.Task
    stream: BoundedStream
    session_id: str
    repaint: asyncio.Event
    framer: framing.LinkFramer


class RelayPublisher:

    def __init__(
        self,
        *,
        url: str,
        credentials: Credentials,
        registry: Any,
        declarations: DeclarationSource,
        connector: Connector = _default_connector,
        redactor_factory: Optional[spectator_redaction.RedactorFactory] = None,
        idle_flush_seconds: float = spectator_redaction.DEFAULT_IDLE_FLUSH_SECONDS,
        refresh_seconds: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        version: str = "",
    ) -> None:
        self._url = url
        self._credentials = credentials
        self._auth: Optional[publish_auth.PublishAuth] = None
        self._status = _NOT_CONNECTED
        self._registry = registry
        self._declarations = declarations
        self._connector = connector
        self._factory = redactor_factory or spectator_redaction.relay_redactor_factory
        self._version = version
        self._idle = idle_flush_seconds
        self._refresh = refresh_seconds
        self._sleep = sleep
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._up = asyncio.Event()
        self._closing = False
        self._publisher_id = proto.new_publisher_id()
        self._poke_event = asyncio.Event()
        self._wake = asyncio.Event()

    @property
    def viewer_base(self) -> str:
        return viewer_base_url(self._url)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> str:
        return "connected" if self._connected else self._status

    @property
    def stopped(self) -> bool:
        return self._task is not None and self._task.done()

    @property
    def protocol_version(self) -> Optional[int]:
        return None if self._auth is None else self._auth.version

    def new_link_identity(self) -> Optional[tuple]:
        return None if self._auth is None else self._auth.new_link_identity()

    def poke(self) -> None:
        self._poke_event.set()

    def on_account_change(self) -> None:
        if self._auth is not None:
            self._auth.invalidate()
        self._wake.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        self._task.add_done_callback(_report_end)

    async def wait_connected(self, timeout: float) -> bool:
        if self._connected:
            return True
        if self._task is None or self._task.done():
            return False
        up = asyncio.create_task(self._up.wait())
        try:
            await asyncio.wait({up, self._task}, timeout=timeout,
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            up.cancel()
        return self._connected

    async def aclose(self, *, drain_seconds: float = 0.0) -> None:
        if self._task is None:
            return
        try:
            if drain_seconds > 0 and self._connected and not self._task.done():
                self._closing = True
                self.poke()
                await asyncio.wait({self._task}, timeout=drain_seconds)
        finally:
            self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        attempt = 0
        while True:
            ws = None
            self._wake.clear()
            try:
                if attempt:
                    await self._declarations()
                self._auth = auth = await self._credentials()
                async with self._connector(self._url, await auth.dial()) as ws:
                    logger.info("relay_publish_connected", version=auth.version)
                    self._connected = True
                    self._up.set()
                    attempt = 0
                    await self._serve(ws, auth)
            except RelayAuthError as exc:
                self._status = _STATUS_TEXT.get(exc.kind, exc.kind)
                if exc.terminal:
                    logger.error("relay_publish_stopped", reason=exc.kind)
                    return
                if exc.parks:
                    logger.info("relay_publish_parked", reason=exc.kind)
                    await self._wake.wait()
                    attempt = 0
                    continue
                logger.warning("relay_publish_auth_unavailable", reason=exc.kind)
            except _CONNECTION_ERRORS as exc:
                self._status = _NOT_CONNECTED
                logger.warning("relay_publish_disconnected", error=type(exc).__name__,
                               close_code=_close_code(ws))
            finally:
                self._connected = False
                self._up.clear()
            if self._closing:
                logger.info("relay_publish_closed_idle")
                return
            code = _close_code(ws)
            if code in (CLOSE_REVOKED, CLOSE_UPDATE_REQUIRED):
                reason = REVOKED if code == CLOSE_REVOKED else UPDATE_REQUIRED
                self._status = _STATUS_TEXT[reason]
                logger.error("relay_publish_stopped", reason=reason, close_code=code)
                return
            if code == CLOSE_TOKEN_EXPIRED and self._auth is not None:
                self._auth.invalidate()
            if code == CLOSE_QUOTA:
                self._status = _STATUS_TEXT["quota"]
                attempt = max(attempt, 5)
            delay = proto.backoff_delay(attempt)
            attempt += 1
            logger.info("relay_publish_retry_scheduled", delay_seconds=round(delay, 2))
            await self._sleep(delay)

    async def _serve(self, ws: Any, auth: publish_auth.PublishAuth) -> None:
        outbox = BoundedStream(
            max_items=viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS,
            max_bytes=viewer_fanout.MAX_VIEWER_QUEUE_BYTES,
            label="relay publish",
        )
        pumps: Dict[str, _Pump] = {}
        writer = asyncio.create_task(_write(ws, outbox))
        closed = asyncio.create_task(ws.wait_closed())
        reader = asyncio.create_task(_read_joins(ws, pumps))
        declared: Optional[List[proto.LinkDeclaration]] = None
        poke_wait: Optional[asyncio.Task] = None
        reauth: Optional[asyncio.Task] = None
        try:
            while True:
                self._poke_event.clear()
                live = await self._declarations()
                usable = [d for d in live if auth.declarable(d)]
                wanted = self._sync_pumps(usable, pumps, outbox, sealed=auth.version == 2)
                viewer_fanout.offer_text(
                    outbox, auth.links_frame(wanted, self._publisher_id))
                reauth = self._step_reauth(auth, reauth, outbox)
                if wanted != declared:
                    logger.info("relay_links_declared", links=len(wanted),
                                undeclarable=len(live) - len(usable))
                    declared = wanted
                if self._closing:
                    outbox.close()
                    await asyncio.wait({writer, closed},
                                       return_when=asyncio.FIRST_COMPLETED)
                    return
                poke_wait = asyncio.create_task(self._poke_event.wait())
                await asyncio.wait({writer, closed, reader, poke_wait},
                                   timeout=self._refresh,
                                   return_when=asyncio.FIRST_COMPLETED)
                poke_wait.cancel()
                if writer.done():
                    writer.result()
                if writer.done() or outbox.overflowed:
                    raise ConnectionError("relay outbox overflowed")
                if reader.done():
                    reader.result()
                if closed.done() or reader.done():
                    raise ConnectionError("relay closed the connection")
        finally:
            if poke_wait is not None:
                poke_wait.cancel()
            if reauth is not None:
                reauth.cancel()
            for pump in pumps.values():
                pump.task.cancel()
                self._registry.unsubscribe(pump.stream, pump.session_id)
            outbox.close()
            reader.cancel()
            writer.cancel()
            closed.cancel()

    def _step_reauth(
        self, auth: publish_auth.PublishAuth, task: Optional[asyncio.Task],
        outbox: BoundedStream,
    ) -> Optional[asyncio.Task]:
        if task is not None and task.done():
            try:
                viewer_fanout.offer_text(outbox, task.result())
            except RelayAuthError as exc:
                if exc.terminal:
                    raise
                logger.warning("relay_reauth_deferred", reason=exc.kind)
            task = None
        if task is None and auth.reauth_due():
            task = asyncio.create_task(auth.reauth_frame())
        return task

    def _sync_pumps(
        self,
        live: List[proto.LinkDeclaration],
        pumps: Dict[str, _Pump],
        outbox: BoundedStream,
        *,
        sealed: bool = False,
    ) -> List[proto.LinkDeclaration]:
        live_ids = {d.link_id for d in live}
        for link_id in list(pumps):
            pump = pumps[link_id]
            task = pump.task
            if link_id not in live_ids or task.done():
                if task.done() and not task.cancelled() and task.exception():
                    logger.error("relay_link_pump_failed", link_id=link_id,
                                 error=type(task.exception()).__name__)
                elif link_id not in live_ids:
                    _offer(outbox, pump.framer.end())
                task.cancel()
                self._registry.unsubscribe(pump.stream, pump.session_id)
                del pumps[link_id]
        for decl in live:
            if decl.link_id in pumps:
                continue
            framer = framing.for_link(decl, sealed=sealed, client_version=self._version)
            if framer is None:
                logger.error("relay_link_not_published", link_id=decl.link_id,
                             error="not sealable: no content key or expiry")
                continue
            try:
                scrubber = spectator_redaction.build_scrubber(
                    label=decl.link_id, factory=self._factory,
                    idle_flush_seconds=self._idle,
                )
            except spectator_redaction.RedactorUnavailableError as exc:
                logger.error("relay_link_not_published", link_id=decl.link_id,
                             error=str(exc))
                continue
            stream = self._registry.subscribe(decl.session_id)
            repaint = asyncio.Event()
            repaint.set()
            session_id = decl.session_id
            task = asyncio.create_task(_pump(
                decl.link_id, stream, scrubber, outbox,
                lambda sid=session_id: self._registry.get_backend(sid), repaint,
                framer=framer))
            pumps[decl.link_id] = _Pump(task, stream, session_id, repaint, framer)
        return [d for d in live if d.link_id in pumps]


def _close_code(ws: Any) -> Optional[int]:
    code = getattr(ws, "close_code", None)
    return code if isinstance(code, int) else None


def _report_end(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("relay_publish_task_failed", error=type(task.exception()).__name__)


async def _write(ws: Any, outbox: BoundedStream) -> None:
    while True:
        frame = await outbox.get()
        if frame is None:
            return
        await ws.send(frame.payload)


def _offer(outbox: BoundedStream, frames: List[framing.Frame]) -> None:
    for frame in frames:
        if isinstance(frame, str):
            viewer_fanout.offer_text(outbox, frame)
        else:
            outbox.offer(viewer_fanout.ViewerFrame(FRAME_RECORD, frame), len(frame))


async def _read_joins(ws: Any, pumps: Dict[str, _Pump]) -> None:
    while True:
        link_id = proto.joined_link_id(await ws.recv())
        pump = pumps.get(link_id) if link_id else None
        if pump is not None:
            pump.repaint.set()


class _ScrubbedPaint:

    def __init__(self, offer: Callable[[spectator_redaction.Scrubbed], None],
                 scrubber: spectator_redaction.SpectatorScrubber) -> None:
        self._offer = offer
        self._scrubber = scrubber
        self.failure: Optional[BaseException] = None

    async def send_bytes(self, data: bytes) -> None:
        try:
            self._offer(await self._scrubber.scrub_off_loop(data))
        except Exception as exc:  # noqa: BLE001
            self.failure = exc
            raise


async def _paint(
    link_id: str, backend: Any, scrubber: spectator_redaction.SpectatorScrubber,
    outbox: BoundedStream, framer: framing.LinkFramer,
) -> Optional[Tuple[int, int]]:
    geometry = await read_pane_geometry(backend)
    if geometry is None:
        logger.info("relay_link_size_unreadable", link_id=link_id)
        _offer(outbox, framer.reopen())
        return None
    _offer(outbox, framer.grid(*geometry))
    sink = _ScrubbedPaint(lambda data: _offer(outbox, framer.paint(data)), scrubber)
    await paint_on_attach(sink, backend)
    if sink.failure is not None:
        raise sink.failure
    return geometry


async def _pump(
    link_id: str,
    stream: BoundedStream,
    scrubber: spectator_redaction.SpectatorScrubber,
    outbox: BoundedStream,
    backend_for: Callable[[], Any],
    repaint: asyncio.Event,
    framer: Optional[framing.LinkFramer] = None,
) -> None:
    shape: framing.LinkFramer = framer or framing.PlainFramer(link_id)

    def offer(data: spectator_redaction.Scrubbed) -> None:
        _offer(outbox, shape.data(data))

    loop = asyncio.get_running_loop()
    sent_size: Optional[Tuple[int, int]] = None
    next_probe = loop.time()
    quiet_since = loop.time()
    painted_at: Optional[float] = None
    getter: Optional[asyncio.Future] = None
    waiter: Optional[asyncio.Future] = None
    try:
        while True:
            paint_due = (painted_at is None
                         or loop.time() - painted_at >= MIN_PAINT_INTERVAL_SECONDS)
            if repaint.is_set() and paint_due:
                repaint.clear()
                if getter is not None and getter.done():
                    if getter.result() is None:
                        logger.info("relay_link_stream_ended", link_id=link_id,
                                    overflowed=stream.overflowed)
                        return
                    getter = None
                while stream.queued_items and not stream.closed:
                    await stream.get()
                sent_size = await _paint(link_id, backend_for(), scrubber, outbox, shape)
                painted_at = loop.time()
                next_probe = loop.time() + GEOMETRY_POLL_SECONDS
            elif loop.time() >= next_probe:
                next_probe = loop.time() + GEOMETRY_POLL_SECONDS
                measured = await read_pane_geometry(backend_for())
                if measured is not None and measured != sent_size:
                    repaint.set()
                    continue
            if getter is None:
                getter = asyncio.ensure_future(stream.get())
            wake = {getter}
            timeout = next_probe - loop.time()
            if repaint.is_set():
                timeout = min(timeout, painted_at + MIN_PAINT_INTERVAL_SECONDS - loop.time())
            else:
                if waiter is None or waiter.done():
                    waiter = asyncio.ensure_future(repaint.wait())
                wake.add(waiter)
            if scrubber.pending:
                timeout = min(timeout, quiet_since + scrubber.idle_flush_seconds - loop.time())
            done, _ = await asyncio.wait(wake, timeout=max(0.0, timeout),
                                         return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                frame = getter.result()
                getter = None
                if frame is None:
                    logger.info("relay_link_stream_ended", link_id=link_id,
                                overflowed=stream.overflowed)
                    return
                quiet_since = loop.time()
                if frame.kind == viewer_fanout.FRAME_PTY:
                    offer(await scrubber.scrub_off_loop(base64.b64decode(frame.payload)))
            elif (scrubber.pending
                  and loop.time() - quiet_since >= scrubber.idle_flush_seconds):
                offer(await scrubber.flush_off_loop())
            now = time.time()
            _offer(outbox, shape.idle(now))
            if shape.rotate_due(now):
                repaint.set()
    finally:
        for pending in (getter, waiter):
            if pending is not None:
                pending.cancel()
        scrubber.log_summary()


def start_if_enabled(
    config: Any, *, registry: Any, store: Any, db_path: Optional[Any] = None,
    version: str = "", account: Optional[Any] = None,
) -> Optional[RelayPublisher]:
    if not config.enabled:
        return None
    if not config.url.startswith("wss://"):
        logger.warning("relay_publish_not_started", reason="url_not_wss")
        return None
    key_seam = {"key_loader": key_loader_for(config.device_key_file)} if config.device_key_file else {}
    session = None if db_path is None else DeviceSession(
        db_path=db_path, control_url=config.control_url, version=version, account=account, **key_seam)
    if session is None and (not config.legacy_fallback or proto.publish_token() is None):
        logger.warning("relay_publish_not_started", reason="token_unset",
                       sources=[*proto.TOKEN_ENVS, "keychain"])
        return None

    async def credentials() -> publish_auth.PublishAuth:
        return await publish_auth.resolve(session, proto.publish_token, config.legacy_fallback)

    async def declarations() -> List[proto.LinkDeclaration]:
        rows = await store.live_relay_declarations()
        return [proto.LinkDeclaration(link_id=lid, token_sha256=digest, session_id=sid,
                                      nonce=nonce, expires_at=expires_at, content_key=key)
                for lid, sid, digest, nonce, expires_at, key in rows]

    publisher = RelayPublisher(
        url=config.url, credentials=credentials, registry=registry,
        declarations=declarations,
        idle_flush_seconds=config.idle_flush_ms / 1000.0,
        refresh_seconds=config.refresh_seconds,
        version=version,
    )
    publisher.start()
    logger.info("relay_publish_started", url=config.url, device_identity=session is not None)
    return publisher
