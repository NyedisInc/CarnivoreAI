
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict, Iterable, List

import structlog

from src.cplugs.host import state as owner_state
from src.cplugs.sdk.manifest import Manifest

logger = structlog.get_logger()

LEGACY_IDS: Dict[str, str] = {"mark-unread": "unread", "share-read-only": "share"}


def import_disabled_plugins(state_dir: Path, disabled_ids: Iterable[object], manifests: Dict[str, Manifest]) -> List[str]:
    written: List[str] = []
    for legacy in disabled_ids:
        target = LEGACY_IDS.get(legacy) if isinstance(legacy, str) else None
        manifest = manifests.get(target) if target else None
        if manifest is None or owner_state.get(state_dir, manifest).stored:
            continue
        try:
            owner_state.update(state_dir, manifest, None, lambda st: replace(st, enabled=False))
        except owner_state.StateWriteFailed as exc:
            logger.warning("cplug_disabled_import_failed", cplug=target, error=str(exc)[:200])
            continue
        written.append(target)
    if written:
        logger.info("cplug_disabled_plugins_imported", cplugs=written)
    return written
