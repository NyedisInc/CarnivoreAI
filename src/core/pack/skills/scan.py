
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from src.core.pack.skills import rules, secrets_gate
from src.core.skills.digest import CHUNK_BYTES, DigestEntry, digest_entries, mode_string
from src.core.skills.roots import symlinked_intermediate

logger = structlog.get_logger()


@dataclass(frozen=True)
class FileEntry:

    path: str
    size: int
    mode: str
    sha256: str


@dataclass(frozen=True)
class SkillScan:

    name: str
    files: tuple[FileEntry, ...] = ()
    digest: str = ""
    problem: Optional[str] = None


@dataclass(frozen=True)
class RootScan:

    root: Path
    healthy: bool
    why: Optional[str] = None
    skills: dict[str, SkillScan] = field(default_factory=dict)


def _read_and_hash(path: Path, size: int) -> tuple[str, Optional[bytes]]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    keep = bytearray() if size <= secrets_gate.SCAN_MAX_BYTES else None
    with os.fdopen(fd, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
            if keep is not None:
                keep += chunk
    return digest.hexdigest(), (bytes(keep) if keep is not None else None)


def _scan_skill(skill_dir: Path, name: str) -> SkillScan:
    files: list[FileEntry] = []
    total = 0
    stack: list[tuple[Path, str]] = [(skill_dir, "")]
    while stack:
        directory, prefix = stack.pop()
        with os.scandir(directory) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            rel = prefix + entry.name
            if entry.is_symlink():
                return SkillScan(name, problem=rules.REASON_LINK_INSIDE)
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                if entry.name not in rules.MACHINE_LOCAL_NAMES:
                    stack.append((Path(entry.path), rel + "/"))
                continue
            if not stat.S_ISREG(info.st_mode):
                return SkillScan(name, problem=f"special file inside: {rel}")
            if entry.name in rules.IGNORED_BASENAMES or rules.is_machine_local_file(entry.name):
                continue
            if info.st_nlink > 1:
                return SkillScan(name, problem=rules.REASON_HARD_LINK)
            bad = rules.path_problem(rel)
            if bad is not None:
                return SkillScan(name, problem=f"{bad}: {rel}")
            reason = secrets_gate.name_problem(rel)
            if reason is not None:
                return SkillScan(name, problem=reason)
            total += info.st_size
            if info.st_size > rules.MAX_FILE_BYTES or total > rules.MAX_SKILL_BYTES or len(files) >= rules.MAX_SKILL_FILES:
                return SkillScan(name, problem=rules.REASON_TOO_LARGE)
            sha, data = _read_and_hash(Path(entry.path), info.st_size)
            reason = secrets_gate.file_problem(rel, data)
            if reason is not None:
                return SkillScan(name, problem=reason)
            files.append(FileEntry(rel, info.st_size, mode_string(bool(info.st_mode & stat.S_IXUSR)), sha))
    clash = rules.collision(f.path for f in files)
    if clash is not None:
        return SkillScan(name, problem=clash)
    digest = digest_entries(DigestEntry(f.path, f.mode, f.sha256) for f in files)
    return SkillScan(name, tuple(sorted(files, key=lambda f: f.path)), digest)


def scan_skill(skill_dir: Path, name: str) -> SkillScan:
    return _scan_skill(skill_dir, name)


def scan_root(root: Path, family: str) -> RootScan:
    """Scan every valid skill folder directly under ``root``.

    Description: dot names, plain files and names failing :func:`rules.skill_name_problem` (``synced``, bundled skills)
      are skipped silently. A root that is a link, sits under a link, or raises OSError is not healthy. An absent root is
      healthy and empty: absence never deletes anywhere, so it can only make skills show as missing on alpha.
    Inputs: root (Path) - ``~/.claude/skills`` or ``~/.agents/skills``; family (str) - for the log only.
    Output: RootScan.
    Example: scan_root(Path.home() / ".claude" / "skills", "claude").skills["sme"].digest
    """
    if symlinked_intermediate(root) is not None or root.is_symlink():
        return RootScan(root, False, f"cannot read {root}")
    if not os.path.lexists(root):
        return RootScan(root, True)
    required = rules.required_skill_names()
    skills: dict[str, SkillScan] = {}
    try:
        with os.scandir(root) as it:
            children = sorted(it, key=lambda e: e.name)
        for child in children:
            name = rules.nfc(child.name)
            if child.name.startswith(".") or rules.skill_name_problem(name, required) is not None:
                continue
            if child.is_symlink():
                skills[name] = SkillScan(name, problem=rules.REASON_LINK_INSIDE)
            elif child.is_dir(follow_symlinks=False):
                skills[name] = _scan_skill(Path(child.path), name)
    except OSError as exc:
        logger.warning("pack_skills_scan_unreadable", family=family, errno=exc.errno)
        return RootScan(root, False, f"cannot read {root}")
    clashes: dict[str, list[str]] = {}
    for name in skills:
        clashes.setdefault(rules.fold_key(name), []).append(name)
    for names in clashes.values():
        if len(names) > 1:
            for name in names:
                skills[name] = SkillScan(name, problem="name differs only by case")
    return RootScan(root, True, skills=skills)
