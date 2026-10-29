
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import structlog
from fastapi import HTTPException

from src.core.pack.skills.targets import SkillRoot
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.core.skills.records import read_sidecar
from src.core.skills.targets import move_to_trash

logger = structlog.get_logger()
REMOVED, GONE, KEPT = "removed", "gone", "kept"


def remove_mirror(row: Mapping[str, Any], root: SkillRoot, target: Path, group_stamp: str) -> str:
    if not target.exists():
        return GONE
    record = read_sidecar(target)
    if record is None or f"{record.publisher}/{record.name}" != row.get("item") or record.version != row.get("version"):
        return KEPT
    move_to_trash(target, root.trash, group_stamp)
    return REMOVED


def remove_install(row: Mapping[str, Any], services: Any) -> str:
    from src.api.catalog_installed_support import uninstall_with
    from src.core.skill_watch.measure import TooLarge
    from src.core.skill_watch.sentinel import measure_folder

    if services is None:
        return KEPT
    with services.catalog.ledger() as ledger:
        found: Optional[Any] = next((r for r in ledger.list() if r.scope == SCOPE_GLOBAL and r.item_id == row.get("item")), None)
        targets = ledger.targets(found.install_id) if found is not None else ()
    if found is None:
        return GONE
    if found.version != row.get("version"):
        return KEPT
    try:
        if any(measure_folder(Path(t.path))[0] != found.digest for t in targets):
            return KEPT
        uninstall_with(services, found.install_id)
    except (TooLarge, OSError, HTTPException) as exc:
        logger.warning("pack_skills_trash_placed_install_kept", error_type=type(exc).__name__)
        return KEPT
    return REMOVED
