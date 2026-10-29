from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.core import slash_command_discovery as scd
from src.core.layouts.broadcast import _live_by_row
from src.core.layouts.store import SavedLayout
from src.core.session_status import STATUS_DEAD
from src.core.slash_command_discovery_scan import (
    DiscoveredCommand,
    _scan_skill_dirs,
    discover_codex_user_scope,
    discover_project_scope,
)

SIGILS = ("/", "$")


def target_infos(layout: SavedLayout, infos: Iterable[Any]) -> List[Any]:
    live = _live_by_row(infos)
    out: List[Any] = []
    for member in sorted(layout.members, key=lambda m: m.position):
        info = live.get(member.session_row_id)
        if (not member.broadcast or info is None or info.session is None
                or info.activity_status == STATUS_DEAD):
            continue
        out.append(info)
    return out


def target_working_dirs(layout: SavedLayout, infos: Iterable[Any]) -> List[str]:
    return [str(info.session.working_dir) for info in target_infos(layout, infos)]


def _entry(found: DiscoveredCommand, scope: str) -> Dict[str, str]:
    return {"name": found.command.lstrip("/"), "description": found.description, "scope": scope}


def _project_names(sigil: str, working_dir: str) -> Dict[str, DiscoveredCommand]:
    if sigil == "/":
        found = discover_project_scope(working_dir)
    else:
        found = _scan_skill_dirs(Path(working_dir) / ".agents" / "skills", "project-codex-skill")
    return {f.command: f for f in found}


def _global_names(sigil: str, profile_dir: Optional[str], claude_home: Optional[Path],
                  codex_skills_root: Optional[Path]) -> Dict[str, DiscoveredCommand]:
    if sigil == "/":
        home = Path(profile_dir) if profile_dir else claude_home
        found = scd.discover_user_scope(home)
        for plugin_found in scd.discover_plugin_scope(home).values():
            found = found + plugin_found
    else:
        root = Path(profile_dir) / "skills" if profile_dir else codex_skills_root
        found = discover_codex_user_scope(root)
    return {f.command: f for f in found}


def suggest(sigil: str, *, working_dirs: List[str], claude_home: Optional[Path] = None,
            codex_skills_root: Optional[Path] = None,
            profile_dirs: Optional[List[Optional[str]]] = None) -> List[Dict[str, str]]:
    if sigil not in SIGILS:
        raise ValueError(f"sigil must be one of {SIGILS}")
    profiles = list(dict.fromkeys(profile_dirs)) if profile_dirs else [None]
    per_profile = [_global_names(sigil, p, claude_home, codex_skills_root) for p in profiles]
    shared_global = set(per_profile[0]).intersection(*(set(g) for g in per_profile[1:]))
    out: Dict[str, Dict[str, str]] = {c: _entry(per_profile[0][c], "global") for c in shared_global}
    per_session = [_project_names(sigil, d) for d in working_dirs]
    if per_session:
        shared = set(per_session[0]).intersection(*(set(p) for p in per_session[1:]))
        for command in shared:
            out.setdefault(command, _entry(per_session[0][command], "project"))
    return sorted(out.values(), key=lambda e: e["name"])
