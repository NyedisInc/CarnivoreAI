
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional

from src.core.project_directory import canonical_path, resolve_project_directory
from src.core.project_move.icloud import in_icloud
from src.core.project_move.paths import is_within

HARD_VERDICT_CODES = frozenset({"outside_allowed_roots", "cannot_determine"})


def canonical_new_root(raw: str) -> Optional[str]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return canonical_path(raw.strip())
    except (OSError, ValueError):
        return None


def missing_ancestors(folder: str) -> List[str]:
    missing: List[str] = []
    parent = os.path.dirname(folder)
    while parent and parent != os.path.dirname(parent) and not os.path.lexists(parent):
        missing.append(parent)
        parent = os.path.dirname(parent)
    return list(reversed(missing))


def nearest_existing(folder: str) -> str:
    missing = missing_ancestors(folder)
    return os.path.dirname(missing[0]) if missing else os.path.dirname(folder)


def _folder_moving_checks(plan: Any, old: str, new: str) -> None:
    old_ok = os.path.isdir(old)
    plan.check("old_folder_exists", old_ok, f"{old} exists" if old_ok else f"{old} is not a folder on this Mac")
    free = not os.path.lexists(new)
    plan.check("new_folder_absent", free, f"{new} does not exist yet" if free
               else f"{new} already exists; the move creates it, so it must not be there yet")
    missing = missing_ancestors(new)
    anchor = nearest_existing(new)
    anchor_ok = os.path.isdir(anchor)
    if not anchor_ok:
        plan.check("new_parent_exists", False, f"{anchor} is not a folder, so nothing can go inside it")
    elif missing and plan.create_parents:
        plan.folders_to_create = missing
        plan.check("new_parent_exists", True, f"will create {', '.join(missing)} first (create_parents)")
    elif missing:
        plan.check("new_parent_exists", False,
                   f"the new folder goes inside {missing[-1]}, which does not exist yet "
                   f"(missing: {', '.join(missing)}); create it first, or pass create_parents true "
                   f"to create {'it' if len(missing) == 1 else 'them'} with the move")
    else:
        plan.check("new_parent_exists", True, f"{os.path.dirname(new)} exists")
    same = False
    try:
        if old_ok and anchor_ok:
            same = os.stat(old).st_dev == os.stat(anchor).st_dev
    except OSError as exc:
        plan.warnings.append(f"could not compare volumes: {exc}")
    plan.check("same_filesystem", same, "both folders are on one volume" if same
               else "the new folder is on another volume (or could not be measured); move it by hand")
    old_cloud, new_cloud = in_icloud(old), in_icloud(anchor)
    side = {True: "inside iCloud Drive", False: "outside iCloud Drive"}
    plan.check("same_icloud_side", old_cloud == new_cloud, f"both folders are {side[old_cloud]}"
               if old_cloud == new_cloud else
               f"the old folder is {side[old_cloud]} and the new one {side[new_cloud]}: moving across that line "
               "downloads every cloud-only file first; move it in Finder, then re-point with move_folder false")


def _repoint_checks(plan: Any, old: str, new: str) -> None:
    if plan.create_parents:
        plan.warnings.append("create_parents does nothing without move_folder: the folder must already be there")
    exists = os.path.isdir(new)
    plan.check("new_folder_exists", exists, f"{new} is a folder" if exists
               else f"{new} is not a folder yet; move it there first or set move_folder")
    try:
        if os.path.isdir(old) and any(Path(old).iterdir()):
            plan.warnings.append(f"the old folder {old} still exists and is not empty")
    except OSError as exc:
        plan.warnings.append(f"the old folder {old} could not be read: {exc}")


def new_root_checks(plan: Any, new_root_raw: str, settings: Any) -> Optional[str]:
    old = plan.old_root
    new = canonical_new_root(new_root_raw)
    if new is None:
        plan.check("new_root_valid", False, "type the new folder: an absolute path or one starting with ~")
        return None
    verdict = resolve_project_directory(new_root_raw.strip(), settings)
    allowed = verdict.code not in HARD_VERDICT_CODES
    plan.check("new_root_valid", allowed, f"the new folder is {new}" if allowed else verdict.message)
    plan.check("new_root_differs", new != old, "new folder differs from the current one"
               if new != old else "the new folder is the project's current folder")
    inside = is_within(new, old)
    plan.check("new_root_outside_old", not inside, "new folder is outside the current one"
               if not inside else "the new folder is inside the current one")
    if plan.move_folder:
        _folder_moving_checks(plan, old, new)
    else:
        _repoint_checks(plan, old, new)
    return new
