
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import structlog

from src.core import resource_push
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unreachable
from src.core.resource_push import topics

logger = structlog.get_logger()

UP, DOWN, UNSUPPORTED, CAP_TOO_LOW, LOGIN_EXPIRED, UNKNOWN = "up", "down", "unsupported", "cap_too_low", "login_expired", "unknown"
READY_PATH = "/_argent/health/v1/ready"
CAP_FLOOR_BYTES = 33554432
INTERVAL_ON, INTERVAL_OFF = 15.0, 60.0
FRESH_SECONDS = 60.0
CAP_SHARE = 0.8


@dataclass(frozen=True)
class HealthReport:

    state: str = UNKNOWN
    version: str = ""
    body_cap_bytes: Optional[int] = None
    mints_accepted: Optional[bool] = None
    upstream_chain: Optional[bool] = None
    dlp: str = ""
    control_plane: Optional[bool] = None
    checked_at: float = 0.0

    def as_public(self) -> Dict[str, Any]:
        return {"state": self.state, "version": self.version, "body_cap_bytes": self.body_cap_bytes, "mints_accepted": self.mints_accepted,
                "upstream_chain": self.upstream_chain, "dlp": self.dlp, "control_plane": self.control_plane, "checked_at": self.checked_at}


def classify(ready: Dict[str, Any]) -> str:
    if ready.get("ok") is False:
        return DOWN
    cap = ready.get("body_cap_bytes")
    if isinstance(cap, int) and not isinstance(cap, bool) and cap < CAP_FLOOR_BYTES:
        return CAP_TOO_LOW
    return UP


async def probe(gateway_url: str, server_url: str, *, ca_path: str = "", login_expired: bool = False, transport: Any = None,
                clock: Callable[[], float] = time.time) -> HealthReport:
    now = clock()
    if not gateway_url:
        return HealthReport(state=UNKNOWN, checked_at=now)
    state, ready = DOWN, {}
    try:
        reply = await ArgentClient(gateway_url, ca_path=ca_path, transport=transport).get(READY_PATH, auth=False)
        ready, state = reply.body, classify(reply.body)
    except NotFound:
        state = UNSUPPORTED
    except ArgentError as exc:
        logger.info("argent_gateway_not_ready", error_type=type(exc).__name__, status=exc.status)
    control: Optional[bool] = None
    if server_url:
        try:
            await ArgentClient(server_url, transport=transport).get("/", auth=False)
            control = True
        except Unreachable:
            control = False
        except ArgentError:
            control = True
    if state == UP and login_expired:
        state = LOGIN_EXPIRED
    cap = ready.get("body_cap_bytes")
    mints = ready.get("mints_accepted")
    if not isinstance(mints, bool) and state in (UP, CAP_TOO_LOW, LOGIN_EXPIRED):
        mints = True
    return HealthReport(state=state, version=str(ready.get("version") or ""), body_cap_bytes=cap if isinstance(cap, int) and not isinstance(cap, bool) else None,
                        mints_accepted=mints if isinstance(mints, bool) else None,
                        upstream_chain=ready.get("upstream_chain") if isinstance(ready.get("upstream_chain"), bool) else None,
                        dlp=str(ready.get("dlp") or ""), control_plane=control, checked_at=now)


REFUSALS = {
    "server_url_empty": "set the argent server address first",
    "gateway_url_empty": "set the argent gateway address first",
    "not_logged_in": "log in to argent first",
    "login_expired": "your argent login expired, log in again",
    "gateway_down": "the argent gateway is not answering",
    "gateway_unsupported": "gateway has no ready route",
    "cap_too_low": "the gateway body cap is too low",
    "mints_refused": "the gateway is not accepting keys",
    "no_upstream_chain": "gateway has no upstream chaining",
}


def switch_on_refusal(report: HealthReport, *, server_url: str, gateway_url: str, logged_in: bool, login_expired: bool) -> Optional[str]:
    if not server_url:
        return "server_url_empty"
    if not gateway_url:
        return "gateway_url_empty"
    if not logged_in:
        return "not_logged_in"
    if login_expired or report.state == LOGIN_EXPIRED:
        return "login_expired"
    if report.state == UNSUPPORTED:
        return "gateway_unsupported"
    if report.state == CAP_TOO_LOW:
        return "cap_too_low"
    if report.state != UP:
        return "gateway_down"
    if report.mints_accepted is not True:
        return "mints_refused"
    if report.upstream_chain is not True:
        return "no_upstream_chain"
    return None


@dataclass
class _Poller:

    task: Optional["asyncio.Task[None]"] = None
    wake: Optional[asyncio.Event] = None
    latest: HealthReport = field(default_factory=HealthReport)
    on_report: Optional[Callable[[HealthReport, bool], Any]] = None


_poller = _Poller()


def latest() -> HealthReport:
    return _poller.latest


def is_running() -> bool:
    return _poller.task is not None and not _poller.task.done()


def remember(report: HealthReport) -> None:
    before = _poller.latest
    _poller.latest = report
    if (before.state, before.version, before.body_cap_bytes, before.mints_accepted, before.upstream_chain, before.control_plane) != (
            report.state, report.version, report.body_cap_bytes, report.mints_accepted, report.upstream_chain, report.control_plane):
        resource_push.notify(topics.ARGENT_STATUS)


async def probe_now(login_expired: bool = False) -> HealthReport:
    cfg = settings_module.read()
    report = await probe(cfg.gateway_url, cfg.server_url, ca_path=cfg.ca_path, login_expired=login_expired)
    remember(report)
    return report


async def _run(login_expired: Callable[[], bool]) -> None:
    assert _poller.wake is not None
    while True:
        cfg = settings_module.read()
        try:
            report = await probe(cfg.gateway_url, cfg.server_url, ca_path=cfg.ca_path, login_expired=await asyncio.to_thread(login_expired))
            remember(report)
            if _poller.on_report is not None:
                await _poller.on_report(report, cfg.enabled)
        except Exception as exc:  # noqa: BLE001
            logger.warning("argent_health_pass_failed", error_type=type(exc).__name__)
        try:
            await asyncio.wait_for(_poller.wake.wait(), INTERVAL_ON if cfg.enabled else INTERVAL_OFF)
        except asyncio.TimeoutError:
            pass
        _poller.wake.clear()


def start(login_expired: Callable[[], bool], on_report: Optional[Callable[[HealthReport, bool], Any]] = None) -> None:
    if is_running():
        return
    _poller.on_report = on_report
    _poller.wake = asyncio.Event()
    _poller.task = asyncio.get_running_loop().create_task(_run(login_expired))


async def stop() -> None:
    task, _poller.task = _poller.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _poller.latest = HealthReport()
    _poller.on_report = None


def poke() -> None:
    if _poller.wake is not None:
        _poller.wake.set()
