
from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from src.config import settings

MAX_BYTES: Dict[str, int] = {"image": 10 * 2**20, "video": 50 * 2**20, "file": 25 * 2**20}
MAX_POSTER_BYTES = 2**20
KEEP_SECONDS = 7 * 24 * 3600
TOTAL_MAX_BYTES = 500 * 2**20
ID_RE = re.compile(r"[0-9a-f]{32}")
_MIME_RE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,60}/[a-z0-9][a-z0-9.+-]{0,60}")


@dataclass(frozen=True)
class MediaEntry:

    media_id: str
    mime: str
    size: int
    path: Path
    poster: Optional[Path]


def media_dir() -> Path:
    root = Path(settings.get_state_dir()) / "notify-media"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def _put(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def write(kind: str, data: bytes, mime: str, *, poster: Optional[bytes] = None) -> MediaEntry:
    if kind not in MAX_BYTES or not _MIME_RE.fullmatch(mime):
        raise ValueError("unknown kind or mime")
    if not data or len(data) > MAX_BYTES[kind] or (poster is not None and len(poster) > MAX_POSTER_BYTES):
        raise ValueError("attachment is empty or larger than its cap")
    media_id = secrets.token_hex(16)
    root = media_dir()
    _put(root / f"{media_id}.bin", data)
    if poster is not None:
        _put(root / f"{media_id}.poster.png", poster)
    _put(root / f"{media_id}.json", json.dumps({"mime": mime, "bytes": len(data)}).encode())
    return entry(media_id)  # type: ignore[return-value]


def entry(media_id: str) -> Optional[MediaEntry]:
    if not ID_RE.fullmatch(media_id or ""):
        return None
    root = media_dir()
    try:
        meta = json.loads((root / f"{media_id}.json").read_text())
        mime, size = str(meta["mime"]), int(meta["bytes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    data, poster = root / f"{media_id}.bin", root / f"{media_id}.poster.png"
    return MediaEntry(media_id, mime, size, data, poster if poster.exists() else None) if data.exists() else None


def prune(now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    files = []
    for path in media_dir().iterdir():
        try:
            info = path.stat()
        except OSError:
            continue
        files.append((info.st_mtime, info.st_size, path))
    removed, total = 0, sum(size for _, size, _ in files)
    for mtime, size, path in sorted(files, key=lambda item: item[0]):
        if mtime >= now - KEEP_SECONDS and total <= TOTAL_MAX_BYTES:
            break
        try:
            path.unlink()
            removed += 1
            total -= size
        except OSError:
            continue
    return removed
