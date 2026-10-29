
from __future__ import annotations

from typing import Dict, List, Tuple

from src.core.agent_families import AGENT_FAMILIES, wrappers_for_family
from src.core.launch_wrappers.family_defaults import (
    ensure_family_defaults,
    same_launch,
    script_from_command,
    standard_wrapper,
    unique_id,
)

LEGACY_COMMANDS: Dict[str, Tuple[str, str]] = {
    "claude": ("claude_command", ""),
    "codex": ("codex_command", "codex"),
    "hermes": ("hermes_command", "hermes"),
    "openclaw": ("openclaw_command", "openclaw tui"),
    "local": ("local_command", "cldl"),
    "shell": ("shell_command", "$SHELL -i"),
}


def customised_command(agents: dict, family_name: str) -> str:
    key, shipped = LEGACY_COMMANDS[family_name]
    raw = agents.get(key)
    if not isinstance(raw, str):
        return ""
    value = raw.strip()
    return "" if value == shipped.strip() else value


def _folded_wrapper(family, command: str, *, default: bool, taken) -> dict:
    key = LEGACY_COMMANDS[family.name][0]
    wrapper = standard_wrapper(family, ())
    base = family.default_wrapper_id if default else f"{family.name}-legacy"
    wrapper.update({
        "id": unique_id(base, taken),
        "label": family.default_label if default else f"{family.name} (legacy command)",
        "script": script_from_command(family.name, command),
        "default": default,
        "description": (
            f"moved here from the retired agents.{key} setting."
            if default else
            f"kept from the retired agents.{key} setting, which no launch "
            f"read: this family already had wrappers."
        ),
    })
    return wrapper


def fold_legacy_commands(data: Dict) -> Dict:
    agents = data.get("agents")
    if agents is None:
        agents = {}
    if not isinstance(agents, dict):
        return dict(data)
    wrappers = agents.get("wrappers")
    if wrappers is None:
        wrappers = []
    if not isinstance(wrappers, list):
        return dict(data)

    result: List = [dict(w) if isinstance(w, dict) else w for w in wrappers]
    for family in AGENT_FAMILIES:
        if not family.seeded:
            continue
        command = customised_command(agents, family.name)
        if not command:
            continue
        own = wrappers_for_family([w for w in result if isinstance(w, dict)], family.name)
        if own and any(same_launch(command, w.get("script", "")) for w in own):
            continue
        taken = [w.get("id") for w in result if isinstance(w, dict)]
        result.append(_folded_wrapper(family, command, default=not own, taken=taken))

    new_agents = dict(agents)
    new_agents["wrappers"] = ensure_family_defaults(result)
    new_data = dict(data)
    new_data["agents"] = new_agents
    return new_data
