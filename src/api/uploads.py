
import os
import re
import unicodedata
import uuid
from io import BytesIO
from pathlib import Path, PureWindowsPath
from typing import Tuple

import structlog
from fastapi import HTTPException
from src.api.error_response import api_error
from PIL import Image, UnidentifiedImageError

from src.core.product_identity import UPLOAD_DIR_NAME
from src.core.uploads.bucket_guard import BUCKET_GITIGNORE

logger = structlog.get_logger()

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "gif", "webp"})

MAX_BASENAME_LENGTH: int = 128

_SAFE_BASENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

_REPEATED_UNDERSCORE = re.compile(r"_{2,}")

_FALLBACK_BASENAME: str = "upload"

_EXT_TO_PIL_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "gif": "GIF",
    "webp": "WEBP",
}


def sanitize_filename(declared_filename: str) -> str:
    raw = (declared_filename or "").strip()

    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]
    raw = PureWindowsPath(raw).name or raw

    raw = unicodedata.normalize("NFKD", raw)
    raw = raw.encode("ascii", "ignore").decode("ascii")

    raw = "".join(ch for ch in raw if ch.isprintable())

    safe = _SAFE_BASENAME_CHARS.sub("_", raw)
    safe = _REPEATED_UNDERSCORE.sub("_", safe).strip("_")

    while safe.startswith(".") or safe.startswith("-"):
        safe = safe[1:]

    if not safe or safe in (".", ".."):
        return _FALLBACK_BASENAME

    if len(safe) > MAX_BASENAME_LENGTH:
        stem, dot, ext = safe.rpartition(".")
        if dot and len(ext) <= 16:
            keep = max(1, MAX_BASENAME_LENGTH - len(ext) - 1)
            safe = f"{stem[:keep]}.{ext}"
        else:
            safe = safe[:MAX_BASENAME_LENGTH]

    return safe


def extension_of(safe_basename: str) -> str:
    stem, dot, ext = safe_basename.rpartition(".")
    if not dot or not stem:
        return ""
    return ext.lower()


def validate_upload(
    data: bytes,
    declared_filename: str,
    max_image_size_mb: int,
    max_file_size_mb: int,
) -> Tuple[bytes, str]:
    safe_name = sanitize_filename(declared_filename)
    ext = extension_of(safe_name)

    if ext in ALLOWED_EXTENSIONS:
        validate_image(data, safe_name, max_image_size_mb)
        return data, safe_name

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file payload")

    max_bytes = max_file_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {max_file_size_mb} MB",
        )

    return data, safe_name


def _ensure_bucket_gitignore(upload_dir: Path) -> None:
    try:
        fd = os.open(upload_dir / BUCKET_GITIGNORE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, b"*\n")
    finally:
        os.close(fd)


def save_upload_to_session_dir(
    data: bytes, safe_basename: str, working_dir: str
) -> Path:
    try:
        base = Path(working_dir).expanduser().resolve()
        upload_dir = base / UPLOAD_DIR_NAME
        upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        upload_dir = upload_dir.resolve()
        _ensure_bucket_gitignore(upload_dir)
    except OSError as exc:
        logger.error(
            "upload_dir_create_failed", working_dir=working_dir, error=str(exc)
        )
        raise HTTPException(
            status_code=500, detail="Failed to prepare upload directory"
        ) from exc

    target = (upload_dir / f"{uuid.uuid4().hex[:8]}-{safe_basename}").resolve()
    try:
        target.relative_to(upload_dir)
    except ValueError:
        logger.error(
            "upload_path_escaped_bucket",
            target=str(target),
            upload_dir=str(upload_dir),
        )
        raise HTTPException(status_code=400, detail="Invalid upload filename")

    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        target.chmod(0o600)
    except FileExistsError as exc:
        logger.error("upload_target_exists", target=str(target))
        raise HTTPException(
            status_code=409, detail="Upload target already exists"
        ) from exc
    except OSError as exc:
        logger.error("upload_write_failed", target=str(target), error=str(exc))
        raise HTTPException(
            status_code=500, detail="Failed to write uploaded file"
        ) from exc

    return target


def validate_image(
    data: bytes, declared_filename: str, max_size_mb: int
) -> Tuple[bytes, str]:
    if not declared_filename or "." not in declared_filename:
        raise HTTPException(status_code=400, detail="Filename must include an extension")

    ext = declared_filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image extension '.{ext}'. Allowed: png, jpg, jpeg, gif, webp",
        )

    max_bytes = max_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Image exceeds maximum size of {max_size_mb} MB",
        )

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty image payload")

    expected_format = _EXT_TO_PIL_FORMAT[ext]
    try:
        with Image.open(BytesIO(data)) as img:
            actual_format = img.format
            img.verify()
    except (UnidentifiedImageError, Exception) as exc:
        raise api_error(400, "image_invalid", exc) from exc

    if actual_format != expected_format:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Image content does not match declared extension '.{ext}' "
                f"(detected {actual_format})"
            ),
        )

    return data, ext
