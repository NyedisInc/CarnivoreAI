
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional, Sequence

import structlog

from src.core.pack.skills import rules
from src.core.pack.skills.bundle import BundleError, build_bundle
from src.core.pack.skills.scan import scan_skill
from src.core.pack.skills.targets import SkillRoot, roots_for
from src.core.pack.transport import blobs
from src.core.skills.records import SIDECAR_NAME

logger = structlog.get_logger()

MAX_EXPORT_BYTES = rules.MAX_SKILL_BYTES + 4 * 1024 * 1024
PURGE_SECONDS = 3600.0
MAX_FOLDER_BYTES = 4 * MAX_EXPORT_BYTES
CHUNK_BYTES = blobs.CHUNK_BYTES


class ExportError(Exception):

    def __init__(self, code: str, status: int = 422, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.status, self.detail = code, status, detail


def _path(directory: Path, blob_id: str) -> Path:
    if not blobs.valid_id(blob_id):
        raise ExportError("bad_blob", 400)
    return directory / f"{blob_id}.tgz"


def purge(directory: Path, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    try:
        for entry in os.scandir(directory):
            if entry.is_symlink() or now - entry.stat(follow_symlinks=False).st_mtime <= PURGE_SECONDS:
                continue
            if entry.name.endswith(".tgz") and entry.is_file(follow_symlinks=False):
                os.unlink(entry.path)
            elif entry.name.startswith("take-") and entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
    except OSError:
        pass


def _folder_bytes(directory: Path) -> int:
    try:
        return sum(e.stat(follow_symlinks=False).st_size for e in os.scandir(directory) if e.name.endswith(".tgz"))
    except OSError:
        return 0


def remove(directory: Path, blob_id: str) -> None:
    try:
        os.unlink(_path(directory, blob_id))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("pack_skills_export_remove_failed", errno=exc.errno)


def make_export(roots: Sequence[SkillRoot], family: str, name: str, directory: Path) -> dict[str, Any]:
    if family not in rules.FAMILIES or rules.skill_name_problem(name) is not None or rules.nfc(name) != name:
        raise ExportError("bad_skill")
    found = next((r for r in roots_for(roots, family) if not r.problem and os.path.lexists(r.leaf / name)), None)
    if found is None:
        raise ExportError("not_found", 404)
    folder = found.leaf / name
    if folder.is_symlink():
        raise ExportError("skill_is_link")
    if os.path.lexists(folder / SIDECAR_NAME):
        raise ExportError("catalog_skill")
    try:
        scan = scan_skill(folder, name)
    except OSError as exc:
        raise ExportError("skill_held", detail=f"unreadable ({exc.errno})") from None
    if scan.problem is not None:
        raise ExportError("skill_held", detail=scan.problem)
    purge(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    blob_id = blobs.new_id()
    out = _path(directory, blob_id)
    try:
        build_bundle(out, [(family, name, folder, scan.files)])
    except (OSError, BundleError) as exc:
        remove(directory, blob_id)
        raise ExportError("skill_held", detail=f"changed while bundling ({type(exc).__name__})") from None
    size = out.stat().st_size
    if size > MAX_EXPORT_BYTES:
        remove(directory, blob_id)
        raise ExportError("too_large", 413)
    if _folder_bytes(directory) > MAX_FOLDER_BYTES:
        remove(directory, blob_id)
        raise ExportError("export_busy", 429, "other exports are still waiting to be read; try again soon")
    return {"blob_id": blob_id, "size": size, "sha256": blobs.file_sha256(str(out)), "digest": scan.digest}


def read_chunk(directory: Path, blob_id: str, offset: int) -> dict[str, Any]:
    path = _path(directory, blob_id)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ExportError("not_found", 404) from None
    with os.fdopen(fd, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        if offset < 0 or offset > size:
            raise ExportError("not_found", 404)
        handle.seek(offset)
        data = handle.read(min(CHUNK_BYTES, size - offset))
    return {"offset": offset, "data": base64.b64encode(data).decode("ascii"), "sha256": hashlib.sha256(data).hexdigest(),
            "eof": offset + len(data) >= size}
