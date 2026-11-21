
from __future__ import annotations

from typing import Tuple

from fastapi import HTTPException, UploadFile
from starlette.datastructures import UploadFile as FormFile

from src.api.capped_reads import read_capped_upload
from src.api.uploads import ALLOWED_EXTENSIONS, extension_of, sanitize_filename, validate_upload
from src.config import settings


def is_image_name(safe_name: str) -> bool:
    return extension_of(safe_name) in ALLOWED_EXTENSIONS


async def read_validated_upload(file: UploadFile) -> Tuple[bytes, str]:
    cfg = settings.load_auth_config().uploads
    data = await read_capped_upload(file, max(cfg.max_size_mb, cfg.max_file_size_mb) * 1024 * 1024)
    return validate_upload(data, file.filename or "", cfg.max_size_mb, cfg.max_file_size_mb)


class UploadRefused(ValueError):
    pass


def caps() -> Tuple[int, int]:
    cfg = settings.load_auth_config().uploads
    return cfg.max_size_mb * 1024 * 1024, cfg.max_file_size_mb * 1024 * 1024


def safe_name(declared: str) -> str:
    return sanitize_filename(declared)


def check_bytes(data: bytes, declared_name: str) -> Tuple[bytes, str]:
    cfg = settings.load_auth_config().uploads
    try:
        return validate_upload(data, declared_name, cfg.max_size_mb, cfg.max_file_size_mb)
    except HTTPException as exc:
        raise UploadRefused(str(exc.detail)) from exc


def is_form_file(value: object) -> bool:
    return isinstance(value, FormFile)
