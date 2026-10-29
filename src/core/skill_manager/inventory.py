
from __future__ import annotations

import dataclasses
import math
import os
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.core.skill_manager import claude_overrides, codex_overrides, skill_extensions
from src.core.skill_manager.roots import enumerate_roots, git_root, profile_groups
from src.core.skill_manager.scan import SkippedFolder, ScannedSkill, scan_root
from src.core.skill_manager.types import (
    CLAUDE,
    CLAUDE_STATES,
    CODEX,
    CODEX_STATES,
    PLUGIN_NO_TOGGLE_REASON,
    SCOPE_PERSONAL,
    SCOPE_PLUGIN,
    SCOPE_PROJECT,
    Profile,
    ProfileGroup,
    SkillGroup,
    SkillLocation,
    SkillRoot,
)
from src.core.skills.ledger_types import InstalledItem, InstallTarget
from src.core.skills.records import read_sidecar

PROJECT_SETTINGS: Tuple[Tuple[str, str], ...] = (
    ("project", "settings.json"),
    ("local", "settings.local.json"),
)


def estimate_tokens(name: str, description: str) -> int:
    return math.ceil((len(name) + len(description) + 8) / 4)


def _toggle(root: SkillRoot) -> Dict[str, object]:
    if root.scope == SCOPE_PLUGIN:
        return {"kind": "none", "states": [], "reason": PLUGIN_NO_TOGGLE_REASON}
    if root.harness == CLAUDE:
        return {"kind": "four_state", "states": list(CLAUDE_STATES), "reason": None}
    return {
        "kind": "on_off",
        "states": list(CODEX_STATES),
        "reason": "codex can only switch a skill on or off",
    }


