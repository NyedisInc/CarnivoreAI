
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

from src.cplugs.reviewboard.schema import Revision, Sidecar

logger = structlog.get_logger()

EXT_ID = "scratch"
EXT_VERSION = 1
FILES_DIR = "files"
GITIGNORE = ".gitignore"
GITIGNORE_TEXT = b"*\n"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MEMBER = re.compile(r"files/r([0-9]{3,4})/(" + NAME.pattern + r")")
_REFERENCE = re.compile(rb"(?<=[\"'(\s=,])(?:\./)?files/([A-Za-z0-9][A-Za-z0-9._-]{0,127})(?=[\"')\s,>]|$)")
OPAQUE = "application/octet-stream"


def is_scratch(sidecar: Sidecar) -> bool:
    return EXT_ID in sidecar.ext


def rel_path(n: int, name: str) -> str:
    return f"{FILES_DIR}/r{n:03d}/{name}"


def manifest(rev: Revision) -> List[Dict[str, Any]]:
    block = rev.ext.get(EXT_ID)
    files = (block.model_extra or {}).get("files") if block is not None else None
    out: List[Dict[str, Any]] = []
    for entry in files if isinstance(files, list) else []:
        if (isinstance(entry, dict) and isinstance(entry.get("name"), str) and NAME.fullmatch(entry["name"])
                and isinstance(entry.get("file"), str) and MEMBER.fullmatch(entry["file"]) and isinstance(entry.get("sha256"), str)
                and isinstance(entry.get("bytes"), int) and not isinstance(entry.get("bytes"), bool)):
            out.append({"name": entry["name"], "file": entry["file"], "sha256": entry["sha256"], "bytes": entry["bytes"],
                        "image": bool(entry.get("image"))})
    return out


def named_files(sidecar: Sidecar) -> Set[str]:
    return {e["file"] for rev in sidecar.revisions for e in manifest(rev)}


def member(folder: Path, rel: str) -> Optional[Path]:
    """The stored file at ``rel`` inside the board folder, or None. Description: ``rel`` must be ``files/r<nnn>/<name>``, and ``files``,
      the revision folder and the file must each be real (a folder, a folder, a regular file; never a symlink).
    Inputs: folder (the board folder); rel. Output: Path | None.
    """
    if not MEMBER.fullmatch(rel):
        return None
    path = folder
    for i, part in enumerate(rel.split("/")):
        path = path / part
        try:
            mode = path.lstat().st_mode
        except OSError:
            return None
        if not (stat.S_ISREG(mode) if i == 2 else stat.S_ISDIR(mode)):
            return None
    return path


def check_folder(folder: Path, sidecar: Sidecar, add: Callable[[str, str, str], None]) -> Set[str]:
    if not is_scratch(sidecar):
        return set()
    for rev in sidecar.revisions:
        for entry in manifest(rev):
            path = member(folder, entry["file"])
            if path is None or path.lstat().st_size != entry["bytes"]:
                add("error", "missing_file", f"{rev.id} scratch file {entry['file']} is missing, or is not the file recorded")
    return {FILES_DIR}


def _data_uri(entry: Dict[str, Any], data: bytes) -> bytes:
    kind = (mimetypes.guess_type(entry["name"])[0] or OPAQUE) if entry["image"] else OPAQUE
    if not kind.startswith("image/"):
        kind = OPAQUE
    return f"data:{kind};base64,".encode("ascii") + base64.b64encode(data)


def _load(folder: Path, entry: Dict[str, Any]) -> Optional[bytes]:
    path = member(folder, entry["file"])
    try:
        data = path.read_bytes() if path is not None else None
    except OSError as exc:
        logger.warning("reviewboard_scratch_file_unreadable", file=entry["file"], error=type(exc).__name__)
        return None
    if data is None or len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        logger.warning("reviewboard_scratch_file_changed", file=entry["file"])
        return None
    return data


def resolve(page: bytes, folder: Path, rev: Revision) -> bytes:
    entries = {e["name"]: e for e in manifest(rev)}
    if not entries:
        return page
    cache: Dict[str, Optional[bytes]] = {}

    def swap(match: "re.Match[bytes]") -> bytes:
        name = match.group(1).decode("ascii")
        entry = entries.get(name)
        if entry is None:
            return match.group(0)
        if name not in cache:
            data = _load(folder, entry)
            cache[name] = _data_uri(entry, data) if data is not None else None
        return cache[name] or match.group(0)

    return _REFERENCE.sub(swap, page)
