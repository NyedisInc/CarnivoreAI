
from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional

import structlog

from src.core.automations.store import AutomationStore

logger = structlog.get_logger()

KILL_GRACE_S = 5.0


def _lstart(pid: int) -> Optional[str]:
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("automation_orphan_ps_failed", error_type=type(exc).__name__)
        return None
    return out.stdout.strip() or None


def describe_child(pid: int) -> Optional[Dict[str, Any]]:
    started = _lstart(pid)
    return {"pid": pid, "pgid": pid, "started_lstart": started} if started else None


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


def stop_orphan(child: Dict[str, Any]) -> str:
    pid, pgid, started = child.get("pid"), child.get("pgid"), child.get("started_lstart")
    if not (isinstance(pid, int) and isinstance(pgid, int)) or pgid <= 1 or pgid == os.getpgrp() or not started:
        logger.warning("automation_orphan_left", reason="record_unusable")
        return "left"
    seen = _lstart(pid)
    if seen is None:
        return "gone"
    if seen != started:
        logger.warning("automation_orphan_left", reason="start_instant_mismatch", pid=pid)
        return "left"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    deadline = time.monotonic() + KILL_GRACE_S
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _group_alive(pgid):
        os.killpg(pgid, signal.SIGKILL)
    logger.info("automation_orphan_stopped", pid=pid, pgid=pgid)
    return "stopped"


def reconcile_boot(store: AutomationStore, boot_id: str) -> List[Dict[str, Any]]:
    failed = store.reconcile_boot(boot_id)
    for run in failed:
        if run.get("child"):
            stop_orphan(run["child"])
    if failed:
        logger.info("automation_boot_reconciled", interrupted=len(failed))
    return failed
