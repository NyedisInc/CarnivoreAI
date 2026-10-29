"""What the consent sheet shows before anything is copied anywhere.

A person is about to let this app write a folder of somebody else's files
into their home directory. The only honest way to ask for that is to show
them what the folder actually contains, so this module reads a STAGED copy
(already validated, already digest-matched) and answers three things: the
text of ``SKILL.md``, every file with its size, and a list of front-matter
keys the two harnesses do not agree about.

**WARN, NEVER STRIP.** The tempting behaviour is to remove a key Codex
does not understand. Two reasons not to, and the second is fatal. Codex
IGNORES an unknown front-matter key, so stripping buys nothing at all;
and the folder's digest is computed over its bytes, so editing one byte of
``SKILL.md`` breaks the one number that connects this folder to the
signature the publisher put on it. A warning costs nothing and keeps the
folder byte-identical to the thing that was verified.

**THIS MODULE WRITES NOTHING AND CREATES NOTHING.** It is a read over a
directory the caller staged. That is what makes it safe to call on the
preview path, where no consent has been given yet.

**WHY THE TEXT IS SIZE-CAPPED AND THE CAP IS REPORTED.** ``SKILL.md`` is
bounded by the archive validator, but this text crosses a wire into a
browser and is rendered in a sheet, and a multi-megabyte manifest would be
a denial of service against the person reading it. So the text is capped,
and ``skill_md_truncated`` says so. A cap that silently truncates would
show the user a partial document and let them consent to it as though it
were the whole thing, which is the same defect as stripping a key.

**WHY THE FRONT MATTER IS PARSED THE WAY IT IS.**
:mod:`src.core.slash_command_discovery` already reads this exact block
with one regex and ``yaml.safe_load``, tolerating a parse failure rather
than raising, because the file belongs to somebody else. The same shape is
repeated here rather than imported: that module binds ``CLAUDE_HOME`` at
import time with a module-scope ``Path.home()``, and the install package
must never acquire that dependency by accident. The regex is four
characters of pattern; the import would have been a rule broken.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

from src.core.skills import kinds

logger = structlog.get_logger()

MANIFEST_NAME = kinds.MANIFEST_FOR[kinds.KIND_SKILL]

MAX_MANIFEST_TEXT_BYTES = 64 * 1024

PORTABLE_FRONTMATTER_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "license",
        "compatibility",
        "allowed-tools",
        "metadata",
    }
)

CLAUDE_ONLY_FRONTMATTER_KEYS: frozenset[str] = frozenset(
    {
        "disable-model-invocation",
        "user-invocable",
    }
)

_FRONTMATTER_RX = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class FileEntry:

    relpath: str
    size: int


@dataclass(frozen=True)
class ManifestPreview:

    skill_md_text: str
    skill_md_truncated: bool
    files: tuple[FileEntry, ...]
    total_bytes: int
    frontmatter_warnings: tuple[str, ...]


def read_manifest_text(
    directory: Path, kind: str = kinds.KIND_SKILL
) -> tuple[str, bool]:
    source = directory / kinds.manifest_name(kind)
    with open(source, "rb") as handle:
        raw = handle.read(MAX_MANIFEST_TEXT_BYTES + 1)
    if len(raw) > MAX_MANIFEST_TEXT_BYTES:
        logger.info(
            "skill_manifest_truncated",
            directory=str(directory),
            cap_bytes=MAX_MANIFEST_TEXT_BYTES,
        )
        return raw[:MAX_MANIFEST_TEXT_BYTES].decode("utf-8", errors="replace"), True
    return raw.decode("utf-8"), False


def list_files(directory: Path) -> tuple[tuple[FileEntry, ...], int]:
    entries: list[FileEntry] = []
    total = 0
    for parent, _dir_names, file_names in os.walk(directory):
        for file_name in file_names:
            absolute = Path(parent) / file_name
            try:
                size = absolute.lstat().st_size
            except OSError as exc:
                logger.warning(
                    "skill_preview_entry_unreadable",
                    path=str(absolute),
                    error=str(exc),
                )
                continue
            relpath = absolute.relative_to(directory).as_posix()
            entries.append(FileEntry(relpath=relpath, size=size))
            total += size
    entries.sort(key=lambda entry: entry.relpath)
    return tuple(entries), total


def frontmatter_keys(text: str) -> tuple[str, ...]:
    match = _FRONTMATTER_RX.match(text)
    if not match:
        return ()
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("skill_frontmatter_parse_failed", error=str(exc))
        return ()
    if not isinstance(parsed, dict):
        logger.warning(
            "skill_frontmatter_not_a_mapping",
            shape=type(parsed).__name__,
        )
        return ()
    return tuple(str(key) for key in parsed)


def frontmatter_warnings(text: str) -> tuple[str, ...]:
    warnings: list[str] = []
    for key in frontmatter_keys(text):
        if key in PORTABLE_FRONTMATTER_KEYS:
            continue
        if key in CLAUDE_ONLY_FRONTMATTER_KEYS:
            warnings.append(
                f"{key!r} is a Claude Code front-matter key. Codex ignores "
                "it, so this skill behaves differently in the two harnesses. "
                "It is kept exactly as published."
            )
            continue
        warnings.append(
            f"{key!r} is not a front-matter key either harness defines. It "
            "is kept exactly as published and is likely to be ignored."
        )
    return tuple(warnings)


def preview_manifest(
    staged_dir: Path, kind: str = kinds.KIND_SKILL
) -> ManifestPreview:
    text, truncated = read_manifest_text(staged_dir, kind)
    files, total_bytes = list_files(staged_dir)
    warnings = frontmatter_warnings(text) if kind == kinds.KIND_SKILL else ()
    logger.info(
        "skill_manifest_previewed",
        directory=str(staged_dir),
        files=len(files),
        total_bytes=total_bytes,
        warnings=len(warnings),
        truncated=truncated,
    )
    return ManifestPreview(
        skill_md_text=text,
        skill_md_truncated=truncated,
        files=files,
        total_bytes=total_bytes,
        frontmatter_warnings=warnings,
    )
