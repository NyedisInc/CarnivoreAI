
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.skill_manager.skill_extensions import parse_extension
from src.core.skill_manager.types import SkillRoot
from src.core.skills.roots import unsafe_name_reason
from src.core.slash_command_discovery_scan import describe_text, read_skill_frontmatter

logger = structlog.get_logger()

MAX_SKILL_MD_BYTES = 64 * 1024

MEMO_LIMIT = 4096

SILENT_DOT_FOLDERS = frozenset({".system", ".carnivore-trash"})


@dataclass(frozen=True)
class ScannedSkill:

    folder: str
    name: str
    path: str
    description: str
    is_symlink: bool
    link_target: Optional[str]
    frontmatter_keys: Tuple[str, ...]
    extends: Optional[str] = None
    guide_rev: Optional[int] = None


@dataclass(frozen=True)
class SkippedFolder:

    root_key: str
    folder: str
    reason: str


_Parsed = Tuple[str, str, Tuple[str, ...], Optional[str], Optional[int]]

_MEMO: Dict[Tuple[str, int, int], _Parsed] = {}


def read_skill_md(skill_md: str, fallback_name: str) -> Optional[_Parsed]:
    try:
        info = os.stat(skill_md)
    except OSError:
        return None
    key = (skill_md, info.st_mtime_ns, info.st_size)
    hit = _MEMO.get(key)
    if hit is not None:
        return hit
    try:
        with open(skill_md, "rb") as handle:
            raw = handle.read(MAX_SKILL_MD_BYTES)
    except OSError as exc:
        logger.warning("skill_manager_skill_md_unreadable", path=skill_md, error=str(exc))
        return None
    text = raw.decode("utf-8", errors="replace")
    front = read_skill_frontmatter(text)
    declared = front.get("name")
    name = declared.strip() if isinstance(declared, str) and declared.strip() else fallback_name
    parsed = (name, describe_text(text, fallback_name), tuple(sorted(str(k) for k in front)), *parse_extension(front))
    if len(_MEMO) >= MEMO_LIMIT:
        _MEMO.clear()
    _MEMO[key] = parsed
    return parsed


def _skill_md_path(folder_path: str) -> Optional[str]:
    candidate = os.path.join(folder_path, "SKILL.md")
    if not os.path.lexists(candidate):
        return None
    if os.path.islink(candidate):
        base = os.path.realpath(folder_path)
        target = os.path.realpath(candidate)
        if os.path.commonpath([base, target]) != base:
            logger.warning("skill_manager_skill_md_escapes", path=candidate)
            return None
        return candidate
    return candidate if os.path.isfile(candidate) else None


def scan_root(root: SkillRoot) -> Tuple[List[ScannedSkill], List[SkippedFolder]]:
    skills: List[ScannedSkill] = []
    skipped: List[SkippedFolder] = []
    try:
        entries = sorted(os.scandir(root.path), key=lambda e: e.name)
    except OSError:
        return skills, skipped
    for entry in entries:
        name = entry.name
        if name in SILENT_DOT_FOLDERS:
            continue
        reason = unsafe_name_reason(name)
        if reason is not None:
            skipped.append(SkippedFolder(root.root_key, name, reason))
            continue
        if not entry.is_dir(follow_symlinks=True):
            continue
        skill_md = _skill_md_path(entry.path)
        if skill_md is None:
            continue
        parsed = read_skill_md(skill_md, name)
        if parsed is None:
            continue
        link = entry.is_symlink()
        skills.append(
            ScannedSkill(
                folder=name,
                name=parsed[0],
                path=entry.path,
                description=parsed[1],
                is_symlink=link,
                link_target=os.path.realpath(entry.path) if link else None,
                frontmatter_keys=parsed[2],
                extends=parsed[3],
                guide_rev=parsed[4],
            )
        )
    return skills, skipped
