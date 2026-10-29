
from __future__ import annotations

import os
import re
import stat
import time
from typing import Any, FrozenSet, List, Optional, Tuple

from src.core.skill_watch.classify import classify_call
from src.core.skill_watch.tripwire import disclosed_categories

TTL_SECONDS = 30.0
MAX_SKILL_MD = 256 * 1024
_DYNAMIC = re.compile(r"!`([^`\n]{1,1000})`")
_HOOK = re.compile(r"^\s*-?\s*command:\s*(.+?)\s*$", re.M)


def dynamic_categories(text: str) -> FrozenSet[str]:
    commands = _DYNAMIC.findall(text)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        commands += [c.strip("'\"") for c in _HOOK.findall(text[3:end] if end > 0 else "")]
    found: set = set()
    for command in commands:
        found |= classify_call("Bash", {"command": command})
    return frozenset(found)


def _read_skill_md(folder: str) -> str:
    try:
        fd = os.open(os.path.join(folder, "SKILL.md"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        return os.read(fd, MAX_SKILL_MD).decode("utf-8", "replace")
    except OSError:
        return ""
    finally:
        os.close(fd)


def _inside(cwd: str, project: str) -> bool:
    a, b = os.path.realpath(cwd), os.path.realpath(project)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


class SkillAttribution:

    def __init__(self, services: Any) -> None:
        self._services = services
        self._loaded = 0.0
        self._rows: List[Tuple[Any, Tuple[str, ...]]] = []

    def _load(self) -> None:
        if self._rows and time.monotonic() - self._loaded < TTL_SECONDS:
            return
        with self._services.catalog.ledger() as ledger:
            self._rows = [(r, tuple(t.path for t in ledger.targets(r.install_id)))
                          for r in ledger.list() if r.kind == "skill"]
        self._loaded = time.monotonic()

    def applicable(self, skill: str, cwd: Optional[str]) -> List[Tuple[Any, Tuple[str, ...]]]:
        self._load()
        return [(r, paths) for r, paths in self._rows if r.name == skill and (
            r.scope != "project" or not cwd or not r.project_path or _inside(cwd, r.project_path))]

    def row(self, skill: str, cwd: Optional[str]) -> Optional[Any]:
        found = self.applicable(skill, cwd)
        return found[0][0] if len(found) == 1 else None

    def disclosed(self, skill: str, cwd: Optional[str] = None) -> Optional[FrozenSet[str]]:
        found = self.applicable(skill, cwd)
        verified = self._services.catalog.index_cache.snapshot().verified
        if not found or verified is None:
            return None
        sets: List[FrozenSet[str]] = []
        for row, _paths in found:
            item = next((i for i in verified.items if i.id == row.item_id), None)
            if item is None:
                continue
            version = next((v for v in item.versions if v.v == row.version), None)
            got = disclosed_categories(version.review if version else None, item.fm.allowed_tools)
            if got is not None:
                sets.append(got)
        return frozenset.intersection(*sets) if sets else None

    def dynamic(self, skill: str, cwd: Optional[str] = None) -> FrozenSet[str]:
        found: set = set()
        for _row, paths in self.applicable(skill, cwd):
            for folder in paths:
                found |= dynamic_categories(_read_skill_md(folder))
        return frozenset(found)

