
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import structlog

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
    launch_line: Optional[str] = None,
    permission_hook: bool = False,
    approved_resume_prefixes: Sequence[str] = (),
) -> str:
    profiles = profiles_for(profiles, agents)
    scripts_dir = wrapper_scripts_dir(resolve_state_dir())
    base = LaunchRequest(
        profiles=profiles, agent_type=agent_type, explicit=explicit, model=model,
        model_is_explicit=model_is_explicit,
        scripts_dir=scripts_dir, disable_alternate_screen=disable_alternate_screen(), connections=tuple(connections),
    )
    profile = pick_profile(base)
    harness = profile.harness
    app_args = list(extra_args or [])
    custom_resume_id = app_args[app_args.index("--resume") + 1] if harness == "custom" and "--resume" in app_args[:-1] else None
    if harness == DEFAULT_FAMILY:
        app_args = single_name_flag(app_args)
        app_args = mcp_config_args() + app_args
        if launch_line:
            from src.core.pack.jobs.launch_line import add_to_args
            app_args = add_to_args(app_args, launch_line)
        if launch_line or permission_hook:
            from src.core.beast_prompts.launch_hooks import add_hooks
            app_args = add_hooks(app_args, delegate=bool(launch_line), permission=permission_hook)
        if carnivore_mcp_url:
            app_args = mcp_launch.claude_args(channel=carnivore_mcp_channel) + app_args
    elif harness == "codex" and carnivore_mcp_url:
        app_args = mcp_launch.codex_args(carnivore_mcp_url) + app_args
    elif harness == "custom":
        from src.core.agy.identity import is_agy_profile

        app_args = _agy_safe_args(app_args) if is_agy_profile(profile) else []
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
    from src.core.agy.launch import wrap_command

    return wrap_command(profile, _custom_resume(profile, plan.command, custom_resume_id, approved_resume_prefixes), launch_line)


_AGY_MODES = frozenset({"accept-edits", "auto", "plan"})


def _agy_safe_args(args: Sequence[str]) -> List[str]:
    from src.models.model_ids import is_valid_model_id

    out: List[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--dangerously-skip-permissions":
            out.append(tok)
            i += 1
        elif tok == "--mode" and i + 1 < len(args) and args[i + 1] in _AGY_MODES:
            out.extend((tok, args[i + 1]))
            i += 2
        elif tok == "--model" and i + 1 < len(args) and is_valid_model_id(args[i + 1]):
            out.extend((tok, args[i + 1]))
            i += 2
        elif tok == "--prompt-interactive" and i + 1 < len(args) and args[i + 1] and "\0" not in args[i + 1]:
            out.extend((tok, args[i + 1]))
            i += 2
        else:
            i += 1
    return out


def _custom_resume(profile: LaunchProfile, command: str, resume_id: Optional[str], approved: Sequence[str]) -> str:
    from src.core.launch_profiles.agent_resume import ResumePrefixNotApproved, resume_command
    from src.core.shell_init import rc_prefixed

    if not resume_id or profile.agent is None:
        return command
    try:
        resumed = resume_command(profile.agent, resume_id, approved)
    except ResumePrefixNotApproved as exc:
        structlog.get_logger().warning("custom_resume_prefix_not_approved", profile=profile.id, prefix=exc.prefix)
        return command
    if resumed is None:
        return command
    return rc_prefixed(resumed) if profile.shell_profile else resumed
