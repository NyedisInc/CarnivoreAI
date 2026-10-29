
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import ProjectIndex

NO_PROJECT_GROUP = "imported, no project"


@dataclass(frozen=True)
class Attribution:

    original: Optional[str]
    working_dir: Optional[str]
    project_uid: Optional[str]
    project_name: Optional[str]
    how: str


def load_rules(paths: Iterable[Path]) -> List[Tuple[str, str]]:
    rules: List[Tuple[str, str]] = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "\t" in line:
                old, new = line.split("\t")[:2]
                rules.append((old.removeprefix("Development/"), new.removeprefix("Development/")))
    return sorted(rules, key=lambda r: -len(r[0]))


class Attributor:

    def __init__(self, index: ProjectIndex, rules: Sequence[Tuple[str, str]] = (), roots: Sequence[str] = (), target: str = "") -> None:
        self._index, self._rules, self._roots, self._target = index, list(rules), tuple(roots), target

    def remap(self, folder: str) -> str:
        for root in self._roots:
            if folder.startswith(root):
                tail = folder[len(root):]
                for old, new in self._rules:
                    if tail == old or tail.startswith(old + "/"):
                        return self._target + new + tail[len(old):]
                return self._target + tail if self._target else folder
        return folder

    def resolve(self, head: bytes) -> Attribution:
        original = units.working_dir_in(head)
        if not original:
            return Attribution(None, None, None, None, "no_folder")
        row = self._index.lookup(original)
        if row is not None:
            return Attribution(original, original, row.get("uid"), row.get("display_name"), "as_is")
        moved = self.remap(original)
        row = self._index.lookup(moved) if moved != original else None
        if row is not None:
            return Attribution(original, moved, row.get("uid"), row.get("display_name"), "reorg")
        return Attribution(original, original, None, None, "none")
