
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from src.core.session_git.diff import EscapesRepository, read_file_diff
from src.models.session_git import GitFile

MAX_FILES = 3


def count_diff_lines(text: str) -> List[int]:
    added = removed = 0
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return [added, removed]


def file_stats(root: Path, entries: Sequence[GitFile], *, unborn: bool) -> List[List[int]]:
    out: List[List[int]] = []
    for entry in list(entries)[:MAX_FILES]:
        try:
            diff = read_file_diff(root, entry, staged=False, unborn=unborn)
        except (EscapesRepository, OSError):
            out.append([])
            continue
        trusted = diff.state == "ok" and not (diff.binary or diff.sensitive or diff.directory or diff.truncated)
        out.append(count_diff_lines(diff.text) if trusted else [])
    return out
