
from __future__ import annotations

import hashlib
import os
import stat
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import structlog

from src.core.skills.digest import digest_directory

logger = structlog.get_logger()

DIGEST_ALGORITHM = "sha256"
"""Named once. The stored record carries only the hex, so a future second
algorithm would need its own field rather than a prefix nobody parses."""

MAX_EFFECTS_BYTES = 4 * 1024 * 1024
"""A theme effects module is a few kilobytes of animation code. Four
megabytes is a ceiling rather than a target: it stops a pathological file
turning a manifest scan into a long read, and a file over it answers
``None``, which REFUSES rather than silently running something the digest
never covered."""

MAX_THEME_FOLDER_BYTES = 16 * 1024 * 1024
MAX_THEME_FOLDER_FILES = 512
"""The bounds on the FOLDER the grant is now keyed to. A theme is a
manifest, a stylesheet, a script and a handful of images; these are
ceilings rather than targets. A folder over either one answers ``None``,
which the ladder reads as unverifiable and REFUSES, because the
alternative is a scan whose cost an untrusted folder gets to choose."""


_file_cache: Dict[str, Tuple[Tuple[int, int, int, int], Optional[str]]] = {}


def digest_file(path: Path) -> Optional[str]:
    try:
        info = os.stat(path)
    except OSError:
        return _compute_file_digest(path)
    key = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
    with _folder_cache_lock:
        hit = _file_cache.get(str(path))
    if hit is not None and hit[0] == key:
        return hit[1]
    value = _compute_file_digest(path)
    with _folder_cache_lock:
        _file_cache[str(path)] = (key, value)
    return value


def _compute_file_digest(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("theme_effects_digest_stat_failed", path=str(path), error=str(exc))
        return None

    if size > MAX_EFFECTS_BYTES:
        logger.warning(
            "theme_effects_digest_too_large",
            path=str(path),
            size=size,
            limit=MAX_EFFECTS_BYTES,
        )
        return None

    hasher = hashlib.new(DIGEST_ALGORITHM)
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
    except OSError as exc:
        logger.warning("theme_effects_digest_read_failed", path=str(path), error=str(exc))
        return None
    return hasher.hexdigest()


FolderSignature = Tuple[Tuple[str, int, int, int, int, int], ...]
"""One entry per file or directory under a theme folder: (relpath, mode, size, mtime_ns, ctime_ns, inode)."""

_folder_cache: Dict[str, Tuple[FolderSignature, Optional[str]]] = {}
_folder_cache_lock = threading.Lock()


def folder_signature(theme_dir: Path) -> FolderSignature:
    root = str(theme_dir)
    rows = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames) + filenames:
            full = os.path.join(dirpath, name)
            info = os.lstat(full)
            rows.append(
                (os.path.relpath(full, root), info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
            )
    return tuple(sorted(rows))


def invalidate(theme_dir: Optional[Path] = None) -> None:
    with _folder_cache_lock:
        if theme_dir is None:
            _folder_cache.clear()
            _file_cache.clear()
        else:
            _folder_cache.pop(str(theme_dir), None)
            prefix = str(theme_dir) + os.sep
            for cached in [k for k in _file_cache if k.startswith(prefix)]:
                del _file_cache[cached]


def digest_theme_folder(theme_dir: Path) -> Optional[str]:
    key = str(theme_dir)
    try:
        signature = folder_signature(theme_dir)
    except OSError as exc:
        logger.warning("theme_folder_digest_read_failed", theme_dir=key, error=str(exc))
        invalidate(theme_dir)
        return None
    with _folder_cache_lock:
        hit = _folder_cache.get(key)
    if hit is not None and hit[0] == signature:
        return hit[1]
    value = _compute_theme_folder_digest(theme_dir)
    with _folder_cache_lock:
        _folder_cache[key] = (signature, value)
    return value


def _compute_theme_folder_digest(theme_dir: Path) -> Optional[str]:
    try:
        files = 0
        total = 0
        for dirpath, _dirnames, filenames in os.walk(str(theme_dir), followlinks=False):
            for filename in filenames:
                info = os.lstat(os.path.join(dirpath, filename))
                if not stat.S_ISREG(info.st_mode):
                    continue
                files += 1
                total += info.st_size
                if files > MAX_THEME_FOLDER_FILES or total > MAX_THEME_FOLDER_BYTES:
                    logger.warning(
                        "theme_folder_digest_too_large",
                        theme_dir=str(theme_dir),
                        files=files,
                        bytes=total,
                        file_limit=MAX_THEME_FOLDER_FILES,
                        byte_limit=MAX_THEME_FOLDER_BYTES,
                    )
                    return None
        if files == 0:
            return None
        folder_digest, _entries = digest_directory(theme_dir)
    except OSError as exc:
        logger.warning(
            "theme_folder_digest_read_failed",
            theme_dir=str(theme_dir),
            error=str(exc),
        )
        return None
    return folder_digest


def digest_effects(theme_dir: Path, effects_filename: Optional[str]) -> Optional[str]:
    if not effects_filename or not isinstance(effects_filename, str):
        return None
    if "/" in effects_filename or "\\" in effects_filename or ".." in effects_filename:
        logger.warning(
            "theme_effects_digest_rejected_name",
            theme_dir=str(theme_dir),
            reason="the effects filename must be a bare name in the theme directory",
        )
        return None
    if digest_file(theme_dir / effects_filename) is None:
        return None
    return digest_theme_folder(theme_dir)
