
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.cplugs.runtime import guards

KEYS = frozenset({"project", "prompt", "family"})
FAMILIES = frozenset({"claude", "codex"})
SIDELOAD_TIER = "local"


def checked(tier: str, params: Dict[str, Any]) -> Tuple[int, str, Optional[str]]:
    if tier != SIDELOAD_TIER:
        raise guards.Refused("permission_denied", "sideload_only", {"reason": "sideload_only"})
    extra = sorted(str(k) for k in params if k not in KEYS)
    if extra:
        raise guards.Refused("permission_denied", "option_not_allowed", {"reason": "option_not_allowed", "keys": extra})
    project, prompt, family = params.get("project"), params.get("prompt", ""), params.get("family")
    if not isinstance(project, int) or isinstance(project, bool):
        raise guards.Refused("invalid_params", "project must be a project row id (int)", {"reason": "bad_project"})
    if not isinstance(prompt, str):
        raise guards.Refused("invalid_params", "prompt must be text", {"reason": "bad_prompt"})
    if family is not None and family not in FAMILIES:
        raise guards.Refused("invalid_params", "family must be claude or codex", {"reason": "bad_family"})
    return project, guards.strip_invisible(prompt), family
