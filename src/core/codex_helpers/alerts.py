
from __future__ import annotations

import functools
from typing import Dict, Optional

import structlog

from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.codex_helpers import constants as K
from src.core.codex_helpers.check import HelperCheck

logger = structlog.get_logger(__name__)


def alert_key(check: HelperCheck) -> str:
    return K.ALERT_KEY_PREFIX + check.version_label


def short_version(check: HelperCheck) -> str:
    parts = check.version_label.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) else check.version_label


def params_for(check: HelperCheck) -> Dict[str, str]:
    names = check.unapproved_names() or [K.HOST_NAME]
    params = {"version": short_version(check), "helpers": ", ".join(names), "agent": "codex"}
    if check.verdict in K.NOTIFY_VARIANTS:
        params["notify_variant"] = K.NOTIFY_VARIANTS[check.verdict]
    return params


def raise_for(check: HelperCheck) -> Optional[dict]:
    if not check.failing:
        return None
    logger.warning("codex_helpers_failing", version=check.version_label, verdict=check.verdict,
                   unapproved=check.unapproved_names(),
                   handshake=check.handshake.outcome if check.handshake else None)
    return service.raise_alert(alert_key(check), source=K.ALERT_SOURCE, severity=AK.SEV_ERROR, auto_resolve=True,
                               title_key=K.TITLE_KEYS[check.verdict], detail_key=K.DETAIL_KEYS[check.verdict],
                               params=params_for(check))


def resolve_for(check: HelperCheck) -> int:
    return len(service.resolve(alert_key(check)))


@functools.lru_cache(maxsize=1)
def _row_lines() -> Dict[str, str]:
    from src.core.notifications.catalog_lines import read_prefixed  # noqa: PLC0415

    return read_prefixed(("codex_helpers.row.",))


def row_text(check: HelperCheck) -> Optional[str]:
    if not check.failing:
        return None
    key = K.ROW_KEYS[check.verdict]
    try:
        template = _row_lines()[key]
    except (KeyError, OSError, ValueError) as exc:
        logger.error("codex_helpers_row_text_missing", key=key, error=str(exc))
        return key
    return template.format(**params_for(check))
