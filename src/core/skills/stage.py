"""Write an approved skill archive to a fresh directory, member by member.

WHY THIS WRITES THE FILES ITSELF. ``tarfile``'s whole-archive helper and
its single-member twin both build the destination path out of the member
name, and the member name is the attacker's input. Every published tar
defect since 2001 lives in that one sentence. This module never calls
either of them: it takes the list :mod:`src.core.skills.validate` already
approved, joins each relative path to the destination itself, checks the
result is still inside the destination, and opens it with ``"xb"`` so an
existing file is a failure rather than an overwrite. A test reads this
file's source and fails the build if either helper's name reappears,
because the obvious "simplification" is to call one of them.

Python 3.12 does have the ``filter=`` hardening on those helpers, and this
package deliberately does not rely on it. The hardening is a property of
the interpreter the app happens to be running under, and the app's own
bootstrap accepts any 3.12.x; a guarantee that depends on which patch
release someone installed is not a guarantee. The interpreter version is
LOGGED as an advisory and gates nothing.

WHY 0o644 AND NEVER THE MEMBER'S MODE. The member's mode is a number the
publisher chose. Copying it is how an archive gets to decide that a file
on the user's disk is executable. So the mode written here is decided by
THIS MODULE, from two facts: whether the caller passed ``allow_scripts``,
which it does only while holding a recorded human consent for these exact
bytes, and whether the validator classified this member as executable.
``0o755`` is written for exactly the intersection and ``0o644`` for
everything else; ``member.mode`` is never the source, in either mode.
With ``allow_scripts`` off - the default, and every caller that does not
say otherwise - the validator has already refused every executable
member, so the exec branch is unreachable rather than merely unused.
Parent directories are 0o700 because nothing but this user needs to
traverse a staging directory.

WHY THE DIGEST IS RECOMPUTED FROM DISK AFTERWARDS. The validator read the
archive in one pass and this writer reads it in a second pass, so the two
passes could in principle see different bytes (a file swapped underneath
us between them). Re-hashing what actually landed closes that window and,
more usefully, it is the only check that covers the WRITER: if this module
ever truncated, mis-joined or mis-ordered a file, the digest of the staged
copy would stop matching the digest the publisher signed. Note that the
0o644 chmod cannot move the digest for a skill this version accepts,
for a skill installed without ``allow_scripts``, because the validator
refuses every executable member there, so every mode field on both sides
is ``100644``.

Example:
"""

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

# something else
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
    """Create the directories above a target, each owner-only.

    :param dest: the staging directory, which already exists.
    :param target: the file about to be written.
    :returns: None.

    Created one component at a time and chmodded explicitly, because the
    process umask masks the mode ``mkdir`` is given and the 0o700 here is
    a statement, not a request.
    """
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
    """Validate an item tarball, then write its members into a fresh directory.

    :param archive_path: the ``.tar.gz`` on disk.
    :param dest: a directory that MUST NOT exist; the caller supplies a
        fresh unique path.
    :param publisher: the catalog publisher, already format-validated.
    :param name: the item name, already format-validated.
    :param kind: ``"skill"`` or ``"theme"``; passed straight to
        :func:`~src.core.skills.validate.validate_archive`, which is the
        only thing in the staging path that cares. The WRITER is
        kind-independent: it writes the members the validator approved,
        at ``0o644``, whatever they describe.
    :param limits: the bounds to enforce.
    :param src_path: the signed ``version.src.path``, passed to the validator.
    :param allow_scripts: keep executable content and write ``0o755`` on
        the members the validator classified as executable. DEFAULTS TO
        FALSE, so a caller unlocks it by saying so and never by omission;
        the only callers that pass True hold a recorded human consent for
        these exact bytes.
    :returns: the staged directory and the digest recomputed from it.
    :raises FileExistsError: if ``dest`` already exists.
    :raises ArchiveRefused: ``scripts_not_supported`` or
        ``archive_invalid``; nothing is left on disk when it does.
    """
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
