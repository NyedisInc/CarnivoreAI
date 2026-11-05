
from __future__ import annotations

from pathlib import Path

from src.core.skills.kinds import KIND_CPLUG, KIND_MOD, KIND_PLUGIN, KIND_SKILL
from src.core.skills.manifest_rules import declares_script
from src.core.skills.plugin_safe_subset import folder_declares_code, staged_has_script_members


def staged_plugin_declares_code(kind: str, staged_path: Path) -> bool:
    if kind == KIND_MOD:
        return True
    if kind == KIND_CPLUG:
        return True
    if kind == KIND_PLUGIN and declares_script(kind, staged_path):
        return True
    if kind in (KIND_SKILL, KIND_PLUGIN) and staged_has_script_members(staged_path):
        return True
    return folder_declares_code(staged_path, plugin=kind == KIND_PLUGIN)
