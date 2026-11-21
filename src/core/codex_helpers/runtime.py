
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

import structlog

from src.core.codex_helpers import alerts
from src.core.codex_helpers import constants as K
from src.core.codex_helpers.check import HelperCheck, Identity, identity_of, run_check

logger = structlog.get_logger(__name__)

Finder = Callable[[], Optional[str]]
Versioner = Callable[[str], Optional[str]]
Checker = Callable[[Identity, Optional[str]], HelperCheck]

_state_lock = threading.Lock()
_run_lock = threading.Lock()
_finder: Optional[Finder] = None
_versioner: Optional[Versioner] = None
_checker: Checker = run_check
_on_change: Optional[Callable[[], None]] = None
_checks: Dict[Identity, HelperCheck] = {}
_current: Optional[Identity] = None


def install(finder: Finder, versioner: Versioner, *, checker: Checker = run_check,
            on_change: Optional[Callable[[], None]] = None) -> None:
    global _finder, _versioner, _checker, _on_change
    with _state_lock:
        _finder, _versioner, _checker, _on_change = finder, versioner, checker, on_change


def uninstall() -> None:
    global _finder, _versioner, _checker, _on_change, _current
    with _state_lock:
        _finder, _versioner, _checker, _on_change, _current = None, None, run_check, None, None
        _checks.clear()


def installed() -> bool:
    return _finder is not None


def latest() -> Optional[HelperCheck]:
    with _state_lock:
        return _checks.get(_current) if _current is not None else None


def for_version(version: Optional[str]) -> Optional[HelperCheck]:
    if not version:
        return None
    with _state_lock:
        found = [c for c in _checks.values() if c.version == version]
    return max(found, key=lambda c: c.checked_at) if found else None


def _resolve_identity() -> Optional[tuple]:
    finder, versioner = _finder, _versioner
    if finder is None or versioner is None:
        return None
    binary = finder()
    identity = identity_of(binary) if binary else None
    if identity is None:
        return None
    return identity, versioner(identity[0])


def _store(check: HelperCheck) -> Optional[HelperCheck]:
    global _current
    with _state_lock:
        before = _checks.get(check.identity)
        _checks[check.identity] = check
        _current = check.identity
    return before


def _announce(before: Optional[HelperCheck], check: HelperCheck) -> None:
    if before is not None and before.verdict == check.verdict:
        return
    logger.info("codex_helpers_verdict", version=check.version_label, verdict=check.verdict,
                before=before.verdict if before else None)
    if check.failing:
        alerts.raise_for(check)
    else:
        alerts.resolve_for(check)
    callback = _on_change
    if callback is not None:
        try:
            callback()
        except RuntimeError as exc:
            logger.warning("codex_helpers_notice_failed", error=str(exc))


def check_now(*, force: bool = False) -> Optional[HelperCheck]:
    resolved = _resolve_identity()
    if resolved is None:
        return None
    identity, version = resolved
    with _run_lock:
        with _state_lock:
            cached = _checks.get(identity)
        if cached is not None and not force and not cached.failing:
            _store(cached)
            return cached
        check = _checker(identity, version)
        before = _store(check)
    _announce(before, check)
    return check


def before_launch() -> Optional[HelperCheck]:
    resolved = _resolve_identity()
    if resolved is None:
        return None
    with _state_lock:
        cached = _checks.get(resolved[0])
    if cached is not None:
        return cached
    if not _run_lock.acquire(timeout=K.LAUNCH_WAIT_SECONDS):
        logger.warning("codex_helpers_launch_wait_expired")
        return None
    _run_lock.release()
    return check_now()


def status() -> dict:
    check = latest()
    body = {**check.to_dict(), "text": alerts.row_text(check)} if check else None
    return {"armed": installed(), "check": body}
