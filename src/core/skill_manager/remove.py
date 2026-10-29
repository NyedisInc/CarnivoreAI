
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from src.core.live_install_roots import TRASH_DIR_NAME
from src.core.skill_manager.types import OverrideError, SCOPE_PLUGIN, SCOPE_SYSTEM
from src.core.skills.roots import unsafe_name_reason
from src.core.skills.targets import TrashFolderIsLink, move_to_trash


def remove_location(location: Dict[str, Any], root: Dict[str, Any], stamp: str) -> str:
    if root["read_only"] or root["scope"] in (SCOPE_PLUGIN, SCOPE_SYSTEM):
        raise OverrideError(409, "read_only", "plugin and Codex system skills are read only")
    managed = location.get("managed") or {}
    if managed.get("source") == "ledger":
        raise OverrideError(
            409, "use_catalog_uninstall", "this skill is catalog-managed; uninstall it from the catalog"
        )
    folder = location["folder"]
    if unsafe_name_reason(folder) is not None:
        raise OverrideError(409, "target_unsafe", "the folder name is not safe to act on")
    if root["is_symlink"] or not os.path.isdir(root["path"]):
        raise OverrideError(409, "target_unsafe", "the skills folder is a link or is missing")
    entry = Path(root["path"]) / folder
    if os.path.realpath(entry.parent) != root["path"]:
        raise OverrideError(409, "target_unsafe", "the folder is outside its skills root")
    if not os.path.lexists(entry):
        raise OverrideError(404, "gone", "that skill folder is no longer there")
    if not entry.is_symlink() and not entry.is_dir():
        raise OverrideError(409, "not_a_skill_folder", "that entry is not a folder")
    trash = entry.parent.parent / TRASH_DIR_NAME
    if trash.is_symlink():
        raise OverrideError(409, "target_unsafe", "the trash folder is a link")
    try:
        return str(move_to_trash(entry, trash, stamp))
    except TrashFolderIsLink:
        raise OverrideError(409, "target_unsafe", "the trash folder is a link")
    except FileExistsError:
        raise OverrideError(409, "trash_name_taken", "the trash already holds one moved this second; retry")
