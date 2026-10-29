
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

import structlog

from src.core.app_alerts import constants as K
from src.core.app_alerts import service

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Active:

    severity: str
    title_key: str
    params: Mapping[str, Any] = field(default_factory=dict)
    actions: Sequence[Mapping[str, Any]] = ()
    detail_key: Optional[str] = None


class _Clear:

    def __repr__(self) -> str:
        return "CLEAR"


CLEAR = _Clear()
ProbeResult = Union[Active, _Clear]
Probe = Callable[[], ProbeResult]


@dataclass
class _Entry:
    key: str
    source: str
    probe: Probe
    interval_s: float
    next_due: float = 0.0


_registry: Dict[str, _Entry] = {}
_reg_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="app-alert-probe")


def register_condition(key: str, probe: Probe, interval_s: float, *, source: str) -> None:
    with _reg_lock:
        _registry[key] = _Entry(key=key, source=source, probe=probe, interval_s=max(1.0, float(interval_s)))


def unregister_condition(key: str) -> None:
    with _reg_lock:
        _registry.pop(key, None)


def _probe(entry: _Entry, budget: float) -> Optional[ProbeResult]:
    try:
        return _pool.submit(entry.probe).result(timeout=budget)
    except FutureTimeout:
        logger.warning("app_alert_probe_overran", key=entry.key, budget_s=budget)
    except Exception as exc:  # noqa: BLE001
        logger.warning("app_alert_probe_failed", key=entry.key, error=str(exc), error_type=type(exc).__name__)
    return None


def run_due(*, now: Optional[float] = None, db_path: Optional[Path] = None,
            budget: float = K.PROBE_BUDGET_SECONDS) -> List[str]:
    moment = time.monotonic() if now is None else now
    with _reg_lock:
        due = [e for e in _registry.values() if e.next_due <= moment]
        for entry in due:
            entry.next_due = moment + entry.interval_s
    answered: List[str] = []
    for entry in due:
        result = _probe(entry, budget)
        if result is None:
            continue
        answered.append(entry.key)
        if isinstance(result, Active):
            service.raise_alert(entry.key, source=entry.source, severity=result.severity,
                                title_key=result.title_key, params=result.params, actions=result.actions,
                                detail_key=result.detail_key, db_path=db_path)
        else:
            service.resolve(entry.key, db_path=db_path)
    return answered


class _Runner:

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="app-alert-conditions", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            run_due()

    def stop(self) -> None:
        self._stop.set()


_runner = _Runner()


def start_runner() -> None:
    _runner.start()


def stop_runner() -> None:
    _runner.stop()
