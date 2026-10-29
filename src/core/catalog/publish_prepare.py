
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core import message_model_secrets
from src.core.catalog import grade_lint, submission_preview
from src.core.catalog import submission_rules as rules


@dataclass
class Prepared:

    name: str
    version: str
    members: List[Tuple[str, bytes]] = field(default_factory=list)
    total_bytes: int = 0
    refusals: List[rules.Refusal] = field(default_factory=list)
    lint: Dict[str, Any] = field(default_factory=dict)
    compatibility: Optional[str] = None
    digest: str = ""
    kind: str = "skill"


def _read_member(folder: Path, relpath: str, limit: int = rules.MAX_FILE_BYTES) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    parts = relpath.split("/")
    fds: List[int] = [os.open(folder, os.O_RDONLY | os.O_DIRECTORY)]
    try:
        for part in parts[:-1]:
            fds.append(
                os.open(part, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=fds[-1])
            )
        fd = os.open(parts[-1], os.O_RDONLY | nofollow | os.O_NONBLOCK, dir_fd=fds[-1])
    finally:
        for opened in fds:
            os.close(opened)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(limit + 1)


def _hidden(relpath: str) -> bool:
    return any(part.startswith(".") for part in relpath.split("/"))


def digest_of(name: str, version: str, members: List[Tuple[str, bytes]]) -> str:
    sha = hashlib.sha256()
    for part in (name, version):
        sha.update(part.encode("utf-8"))
        sha.update(b"\0")
    for path, content in sorted(members):
        sha.update(path.encode("utf-8"))
        sha.update(b"\0")
        sha.update(str(len(content)).encode("ascii"))
        sha.update(b"\0")
        sha.update(content)
    return sha.hexdigest()


def _read_members(
    folder: Path, files: List[Tuple[str, int]], prepared: Prepared
) -> None:
    for relpath, _size in files:
        if _hidden(relpath):
            prepared.refusals.append(
                rules.Refusal(
                    rules.SUBMISSION_INVALID,
                    "hidden files and folders (.git, .env and other dotfiles) "
                    "are never sent; remove it",
                    relpath,
                )
            )
            continue
        try:
            content = _read_member(folder, relpath)
        except OSError as exc:
            prepared.refusals.append(
                rules.Refusal(
                    rules.SUBMISSION_INVALID,
                    f"this file could not be read: {exc.strerror or exc}",
                    relpath,
                )
            )
            continue
        detectors = sorted(
            {
                finding.detector
                for finding in message_model_secrets.scan_text(
                    content.decode("utf-8", errors="replace")
                )
            }
        )
        if detectors:
            prepared.refusals.append(
                rules.Refusal(
                    rules.SUBMISSION_INVALID,
                    "this file looks like it holds a credential "
                    f"({', '.join(detectors)}); remove it before publishing",
                    relpath,
                )
            )
        prepared.members.append((relpath, content))
        prepared.total_bytes += len(content)


def prepare(folder_path: str, version: str) -> Prepared:
    preview = submission_preview.preview_folder(folder_path)
    folder = Path(os.path.realpath(folder_path))
    prepared = Prepared(
        name=preview.name, version=version, refusals=list(preview.refusals)
    )
    over_cap = (
        len(preview.files) > rules.MAX_MEMBERS
        or preview.total_bytes > rules.MAX_SUBMISSION_BYTES
    )
    if not over_cap:
        _read_members(folder, preview.files, prepared)
    prepared.members.sort()
    if submission_preview._read_manifest(folder) is not None:
        manifest = grade_lint.read_manifest(folder)
        prepared.lint = grade_lint.grade_skill(folder, manifest).to_index()
        compat = manifest.get("compatibility")
        if isinstance(compat, str) and compat.strip():
            prepared.compatibility = compat.strip()[:500]
    prepared.digest = digest_of(prepared.name, version, prepared.members)
    return prepared
