
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.hosts.remote_host import RemoteHost
from src.core.hosts.ssh_exec import posix_quote
from src.core.sessions import launch_overlay

logger = structlog.get_logger()

_SETTINGS_SCRIPT = (
    'for f in "$HOME/.claude/settings.json" @DIR@/.claude/settings.json @DIR@/.claude/settings.local.json; '
    'do [ -f "$f" ] && { cat "$f"; printf "\\000"; }; done; true')


def session_ref_for(host_key: str, tmux_name: str) -> str:
    return f"remote:{host_key}:{tmux_name}"


async def far_settings_override(host: RemoteHost, far_dir: str) -> bool:
    from src.core.argent.overlay import text_overrides

    result = await host.exec(script=_SETTINGS_SCRIPT.replace("@DIR@", posix_quote(far_dir.rstrip("/"))))
    return any(text_overrides(part) for part in result.stdout_text.split("\x00"))


async def apply(host: RemoteHost, *, family: Optional[str], command: Optional[str], tmux_name: str, far_dir: str,
                label: Optional[str]) -> Tuple[Optional[str], Dict[str, str], str]:
    ref = session_ref_for(host.host_key, tmux_name)
    provider = launch_overlay.get()
    if provider is None or command is None or family not in ("claude", "codex"):
        return command, {}, ref
    await launch_overlay.prepare_host(host.host_key)
    plan = launch_overlay.plan_for(family, "pane", host.host_key)
    if plan is None:
        return command, {}, ref
    ctx = launch_overlay.OverlayContext(
        harness=family, session_ref=ref, working_dir=far_dir, display_name=label or tmux_name, host_key=host.host_key,
        settings_override=(await far_settings_override(host, far_dir)) if family == "claude" else False)
    delivery = await provider.materialize(plan, ctx)
    key = delivery.secrets.get(plan.secret_name, "")
    if not plan.preamble or not key or key == plan.direct_value:
        return command, {}, ref
    flags = "".join(" " + posix_quote(word) for word in plan.flags)
    return f"{plan.preamble}; exec {command}{flags}", {plan.secret_name: key}, ref


async def deliver(backend: Any, secrets: Dict[str, str]) -> None:
    if not secrets:
        return
    outcome = await backend.set_session_environment(f"={backend.tmux_session}", dict(secrets), note="launch_overlay_deliver")
    logger.info("remote_launch_overlay_delivered", host=backend.host_key, names=sorted(secrets), failed=len(outcome.failures))
