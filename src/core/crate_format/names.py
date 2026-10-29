
from __future__ import annotations

import re
from typing import Optional

from src.core.crate_format.constants import (
    M_ENTRIES, M_EXTRACT, M_FILES, M_MAGIC, M_MANIFEST, M_PATHS, M_PROJECT_PATCH, M_README, M_RECONCILE, M_SCHEMA,
    M_SECRETS,
)
from src.core.crate_format.errors import UnsafeName

KIND_FIXED: str = "fixed"
KIND_ROWS: str = "rows"
KIND_LINES: str = "lines"
KIND_BLOB: str = "blob"
KIND_UNKNOWN: str = "unknown"

FIXED_NAMES = frozenset((M_MAGIC, M_README, M_EXTRACT, M_MANIFEST, M_FILES, M_PATHS, M_ENTRIES, M_SECRETS, M_RECONCILE,
                         M_SCHEMA))
ADDED_FIXED_NAMES = frozenset((M_PROJECT_PATCH,))
_ROWS = re.compile(r"rows/[a-z0-9._-]{1,40}/[A-Za-z0-9_]{1,64}(\.[0-9]{4})?\.jsonl")
_LINES = re.compile(r"lines/(claude-history|codex-session-index)-[0-9]{1,3}\.jsonl")
_BLOB = re.compile(r"blobs/([0-9a-f]{2})/([0-9a-f]{64})\.(zst|xz)")
_GENERIC = re.compile(r"[a-z][a-z0-9_-]{0,31}(/[A-Za-z0-9._-]{1,100}){0,4}")
_TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def member_kind(name: str) -> Optional[str]:
    if name in FIXED_NAMES or name in ADDED_FIXED_NAMES:
        return KIND_FIXED
    if _ROWS.fullmatch(name):
        return KIND_ROWS if ".." not in name else None
    if _LINES.fullmatch(name):
        return KIND_LINES
    blob = _BLOB.fullmatch(name)
    if blob:
        return KIND_BLOB if blob.group(1) == blob.group(2)[:2] else None
    if _GENERIC.fullmatch(name) and not any(part in ("", ".", "..") for part in name.split("/")):
        return KIND_UNKNOWN
    return None


def check_member_name(name: str) -> str:
    kind = member_kind(name)
    if kind is None or kind == KIND_UNKNOWN:
        raise UnsafeName(f"member name {name!r} is outside the crate v1 grammar")
    return name


def check_rel(rel: str) -> str:
    if not isinstance(rel, str):
        raise UnsafeName("a relative path must be a string")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or "\x00" in rel or any(p in ("", ".", "..") for p in parts):
        raise UnsafeName(f"unsafe relative path {rel!r}")
    return rel


def check_token(value: str, what: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise UnsafeName(f"unsafe {what} {value!r}")
    return value


def file_name(bundle_id: str, encrypted: bool) -> str:
    return f"{bundle_id}.crate.age" if encrypted else f"{bundle_id}.crate"
