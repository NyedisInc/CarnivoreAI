
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Optional, Tuple

LIKE_ESCAPE = "\\"

JOURNAL_PATH_KEYS = frozenset({"working_dir", "cwd", "folder"})


def is_within(child: str, root: str) -> bool:
    child_parts = PurePosixPath(child).parts
    root_parts = PurePosixPath(root).parts
    return len(child_parts) >= len(root_parts) and child_parts[: len(root_parts)] == root_parts


def rebase(path: str, old_root: str, new_root: str) -> str:
    if not is_within(path, old_root):
        raise ValueError(f"{path!r} is not under {old_root!r}")
    suffix = PurePosixPath(path).parts[len(PurePosixPath(old_root).parts):]
    return str(PurePosixPath(new_root, *suffix))


def escape_like(value: str) -> str:
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def prefix_where(column: str) -> str:
    clause = (
        f"({column} = :old OR ({column} LIKE :like ESCAPE '{LIKE_ESCAPE}' "
        f"AND substr({column}, 1, length(:old_slash)) = :old_slash))"
    )
    return clause


def prefix_params(old_root: str) -> dict:
    old = old_root.rstrip("/") or "/"
    return {"old": old, "like": escape_like(old) + "/%", "old_slash": old + "/"}


@dataclass(frozen=True)
class PathMapping:

    rules: Tuple[Tuple[str, str], ...]

    @classmethod
    def of(cls, rules: Iterable[Tuple[str, str]]) -> "PathMapping":
        ordered = sorted(
            ((old.rstrip("/") or "/", new) for old, new in rules),
            key=lambda pair: -len(PurePosixPath(pair[0]).parts),
        )
        return cls(tuple(ordered))

    def apply(self, path: str) -> Optional[str]:
        for old, new in self.rules:
            if is_within(path, old):
                return rebase(path, old, new)
        return None


def rebase_journal_for(journal: Any, mapping: PathMapping, session_uuids: Iterable[str]) -> int:
    wanted = frozenset(session_uuids)
    changed = 0
    if isinstance(journal, dict):
        mine = journal.get("session_uuid") in wanted
        for key, value in journal.items():
            if mine and key in JOURNAL_PATH_KEYS and isinstance(value, str) and value:
                mapped = mapping.apply(value)
                if mapped is not None and mapped != value:
                    journal[key] = mapped
                    changed += 1
            else:
                changed += rebase_journal_for(value, mapping, wanted)
    elif isinstance(journal, list):
        for item in journal:
            changed += rebase_journal_for(item, mapping, wanted)
    return changed
