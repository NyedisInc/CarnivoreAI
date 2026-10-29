
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from src.config.launch_profiles import LaunchProfile
from src.core.agent_families import INTERACTIVE_SHELL
from src.core.agent_wrappers import _DISABLE_ALTERNATE_SCREEN, render_script_invocation
from src.core.launch_profiles.permissions import permission_flags
from src.core.desktop_app.payload_bytecode import bytecode_flags
from src.core.shell_init import rc_prefixed

STAGING_PREFIX = "CARNIVORE_LAUNCH_SECRET_"

_MODEL_FLAG = {"claude": "--model", "codex": "-m"}


def secret_preamble(secret_names: Sequence[str]) -> str:
    staged = [f"{STAGING_PREFIX}{i}" for i in range(len(secret_names))]
    exports = [f'export {name}="${stage}"' for name, stage in zip(secret_names, staged)]
    return "; ".join(exports + ([f"unset {' '.join(staged)}"] if staged else []))


def env_preamble(env_set: Sequence[Tuple[str, str]], env_unset: Sequence[str], secret_names: Sequence[str]) -> str:
    steps: List[str] = []
    if env_unset:
        steps.append("unset " + " ".join(env_unset))
    steps += [f"export {name}={shlex.quote(value)}" for name, value in env_set]
    if secret_names:
        steps.append(secret_preamble(secret_names))
    return "; ".join(steps)


def render_custom(entry: Optional[str], script_path: Path, model: Optional[str], app_args: Sequence[str],
                  disable_alternate_screen: bool, source_rc: bool, secret_names: Sequence[str] = (),
                  env_set: Sequence[Tuple[str, str]] = (), env_unset: Sequence[str] = ()) -> str:
    return render_script_invocation(
        script_path, entry, model=model, extra_args=list(app_args),
        disable_alternate_screen=disable_alternate_screen, source_rc=source_rc,
        preamble=env_preamble(env_set, env_unset, secret_names),
    )


def _codex_supervisor_body(profile: LaunchProfile, model: Optional[str], app_args: Sequence[str],
                           extra_flags: Sequence[str], codex_server_args: Sequence[str]) -> str:
    from src.core.crosstalk import codex_supervisor

    fresh = all(arg in ("--dangerously-bypass-approvals-and-sandbox", "--no-alt-screen")
                for arg in app_args)
    bypass = "--dangerously-bypass-approvals-and-sandbox"
    server_args = [*codex_server_args, *extra_flags]
    remote_policy = None
    if profile.permissions == "skip_all" or bypass in app_args:
        server_args += ["-c", 'approval_policy="never"',
                        "-c", 'sandbox_mode="danger-full-access"']
        remote_policy = {"approvalPolicy": "never", "sandbox": "danger-full-access"}
    elif profile.permissions == "ask":
        server_args += ["-c", 'approval_policy="on-request"']
        remote_policy = {"approvalPolicy": "on-request"}
    tui_args = [*(arg for arg in app_args if arg != bypass),
                *profile.flags, *extra_flags]
    if model:
        tui_args += ["-m", model]
    spec = json.dumps({"server": server_args, "tui": tui_args, "policy": remote_policy,
                       "model": model,
                       "bootstrap": {"model": model} if fresh else None}, separators=(",", ":"))
    script = shlex.quote(str(Path(codex_supervisor.__file__).resolve()))
    return " ".join((shlex.quote(sys.executable), *map(shlex.quote, bytecode_flags()), script, shlex.quote(spec)))


def render_structured(profile: LaunchProfile, model: Optional[str], app_args: Sequence[str],
                      disable_alternate_screen: bool, extra_flags: Sequence[str] = (),
                      secret_names: Sequence[str] = (), env_set: Sequence[Tuple[str, str]] = (),
                      env_unset: Sequence[str] = (), codex_server_args: Sequence[str] = (),
                      codex_fallback: Optional[Path] = None, fallback_args: Sequence[str] = (),
                      refuse_fallback: bool = False) -> str:
    harness = profile.harness
    permissions = list(permission_flags(harness, profile.permissions))
    flags = [*permissions, *profile.flags, *extra_flags]
    if harness == "shell":
        if flags or model:
            raise ValueError("a shell launch takes no flags and no model")
        body = f'exec {INTERACTIVE_SHELL} "$@"'
    else:
        if model:
            flags += [_MODEL_FLAG[harness], model]
        words = " ".join(shlex.quote(t) for t in flags)
        if harness == "claude":
            body = " ".join(["command claude", words, '"$@"']) if words else 'command claude "$@"'
        elif codex_server_args:
            body = _codex_supervisor_body(profile, model, app_args, extra_flags, codex_server_args)
        else:
            body = " ".join(['codex "$@"', words]) if words else 'codex "$@"'
        if codex_fallback is not None:
            fallback = ("print -u2 -- 'Codex resolves to an alias or function; "
                        "this requested model needs a native Codex profile'; exit 1") if refuse_fallback else (
                            f"source {shlex.quote(str(codex_fallback))} \"$@\"")
            body = ("if [[ \"$(whence -w codex 2>/dev/null)\" == 'codex: command' ]]; then "
                    f"{body}; else {fallback}; fi")
    steps: List[str] = []
    preamble = env_preamble(env_set, env_unset, secret_names)
    if preamble:
        steps.append(preamble)
    if disable_alternate_screen:
        steps.append(_DISABLE_ALTERNATE_SCREEN)
    if profile.before_launch and profile.before_launch.strip():
        steps.append(profile.before_launch.strip())
    steps.append(body)
    inner = "; ".join(steps)
    outer = rc_prefixed(inner) if profile.shell_profile else f"zsh -c {shlex.quote(inner)}"
    args = ([a for a in fallback_args if a] if codex_fallback is not None else
            [a for a in app_args if a and not (codex_server_args and a == "--dangerously-bypass-approvals-and-sandbox")])
    return outer + (" _ " + " ".join(shlex.quote(a) for a in args) if args else "")
