
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.core.live_install_roots import AGENTS_DIR_NAME, CLAUDE_DIR_NAME, SKILLS_DIR_NAME, TRASH_DIR_NAME
from src.core.skills.roots import symlinked_intermediate

REASON_ROOT_LINK = "skills folder is a link"
_RELAY_RE = re.compile(r"^[0-9a-f]{12}-[a-z0-9][a-z0-9-]{0,62}-relay$")


@dataclass(frozen=True)
class SkillRoot:

    family: str
    leaf: Path
    boundary: Path
    trash: Path
    problem: Optional[str] = None

    @property
    def group(self) -> str:
        import hashlib

        return hashlib.sha256(str(self.leaf).encode("utf-8")).hexdigest()[:6]


def _claude_candidates(home: Path, accounts_root: Path, claude_config_dirs: Iterable[str]) -> list[Path]:
    found: list[Path] = [home / CLAUDE_DIR_NAME]
    found += [Path(unicodedata.normalize("NFC", d)) for d in claude_config_dirs if d]
    try:
        with os.scandir(accounts_root) as it:
            found += [Path(e.path) for e in sorted(it, key=lambda e: e.name) if _RELAY_RE.match(e.name) and e.is_dir(follow_symlinks=False)]
    except OSError:
        pass
    seen: set[Path] = set()
    return [p for p in found if not (p in seen or seen.add(p))]


def claude_roots(home: Path, accounts_root: Path, claude_config_dirs: Iterable[str]) -> list[SkillRoot]:
    trash = home / CLAUDE_DIR_NAME / TRASH_DIR_NAME
    groups: dict[str, list[tuple[Path, Path]]] = {}
    for profile in _claude_candidates(home, accounts_root, claude_config_dirs):
        if not profile.is_dir():
            continue
        leaf = profile / SKILLS_DIR_NAME
        key = os.path.realpath(leaf) if os.path.lexists(leaf) else str(leaf)
        groups.setdefault(key, []).append((profile, leaf))
    roots: list[SkillRoot] = []
    for key, members in groups.items():
        real = [m for m in members if not m[1].is_symlink()]
        profile, leaf = real[0] if real else members[0]
        problem = REASON_ROOT_LINK if (not real or symlinked_intermediate(leaf) is not None) else None
        roots.append(SkillRoot("claude", leaf, profile, trash, problem))
    return roots


def codex_roots(home: Path) -> list[SkillRoot]:
    leaf = home / AGENTS_DIR_NAME / SKILLS_DIR_NAME
    agents = leaf.parent
    boundary = agents if agents.is_dir() and not agents.is_symlink() else home
    problem = REASON_ROOT_LINK if (leaf.is_symlink() or agents.is_symlink()) else None
    return [SkillRoot("codex", leaf, boundary, agents / TRASH_DIR_NAME, problem)]


def receiver_roots(home: Path, accounts_root: Path, claude_config_dirs: Iterable[str]) -> list[SkillRoot]:
    return [*claude_roots(home, accounts_root, claude_config_dirs), *codex_roots(home)]


def roots_for(roots: Iterable[SkillRoot], family: str) -> list[SkillRoot]:
    return [r for r in roots if r.family == family]
