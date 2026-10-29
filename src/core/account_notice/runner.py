
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.core.account_notice import constants as C
from src.core.app_alerts import conditions, service
from src.core.app_alerts import constants as AK
from src.core.catalog import catalog_auth
from src.core.db import db_path_for

logger = structlog.get_logger(__name__)

_state_dir: Optional[Path] = None
_pairing_source: Callable[[], Any] = lambda: None  # noqa: E731


class AccountNoticeNotInstalled(RuntimeError):
    """The probe ran before :func:`install` named a state directory."""


def _phone_history(pairing: Any) -> bool:
    return pairing is not None and (pairing.enabled or pairing.device_count() > 0)


def _share_history(state_dir: Path) -> bool:
    path = db_path_for(state_dir)
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            return conn.execute("SELECT 1 FROM spectator_links LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError as exc:
        logger.info("account_notice_share_history_unreadable", error=str(exc))
        return False


def has_hosted_history(state_dir: Path, pairing: Any = None) -> bool:
    return _phone_history(pairing) or _share_history(state_dir)


def probe() -> conditions.ProbeResult:
    if _state_dir is None:
        raise AccountNoticeNotInstalled("account notice probe ran before install()")
    if catalog_auth.read_session(_state_dir) is not None:
        return conditions.CLEAR
    if not has_hosted_history(_state_dir, _pairing_source()):
        return conditions.CLEAR
    return conditions.Active(severity=AK.SEV_WARN, title_key=C.TITLE_SIGNED_OUT, detail_key=C.DETAIL_SIGNED_OUT)


def _apply_now() -> None:
    try:
        result = probe()
    except (AccountNoticeNotInstalled, OSError, sqlite3.Error) as exc:
        logger.warning("account_notice_evaluate_failed", error_type=type(exc).__name__)
        return
    if isinstance(result, conditions.Active):
        service.raise_alert(C.ALERT_KEY, source=C.ALERT_SOURCE, severity=result.severity,
                            title_key=result.title_key, detail_key=result.detail_key)
    else:
        service.resolve(C.ALERT_KEY)


def _on_account_change(_session: Any) -> None:
    threading.Thread(target=_apply_now, name="account-notice", daemon=True).start()


def install(state_dir: Path, pairing: Callable[[], Any] = lambda: None) -> None:
    global _state_dir, _pairing_source
    _state_dir = Path(state_dir)
    _pairing_source = pairing
    conditions.register_condition(C.ALERT_KEY, probe, C.CHECK_INTERVAL_SECONDS, source=C.ALERT_SOURCE)
    catalog_auth.subscribe(_on_account_change)


def uninstall() -> None:
    global _state_dir, _pairing_source
    conditions.unregister_condition(C.ALERT_KEY)
    catalog_auth.unsubscribe(_on_account_change)
    _state_dir = None
    _pairing_source = lambda: None  # noqa: E731
