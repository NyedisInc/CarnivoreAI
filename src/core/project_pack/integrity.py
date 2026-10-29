"""
TWO COSTS, NEVER CONFUSED. :func:`cheap_check` is two ``lstat`` calls (the listing runs it for every packed
project and never reads a byte). :func:`full_check` streams the whole file through sha256 and runs only on an
unpack, or when a caller asks for it explicitly. A cheap ``modified`` is a WARNING, not a verdict: a copy or an
iCloud sync can change the mtime and leave the bytes identical, which only the full check can tell.

Statuses: ``ok``, ``missing`` (archive or sidecar gone), ``modified`` (size or mtime differs, or on a full
check the sha256 differs; modified and replaced outside Carnivore are not told apart), ``unreadable``,
``cloud_only`` (not downloaded; reading it would download it, so it is not read).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.project_move.icloud import SF_DATALESS
from src.core.project_pack import constants as K
from src.core.project_pack.inventory import sha256_file

OK, MISSING, MODIFIED, UNREADABLE, CLOUD_ONLY = "ok", "missing", "modified", "unreadable", "cloud_only"


@dataclass(frozen=True)
class IntegrityResult:

    status: str
    message: str = ""
    full: bool = False

    @property
    def ok(self) -> bool:
        return self.status == OK

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "message": self.message, "full": self.full}


def archive_path(root: str, row: Dict[str, Any]) -> str:
    return os.path.join(root, row.get("archive_name") or "")


def _stat_problem(root: str, row: Dict[str, Any]) -> Optional[IntegrityResult]:
    if not row.get("archive_name"):
        return IntegrityResult(MISSING, "no archive is recorded for this project")
    for name, what in ((row["archive_name"], "archive"), (K.MANIFEST_NAME, "manifest")):
        try:
            st = os.lstat(os.path.join(root, name))
        except FileNotFoundError:
            return IntegrityResult(MISSING, f"the {what} {name} is missing: it was removed or renamed outside Carnivore")
        except OSError as exc:
            return IntegrityResult(UNREADABLE, f"the {what} cannot be read: {exc}")
        if getattr(st, "st_flags", 0) & SF_DATALESS:
            return IntegrityResult(CLOUD_ONLY, f"the {what} is in iCloud only; download it in Finder first")
    return None


def cheap_check(root: str, row: Dict[str, Any]) -> IntegrityResult:
    problem = _stat_problem(root, row)
    if problem:
        return problem
    st = os.lstat(archive_path(root, row))
    if row.get("archive_bytes") is not None and st.st_size != row["archive_bytes"]:
        return IntegrityResult(MODIFIED, f"the archive is {st.st_size} bytes, Carnivore wrote {row['archive_bytes']}: "
                                         "it was modified or replaced outside Carnivore")
    if row.get("archive_mtime_ns") is not None and st.st_mtime_ns != row["archive_mtime_ns"]:
        return IntegrityResult(MODIFIED, "the archive's modified time changed since Carnivore wrote it; "
                                         "unpacking will compare its checksum")
    return IntegrityResult(OK)


def full_check(root: str, row: Dict[str, Any], expected_sha256: Optional[str] = None) -> IntegrityResult:
    problem = _stat_problem(root, row)
    if problem:
        return problem
    try:
        digest = sha256_file(archive_path(root, row))
    except OSError as exc:
        return IntegrityResult(UNREADABLE, f"the archive cannot be read: {exc}")
    if digest != row.get("archive_sha256") or (expected_sha256 and digest != expected_sha256):
        return IntegrityResult(MODIFIED, "the archive's checksum does not match the one Carnivore stored when it "
                                         "packed: it was modified or replaced outside Carnivore", full=True)
    return IntegrityResult(OK, full=True)
