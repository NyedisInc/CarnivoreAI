
from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.config.provider_accounts import profile_dir_for
from src.core.provider_ledger import accounts_store
from src.core.skill_manager.types import (
    CLAUDE,
    CODEX,
    SCOPE_PERSONAL,
    SCOPE_PLUGIN,
    SCOPE_PROJECT,
    SCOPE_SYSTEM,
    Profile,
    ProfileGroup,
    SkillRoot,
)

logger = structlog.get_logger()

DEFAULT_PROFILE_ID = "default"

PROJECT_SKILL_DIRS: Tuple[Tuple[str, str], ...] = (
    (CLAUDE, ".claude/skills"),
    (CODEX, ".agents/skills"),
    (CODEX, ".codex/skills"),
)


def _canonical(path: str) -> str:
    return unicodedata.normalize("NFC", os.path.realpath(os.path.expanduser(path)))


def make_key(kind: str, real_path: str) -> str:
    return f"{kind}-{hashlib.sha256(real_path.encode('utf-8')).hexdigest()[:12]}"


def _is_dir(path: str) -> bool:
    return os.path.isdir(path)


def known_profiles(
    accounts: Iterable[Tuple[str, str]],
    *,
    home: Path,
    managed_root: str,
    foreign_dirs: Iterable[str] = (),
) -> List[Profile]:
    default_dir = os.path.normpath(str(home / ".claude"))
    out: List[Profile] = []
    seen_dirs: set = set()
    default_id = DEFAULT_PROFILE_ID
    resolved: List[Tuple[str, str]] = []
    for account_id, directory in accounts:
        expanded = os.path.normpath(os.path.expanduser(directory))
        resolved.append((account_id, expanded))
        if expanded == default_dir:
            default_id = account_id
    out.append(Profile(default_id, default_dir))
    seen_dirs.add(default_dir)
    for account_id, expanded in resolved:
        if expanded not in seen_dirs:
            out.append(Profile(account_id, expanded))
            seen_dirs.add(expanded)
    managed = os.path.abspath(os.path.expanduser(managed_root))
    foreign = {_canonical(d) for d in foreign_dirs}
    try:
        entries = sorted(os.scandir(managed), key=lambda e: e.name)
    except OSError:
        entries = []
    ids = {p.profile_id for p in out}
    for entry in entries:
        if entry.is_dir(follow_symlinks=False) and entry.path not in seen_dirs and _canonical(entry.path) not in foreign and entry.name not in ids:
            out.append(Profile(entry.name, entry.path))
            seen_dirs.add(entry.path)
            ids.add(entry.name)
    return out


def configured_account_dirs(config_path: Path) -> Tuple[List[Tuple[str, str]], List[str]]:
    try:
        accounts = accounts_store.list_accounts(config_path)
    except (OSError, ValueError) as exc:
        logger.warning("skills_inventory_accounts_unreadable", path=str(config_path), error=type(exc).__name__)
        return [], []
    claude = [(a.id, profile_dir_for(a)) for a in accounts if a.provider == "claude"]
    other = [profile_dir_for(a) for a in accounts if a.provider != "claude"]
    return claude, other


def configured_profiles(home: Path, config_path: Path, managed_root: str) -> List[Profile]:
    pairs, foreign = configured_account_dirs(config_path)
    return known_profiles(pairs, home=home, managed_root=managed_root, foreign_dirs=foreign)


def profile_groups(profiles: Sequence[Profile]) -> Tuple[ProfileGroup, ...]:
    order: List[str] = []
    members: Dict[str, List[Profile]] = {}
    for profile in profiles:
        real = os.path.realpath(os.path.join(profile.directory, "skills"))
        if real not in members:
            order.append(real)
            members[real] = []
        members[real].append(profile)
    groups: List[ProfileGroup] = []
    for real in order:
        group = members[real]
        first = group[0]
        own = any(
            os.path.isdir(os.path.join(p.directory, "skills"))
            and not os.path.islink(os.path.join(p.directory, "skills"))
            for p in group
        )
        groups.append(
            ProfileGroup(
                group_id=make_key("cg", real),
                profiles=tuple(p.profile_id for p in group),
                skills_path=real,
                settings_path=os.path.realpath(os.path.join(first.directory, "settings.json")),
                own_folder=own,
                exists=_is_dir(real),
            )
        )
    return tuple(groups)


def project_dirs(working_dir: str, *, home: Path) -> List[str]:
    start = os.path.realpath(working_dir)
    home_real = os.path.realpath(str(home))
    chain: List[str] = []
    current = start
    while True:
        chain.append(current)
        if os.path.lexists(os.path.join(current, ".git")):
            break
        parent = os.path.dirname(current)
        if parent == current:
            chain = [start]
            break
        current = parent
    return [d for d in chain if d != home_real]


def git_root(working_dir: str, *, home: Path) -> Optional[str]:
    chain = project_dirs(working_dir, home=home)
    if chain and os.path.lexists(os.path.join(chain[-1], ".git")):
        return chain[-1]
    return None


def _root(kind: str, harness: str, scope: str, path: str, **extra: Any) -> SkillRoot:
    real = os.path.realpath(path)
    return SkillRoot(
        root_key=make_key(kind, f"{harness}:{real}"),
        harness=harness,
        scope=scope,
        path=real,
        is_symlink=os.path.islink(path),
        exists=_is_dir(real),
        **extra,
    )


def _plugin_roots(plugin_scope: Callable[[], Dict[str, list]]) -> List[SkillRoot]:
    found: Dict[str, str] = {}
    for plugin, commands in plugin_scope().items():
        for command in commands:
            if command.type != "plugin-skill":
                continue
            for parent in Path(command.source_path).parents:
                if parent.name == "skills":
                    found[str(parent)] = plugin
                    break
    return [
        _root("pl", CLAUDE, SCOPE_PLUGIN, path, read_only=True, plugin=plugin)
        for path, plugin in sorted(found.items())
    ]


def enumerate_roots(
    *,
    group: ProfileGroup,
    project_path: Optional[str],
    home: Path,
    codex_home: Path,
    plugin_scope: Callable[[], Dict[str, list]],
) -> Tuple[SkillRoot, ...]:
    roots: List[SkillRoot] = [
        _root("cp", CLAUDE, SCOPE_PERSONAL, group.skills_path, group_id=group.group_id)
    ]
    roots.extend(_plugin_roots(plugin_scope))
    codex_skills = codex_home / "skills"
    for candidate in (codex_skills, home / ".codex" / "skills", home / ".agents" / "skills"):
        roots.append(_root("cx", CODEX, SCOPE_PERSONAL, str(candidate)))
    roots.append(
        _root("cs", CODEX, SCOPE_SYSTEM, str(codex_skills / ".system"), read_only=True)
    )
    if project_path:
        for directory in project_dirs(project_path, home=home):
            for harness, rel in PROJECT_SKILL_DIRS:
                path = os.path.join(directory, rel)
                if os.path.isdir(path):
                    roots.append(
                        _root("pj", harness, SCOPE_PROJECT, path, project_path=project_path)
                    )
    unique: Dict[Tuple[str, str], SkillRoot] = {}
    for root in roots:
        unique.setdefault((root.harness, root.path), root)
    return tuple(unique.values())
