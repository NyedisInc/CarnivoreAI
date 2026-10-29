
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Dict, Tuple

from src.core.skill_manager.scan import MAX_SKILL_MD_BYTES
from src.core.skill_manager.types import OverrideError
from src.core.skills.roots import unsafe_name_reason


def resolve_skill_md(location: Dict[str, Any], root: Dict[str, Any]) -> Tuple[str, os.stat_result]:
    folder = location["folder"]
    if unsafe_name_reason(folder) is not None:
        raise OverrideError(409, "target_unsafe", "the folder name is not safe to read")
    root_path = root["path"]
    if root["is_symlink"] or not os.path.isdir(root_path):
        raise OverrideError(409, "target_unsafe", "the skills folder is a link or is missing")
    entry = Path(root_path) / folder
    real_entry = os.path.realpath(entry)
    if os.path.dirname(real_entry) != os.path.realpath(root_path):
        raise OverrideError(409, "target_unsafe", "the folder is outside its skills root")
    if not os.path.isdir(real_entry):
        raise OverrideError(404, "gone", "that skill folder is no longer there")
    skill_md = os.path.realpath(os.path.join(real_entry, "SKILL.md"))
    if os.path.dirname(skill_md) != real_entry:
        raise OverrideError(409, "target_unsafe", "SKILL.md resolves outside its folder")
    try:
        info = os.stat(skill_md)
    except OSError:
        raise OverrideError(409, "no_skill_md", "this folder has no readable SKILL.md")
    if not stat.S_ISREG(info.st_mode):
        raise OverrideError(409, "no_skill_md", "SKILL.md is not a regular file")
    return skill_md, info


def read_location_skill_md_hashed(location: Dict[str, Any], root: Dict[str, Any]) -> Tuple[str, bool, int, str]:
    skill_md, info = resolve_skill_md(location, root)
    with open(skill_md, "rb") as handle:
        raw = handle.read(MAX_SKILL_MD_BYTES + 1)
    truncated = len(raw) > MAX_SKILL_MD_BYTES
    text = raw[:MAX_SKILL_MD_BYTES].decode("utf-8", errors="replace")
    return text, truncated, info.st_size, hashlib.sha256(raw).hexdigest()


def read_location_skill_md(location: Dict[str, Any], root: Dict[str, Any]) -> Tuple[str, bool, int]:
    return read_location_skill_md_hashed(location, root)[:3]
