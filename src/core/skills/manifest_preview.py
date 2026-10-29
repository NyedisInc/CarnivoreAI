
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
