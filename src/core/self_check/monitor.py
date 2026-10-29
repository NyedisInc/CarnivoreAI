
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import structlog

from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.self_check import constants as K
from src.core.self_check.checks import CheckResult, Context, SystemIO, report_dict, run_checks

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_last: Dict[str, CheckResult] = {}
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_manager: Any = None


def server_context() -> Context:
    from src.config import settings
    from src.core.db import db_path_for
    from src.core.sessions.agent_update import CLAUDE_INSTALL_CANDIDATES
    from src.core.tmux_discovery import resolve_tmux_path
    from src.core.tmux_socket_resolution import configured_tmux_socket_name, resolve_probe_socket

    holder = _manager if _manager is not None else SimpleNamespace()

    def resolve_socket(list_for_socket):
        return resolve_probe_socket(holder, configured_tmux_socket_name(settings), list_for_socket)

    state = settings.get_state_dir()
    return Context(code_dir=Path(__file__).resolve().parents[3], claude_dir=Path.home() / ".claude",
                   state_dir=state, db_file=db_path_for(state), resolve_socket=resolve_socket,
                   tmux_path=resolve_tmux_path(), claude_candidates=tuple(CLAUDE_INSTALL_CANDIDATES))


def apply(results: List[CheckResult]) -> List[str]:
    touched: List[str] = []
    for result in results:
        with _lock:
            before = _last.get(result.name)
            _last[result.name] = result
        if before is not None and before.status == result.status:
            continue
        touched.append(result.name)
        key = K.ALERT_KEY_PREFIX + result.name
        if result.status == K.FAIL:
            findings = "; ".join(result.findings)
            if len(findings) > K.MAX_FINDINGS_CHARS:
                findings = findings[:K.MAX_FINDINGS_CHARS - 3] + "..."
            logger.warning("self_check_failed", check=result.name, summary=result.summary, findings=result.findings[:5])
            service.raise_alert(key, source=K.ALERT_SOURCE, severity=AK.SEV_ERROR, auto_resolve=True,
                                title_key=K.TITLE_KEY.format(check=result.name),
                                detail_key=K.DETAIL_KEY.format(check=result.name),
                                params={"summary": result.summary, "findings": findings})
        else:
            service.resolve(key)
    return touched


def latest() -> Dict[str, dict]:
    with _lock:
        return {name: r.to_dict() for name, r in _last.items()}


def run_once(ctx: Optional[Context] = None, io: Optional[SystemIO] = None) -> List[CheckResult]:
    results = run_checks(ctx or server_context(), io)
    apply(results)
    return results


def _loop(ctx: Context) -> None:
    while True:
        try:
            run_once(ctx)
        except (OSError, RuntimeError) as exc:
            logger.error("self_check_run_failed", error=str(exc), error_type=type(exc).__name__)
        if _stop.wait(K.INTERVAL_SECONDS):
            return


def install(ctx: Optional[Context] = None, manager: Any = None) -> None:
    global _thread, _manager
    _manager = manager
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(ctx or server_context(),), name="self-check", daemon=True)
    _thread.start()


def uninstall() -> None:
    global _thread, _manager
    _manager = None
    _stop.set()
    _thread = None
    with _lock:
        _last.clear()


def report(ctx: Optional[Context] = None) -> dict:
    return report_dict(run_checks(ctx or server_context()))
