
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.save.offload.ledger import prev_path
from src.plugins.save.vault import health

logger = structlog.get_logger()

PURGE = "purge"
SCRUB = "scrub"
RESTORE = "restore"
LEDGER = "ledger"


def current(state_dir: Path, name: str) -> Dict[str, Any]:
    part = (health.read(Path(state_dir)).get("offload_alerts") or {}).get(name)
    return part if isinstance(part, dict) else {}


def record(state_dir: Path, name: str, *, blobs: Iterable[str], conversations: Iterable[str] = (), now: float) -> bool:
    alerts = dict(health.read(Path(state_dir)).get("offload_alerts") or {})
    before = alerts.get(name) if isinstance(alerts.get(name), dict) else None
    found_blobs: List[str] = sorted(set(blobs))[: C.ALERT_BLOBS_MAX]
    found_convs: List[str] = sorted(set(conversations))
    was_active = bool(before and (before.get("blobs") or before.get("conversations")))
    seq = int((before or {}).get("seq") or 0)
    is_active = bool(found_blobs or found_convs)
    if is_active and before is not None and (not was_active or not set(found_blobs) <= set(before.get("blobs") or []) or not set(found_convs) <= set(before.get("conversations") or [])):
        seq += 1
    part: Dict[str, Any] = {"seq": seq, "blobs": found_blobs, "conversations": found_convs, "at": now}
    if before is not None and {k: v for k, v in before.items() if k != "at"} == {k: v for k, v in part.items() if k != "at"}:
        return False
    if before is None and not is_active:
        return False
    alerts[name] = part
    health.update(Path(state_dir), offload_alerts=alerts)
    if is_active:
        logger.warning("offload_alert_recorded", kind=name, blobs=len(found_blobs), conversations=len(found_convs), script=C.REPAIR_SCRIPT)
    return True


def record_ledger(state_dir: Path, ledger_path: Path, *, readable: bool, now: float) -> bool:
    prev = prev_path(ledger_path)
    named = (str(ledger_path), str(prev)) if prev.exists() else (str(ledger_path),)
    return record(state_dir, LEDGER, blobs=(), conversations=() if readable else named, now=now)
