
from __future__ import annotations

from typing import Callable, List, Optional

from src.config import mcp_launch
from src.config.agents import AgentsConfig
from src.core.agent_families import DEFAULT_FAMILY, resolve_agent_type, wrappers_for_family
from src.core.agent_wrappers import AgentWrapper, default_wrapper, render_wrapper_invocation, wrapper_scripts_dir
from src.core.launch_wrappers.family_defaults import standard_wrapper

mcp_config_args: Callable[[], List[str]] = lambda: []  # noqa: E731


def legacy_agent_command(
    agent_type: Optional[str], *, agents: AgentsConfig, resolve_state_dir: Callable[[], str],
    disable_alternate_screen: Callable[[], bool], model: Optional[str] = None,
    extra_args: Optional[List[str]] = None, carnivore_mcp_url: Optional[str] = None,
) -> str:
    family, explicit = resolve_agent_type(agent_type, agents.wrappers)
    if family.name == DEFAULT_FAMILY:
        extra_args = mcp_config_args() + list(extra_args or [])
        if carnivore_mcp_url:
            extra_args = mcp_launch.claude_args() + extra_args
    elif family.name == "codex" and carnivore_mcp_url:
        extra_args = mcp_launch.codex_args(carnivore_mcp_url) + list(extra_args or [])
    if family.needs_model and not (model and str(model).strip()):
        raise ValueError(f"the '{family.name}' agent needs a model and none was given")
    chosen = explicit if explicit is not None else default_wrapper(wrappers_for_family(agents.wrappers, family.name))
    if chosen is None:
        chosen = AgentWrapper(**standard_wrapper(family, ()))
    effective_model = model if chosen.accepts_model else None
    disable_alt = disable_alternate_screen()
    launch_args = list(extra_args or [])
    if family.name == "codex" and disable_alt:
        launch_args.append("--no-alt-screen")
    return render_wrapper_invocation(
        chosen, wrapper_scripts_dir(resolve_state_dir()), model=effective_model, extra_args=launch_args,
        disable_alternate_screen=disable_alt, source_rc=family.sources_zshrc,
    )
