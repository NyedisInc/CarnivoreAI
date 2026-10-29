"""The opening prompt a new session is born with (issue #759, blueprints).

``CreateSessionRequest.opening_prompt`` asks the agent to start working on
something the moment it launches: a blueprint member's first instruction,
which can invoke a skill installed into its folder.

ONE ARGUMENT, NEVER SHELL TEXT. The prompt travels as a single positional
argument through ``agent_extra_args``, the path the fork route already
uses for ``--resume <uuid> --fork-session``
(``src/api/session_fork_routes.py``). Every renderer quotes each extra
argument on its own with ``shlex.quote`` (``agent_wrappers.
render_wrapper_invocation``, the one launch renderer), so
``$(...)``, backticks, ``;`` and quotes reach the CLI as the literal
characters they are. The text checks in ``check_opening_prompt`` refuse
what the CLI's OWN parser would take for something else: a leading ``-``
(an option) and a lone bare word (a subcommand).

CLAUDE AND CODEX ONLY. Both CLIs take an initial prompt as a positional
argument; a shell takes none and a family this app does not know would
receive it as who knows what. The family is resolved the way the launch
itself resolves it (explicit ``agent_type``, else the project's default,
else claude; then ``resolve_agent_type`` against the configured
wrappers), and the resolved ``agent_type`` is handed back so the launch
cannot resolve a different one.

FIRST LAUNCH ONLY. Nothing stores the prompt: ``agent_extra_args`` is used
once to build the launch command and never persisted, and a restart
resumes the conversation through ``session_resume_target`` instead, so a
restart never sends the prompt a second time.
"""

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
