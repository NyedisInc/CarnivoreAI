
from __future__ import annotations

import mimetypes
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import structlog

from src.core import config_files
from src.core.open_files.content import project_path_for
from src.core.open_files.open_list import OpenFile
from src.core.open_files.session_folder import SessionNotFound

logger = structlog.get_logger(__name__)

DEFAULT_MEDIA_TYPE = "application/octet-stream"

CHUNK_BYTES = 256 * 1024


class DownloadUnavailable(LookupError):
    pass


class DownloadSessionGone(DownloadUnavailable):
    pass


class DownloadUnreadable(OSError):
    pass


@dataclass(frozen=True)
class DownloadTarget:

    fd: int
    size: int
    filename: str
    media_type: str

    def chunks(self) -> Iterator[bytes]:
        try:
            while True:
                piece = os.read(self.fd, CHUNK_BYTES)
                if not piece:
                    return
                yield piece
        finally:
            os.close(self.fd)

    def close(self) -> None:
        os.close(self.fd)


def media_type_for(name: str) -> str:
    guessed, _encoding = mimetypes.guess_type(name, strict=False)
    return guessed or DEFAULT_MEDIA_TYPE


def _open_regular(path: Path) -> tuple[int, int]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise DownloadUnavailable("the file is no longer there") from exc
    except OSError as exc:
        if exc.errno == getattr(os, "ELOOP", None):
            raise DownloadUnavailable("the file is a link, which a download does not follow") from exc
        logger.warning("open_files_download_unreadable", path=str(path), error=str(exc))
        raise DownloadUnreadable(f"could not read the file: {exc.strerror or exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DownloadUnavailable("not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd, info.st_size


def resolve(db_path: Path, row: OpenFile) -> DownloadTarget:
    try:
        project_path = project_path_for(db_path, row.session_uuid, row.root)
    except SessionNotFound as exc:
        raise DownloadSessionGone("the session this file was opened from is gone") from exc
    try:
        path, _root = config_files.resolve_row_path(row.root, row.path, project_path, pinned_absolute=row.root == "absolute",
                                                    trusted_root=row.scope_root)
    except config_files.ConfigFileError as exc:
        logger.info("open_files_download_refused", file_id=row.id, root=row.root, error=str(exc))
        raise DownloadUnavailable(str(exc)) from exc
    fd, size = _open_regular(path)
    return DownloadTarget(fd=fd, size=size, filename=path.name, media_type=media_type_for(path.name))


_UNSAFE_FALLBACK = re.compile(r'[^\x20-\x7e]|["\\]')


def attachment_headers(filename: str, size: int) -> dict[str, str]:
    fallback = _UNSAFE_FALLBACK.sub("_", filename) or "download"
    return {
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}",
        "Content-Length": str(size),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
