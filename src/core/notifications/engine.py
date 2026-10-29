
from __future__ import annotations

import asyncio
import dataclasses
import time
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Set, Tuple

import structlog

from src.core import resource_push
from src.core.app_alerts import service as alert_service
from src.core.notifications import extras, kind_specs, links, types
from src.core.notifications.contracts import (
    NOT_COUNTED, ORIGIN_LOCAL, DeliveryResult, FailureClass, NotifyEvent, Sender,
)
from src.core.notifications.delivery import Item, Lane
from src.core.notifications.destinations.secrets import SecretError
from src.core.notifications.destinations.validate import split_list
from src.core.notifications.sms_cap import SmsDayCount
from src.core.notifications.presence import PresenceLeases, presence as default_presence
from src.core.notifications.routing_view import (
    DestinationStatus, DestinationView, RoutingView, current_view, install_status_provider, routing_writer,
)

log = structlog.get_logger(__name__)

STATUS_TOPIC = "notification_settings"
ALERT_KEY = "notifications.destination_disabled"
ALERT_SOURCE = "notifications"
ALERT_TITLE_KEY = "app_alert.notifications.destination_disabled.title"
ALERT_DETAIL_KEY = "app_alert.notifications.destination_disabled.detail"
DEDUPE_SECONDS = 300.0
COOLDOWN_SECONDS = 10.0
COOLDOWN_EXEMPT = ("swarm.question_climbed",)
PERMANENT_FAILURES_TO_DISABLE = 5
TEST_INTERVAL_SECONDS = 10.0
TEST_TYPE_ID = "alert.other"
TEST_TITLE = "carnivore test notification"

SenderLookup = Callable[[str], Optional[Sender]]
SecretsLookup = Callable[[str], Awaitable[Optional[Mapping[str, str]]]]
OpenCheck = Callable[[NotifyEvent], bool]


@dataclass(frozen=True)
class SendTestOutcome:

    found: bool
    limited: bool = False
    result: Optional[DeliveryResult] = None


