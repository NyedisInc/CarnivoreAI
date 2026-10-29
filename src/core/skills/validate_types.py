
from __future__ import annotations

from dataclasses import dataclass


ARCHIVE_INVALID = "archive_invalid"
SCRIPTS_NOT_SUPPORTED = "scripts_not_supported"

SCRIPTS_DIR = "scripts"

EXCLUDED_SEGMENTS = frozenset({".git", "__MACOSX"})
EXCLUDED_BASENAMES = frozenset({".DS_Store"})
EXCLUDED_BASENAME_PREFIXES = ("._",)


@dataclass(frozen=True)
class Limits:

    max_members: int = 2000
    max_bytes: int = 10 * 1024 * 1024
    max_archive_bytes: int = 64 * 1024 * 1024


class ArchiveRefused(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ValidatedMember:

    relpath: str
    size: int
    mode: str
    sha256: str


@dataclass(frozen=True)
class ValidatedArchive:

    prefix: str
    skill_root: str
    members: tuple[ValidatedMember, ...]
    digest: str
    total_bytes: int
    script_members: tuple[str, ...] = ()
