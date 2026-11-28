
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from src.config import settings
from src.core.agy.identity import agy_profile_id
from src.core.plugin_studio.errors import (
    AgyProfileNotConfiguredError,
    StudioActionError,
    WorkspaceValidationError,
)
from src.models.blueprints import check_opening_prompt
from src.models.session_requests import CreateSessionRequest

AGENT_KINDS = ("claude", "codex", "agy")
SessionCreator = Callable[[CreateSessionRequest], Awaitable[Any]]


def resolve_agent_type(agent_kind: str) -> str:
    kind = (agent_kind or "").strip().lower()
    if kind not in AGENT_KINDS:
        raise WorkspaceValidationError(
            f"agent_kind must be one of {', '.join(AGENT_KINDS)}",
            code="invalid_agent_kind",
        )
    if kind in ("claude", "codex"):
        return kind
    profile_id = agy_profile_id(settings.get_launch_profiles())
    if not profile_id:
        raise AgyProfileNotConfiguredError()
    return profile_id


def build_opening_prompt(workspace: Dict[str, Any], *, override_prompt: Optional[str] = None) -> str:
    plugin_id = str(workspace.get("plugin_id") or "plugin")
    template = str(workspace.get("template") or "python")
    goal = (override_prompt or workspace.get("prompt") or "Implement the Carnivore plugin described in STUDIO_BRIEF.md.").strip()
    raw = (
        f"Read STUDIO_BRIEF.md in this workspace and build the {plugin_id} ({template}) Carnivore plugin. "
        f"Goal: {goal}. Keep carnivore plugin dev running while editing and satisfy Warez readiness checks."
    )
    encoded = raw.encode("utf-8")
    if len(encoded) > 4000:
        raw = encoded[:4000].decode("utf-8", errors="ignore").rstrip()
    try:
        checked = check_opening_prompt(raw)
    except ValueError as exc:
        raise WorkspaceValidationError(str(exc), code="invalid_opening_prompt") from exc
    if not checked:
        raise WorkspaceValidationError("opening_prompt cannot be empty", code="invalid_opening_prompt")
    return checked


async def launch_agent_session(
    workspace: Dict[str, Any],
    *,
    agent_kind: str,
    session_creator: SessionCreator,
    prompt_override: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_agent_type = resolve_agent_type(agent_kind)
    opening_prompt = build_opening_prompt(workspace, override_prompt=prompt_override)
    plugin_id = str(workspace.get("plugin_id") or "plugin")
    body = CreateSessionRequest(
        working_dir=str(workspace["folder"]),
        auto_start_claude=True,
        copy_templates=False,
        project_name=f"studio-{plugin_id}",
        label=f"Studio: {plugin_id}",
        agent_type=resolved_agent_type,
        opening_prompt=opening_prompt,
    )
    created = await session_creator(body)
    if isinstance(created, dict):
        session_id = created.get("id")
        tmux_session = created.get("tmux_session")
        agent_type_out = created.get("agent_type") or resolved_agent_type
    else:
        session_id = getattr(created, "id", None)
        tmux_session = getattr(created, "tmux_session", None)
        agent_type_out = getattr(created, "agent_type", None) or resolved_agent_type
    if not session_id:
        raise StudioActionError(502, "studio_session_create_failed", "Session creator returned no session id.")
    return {
        "session_id": str(session_id),
        "tmux_session": str(tmux_session) if tmux_session else None,
        "agent_kind": agent_kind,
        "agent_type": str(agent_type_out),
        "opening_prompt": opening_prompt,
    }
