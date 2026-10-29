
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.skill_manager import claude_overrides, codex_overrides
from src.core.skill_manager.roots import PROJECT_SKILL_DIRS, project_dirs
from src.core.skill_manager.types import CLAUDE, CODEX, ProfileGroup, OverrideError
from src.core.skills.roots import unsafe_name_reason
from src.core.test_write_guard import assert_test_write_allowed

FILES = ("user", "project", "local")
_PROJECT_LEAF = {"project": "settings.json", "local": "settings.local.json"}
CLAUDE_RELOAD_HINT = (
    "a running claude session applies this on its next skill call; run /reload-skills if its skill list looks stale"
)
CODEX_RESTART_HINT = "restart the codex session for this to take effect"


def _need_project(project_path: Optional[str], file: str) -> str:
    if not project_path:
        raise OverrideError(400, "project_required", f"file '{file}' needs a project")
    return project_path


def claude_settings_target(group: ProfileGroup, file: str, project_path: Optional[str]) -> str:
    if file == "user":
        return group.settings_path
    leaf = _PROJECT_LEAF.get(file)
    if leaf is None:
        raise OverrideError(400, "bad_file", "file must be user, project or local")
    project = _need_project(project_path, file)
    directory = os.path.join(project, ".claude")
    target = os.path.join(directory, leaf)
    if os.path.islink(directory) or os.path.realpath(target) != target:
        raise OverrideError(409, "target_unsafe", "the project's .claude folder or settings file is a link")
    return target


def ensure_project_claude_dir(target: str) -> None:
    directory = os.path.dirname(target)
    if not os.path.isdir(directory) and os.path.isdir(os.path.dirname(directory)):
        assert_test_write_allowed(Path(directory))
        os.mkdir(directory)


def _require_inside_claude_dir(target: str, project_path: Optional[str]) -> None:
    expected = os.path.join(_need_project(project_path, "project"), ".claude")
    if os.path.dirname(os.path.realpath(target)) != expected:
        raise OverrideError(409, "target_unsafe", "the settings file does not resolve into the project's .claude folder")


def codex_rules(file: str, skill: str, project_path: Optional[str], home: Path) -> List[Tuple[str, str]]:
    if file == "user":
        return [("name", skill)]
    if file == "local":
        raise OverrideError(400, "codex_no_local", "codex has no local settings file")
    project = _need_project(project_path, file)
    found = []
    for directory in project_dirs(project, home=home):
        for harness, rel in PROJECT_SKILL_DIRS:
            skill_md = os.path.join(directory, rel, skill, "SKILL.md")
            if harness == CODEX and os.path.isfile(skill_md):
                found.append(os.path.realpath(skill_md))
    if not found:
        raise OverrideError(404, "skill_not_found", "that skill has no copy in this project's codex folders")
    return [("path", path) for path in found]


def apply_override(
    *,
    harness: str,
    file: str,
    skill: str,
    state: Optional[str],
    group: Optional[ProfileGroup],
    project_path: Optional[str],
    home: Path,
    codex_home: Path,
) -> Dict[str, Any]:
    if file not in FILES:
        raise OverrideError(400, "bad_file", "file must be user, project or local")
    if harness == CLAUDE:
        if group is None:
            raise OverrideError(404, "unknown_profile", "no claude profile to write to")
        target = claude_settings_target(group, file, project_path)
        if file != "user" and state is not None:
            ensure_project_claude_dir(target)
        if file != "user":
            _require_inside_claude_dir(target, project_path)
        wrote = claude_overrides.write_skill_override(target, skill, state, backup=file == "user")
        hint, restart = CLAUDE_RELOAD_HINT, False
    elif harness == CODEX:
        if state not in (None, "on", "off"):
            raise OverrideError(400, "codex_two_state", "codex can only switch a skill on or off")
        reason = unsafe_name_reason(skill)
        if reason is not None:
            raise OverrideError(400, "bad_skill", reason)
        wrote = False
        for kind, value in codex_rules(file, skill, project_path, home):
            wrote = codex_overrides.write_codex_rule(codex_home, kind, value, state != "off") or wrote
        hint, restart = CODEX_RESTART_HINT, True
    else:
        raise OverrideError(400, "bad_harness", "harness must be claude or codex")
    return {
        "harness": harness,
        "file": file,
        "skill": skill,
        "state": state,
        "wrote": wrote,
        "restart_required": restart,
        "reload_hint": hint,
    }
