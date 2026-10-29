
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core.backup_health import checks
from src.core.backup_health import constants as K
from src.core.backup_health import vault_check

logger = structlog.get_logger()


def _tm_misses(state_dir: Path, verdict: checks.Verdict) -> int:
    """Update and return the consecutive-unknown Time Machine count (OK resets it, FIRING resets it, BUSY leaves it at 0).

    Inputs: state_dir; verdict (the Time Machine verdict). Output: int, the count after this pass. The count lives in a
    small JSON file in the state directory; an unreadable file counts as 0 and a write failure is logged, so the worst
    case is one extra pass before the alert, never a false alert.
    """
    from src.core.json_artifact import atomic_write_json

    path = Path(state_dir) / K.TM_MISS_STATE_FILE
    try:
        previous = int(json.loads(path.read_text(encoding="utf-8")).get("misses", 0))
    except FileNotFoundError:
        previous = 0
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("backup_health_tm_misses_unreadable", error_type=type(exc).__name__)
        previous = 0
    misses = previous + 1 if verdict.state == checks.UNKNOWN else 0
    if misses != previous:
        atomic_write_json(path, {"misses": misses}, log_event="backup_health_tm_misses_write_failed")
    return misses


def _apply(verdict: checks.Verdict, db_path: Path, misses: int = 0) -> str:
    from src.core.app_alerts import constants as AK
    from src.core.app_alerts import service as alerts

    raises = verdict.state == checks.FIRING or (
        verdict.state == checks.UNKNOWN and verdict.key == K.KEY_TIME_MACHINE and misses >= K.TM_UNKNOWN_PASSES_TO_ALERT)
    if raises:
        alerts.raise_alert(verdict.key, source=K.ALERT_SOURCE, severity=verdict.severity or AK.SEV_WARN,
                           title_key=verdict.title_key, detail_key=verdict.detail_key, params=verdict.params, db_path=db_path)
        return "raised"
    if verdict.state == checks.OK:
        alerts.resolve(verdict.key, db_path=db_path)
        return "resolved"
    return "kept"


def run_checks(state_dir: Path, db_path: Path, *, now: Optional[float] = None,
               tmutil: Optional[checks.TmutilRunner] = None, volume: Optional[Path] = None,
               tm_status: Optional[checks.TmutilRunner] = None) -> Dict[str, str]:
    stamp = time.time() if now is None else now
    verdicts: List[checks.Verdict] = []
    usb = checks.check_usb_backup(stamp, volume)
    if usb is not None:
        verdicts.append(usb)
    else:
        from src.core.app_alerts import service as alerts

        alerts.resolve(K.KEY_USB, db_path=db_path)
    tm_verdict = checks.check_time_machine(stamp, tmutil, status=tm_status)
    verdicts.append(tm_verdict)
    verdicts.extend(vault_check.check_vault(state_dir, stamp))
    outcome = {verdict.key: _apply(verdict, db_path, _tm_misses(state_dir, tm_verdict) if verdict is tm_verdict else 0)
               for verdict in verdicts}
    logger.info("backup_health_pass", checked=len(outcome), raised=sorted(k for k, v in outcome.items() if v == "raised"))
    return outcome