class NotifyEngine:

    def __init__(self, *, sender_lookup: SenderLookup, is_muted: Callable[[str], bool],
                 secrets_lookup: SecretsLookup,
                 sms_state_dir: Optional[Path] = None,
                 is_uuid_muted: Callable[[str], bool] = lambda _uuid: False,
                 link_base: Optional[Callable[[], Awaitable[str]]] = None,
                 computer_name: Callable[[], str] = lambda: "",
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 screens: PresenceLeases = default_presence) -> None:
        self._sender_lookup = sender_lookup
        self._is_muted = is_muted
        self._is_uuid_muted = is_uuid_muted
        self._sms_counts = SmsDayCount(sms_state_dir)
        self._secrets_lookup = secrets_lookup
        self._link_base = link_base
        self._computer_name = computer_name
        self._clock = clock
        self._sleep = sleep
        self._screens = screens
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lanes: Dict[str, Lane] = {}
        self._tasks: Set[asyncio.Task] = set()
        self._dedupe: Dict[Tuple[str, Tuple], float] = {}
        self._cooldown: Dict[Tuple[str, str, str], float] = {}
        self._open_checks: Dict[str, OpenCheck] = {}
        self._status: Dict[str, DestinationStatus] = {}
        self._disabled_here: Set[str] = set()
        self._last_test: Dict[str, float] = {}
        self._status_flush_pending = False


    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        install_status_provider(self.statuses)

    async def stop(self) -> None:
        self._loop = None
        cancelled = list(self._tasks)
        for task in cancelled:
            task.cancel()
        self._tasks.clear()
        cancelled += [t for t in (lane.cancel() for lane in self._lanes.values()) if t is not None]
        self._lanes.clear()
        install_status_provider(dict)
        if cancelled:
            await asyncio.gather(*cancelled, return_exceptions=True)

    def offer(self, event: NotifyEvent) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._spawn, self.handle(event))
        except RuntimeError:
            log.warning("notify_offer_loop_closed", type_id=event.type_id)

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def register_open_check(self, type_id: str, fn: OpenCheck) -> None:
        self._open_checks[type_id] = fn

    def statuses(self) -> Mapping[str, DestinationStatus]:
        return dict(self._status)

    async def join(self) -> None:
        for lane in list(self._lanes.values()):
            await lane.join()


    async def handle(self, event: NotifyEvent) -> bool:
        if self._peer_owned(event):
            log.info("notify_refused_peer_origin", type_id=event.type_id)
            return False
        view = current_view()
        if view is None or view.paused:
            return False
        if not types.is_registered(event.type_id):
            log.warning("notify_unregistered_type", type_id=event.type_id)
            return False
        if self._muted(event):
            return False
        event = await self._fill(event)
        taken = [self._consider(view, dest, event) for dest in list(view.destinations())]
        return any(taken)

    async def deliver(self, event: NotifyEvent) -> bool:
        loop = self._loop
        if loop is None:
            return False
        if loop is asyncio.get_running_loop():
            return await self.handle(event)
        try:
            return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self.handle(event), loop))
        except RuntimeError:
            log.warning("notify_deliver_loop_closed", type_id=event.type_id)
            return False

    @staticmethod
    def _peer_owned(event: NotifyEvent) -> bool:
        return event.origin != ORIGIN_LOCAL or (event.session_id or "").startswith("remote:")

    def _admit(self, item: Item) -> Optional[Item]:
        live = self._still_wanted(item.dest.id, item.event)
        if live is None or (item.recheck_open and not self._is_open(item.event)):
            return None
        return Item(live, self._strip_details(live, item.event), item.recheck_open)

    def _muted(self, event: NotifyEvent) -> bool:
        if event.session_id and self._is_muted(event.session_id):
            return True
        return bool(event.session_uuid) and bool(self._is_uuid_muted(event.session_uuid))

    async def _fill(self, event: NotifyEvent) -> NotifyEvent:
        base = await self._link_base() if self._link_base is not None else ""
        slug = event.tmux_name or event.session_ref
        link = links.deep_link(base, slug) if slug else (base or None)
        return dataclasses.replace(event, computer=event.computer or self._computer_name(),
                                   link=link or event.link)

    def _consider(self, view: RoutingView, dest: DestinationView, event: NotifyEvent) -> bool:
        if not dest.enabled:
            return False
        self._disabled_here.discard(dest.id)
        if not view.is_ticked(dest.id, event.type_id):
            return False
        if not extras.project_allowed(dest.projects, event.project):
            return False
        now = self._clock()
        if extras.in_quiet_hours(dest.quiet, datetime.fromtimestamp(now)) and not extras.passes_quiet_hours(event.type_id):
            return False
        needs_you = event.type_id in types.NEEDS_YOU
        dedupe_key = (dest.id, self._dedupe_identity(event))
        if self._seen(self._dedupe, dedupe_key, now, DEDUPE_SECONDS):
            return False
        cooldown_key = (dest.id, event.type_id, event.session_id or event.tmux_name or "")
        cools = not needs_you and event.type_id not in COOLDOWN_EXEMPT
        if cools and self._seen(self._cooldown, cooldown_key, now, COOLDOWN_SECONDS):
            return False
        self._dedupe[dedupe_key] = now
        if cools:
            self._cooldown[cooldown_key] = now
        if extras.should_hold_for_away(dest.away, self._screens.is_screen_active()):
            self._spawn(self._held(dest, event))
        else:
            self._queue(dest, event)
        return True

    @staticmethod
    def _dedupe_identity(event: NotifyEvent) -> Tuple:
        return (event.type_id, event.instance_key, event.toast_id, event.toast_version,
                event.session_id or event.tmux_name or "")

    def _seen(self, table: Dict, key: Tuple, now: float, window: float) -> bool:
        if len(table) > 2048:
            for stale in [k for k, ts in table.items() if now - ts >= DEDUPE_SECONDS]:
                del table[stale]
        stamp = table.get(key)
        return stamp is not None and now - stamp < window

    def _is_open(self, event: NotifyEvent) -> bool:
        check = self._open_checks.get(event.type_id)
        if check is None:
            return True
        try:
            return bool(check(event))
        except Exception as exc:  # noqa: BLE001
            log.warning("notify_open_check_failed", type_id=event.type_id, error_type=type(exc).__name__)
            return True

    def _still_wanted(self, dest_id: str, event: NotifyEvent) -> Optional[DestinationView]:
        view = current_view()
        if self._peer_owned(event) or view is None or view.paused or self._muted(event):
            return None
        dest = next((d for d in view.destinations() if d.id == dest_id), None)
        if dest is None or not dest.enabled or not view.is_ticked(dest.id, event.type_id):
            return None
        return dest

    async def _held(self, dest: DestinationView, event: NotifyEvent) -> None:
        await self._sleep(extras.AWAY_HOLD_SECONDS)
        live = self._still_wanted(dest.id, event)
        if live is not None and self._is_open(event):
            self._queue(live, event, recheck_open=True)

    def _queue(self, dest: DestinationView, event: NotifyEvent, *, recheck_open: bool = False) -> None:
        self._enqueue(dest, event, recheck_open=recheck_open)
        delay = extras.reminder_delay_seconds(event.type_id, dest.reminder_minutes)
        if delay is not None:
            self._spawn(self._remind(dest.id, event, delay))

    def _enqueue(self, dest: DestinationView, event: NotifyEvent, *, recheck_open: bool = False) -> None:
        self._lane(dest, kind_specs.get_kind(dest.kind)).enqueue(Item(dest, self._strip_details(dest, event), recheck_open))

    @staticmethod
    def _strip_details(dest: DestinationView, event: NotifyEvent) -> NotifyEvent:
        spec = kind_specs.get_kind(dest.kind)
        if event.details is not None and not (dest.details and spec is not None and spec.details_allowed
                                              and not spec.sms_like):
            return dataclasses.replace(event, details=None)
        return event

    async def _remind(self, dest_id: str, event: NotifyEvent, delay: float) -> None:
        await self._sleep(delay)
        live = self._still_wanted(dest_id, event)
        if live is not None and self._is_open(event):
            self._enqueue(live, event, recheck_open=True)

    def _lane(self, dest: DestinationView, spec: Optional[kind_specs.KindSpec]) -> Lane:
        lane = self._lanes.get(dest.id)
        if lane is None:
            lane = Lane(dest.id, sms_like=bool(spec and spec.sms_like), clock=self._clock, sleep=self._sleep,
                        attempt=self._attempt, on_result=self._on_result,
                        recipients=self._recipient_count, admit=self._admit, day_count=self._sms_counts)
            self._lanes[dest.id] = lane
        return lane


    async def _recipient_count(self, item: Item) -> int:
        try:
            found = await self._secrets_lookup(item.dest.id)
        except SecretError:
            return 0
        return len(split_list((found or {}).get("numbers")))

    async def _attempt(self, item: Item) -> DeliveryResult:
        sender = self._sender_lookup(item.dest.kind)
        if sender is None:
            return DeliveryResult(ok=False, failure=FailureClass.INVALID, detail="no sender for kind")
        spec = kind_specs.get_kind(item.dest.kind)
        secrets: Mapping[str, str] = {}
        if spec is None or not spec.virtual:
            try:
                found = await self._secrets_lookup(item.dest.id)
            except SecretError as exc:
                log.warning("notify_secrets_unavailable", dest=item.dest.id, error_type=type(exc).__name__)
                return DeliveryResult(ok=False, failure=FailureClass.KEYCHAIN_LOCKED, detail="secret store unavailable")
            if found is None:
                return DeliveryResult(ok=False, failure=FailureClass.SECRET_MISSING, detail="no stored secret")
            secrets = found
        config = {**item.dest.config, "dest_id": item.dest.id, "details": item.dest.details}
        try:
            return await sender.send(item.event, config, secrets)
        except Exception as exc:  # noqa: BLE001
            log.error("notify_sender_raised", dest=item.dest.id, kind=item.dest.kind, error_type=type(exc).__name__)
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail="sender error")

    async def _on_result(self, item: Item, result: DeliveryResult) -> None:
        dest = item.dest
        status = self._status.get(dest.id, DestinationStatus())
        now = self._clock()
        if result.ok:
            self._set_status(dest.id, dataclasses.replace(status, last_ok_ts=now, consecutive_permanent_failures=0,
                                                          disabled_reason=None))
            return
        failure = result.failure.value if result.failure else None
        permanent = not result.retryable and result.failure not in NOT_COUNTED
        count = status.consecutive_permanent_failures + (1 if permanent else 0)
        self._set_status(dest.id, dataclasses.replace(status, last_failure_ts=now, last_failure=failure,
                                                      consecutive_permanent_failures=count))
        log.warning("notify_delivery_failed", dest=dest.id, kind=dest.kind, failure=failure,
                    status_code=result.status_code, permanent=permanent)
        if count >= PERMANENT_FAILURES_TO_DISABLE and dest.id not in self._disabled_here:
            await self._disable(dest, failure or "unknown")

    async def _disable(self, dest: DestinationView, failure: str) -> None:
        self._disabled_here.add(dest.id)
        lane = self._lanes.get(dest.id)
        if lane is not None:
            lane.clear()
        reason = f"{PERMANENT_FAILURES_TO_DISABLE} failures in a row: {failure}"
        writer = routing_writer()
        if writer is not None:
            await writer.disable_locally(dest.id, reason)
        status = self._status.get(dest.id, DestinationStatus())
        self._set_status(dest.id, dataclasses.replace(status, consecutive_permanent_failures=0,
                                                      disabled_reason=reason))
        log.warning("notify_destination_disabled", dest=dest.id, kind=dest.kind, failure=failure)
        await asyncio.to_thread(lambda: alert_service.raise_alert(
            ALERT_KEY, source=ALERT_SOURCE, severity="warn", title_key=ALERT_TITLE_KEY,
            params={"name": dest.name, "kind": dest.kind}, detail_key=ALERT_DETAIL_KEY))

    def _set_status(self, dest_id: str, status: DestinationStatus) -> None:
        self._status[dest_id] = status
        if self._status_flush_pending or self._loop is None:
            return
        self._status_flush_pending = True
        self._loop.call_soon(self._flush_status)

    def _flush_status(self) -> None:
        self._status_flush_pending = False
        resource_push.notify(STATUS_TOPIC)


    async def send_test(self, dest_id: str) -> SendTestOutcome:
        view = current_view()
        dest = next((d for d in view.destinations() if d.id == dest_id), None) if view is not None else None
        if dest is None:
            return SendTestOutcome(found=False)
        now = self._clock()
        last = self._last_test.get(dest_id)
        if last is not None and now - last < TEST_INTERVAL_SECONDS:
            return SendTestOutcome(found=True, limited=True)
        self._last_test[dest_id] = now
        event = NotifyEvent(type_id=TEST_TYPE_ID, kind="test", title=TEST_TITLE, ts=now,
                            computer=self._computer_name())
        result = await self._attempt(Item(dest, event))
        status = self._status.get(dest_id, DestinationStatus())
        if result.ok:
            status = dataclasses.replace(status, last_ok_ts=now)
        else:
            status = dataclasses.replace(status, last_failure_ts=now,
                                         last_failure=result.failure.value if result.failure else None)
        self._set_status(dest_id, status)
        return SendTestOutcome(found=True, result=result)


_engine: Optional[NotifyEngine] = None


def install_engine(engine: Optional[NotifyEngine]) -> None:
    global _engine
    _engine = engine


def current_engine() -> Optional[NotifyEngine]:
    return _engine