def _owned_by_user(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return not stat.S_ISLNK(st.st_mode) and st.st_uid == os.getuid()


def _local_settings_paths(project_path: str, home: Path) -> List[str]:
    leaf = dict(PROJECT_SETTINGS)["local"]
    own = os.path.join(project_path, ".claude", leaf)
    root = git_root(project_path, home=home)
    if root is None or root == os.path.realpath(project_path):
        return [own]
    if not all(_owned_by_user(p) for p in (root, os.path.join(root, ".git"), os.path.join(root, ".claude"))):
        return [own]
    return [own, os.path.join(root, ".claude", leaf)]


def _claude_states(
    group: ProfileGroup, project_path: Optional[str], home: Path
) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    layers: List[Tuple[str, str]] = [("user", group.settings_path)]
    if project_path:
        layers.append(("project", os.path.join(project_path, ".claude", dict(PROJECT_SETTINGS)["project"])))
        layers += [("local", path) for path in _local_settings_paths(project_path, home)]
    merged: Dict[str, Tuple[str, str]] = {}
    bad: List[str] = []
    for kind, path in layers:
        values = claude_overrides.read_skill_overrides(path)
        if values is None:
            bad.append(kind)
            continue
        for skill, state in values.items():
            merged[skill] = (state, kind)
    return merged, bad


def _managed_map(
    rows: Sequence[InstalledItem],
    targets_for: Callable[[str], Sequence[InstallTarget]],
    update_check: Callable[[InstalledItem], bool],
) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for row in rows:
        info = {
            "source": "ledger",
            "install_id": row.install_id,
            "item_id": row.item_id,
            "version": row.version,
            "scope": row.scope,
            "update_available": bool(update_check(row)),
        }
        for target in targets_for(row.install_id):
            out[os.path.realpath(target.path)] = info
    return out


def _managed_for(folder: str, managed: Dict[str, Dict[str, object]]) -> Optional[Dict[str, object]]:
    hit = managed.get(os.path.realpath(folder))
    if hit is not None:
        return hit
    record = read_sidecar(Path(folder))
    if record is None:
        return None
    return {
        "source": "sidecar",
        "item_id": f"{record.publisher}/{record.name}",
        "version": record.version,
        "update_available": False,
    }


def _location(
    root: SkillRoot,
    skill: ScannedSkill,
    *,
    claude_states: Dict[str, Tuple[str, str]],
    codex_rules: Optional[List[Tuple[str, str, bool]]],
    managed: Dict[str, Dict[str, object]],
) -> SkillLocation:
    state, source = "on", None
    if root.harness == CLAUDE and root.scope != SCOPE_PLUGIN and skill.name in claude_states:
        state, source = claude_states[skill.name]
    elif root.harness == CODEX and codex_rules:
        enabled, matched = codex_overrides.codex_enabled(
            codex_rules, skill.name, os.path.realpath(os.path.join(skill.path, "SKILL.md"))
        )
        if matched:
            state, source = ("on" if enabled else "off"), "config.toml"
    return SkillLocation(
        location_id=f"{root.root_key}:{skill.folder}",
        root_key=root.root_key,
        folder=skill.folder,
        name=skill.name,
        harness=root.harness,
        scope=root.scope,
        path=skill.path,
        description=skill.description,
        description_tokens_est=estimate_tokens(skill.name, skill.description),
        is_symlink=skill.is_symlink,
        link_target=skill.link_target,
        read_only=root.read_only,
        plugin=root.plugin,
        project_path=root.project_path,
        toggle=_toggle(root),
        state=state,
        state_source=source,
        managed=None if root.scope == SCOPE_PLUGIN else _managed_for(skill.path, managed),
        extends=skill.extends,
        guide_rev=skill.guide_rev,
        behind_rules=skill_extensions.behind_rules(skill.extends, skill.guide_rev),
    )


def apply_shadowing(locations: List[SkillLocation]) -> List[SkillLocation]:
    by_name: Dict[str, List[int]] = {}
    for index, loc in enumerate(locations):
        if loc.harness == CLAUDE and loc.scope in (SCOPE_PERSONAL, SCOPE_PROJECT):
            by_name.setdefault(loc.name, []).append(index)
    for indexes in by_name.values():
        if len(indexes) < 2:
            continue
        ranked = sorted(indexes, key=lambda i: 0 if locations[i].scope == SCOPE_PERSONAL else 1)
        winner, losers = ranked[0], ranked[1:]
        locations[winner] = dataclasses.replace(
            locations[winner], shadows=tuple(locations[i].location_id for i in losers)
        )
        for i in losers:
            locations[i] = dataclasses.replace(locations[i], shadowed_by=locations[winner].location_id)
    return locations


def build_inventory(
    *,
    profiles: Sequence[Profile],
    profile_id: Optional[str],
    project_path: Optional[str],
    home: Path,
    codex_home: Path,
    ledger_rows: Sequence[InstalledItem],
    targets_for: Callable[[str], Sequence[InstallTarget]],
    update_check: Callable[[InstalledItem], bool],
    plugin_scope: Callable[[], Dict[str, list]],
) -> Dict[str, Any]:
    groups = profile_groups(profiles)
    wanted = profile_id or profiles[0].profile_id
    group = next((g for g in groups if wanted in g.profiles), None)
    if group is None:
        raise KeyError(wanted)
    roots = enumerate_roots(
        group=group, project_path=project_path, home=home, codex_home=codex_home, plugin_scope=plugin_scope
    )
    states, bad = _claude_states(group, project_path, home)
    rules = codex_overrides.read_codex_rules(str(codex_home / "config.toml"))
    if rules is None:
        bad.append("codex")
    managed = _managed_map(ledger_rows, targets_for, update_check)

    locations: List[SkillLocation] = []
    skipped: List[SkippedFolder] = []
    for root in roots:
        skills, refused = scan_root(root)
        skipped.extend(refused)
        locations.extend(
            _location(root, s, claude_states=states, codex_rules=rules, managed=managed) for s in skills
        )
    locations = apply_shadowing(locations)
    skill_extensions.refresh(locations, (root.root_key for root in roots))

    by_name: Dict[str, List[SkillLocation]] = {}
    for loc in locations:
        by_name.setdefault(loc.name, []).append(loc)
    skill_groups = [SkillGroup(name, tuple(locs)) for name, locs in sorted(by_name.items())]
    return {
        "context": {"profile": wanted, "group_id": group.group_id, "project_path": project_path},
        "profile_groups": [dataclasses.asdict(g) for g in groups],
        "roots": [dataclasses.asdict(r) for r in roots],
        "skills": [dataclasses.asdict(g) for g in skill_groups],
        "skipped": [dataclasses.asdict(s) for s in skipped],
        "settings_unparseable": bad,
        "tokens_label": "est.",
    }

