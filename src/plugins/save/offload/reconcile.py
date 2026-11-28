
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

import structlog

from src.plugins.save.offload import constants as C, homes as homes_mod, push
from src.plugins.save.offload.ledger import Entry, Ledger
from src.plugins.save.offload.restore_chain import STATUS_ALREADY_PRESENT, STATUS_DISK_NEWER, classify
from src.plugins.save.vault import restore
from src.plugins.save.vault.manifest import FileEntry, ManifestError
from src.plugins.save.vault.store import Vault

logger = structlog.get_logger()

OUTCOME_OFFLOADED = "offloaded"
OUTCOME_DROPPED = "dropped"
OUTCOME_FAILED = "failed"

_BACK: frozenset = frozenset({STATUS_ALREADY_PRESENT, STATUS_DISK_NEWER})


def _undo_mix(files: List[FileEntry], destination: Callable[[FileEntry], Path], holding: Path) -> str:
    for file in files:
        held, dest = holding / file.home / file.rel, destination(file)
        if not held.is_file():
            continue
        if os.path.lexists(dest):
            return f"{dest} is taken, so the held copy could not go back"
        try:
            os.rename(held, dest)
        except OSError as exc:
            return f"{held.name} could not go back: {exc.strerror or exc}"
    return ""


def _settle_one(vault: Vault, ledger: Ledger, entry: Entry, homes: Dict[str, Path], folder: Optional[str]) -> str:
    point = vault.manifests.read(entry.unit, entry.point_id)
    holding = Path(entry.holding_dir)
    held = [f for f in point.files if entry.holding_dir and (holding / f.home / f.rel).is_file()]
    if entry.state == C.STATE_RESTORING:
        destination = homes_mod.point_destination(homes, point, folder)
        if held or not all(classify(f, destination(f)) in _BACK for f in point.files):
            ledger.update(entry.conversation_id, state=C.STATE_OFFLOADED, error="")
            return OUTCOME_OFFLOADED
        ledger.remove(entry.conversation_id)
        return OUTCOME_DROPPED
    destination = restore.homes_destination(homes)
    in_place = [f for f in point.files if os.path.lexists(destination(f))]
    if len(held) == len(point.files) and not in_place:
        ledger.update(entry.conversation_id, state=C.STATE_OFFLOADED, error="")
        return OUTCOME_OFFLOADED
    reason = _undo_mix(point.files, destination, holding) if held else ""
    if reason:
        ledger.update(entry.conversation_id, state=C.STATE_FAILED, error=reason[:300])
        return OUTCOME_FAILED
    ledger.remove(entry.conversation_id)
    return OUTCOME_DROPPED


@push.coalescing
def reconcile(vault: Vault, ledger: Ledger, homes: Dict[str, Path], folders: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    outcomes: Dict[str, str] = {}
    for entry in list(ledger.read().values()):
        if entry.state not in (C.STATE_OFFLOADING, C.STATE_RESTORING):
            continue
        try:
            outcomes[entry.conversation_id] = _settle_one(vault, ledger, entry, homes, (folders or {}).get(entry.conversation_id))
        except (ManifestError, restore.RestoreError, OSError) as exc:
            logger.error("offload_reconcile_failed", conversation_id=entry.conversation_id, error_type=type(exc).__name__, error=str(exc)[:200])
            ledger.update(entry.conversation_id, state=C.STATE_FAILED, error=f"could not settle after a restart: {str(exc)[:200]}")
            outcomes[entry.conversation_id] = OUTCOME_FAILED
    if outcomes:
        logger.info("offload_reconciled", outcomes=outcomes)
    return outcomes
