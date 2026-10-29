
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from src.config import mcp_launch
from src.config.agents import AgentsConfig
from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile
from src.core.account_switch.shared_mcp import mcp_config_args
from src.core.agent_families import DEFAULT_FAMILY
from src.core.agent_wrappers import WRAPPER_SCRIPT_MODE, wrapper_scripts_dir
from src.core.byoai.contracts import Connection
from src.core.launch_profiles.plan import Purpose
from src.core.launch_profiles.resolve import LaunchRequest, pick_profile, resolve_launch
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.safe_file_write import write_private_file


def claude_cli_path(configured: Optional[str]) -> str:
    import shutil

    if configured:
        return configured

    claude_in_path = shutil.which("claude")
    if claude_in_path:
        return claude_in_path

    home_path = Path.home() / ".claude" / "local" / "claude"
    if home_path.exists():
        return str(home_path)

    return "claude"


def profiles_for(profiles: Optional[Sequence[LaunchProfile]], agents: AgentsConfig) -> tuple:
    if profiles is not None:
        return tuple(profiles)
    derived = seed_launch_profiles({"agents": {"wrappers": [w.model_dump() for w in agents.wrappers]}})
    return tuple(LaunchProfile.model_validate(p) for p in derived[LAUNCH_PROFILES_KEY]["profiles"])


def single_name_flag(args: Sequence[str]) -> List[str]:
    last = max((i for i in range(len(args) - 1) if args[i] == "--name"), default=-1)
    out: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--name":
            if i == last:
                out += args[i:i + 2]
            i += 2
            continue
        out.append(args[i])
        i += 1
    return out


def agent_command(
    agent_type: Optional[str],
    *,
    agents: AgentsConfig,
    resolve_state_dir: Callable[[], str],
    disable_alternate_screen: Callable[[], bool],
    model: Optional[str] = None,
    model_is_explicit: bool = False,
    extra_args: Optional[List[str]] = None,
    carnivore_mcp_url: Optional[str] = None,
    carnivore_mcp_channel: bool = False,
    profiles: Optional[Sequence[LaunchProfile]] = None,
    connections: Sequence[Connection] = (),
    explicit: bool = False,
    plan_sink: Optional[list] = None,
    purpose: Purpose = "pane",
) -> str:
    profiles = profiles_for(profiles, agents)
    scripts_dir = wrapper_scripts_dir(resolve_state_dir())
    base = LaunchRequest(
        profiles=profiles, agent_type=agent_type, explicit=explicit, model=model,
        model_is_explicit=model_is_explicit,
        scripts_dir=scripts_dir, disable_alternate_screen=disable_alternate_screen(), connections=tuple(connections),
    )
    harness = pick_profile(base).harness
    app_args = list(extra_args or [])
    if harness == DEFAULT_FAMILY:
        app_args = single_name_flag(app_args)
        app_args = mcp_config_args() + app_args
        if carnivore_mcp_url:
            app_args = mcp_launch.claude_args(channel=carnivore_mcp_channel) + app_args
    elif harness == "codex" and carnivore_mcp_url:
        app_args = mcp_launch.codex_args(carnivore_mcp_url) + app_args
    elif harness == "custom":
        app_args = []
    plan = resolve_launch(replace(base, app_args=tuple(app_args)), purpose)
    if plan_sink is not None:
        plan_sink.append(plan)
    elif plan.secret_refs:
        raise ValueError(
            f"launch profile {plan.display.label!r} needs Keychain secrets; only a session create or restart "
            "materializes those"
        )
    if plan.script_file is not None:
        path = Path(plan.script_file.path)
        write_private_file(path.parent, path.name, plan.script_file.content.encode("utf-8"), WRAPPER_SCRIPT_MODE)
    return plan.command
