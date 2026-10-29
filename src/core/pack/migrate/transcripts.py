
from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.claude_project_dirs import path_spellings
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.project_move.claude_side import files_under, transcript_roots

logger = structlog.get_logger()

MAX_TRANSCRIPT_BYTES = 4 * 1024 ** 3


class TranscriptError(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(path: str, limit: int) -> str:
    digest, left = hashlib.sha256(), limit
    with open(path, "rb") as handle:
        while left > 0:
            block = handle.read(min(1 << 20, left))
            if not block:
                break
            digest.update(block)
            left -= len(block)
    return digest.hexdigest()


def _longer_copy(have: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    short, long_ = (have, other) if have["size"] <= other["size"] else (other, have)
    if short["size"] == long_["size"]:
        return have
    if _digest(short["path"], short["size"]) != _digest(long_["path"], short["size"]):
        logger.warning("pack_migrate_transcript_duplicate_dropped", rel_len=len(have["rel"]))
        return have
    return long_


def source_files(root: str, roots: Optional[Iterable[Path]] = None, prefer_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    bases = list(roots) if roots is not None else list(transcript_roots())
    if prefer_root is not None:
        bases = [Path(prefer_root)] + [b for b in bases if os.path.realpath(b) != os.path.realpath(prefer_root)]
    for base in bases:
        for name in dict.fromkeys(slugify_project_dir(s) for s in path_spellings(root)):
            folder = Path(base) / name
            if not folder.is_dir():
                continue
            for rel in files_under(folder):
                path = folder / rel
                if path.is_symlink() or not path.is_file():
                    continue
                entry = {"rel": rel, "path": str(path), "size": path.stat().st_size}
                found[rel] = _longer_copy(found[rel], entry) if rel in found else entry
    files = [found[k] for k in sorted(found)]
    if sum(f["size"] for f in files) > MAX_TRANSCRIPT_BYTES:
        raise TranscriptError("too_large", "the project's conversation files are too large to carry")
    for entry in files:
        entry["sha256"] = _sha256(Path(entry["path"]))
    return files


def build_archive(files: List[Dict[str, Any]], dest: str) -> int:
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out, tarfile.open(fileobj=out, mode="w:gz") as tar:
        for entry in files:
            tar.add(entry["path"], arcname=entry["rel"], recursive=False)
    return os.path.getsize(dest)


def target_folder(target_root: str, projects_root: Optional[Path] = None) -> Path:
    base = Path(projects_root) if projects_root is not None else transcript_roots()[0]
    return base / slugify_project_dir(target_root)


def _compare(tar: tarfile.TarFile, member: tarfile.TarInfo, existing: Path) -> str:
    have = existing.stat().st_size
    if have > member.size:
        return "clash"
    theirs, handle, left = hashlib.sha256(), tar.extractfile(member), have
    while left:
        block = handle.read(min(1 << 20, left))
        if not block:
            return "clash"
        theirs.update(block)
        left -= len(block)
    if theirs.hexdigest() != _sha256(existing):
        return "clash"
    return "same" if have == member.size else "prefix"


def _backup_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.premigrate")


def restore_replaced(folder: Path, rels: Iterable[str]) -> None:
    for rel in rels:
        backup = _backup_path(folder / rel)
        if backup.is_file():
            os.replace(backup, folder / rel)


def drop_backups(folder: Path, rels: Iterable[str]) -> None:
    for rel in rels:
        _backup_path(folder / rel).unlink(missing_ok=True)


def unpack(archive: str, target_root: str, projects_root: Optional[Path] = None) -> Tuple[List[str], List[str], List[str]]:
    dest = target_folder(target_root, projects_root)
    with tarfile.open(archive, mode="r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts:
                raise TranscriptError("unsafe_archive", "the conversation archive names a path outside its folder")
        verdicts: Dict[str, str] = {}
        clashes = []
        for m in members:
            existing = dest / m.name
            if existing.is_file():
                verdicts[m.name] = "clash" if existing.is_symlink() else _compare(tar, m, existing)
                if verdicts[m.name] == "clash":
                    clashes.append(m.name)
        if clashes:
            raise TranscriptError("transcript_clash", f"{len(clashes)} conversation file(s) already here hold different content; merge them by hand first")
        written: List[str] = []
        same: List[str] = []
        replaced: List[str] = []
        for m in members:
            existing = dest / m.name
            if verdicts.get(m.name) == "same":
                same.append(m.name)
                continue
            existing.parent.mkdir(parents=True, exist_ok=True)
            temp = existing.with_name(f".{existing.name}.migrating")
            with open(temp, "wb") as out:
                handle = tar.extractfile(m)
                for block in iter(lambda: handle.read(1 << 20), b""):
                    out.write(block)
            if verdicts.get(m.name) == "prefix":
                shutil.copyfile(existing, _backup_path(existing))
                replaced.append(m.name)
            else:
                written.append(m.name)
            os.replace(temp, existing)
    return written, same, replaced


def verify(files: List[Dict[str, Any]], target_root: str, projects_root: Optional[Path] = None) -> List[str]:
    dest = target_folder(target_root, projects_root)
    return [f["rel"] for f in files if not (dest / f["rel"]).is_file() or _sha256(dest / f["rel"]) != f["sha256"]]
