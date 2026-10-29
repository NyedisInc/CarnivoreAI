
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()

MAX_NEST: int = 3
MEMORY_DIR: str = "memory"
MERGED_SIDE_PREFIX: str = "_from-"
SIDECAR_DIRS: Tuple[str, ...] = ("subagents", "tool-results", MEMORY_DIR)
_CONFLICT = re.compile(r"^(?P<base>.+) (?P<n>[0-9]{1,3})$")

FORM_MAIN, FORM_FOLDER, FORM_SET_ASIDE, FORM_CONFLICT = "main", "folder", "set_aside", "conflict"


@dataclass(frozen=True)
class Entry:

    name: str
    is_dir: bool
    is_file: bool
    link: bool


def entries(folder: Path) -> List[Entry]:
    try:
        with os.scandir(folder) as scan:
            out = [Entry(e.name, e.is_dir(follow_symlinks=False), e.is_file(follow_symlinks=False), e.is_symlink())
                   for e in scan]
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("inventory_folder_unreadable", path=str(folder), error=type(exc).__name__)
        return []
    return sorted(out, key=lambda e: e.name)


def _merged_side(entry: Entry) -> bool:
    return entry.is_dir and entry.name.startswith(MERGED_SIDE_PREFIX)


def is_project_folder(name: str, listing: List[Entry]) -> bool:
    return name.startswith("-") or any((e.is_file and not e.name.startswith(".")) or (e.is_dir and e.name == MEMORY_DIR)
                                       or _merged_side(e) for e in listing)


def project_folders(projects: Path) -> List[Tuple[str, Path]]:
    found: List[Tuple[str, Path]] = []

    def walk(folder: Path, prefix: str, depth: int) -> None:
        for entry in entries(folder):
            if (not entry.is_dir or entry.name.startswith(".") or entry.name in SIDECAR_DIRS
                    or entry.name.startswith(MERGED_SIDE_PREFIX)):
                continue
            child = folder / entry.name
            if is_project_folder(entry.name, entries(child)):
                found.append((prefix + entry.name, child))
            elif depth + 1 < MAX_NEST:
                walk(child, prefix + entry.name + "/", depth + 1)

    walk(Path(projects), "", 0)
    return found


def conversation_form(name: str, is_dir: bool) -> Optional[Tuple[str, str]]:
    if name.startswith(".") or (is_dir and (name == MEMORY_DIR or name.startswith(MERGED_SIDE_PREFIX))):
        return None
    if is_dir:
        conflict = _CONFLICT.match(name)
        return (conflict.group("base"), FORM_CONFLICT) if conflict else (name, FORM_FOLDER)
    if name.endswith(".jsonl"):
        stem = name[:-len(".jsonl")]
        conflict = _CONFLICT.match(stem)
        if conflict:
            return conflict.group("base"), FORM_CONFLICT
        return (stem, FORM_MAIN) if stem else None
    head, sep, tail = name.partition(".jsonl.")
    return (head, FORM_SET_ASIDE) if sep and head and tail else None


def conversation_entries(folder: Path, conv: str) -> List[Tuple[Path, str]]:
    out: List[Tuple[Path, str]] = []
    for entry in entries(folder):
        found = conversation_form(entry.name, entry.is_dir)
        if found is not None and found[0] == conv:
            out.append((folder / entry.name, found[1]))
    return out


def notes_entries(folder: Path) -> List[Path]:
    out: List[Path] = []
    for entry in entries(folder):
        if entry.name.startswith("."):
            continue
        if entry.is_dir and (entry.name == MEMORY_DIR or entry.name.startswith(MERGED_SIDE_PREFIX)):
            out.append(folder / entry.name)
        elif entry.is_file and conversation_form(entry.name, False) is None:
            out.append(folder / entry.name)
    return out
