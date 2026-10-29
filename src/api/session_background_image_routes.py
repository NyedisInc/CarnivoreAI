"""Uploading, serving and removing one session's own background picture.

Three routes over one file per session. They sit beside
:mod:`src.api.session_background_routes`, which owns the same resource's
JSON half (which theme's picture to borrow, how dark the scrim is, whether
the picture is off here at all), and they are a separate module because
this half handles BYTES FROM A CLIENT and that is a different job with a
different set of rules.

**EVERY BYTE IS HOSTILE AND ONLY THE BYTES MAY DECIDE THE TYPE.** The
client's ``Content-Type`` and the filename it declares are read for the log
line and are used for NOTHING else. The type is sniffed out of the leading
bytes by :func:`src.core.terminal_background.sniff_image_extension`, and
the same sniffed extension is what the GET later derives its response type
from - so the byte that decided what was stored is the byte that decides
what it is served as. A PNG named ``.txt`` is stored as a PNG; a shell
script named ``.png`` is a 415.

**SVG IS REFUSED AND CANNOT BE ACCEPTED BY ACCIDENT.** It has no magic
number, so the sniffer has nothing to match and there is no table entry to
add one to. That is not an oversight: an SVG is a document that can carry
script, and this app's whole CSP argument rests on a picture not being able
to become a program.

**THE CAP IS APPLIED WHILE READING, NOT AFTER.** The body is consumed in
chunks and the request is refused the moment the accumulated size passes
``UploadsConfig.max_size_mb``, so nothing oversize is ever assembled into a
contiguous buffer and nothing oversize ever reaches the state directory.
The cap is the one the paste-an-image endpoint already uses, not a second
number that could drift from it.

**THE STORED NAME IS COMPOSED HERE, NEVER RECEIVED.** The file is
``<session name>.<sniffed ext>`` inside one directory, and the composed
name is run through :func:`src.core.terminal_background.safe_image_filename`
- the same allowlist a catalog theme's manifest is held to - before it
reaches a path join. A session name carrying anything outside that
allowlist is refused rather than rewritten.

**THE READ IS AUTHENTICATED, WHICH IS WHY THE CLIENT PAINTS A BLOB.** A
browser cannot put an ``Authorization`` header on a CSS ``url()``, so the
picture cannot be a plain url in a stylesheet without either dropping the
auth or inventing a token-in-the-query scheme that would then live in
history, logs and referrers. It does neither: the client fetches these
bytes with its ordinary authenticated fetch and paints the result through
an object url, which is same-origin, carries no credential and is revoked
when it is replaced. See ``client/js/terminal-background.js``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from src.api.auth import require_auth
from src.api.remote_route_guard import routed_remote
from src.api.session_background_routes import _entry_model, _store
from src.api.session_name_known import known_tmux_names, strip_adopted_prefix
from src.config import settings
from src.core import terminal_background
from src.core.hosts.remote_controls import image_file_stem
from src.core.terminal_background import UnsafeImageName
from src.core.unique_tmp_path import unique_tmp_path
from src.models import SessionBackgroundEntry

logger = structlog.get_logger()
router = APIRouter()

_CHUNK_BYTES = 64 * 1024


def _known_session(request: Request, session_name: str) -> str:
    session_manager = request.app.state.session_manager
    remote = routed_remote(session_manager, session_name)
    if remote is not None:
        return remote.key
    owned_tmux = request.app.state.services.owned_tmux
    name = strip_adopted_prefix(session_name)
    if name not in known_tmux_names(session_manager, owned_tmux):
        logger.info("session_background_image_404", session_name=name)
        raise HTTPException(status_code=404, detail=f"Unknown session {name!r}")
    return name


def _images_dir() -> Path:
    return settings.get_session_background_images_dir()


def _stored_path(name: str, image: Optional[str]) -> Optional[Path]:
    if not image:
        return None
    try:
        safe = terminal_background.safe_image_filename(image)
    except UnsafeImageName as exc:
        logger.warning(
            "session_background_image_stored_name_refused",
            session_name=name,
            reason=exc.reason,
        )
        return None
    return _images_dir() / safe


def _remove_other_extensions(name: str, keep: Optional[str]) -> None:
    directory = _images_dir()
    for ext in terminal_background.CONTENT_TYPES:
        candidate = directory / f"{image_file_stem(name)}.{ext}"
        if keep is not None and candidate.name == keep:
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "session_background_image_stale_unlink_failed",
                path=str(candidate),
                error=str(exc),
            )


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "image exceeds the maximum upload size of "
                    f"{max_bytes // (1024 * 1024)} MB"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _write_atomically(target: Path, data: bytes) -> None:
    """Put the bytes on disk so a reader never sees a partial file.

    Description: the sequence every durable write in this app uses -
      unique temp file in the same directory, fsync, ``os.replace`` - plus
      mode 0o600, because these are a user's own pictures sitting in a
      shared state directory and no other local account has any business
      reading them. ``os.replace`` is atomic within a filesystem, which is
      what makes a re-upload swap the file rather than briefly empty it.
    Inputs: target (Path). data (bytes).
    Output: None.
    Raises: HTTPException(500) when the directory or the file cannot be
      written.
    Example: _write_atomically(dir / "cloude_api.png", data)
    """
    tmp: Optional[Path] = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = unique_tmp_path(target)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(target))
    except OSError as exc:
        logger.error(
            "session_background_image_write_failed",
            target=str(target),
            error=str(exc),
        )
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(
            status_code=500, detail="could not store the background image"
        ) from exc


@router.put(
    "/sessions/{session_name}/background/image",
    response_model=SessionBackgroundEntry,
    dependencies=[Depends(require_auth)],
)
async def upload_session_background_image(
    request: Request, session_name: str, file: UploadFile
) -> SessionBackgroundEntry:
    """Store one session's own background picture.

    Multipart ``file``. The bytes decide the type: a buffer that is not a
    PNG, JPEG, GIF, WEBP or AVIF is a 415 whatever it was called, and a
    buffer past the configured image cap is a 413 refused while it is
    still being read. The stored file replaces whatever this session had
    before, including one of a different type.

    Inputs: session_name (str) - the bare tmux name, or ``adopted:<name>``.
      file (UploadFile).
    Output: SessionBackgroundEntry - the session's override, now naming
      the stored file.
    Raises: HTTPException 404 unknown session, 413 too large, 415 not a
      supported image, 400 a session name that cannot be a filename, 500
      a failed write.
    """
    name = _known_session(request, session_name)
    max_bytes = settings.load_auth_config().uploads.max_size_mb * 1024 * 1024
    data = await _read_capped(file, max_bytes)

    ext = terminal_background.sniff_image_extension(
        data[: terminal_background.SNIFF_LENGTH]
    )
    logger.info(
        "api_upload_session_background_image",
        session_name=name,
        size=len(data),
        sniffed=ext,
        declared_type=file.content_type,
        declared_name=file.filename,
    )
    if ext is None:
        raise HTTPException(
            status_code=415,
            detail=(
                "unsupported image type; png, jpeg, gif, webp and avif are "
                "accepted"
            ),
        )

    try:
        filename = terminal_background.safe_image_filename(f"{image_file_stem(name)}.{ext}")
    except UnsafeImageName as exc:
        logger.warning(
            "session_background_image_name_unusable",
            session_name=name,
            reason=exc.reason,
        )
        raise HTTPException(
            status_code=400,
            detail="this session's name cannot be used as a filename",
        ) from exc

    _write_atomically(_images_dir() / filename, data)
    _remove_other_extensions(name, keep=filename)
    entry = _store(request).set_image(name, filename)
    if entry is None:
        logger.error("session_background_image_not_recorded", session_name=name)
        raise HTTPException(
            status_code=500, detail="could not record the background image"
        )
    return _entry_model(entry)


@router.get(
    "/sessions/{session_name}/background/image",
    dependencies=[Depends(require_auth)],
)
async def get_session_background_image(
    request: Request, session_name: str
) -> Response:
    """Serve one session's stored background picture.

    The response type comes from the extension that was SNIFFED when the
    file was written, never from anything on this request. Not cached:
    the url never changes when the picture does, so a cached copy would
    show the previous upload.

    Inputs: session_name (str).
    Output: FileResponse - the bytes, typed from the stored extension.
    Raises: HTTPException 404 when the session is unknown, has no stored
      picture, or the recorded file is gone from disk.
    """
    name = _known_session(request, session_name)
    entry = _store(request).get(name) or {}
    path = _stored_path(name, entry.get("image"))
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="no stored background image")

    media_type = terminal_background.content_type_for_extension(path.suffix.lstrip("."))
    if media_type is None:
        logger.error(
            "session_background_image_untypable", session_name=name, path=str(path)
        )
        raise HTTPException(status_code=404, detail="no stored background image")

    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.delete(
    "/sessions/{session_name}/background/image",
    status_code=204,
    dependencies=[Depends(require_auth)],
)
async def delete_session_background_image(
    request: Request, session_name: str
) -> Response:
    """Remove one session's stored picture and clear the field.

    Inputs: session_name (str).
    Output: Response - 204, no body.
    Raises: HTTPException(404) when the session is unknown.
    """
    name = _known_session(request, session_name)
    store = _store(request)
    entry = store.get(name) or {}
    path = _stored_path(name, entry.get("image"))
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "session_background_image_unlink_failed",
                session_name=name,
                error=str(exc),
            )
    if entry.get("image"):
        store.set_image(name, None)
    logger.info("api_delete_session_background_image", session_name=name)
    return Response(status_code=204)
