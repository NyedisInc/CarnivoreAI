
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.skill_manager.inventory import build_inventory, estimate_tokens
from src.core.skill_manager.types import CLAUDE, CODEX, Profile

REASON_OFF = "off"
REASON_SHADOWED = "shadowed"
REASON_USER_ONLY = "user-invocable-only"


def _profile_for(config_dir: Optional[str], home: Path) -> Profile:
    if config_dir and os.path.isabs(os.path.expanduser(config_dir)):
        return Profile("pane", os.path.normpath(os.path.expanduser(config_dir)))
    return Profile("default", os.path.normpath(str(home / ".claude")))


def _visibility(loc: Dict[str, Any]) -> Dict[str, Any]:
    full = int(loc["description_tokens_est"])
    if loc["shadowed_by"]:
        return {"model_sees": False, "reason": REASON_SHADOWED, "tokens_est": 0}
    if loc["state"] == "off":
        return {"model_sees": False, "reason": REASON_OFF, "tokens_est": 0}
    if loc["state"] == "user-invocable-only":
        return {"model_sees": False, "reason": REASON_USER_ONLY, "tokens_est": 0}
    if loc["state"] == "name-only":
        return {"model_sees": True, "reason": None, "tokens_est": estimate_tokens(loc["name"], "")}
    return {"model_sees": True, "reason": None, "tokens_est": full}


def _made_after(path: str, started: Optional[datetime]) -> bool:
    if started is None:
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    born = getattr(st, "st_birthtime", st.st_ctime)
    stamp = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
    return born > stamp.timestamp()


def resolve_session_skills(
    *,
    family: Optional[str],
    config_dir: Optional[str],
    codex_home: Path,
    codex_from_pane: bool = False,
    working_dir: str,
    started: Optional[datetime],
    home: Path,
    plugin_scope: Callable[[], Dict[str, list]],
) -> Dict[str, Any]:
    if family not in (CLAUDE, CODEX):
        return {"state": "unsupported", "family": family, "detail": "skills are read for claude and codex only"}
    profile = _profile_for(config_dir, home)
    project = os.path.realpath(working_dir)
    inventory = build_inventory(
        profiles=[profile],
        profile_id=profile.profile_id,
        project_path=project,
        home=home,
        codex_home=codex_home,
        ledger_rows=(),
        targets_for=lambda _install_id: (),
        update_check=lambda _row: False,
        plugin_scope=plugin_scope,
    )
    skills: List[Dict[str, Any]] = []
    for group in inventory["skills"]:
        for loc in group["locations"]:
            if loc["harness"] != family:
                continue
            skills.append(
                {
                    "name": loc["name"],
                    "location_id": loc["location_id"],
                    "scope": loc["scope"],
                    "state": loc["state"],
                    "state_source": loc["state_source"],
                    "description_tokens_est": loc["description_tokens_est"],
                    "shadowed_by": loc["shadowed_by"],
                    **_visibility(loc),
                }
            )
    reload_hint = family == CLAUDE and any(
        _made_after(r["path"], started) for r in inventory["roots"] if r["harness"] == CLAUDE and r["exists"]
    )
    return {
        "state": "ok",
        "family": family,
        "profile": {"source": "pane" if profile.profile_id == "pane" else "default", "directory": profile.directory}
        if family == CLAUDE
        else {"source": "pane" if codex_from_pane else "default", "directory": str(codex_home)},
        "working_dir": project,
        "skills": skills,
        "budget_tokens_est": sum(s["tokens_est"] for s in skills),
        "tokens_label": "est.",
        "restart_required": family == CODEX,
        "reload_hint": "/reload-skills" if reload_hint else None,
        "settings_unparseable": inventory["settings_unparseable"],
    }
