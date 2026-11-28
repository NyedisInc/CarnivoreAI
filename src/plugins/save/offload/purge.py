
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import structlog

from src.plugins.save.offload import alerts, chunk_check, push
from src.plugins.save.offload import constants as C
from src.plugins.save.offload.ledger import OPERATION, Entry, Ledger
from src.plugins.save.offload.verify import manifest_digest
from src.plugins.save.vault.manifest import Manifest, ManifestError
from src.plugins.save.vault.store import Vault
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()


@dataclass
class PurgeResult:

    purged: List[str] = field(default_factory=list)
    kept: Dict[str, List[str]] = field(default_factory=dict)
    not_due: int = 0
    busy: bool = False
    cancelled: bool = False
    switched_off: bool = False
    complete: bool = False


class HoldingOutsideRoot(RuntimeError):
    pass


def is_due(entry: Entry, now: float) -> bool:
    if entry.state != C.STATE_OFFLOADED or not entry.holding_dir or entry.purged_at is not None or entry.purge_after is None or entry.offloaded_at <= 0:
        return False
    return now >= max(entry.purge_after, entry.offloaded_at + C.HOLD_SECONDS)


def _inside(root: Path, folder: str) -> Path:
    resolved, base = Path(folder).resolve(), Path(root).resolve()
    if base not in resolved.parents:
        raise HoldingOutsideRoot(f"{folder} is not inside {root}")
    return resolved


def _own_folder(root: Path, entry: Entry) -> None:
    if _inside(root, entry.holding_dir) != Path(root).resolve() / entry.unit:
        raise HoldingOutsideRoot(f"{entry.holding_dir} is not the holding folder of {entry.unit}")


def delete_held(root: Path, folder: str) -> int:
    target = _inside(root, folder)
    removed = 0
    if not target.is_dir():
        return 0
    for current, dirs, files in os.walk(target, topdown=False, followlinks=False):
        for name in files:
            os.unlink(os.path.join(current, name))
            removed += 1
        for name in dirs:
            path = os.path.join(current, name)
            if os.path.islink(path):
                os.unlink(path)
            else:
                os.rmdir(path)
    os.rmdir(target)
    return removed


def _point_is_the_verified_one(entry: Entry, manifest: Manifest) -> bool:
    return bool(manifest.files) and len(manifest.files) == entry.files and manifest_digest(manifest) == entry.manifest_sha256


def _unverified_chunks(vault: Vault, entry: Entry, pace: Optional[Throttle]) -> Optional[List[str]]:
    conv = entry.conversation_id
    try:
        manifest = vault.manifests.read(entry.unit, entry.point_id)
    except ManifestError as exc:
        logger.error("offload_purge_manifest_unreadable", conversation_id=conv, error=str(exc)[:200])
        return None
    if not _point_is_the_verified_one(entry, manifest):
        logger.error("offload_purge_point_changed", conversation_id=conv, point_id=entry.point_id, files=len(manifest.files), expected_files=entry.files)
        return None
    return chunk_check.bad_chunks(vault.blobs, manifest, pace)


def _purge_one(vault: Vault, ledger: Ledger, entry: Entry, root: Path, now: float, pace: Optional[Throttle], allowed: Callable[[], bool], result: PurgeResult) -> bool:
    conv = entry.conversation_id
    try:
        _own_folder(root, entry)
    except HoldingOutsideRoot as exc:
        logger.error("offload_purge_outside_holding", conversation_id=conv, error=str(exc)[:200])
        result.kept[conv] = []
        return True
    bad = _unverified_chunks(vault, entry, pace)
    if bad is None or bad:
        if bad:
            logger.error("offload_purge_kept_unverified", conversation_id=conv, bad=len(bad), script=C.REPAIR_SCRIPT)
        result.kept[conv] = bad or []
        return True
    if not allowed():
        logger.info("offload_purge_switched_off", conversation_id=conv)
        result.switched_off = True
        return False
    try:
        removed = delete_held(root, entry.holding_dir)
    except HoldingOutsideRoot as exc:
        logger.error("offload_purge_outside_holding", conversation_id=conv, error=str(exc)[:200])
        result.kept[conv] = []
        return True
    except OSError as exc:
        logger.error("offload_purge_delete_failed", conversation_id=conv, error_type=type(exc).__name__, error=str(exc)[:200])
        return True
    ledger.update(conv, holding_dir="", purged_at=now)
    result.purged.append(conv)
    logger.info("offload_purged", conversation_id=conv, files=removed)
    return True


def _order(entries: List[Entry], now: float, kept_before: List[str]) -> List[str]:
    last = set(kept_before)
    due = [e for e in entries if is_due(e, now)]
    return [e.conversation_id for e in sorted(due, key=lambda e: (e.conversation_id in last, e.purge_after or 0.0, e.conversation_id))]


def _one_row(vault: Vault, ledger: Ledger, conv: str, holding_root: Path, now: float, pace: Optional[Throttle], allowed: Callable[[], bool], result: PurgeResult) -> bool:
    if not OPERATION.acquire(blocking=False):
        result.busy = True
        return False
    try:
        entry = ledger.get(conv)
        if entry is None or not is_due(entry, now):
            return True
        return _purge_one(vault, ledger, entry, holding_root, now, pace, allowed, result)
    finally:
        OPERATION.release()


@push.coalescing
def run_purge(vault: Vault, ledger: Ledger, holding_root: Path, *, now: float, pace: Optional[Throttle] = None, allowed: Callable[[], bool] = lambda: True) -> PurgeResult:
    result = PurgeResult()
    entries = list(ledger.read().values())
    result.not_due = sum(1 for e in entries if e.state == C.STATE_OFFLOADED and e.holding_dir and e.purged_at is None and not is_due(e, now))
    order = _order(entries, now, list(alerts.current(ledger.state_dir, alerts.PURGE).get("conversations") or []))
    for index, conv in enumerate(order):
        if index and pace is not None and pace.expired():
            return result
        if not allowed():
            result.switched_off = True
            return result
        try:
            if not _one_row(vault, ledger, conv, holding_root, now, pace, allowed, result):
                return result
        except chunk_check.CheckIncomplete:
            result.cancelled = True
            return result
    result.complete = True
    alerts.record(ledger.state_dir, alerts.PURGE, blobs=[b for bad in result.kept.values() for b in bad], conversations=result.kept, now=now)
    return result
