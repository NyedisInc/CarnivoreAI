
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from src.config.launch_profiles import LaunchProfile
from src.config import mcp_launch
from src.core.agent_families import (
    AGENT_FAMILY_BY_NAME,
    DEFAULT_FAMILY,
    RESERVED_FAMILY_NAMES,
)
from src.core.byoai.contracts import Connection
from src.core.launch_profiles.endpoints import EndpointLaunch, UnsupportedEndpoint, endpoint_launch
from src.core.launch_profiles.plan import PURPOSES, LaunchDisplay, LaunchPlan, Purpose, ScriptFile
from src.core.launch_profiles.render import render_custom, render_structured
from src.core.agy.identity import is_agy_profile
from src.core.sessions import launch_overlay
from src.core.launch_profiles.seed_from_wrappers import profile_from_wrapper
from src.core.launch_wrappers.family_defaults import standard_wrapper

_CODEX_NO_ALT_SCREEN = "--no-alt-screen"


class LaunchProfileNotFound(LookupError):

    codes = ("wrapper_needed", "launch_profile_needed")

    def __init__(self, profile_id: str) -> None:
        super().__init__(f"launch profile {profile_id!r} does not exist")
        self.profile_id = profile_id


@dataclass(frozen=True)
class LaunchRequest:

    profiles: Tuple[LaunchProfile, ...]
    agent_type: Optional[str] = None
    explicit: bool = False
    model: Optional[str] = None
    model_is_explicit: bool = False
    app_args: Tuple[str, ...] = ()
    scripts_dir: Path = Path(".")
    disable_alternate_screen: bool = False
    connections: Tuple[Connection, ...] = ()


def default_profile(profiles: Sequence[LaunchProfile], harness: str) -> LaunchProfile:
    own = [p for p in profiles if p.harness == harness]
    for p in own:
        if p.default:
            return p
    if own:
        return own[0]
    return LaunchProfile.model_validate(profile_from_wrapper(standard_wrapper(AGENT_FAMILY_BY_NAME[harness], ())))


def pick_profile(request: LaunchRequest) -> LaunchProfile:
    normalized = (request.agent_type or DEFAULT_FAMILY).lower()
    if normalized in RESERVED_FAMILY_NAMES:
        return default_profile(request.profiles, normalized)
    for p in request.profiles:
        if p.id == normalized:
            return p
    if request.explicit:
        raise LaunchProfileNotFound(normalized)
    return default_profile(request.profiles, DEFAULT_FAMILY)


def _digest(profile: LaunchProfile) -> str:
    blob = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _transparent_codex_yolo(profile: LaunchProfile) -> bool:
    command = profile.custom_command
    return (profile.harness == "codex" and profile.model.mode == "default"
            and profile.permissions == "harness_default" and command is not None
            and profile.endpoint.mode == "native" and not profile.flags
            and not (profile.before_launch or "").strip()
            and command.entry is None and command.script.strip() == 'codex --yolo "$@"')


def _transparent_claude(profile: LaunchProfile) -> bool:
    command = profile.custom_command
    return (profile.harness == "claude" and profile.model.mode == "default"
            and profile.permissions == "harness_default" and command is not None
            and profile.endpoint.mode == "native" and not profile.flags
            and not (profile.before_launch or "").strip()
            and command.entry is None and command.script.strip() in ('claude "$@"', 'command claude "$@"'))


def _model_for(profile: LaunchProfile, requested: Optional[str], transparent_codex: bool = False,
               explicit: bool = False) -> Optional[str]:
    if profile.model.mode == "fixed":
        return profile.model.value
    if profile.model.mode == "ask":
        return (requested or "").strip() or None
    wanted = (requested or "").strip() or None
    if wanted and explicit and profile.custom_command is not None and not transparent_codex and profile.harness != "custom":
        raise ValueError(f"launch profile {profile.id!r} uses an opaque custom command and cannot apply a requested "
                         "model; choose a structured profile or a model-aware custom profile")
    if (profile.custom_command is None and profile.harness in ("claude", "codex")) or transparent_codex:
        return wanted
    return None


def _endpoint_for(profile: LaunchProfile, request: LaunchRequest, model: Optional[str]) -> Optional[EndpointLaunch]:
    if profile.endpoint.mode != "connection":
        return None
    if profile.custom_command is not None:
        raise UnsupportedEndpoint("a custom command owns its own environment and cannot also use a connection")
    wanted = profile.endpoint.connection_id
    connection = next((c for c in request.connections if c.id == wanted), None)
    endpoint = endpoint_launch(profile.harness, connection, model, wanted or "")
    taken = {row.name for row in (*profile.env, *profile.secrets)}
    clash = taken & ({n for n, _ in endpoint.env_set} | {n for n, _ in endpoint.secret_refs} | set(endpoint.env_unset))
    if clash:
        raise UnsupportedEndpoint(f"the profile sets {sorted(clash)[0]} by hand, and the connection owns it")
    return endpoint


def _split_codex_server_args(app_args: list[str]) -> tuple[tuple[str, ...], list[str]]:
    expected = len(mcp_launch.codex_args(""))
    key_prefix = f"mcp_servers.{mcp_launch.SERVER_NAME}."
    pairs = list(zip(app_args[0::2], app_args[1::2]))
    carnivore_pairs = 0
    for flag, value in pairs:
        if flag != "-c" or not value.startswith(key_prefix):
            break
        carnivore_pairs += 1
    if carnivore_pairs * 2 < expected:
        return (), app_args
    server_args = app_args[:carnivore_pairs * 2]
    rest = app_args[carnivore_pairs * 2:]
    while len(rest) >= 2 and rest[0] == "-c":
        server_args.extend(rest[:2])
        rest = rest[2:]
    return tuple(server_args), rest


