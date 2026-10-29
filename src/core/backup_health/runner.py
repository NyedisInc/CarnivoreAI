
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core.backup_health import checks
from src.core.backup_health import constants as K
from src.core.backup_health import vault_check

logger = structlog.get_logger()


def _apply(verdict: checks.Verdict, db_path: Path) -> str:
    from src.core.app_alerts import constants as AK
    from src.core.app_alerts import service as alerts

    if verdict.state == checks.FIRING:
        alerts.raise_alert(verdict.key, source=K.ALERT_SOURCE, severity=verdict.severity or AK.SEV_WARN,
                           title_key=verdict.title_key, detail_key=verdict.detail_key, params=verdict.params, db_path=db_path)
        return "raised"
    if verdict.state == checks.OK:
        alerts.resolve(verdict.key, db_path=db_path)
        return "resolved"
    return "kept"


def run_checks(state_dir: Path, db_path: Path, *, now: Optional[float] = None,
               volume: Optional[Path] = None) -> Dict[str, str]:
    stamp = time.time() if now is None else now
    verdicts: List[checks.Verdict] = []
    usb = checks.check_usb_backup(stamp, volume)
    if usb is not None:
        verdicts.append(usb)
    else:
        from src.core.app_alerts import service as alerts

        alerts.resolve(K.KEY_USB, db_path=db_path)
    verdicts.extend(vault_check.check_vault(state_dir, stamp))
    outcome = {verdict.key: _apply(verdict, db_path) for verdict in verdicts}
    logger.info("backup_health_pass", checked=len(outcome), raised=sorted(k for k, v in outcome.items() if v == "raised"))
    return outcome
