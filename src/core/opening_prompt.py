
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from src.core.agent_families import resolve_agent_type
from src.models.blueprints import PROMPT_FAMILIES, check_opening_prompt


def launch_agent_type(settings: Any, agent_type: Optional[str],
                      project_name: Optional[str]) -> str:
    if agent_type:
        return agent_type
    if project_name:
        from src.api import projects_service

        try:
            found = projects_service.agent_type_for(settings, project_name)
        except (OSError, ValueError, RuntimeError):
            found = None
        if found:
            return found
    return "claude"


def prompt_launch(settings: Any, *, agent_type: Optional[str], project_name: Optional[str],
                  opening_prompt: str, auto_start: bool = True) -> Tuple[str, List[str]]:
    text = check_opening_prompt(opening_prompt)
    if text is None:
        raise ValueError("the opening prompt is empty")
    if not auto_start:
        raise ValueError("an opening prompt needs the agent to start (auto_start_claude)")
    resolved = launch_agent_type(settings, agent_type, project_name)
    wrappers = settings.load_auth_config().agents.wrappers or []
    family, _wrapper = resolve_agent_type(resolved, wrappers)
    if family.name not in PROMPT_FAMILIES:
        raise ValueError(
            f"an opening prompt is for claude and codex sessions; this one launches {family.name}")
    return resolved, [text]