def _own_route(harness: str, env_set: tuple, secret_names: list, endpoint_flags: tuple) -> Optional[launch_overlay.UpstreamRoute]:
    if harness == "claude":
        base = dict(env_set).get("ANTHROPIC_BASE_URL", "").strip()
        key = next((n for n in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if n in secret_names), "")
        return launch_overlay.UpstreamRoute(base, key) if base else None
    words = {k: v for k, v in (w.split("=", 1) for w in endpoint_flags if "=" in w)}
    base_key = next((k for k in words if k.startswith("model_providers.") and k.endswith(".base_url")), "")
    if not base_key:
        return None
    env_key = words.get(base_key[:-len("base_url")] + "env_key", "")
    return launch_overlay.UpstreamRoute(json.loads(words[base_key]), json.loads(env_key) if env_key else "", tuple(endpoint_flags))


def runs_copilot(profile: LaunchProfile) -> bool:
    if profile.harness != "custom":
        return False
    words = (profile.custom_command.script if profile.custom_command else "").split()
    return (words[:1] == ["copilot"]) or (profile.agent is not None and profile.agent.process == "copilot")


def custom_tool(profile: LaunchProfile) -> str:
    if profile.harness != "custom":
        return ""
    return "copilot" if runs_copilot(profile) else "agy" if is_agy_profile(profile) else ""


def resolve_launch(request: LaunchRequest, purpose: Purpose = "pane") -> LaunchPlan:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    profile = pick_profile(request)
    transparent_codex = _transparent_codex_yolo(profile)
    launch_profile = profile.model_copy(update={"custom_command": None, "permissions": "skip_all"}) if transparent_codex else profile
    if profile.account.mode != "follow_active":
        raise NotImplementedError("a pinned account is resolved by S4 (account home)")
    family = AGENT_FAMILY_BY_NAME[profile.harness]
    if family.needs_model and not (request.model and str(request.model).strip()):
        raise ValueError(
            f"the '{family.name}' agent needs a model and none was given; "
            "pick one from the launch modal rather than launching bare"
        )
    transparent_claude = _transparent_claude(profile)
    model = _model_for(profile, request.model, transparent_codex or transparent_claude, request.model_is_explicit)
    endpoint = _endpoint_for(launch_profile, request, model)
    if endpoint is not None:
        model = endpoint.model
    app_args = list(request.app_args)
    if transparent_claude and model:
        app_args = ["--model", model, *app_args]
        model = None
    fallback_args = list(app_args)
    if transparent_codex and request.disable_alternate_screen:
        fallback_args.append(_CODEX_NO_ALT_SCREEN)
    codex_server_args: tuple[str, ...] = ()
    if profile.harness == "codex" and launch_profile.custom_command is None:
        codex_server_args, app_args = _split_codex_server_args(app_args)
    if profile.harness == "codex" and request.disable_alternate_screen:
        app_args.append(_CODEX_NO_ALT_SCREEN)
    secret_refs = (*((r.name, r.keychain_ref) for r in profile.secrets), *(endpoint.secret_refs if endpoint else ()))
    secret_names = [name for name, _ in secret_refs]
    env_set = (*((row.name, row.value) for row in profile.env), *(endpoint.env_set if endpoint else ()))
    env_unset = endpoint.env_unset if endpoint else ()
    overlay = None
    if profile.harness in ("claude", "codex") and launch_profile.custom_command is None:
        route = _own_route(profile.harness, env_set, secret_names, endpoint.flags if endpoint else ())
        overlay = (launch_overlay.chain_plan_for(profile.harness, purpose, route) if route is not None
                   else launch_overlay.plan_for(profile.harness, purpose) if endpoint is None else None)
    if overlay is None and custom_tool(profile):
        overlay = launch_overlay.plan_for(custom_tool(profile), purpose)
    script_file: Optional[ScriptFile] = None
    if launch_profile.custom_command is not None:
        path = request.scripts_dir / f"{profile.id}.zsh"
        script_file = ScriptFile(str(path), profile.custom_command.script)
        command = render_custom(profile.custom_command.entry, path, model, app_args, request.disable_alternate_screen,
                                profile.shell_profile, secret_names, env_set, env_unset, overlay.preamble if overlay else "")
        tail = ([model] if model else []) + [a for a in app_args if a]
    else:
        if transparent_codex:
            path = request.scripts_dir / f"{profile.id}.zsh"
            script_file = ScriptFile(str(path), profile.custom_command.script)
        command = render_structured(launch_profile, model, app_args, request.disable_alternate_screen,
                                    (*(endpoint.flags if endpoint and not (overlay and overlay.replaces_flags) else ()), *(overlay.flags if overlay else ())), secret_names, env_set, env_unset,
                                    codex_server_args, path if transparent_codex else None,
                                    fallback_args, request.model_is_explicit and bool(model),
                                    overlay.preamble if overlay else "")
        tail = [a for a in app_args if a]
    return LaunchPlan(
        command=command,
        argv_tail=tuple(tail),
        env_set=env_set,
        env_unset=env_unset,
        secret_refs=tuple(secret_refs),
        display=LaunchDisplay(
            label=profile.label, harness=profile.harness,
            account=profile.account.account_id or "follow_active",
            model=model or profile.model.mode, permissions=launch_profile.permissions,
            endpoint=endpoint.label if endpoint else "", key_hint=endpoint.key_hint if endpoint else "",
        ),
        digest=_digest(profile),
        purpose=purpose,
        script_file=script_file,
        profile_id=profile.id,
        account_mode=profile.account.mode,
        connection_id=(profile.endpoint.connection_id or "") if endpoint else "",
        overlay=overlay,
    )
