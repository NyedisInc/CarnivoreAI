
from __future__ import annotations

import asyncio
import os
import resource
from pathlib import Path
from typing import Callable, Mapping, Optional

import structlog

from src.core.attention import fs_trigger
from src.core.pack.skills.rules import MACHINE_LOCAL_NAMES, RESERVED_NAMES

logger = structlog.get_logger()

MAX_DIRS = 512
NOFILE_TARGET = 4096
_KEY = "pack-skills"


def raise_open_file_limit(target: int = NOFILE_TARGET) -> Optional[int]:
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = target if hard == resource.RLIM_INFINITY else min(hard, target)
        if soft == resource.RLIM_INFINITY or soft >= want:
            return None
        resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except (OSError, ValueError) as exc:
        logger.info("pack_skills_nofile_raise_failed", error=str(exc))
        return None
    logger.info("pack_skills_nofile_raised", soft=want)
    return want


def plan_dirs(roots: Mapping[str, Path], skills: set[tuple[str, str]], *, deep: bool, limit: int) -> Optional[list[str]]:
    found: set[str] = set()
    for family, root in roots.items():
        if root.is_dir() and not root.is_symlink():
            found.add(str(root))
        for fam, name in skills:
            top = root / name
            if fam != family or name in RESERVED_NAMES or not top.is_dir() or top.is_symlink():
                continue
            if not deep:
                found.add(str(top))
                continue
            for here, dirs, _files in os.walk(top, followlinks=False):
                dirs[:] = [d for d in dirs if d not in MACHINE_LOCAL_NAMES and not os.path.islink(os.path.join(here, d))]
                found.add(here)
                if len(found) > limit:
                    return None
    return sorted(found) if len(found) <= limit else None


class SkillsWatcher:

    def __init__(self, roots: Callable[[], Mapping[str, Path]], selected: Callable[[], set[tuple[str, str]]],
                 on_change: Callable[[], None], *, quiet_seconds: float = fs_trigger.DEBOUNCE_QUIET_SECONDS,
                 max_dirs: int = MAX_DIRS) -> None:
        self._roots, self._selected, self._on_change = roots, selected, on_change
        cap = min(max_dirs, fs_trigger.descriptor_budget(max_dirs))
        self._cap = cap
        self._trigger = fs_trigger.FsTrigger(self._fired, quiet_seconds=quiet_seconds, max_paths=cap)
        self.shallow = False

    def start(self) -> bool:
        return self._trigger.start()

    async def rearm(self) -> None:
        roots, skills = dict(self._roots()), set(self._selected())
        dirs = await asyncio.to_thread(plan_dirs, roots, skills, deep=True, limit=self._cap)
        self.shallow = dirs is None
        if dirs is None:
            dirs = await asyncio.to_thread(plan_dirs, roots, skills, deep=False, limit=self._cap) or []
        self._trigger.rearm({path: [_KEY] for path in dirs})

    def close(self) -> None:
        self._trigger.close()

    def _fired(self, _keys: set[str]) -> None:
        self._on_change()
        try:
            asyncio.get_running_loop().create_task(self.rearm(), name="pack-skills-rearm")
        except RuntimeError:
            logger.debug("pack_skills_rearm_no_loop")
