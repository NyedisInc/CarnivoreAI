from __future__ import annotations

import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

ROOT_NAME = "attachments"
ENV_VAR = "CARNIVORE_RUN_ATTACHMENTS_DIR"
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 20, 10 * 1024 * 1024, 50 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
FILE_KINDS = frozenset({"command", "agent"})


def wants(target: Dict[str, Any]) -> bool:
    kind = target.get("kind")
    if kind == "sequence":
        return any(wants(step) for step in target.get("steps") or ())
    return kind in FILE_KINDS


def folder_for(root: Path, run_id: str) -> Path:
    return Path(root) / run_id


def prepare(root: Path, run_id: str) -> Path:
    folder = folder_for(root, run_id)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    return folder


def _shown(name: str) -> str:
    return name.encode("unicode_escape").decode("ascii")[:128]


def _discard(path: str) -> None:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except OSError as exc:
        logger.warning("automation_attachment_discard_failed", error_type=type(exc).__name__)


def collect(folder: Path) -> Tuple[Optional[List[Dict[str, Any]]], List[Dict[str, str]]]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None, []
    kept: List[Dict[str, Any]] = []
    left: List[Dict[str, str]] = []
    total = 0
    for name in names:
        path = os.path.join(folder, name)
        reason: Optional[str] = None
        size = 0
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if not NAME_RE.match(name):
            reason = "bad_name"
        elif not os.path.stat.S_ISREG(info.st_mode):
            reason = "not_a_file"
        elif info.st_size > MAX_FILE_BYTES:
            reason = "too_large"
        elif len(kept) >= MAX_FILES:
            reason = "too_many"
        elif total + info.st_size > MAX_TOTAL_BYTES:
            reason = "total_too_large"
        else:
            size = info.st_size
        if reason is None:
            kept.append({"name": name, "bytes": size, "mime": mimetypes.guess_type(name)[0] or "application/octet-stream"})
            total += size
        else:
            left.append({"name": _shown(name), "reason": reason})
            _discard(path)
    if not kept:
        try:
            os.rmdir(folder)
        except OSError:
            pass
    return (kept or None), left


def resolve(root: Path, run_id: str, name: str) -> Optional[Path]:
    """The real path of a stored attachment, only when it is a regular file inside the run's folder. Blocking.

    Inputs: root; run_id; name (already looked up in the run's stored list). Output: Path | None.
    """
    folder = os.path.realpath(folder_for(root, run_id))
    real = os.path.realpath(os.path.join(folder, name))
    if os.path.dirname(real) != folder or not os.path.isfile(real):
        return None
    return Path(real)


def remove(root: Path, run_ids: Iterable[str]) -> None:
    for run_id in run_ids:
        shutil.rmtree(folder_for(root, run_id), ignore_errors=True)


def sweep(root: Path, existing: Iterable[str]) -> int:
    keep = set(existing)
    try:
        entries = [e for e in os.scandir(root) if e.is_dir(follow_symlinks=False) and e.name not in keep]
    except OSError:
        return 0
    for entry in entries:
        shutil.rmtree(entry.path, ignore_errors=True)
    return len(entries)
