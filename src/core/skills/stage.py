
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import structlog

from src.core.skills import kinds
from src.core.skills.digest import CHUNK_BYTES, digest_directory, mode_string
from src.core.skills.manifest_rules import check_manifest
from src.core.skills.validate import (
    ARCHIVE_INVALID,
    ArchiveRefused,
    Limits,
    ValidatedArchive,
    ValidatedMember,
    open_capped_tar,
    validate_archive,
)

logger = structlog.get_logger()

FILE_MODE = 0o644
EXEC_FILE_MODE = 0o755
DIR_MODE = 0o700

EXEC_MODE_STRING = mode_string(True)


@dataclass(frozen=True)
class StagedSkill:

    path: Path
    digest: str
    archive: ValidatedArchive


def _target_path(dest: Path, relpath: str) -> Path:
    target = Path(os.path.normpath(os.path.join(str(dest), relpath)))
    if os.path.commonpath([str(dest), str(target)]) != str(dest) or target == dest:
        raise ArchiveRefused(
            ARCHIVE_INVALID, f"member path escapes the staging directory: {relpath!r}"
        )
    return target


def _ensure_parents(dest: Path, target: Path) -> None:
    parent = target.parent
    missing: list[Path] = []
    while parent != dest and dest in parent.parents:
        if parent.is_dir():
            break
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=DIR_MODE, exist_ok=True)
        os.chmod(directory, DIR_MODE)


def member_mode(expected: ValidatedMember, *, allow_scripts: bool) -> int:
    if allow_scripts and expected.mode == EXEC_MODE_STRING:
        return EXEC_FILE_MODE
    return FILE_MODE


def executable_members(archive: ValidatedArchive) -> tuple[str, ...]:
    return tuple(
        member.relpath
        for member in archive.members
        if member.mode == EXEC_MODE_STRING
    )


def _write_member(
    source: IO[bytes],
    target: Path,
    expected: ValidatedMember,
    *,
    limits: Limits,
    allow_scripts: bool,
) -> int:
    written = 0
    with open(target, "xb") as handle:
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > expected.size or written > limits.max_bytes:
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"member body grew between passes: {expected.relpath!r}",
                )
            handle.write(chunk)
    if written != expected.size:
        raise ArchiveRefused(
            ARCHIVE_INVALID, f"member body shrank between passes: {expected.relpath!r}"
        )
    os.chmod(target, member_mode(expected, allow_scripts=allow_scripts))
    return written


def stage_archive(
    archive_path: Path,
    dest: Path,
    *,
    publisher: str,
    name: str,
    kind: str = kinds.KIND_SKILL,
    limits: Limits = Limits(),
    allow_scripts: bool = False,
    src_path: str | None = None,
) -> StagedSkill:
    logger.debug(
        "skill_archive_python_advisory",
        python=".".join(str(part) for part in sys.version_info[:3]),
    )
    dest = Path(os.path.abspath(str(dest)))
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"staging directory already exists: {dest}")

    archive = validate_archive(
        archive_path,
        publisher=publisher,
        name=name,
        kind=kind,
        limits=limits,
        allow_scripts=allow_scripts,
        src_path=src_path,
    )
    wanted = {member.relpath: member for member in archive.members}

    dest.mkdir(mode=DIR_MODE, parents=True)
    os.chmod(dest, DIR_MODE)
    try:
        written_bytes = 0
        written_files = 0
        with open_capped_tar(
            archive_path, max_archive_bytes=limits.max_archive_bytes
        ) as tar:
            for member in tar:
                if not member.isreg() or not member.name.startswith(archive.skill_root):
                    continue
                relpath = member.name[len(archive.skill_root) :]
                expected = wanted.get(relpath)
                if expected is None:
                    continue
                target = _target_path(dest, relpath)
                try:
                    _ensure_parents(dest, target)
                    source = tar.extractfile(member)
                    if source is None:
                        raise ArchiveRefused(
                            ARCHIVE_INVALID, f"member has no readable body: {relpath!r}"
                        )
                    with source:
                        written_bytes += _write_member(
                            source,
                            target,
                            expected,
                            limits=limits,
                            allow_scripts=allow_scripts,
                        )
                except FileExistsError as exc:
                    raise ArchiveRefused(
                        ARCHIVE_INVALID,
                        f"two approved members collide on one path: {relpath!r}",
                    ) from exc
                written_files += 1

        if written_files != len(wanted):
            raise ArchiveRefused(
                ARCHIVE_INVALID,
                f"archive changed between passes: wrote {written_files} of "
                f"{len(wanted)} approved members",
            )

        staged_digest, _entries = digest_directory(dest)
        if staged_digest != archive.digest:
            raise ArchiveRefused(
                ARCHIVE_INVALID,
                "staged copy does not match the validated digest",
            )

        manifest_refusal = check_manifest(kind, dest, expected_id=name)
        if manifest_refusal is not None:
            raise ArchiveRefused(ARCHIVE_INVALID, manifest_refusal)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    logger.info(
        "skill_archive_staged",
        dest=str(dest),
        members=written_files,
        bytes=written_bytes,
        digest=staged_digest,
        scripts=len(archive.script_members),
    )
    return StagedSkill(path=dest, digest=staged_digest, archive=archive)
