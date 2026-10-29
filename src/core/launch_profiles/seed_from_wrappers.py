
from __future__ import annotations

import shlex
from typing import Any, Dict, List

from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile, LaunchProfilesConfig
from src.core.agent_families import AGENT_FAMILY_BY_NAME

_SEED_PERMISSION_FLAGS = {"--dangerously-skip-permissions": "skip_all", "--yolo": "skip_all"}

_STRUCTURED_SEEDS = ("claude", "codex", "shell")


def _seed_structure(family: str, script: str) -> Dict[str, Any]:
    """The structured fields for a family's shipped seed script.

    Example: 'command claude --dangerously-skip-permissions "$@"' -> {"permissions": "skip_all", "flags": []}.
    """
    if family == "shell":
        return {"permissions": "harness_default", "flags": []}
    words = shlex.split(script.replace('"$@"', ""))
    if words and words[0] == "command":
        words = words[1:]
    permission, flags = "harness_default", []
    for word in words[1:]:
        if word in _SEED_PERMISSION_FLAGS:
            permission = _SEED_PERMISSION_FLAGS[word]
        else:
            flags.append(word)
    return {"permissions": permission, "flags": flags}


def profile_from_wrapper(wrapper: Dict[str, Any]) -> Dict[str, Any]:
    family = str(wrapper.get("family") or "claude")
    spec = AGENT_FAMILY_BY_NAME[family]
    script = wrapper.get("script") or ""
    entry = (wrapper.get("entry") or "").strip() or None
    fields: Dict[str, Any] = {
        "id": wrapper["id"], "harness": family, "label": wrapper.get("label") or wrapper["id"],
        "icon": wrapper.get("icon"), "description": wrapper.get("description"),
        "default": bool(wrapper.get("default")),
        "model": {"mode": "ask"} if wrapper.get("accepts_model") else {"mode": "default"},
        "shell_profile": spec.sources_zshrc,
    }
    if family in _STRUCTURED_SEEDS and entry is None and script == spec.default_script:
        fields.update(_seed_structure(family, script))
    else:
        fields["custom_command"] = {"script": script, "entry": entry}
        fields["custom_command_ack_no_args"] = '"$@"' not in script and entry is None
    return LaunchProfile.model_validate(fields).model_dump(mode="json")


def seed_launch_profiles(data: Dict[str, Any]) -> Dict[str, Any]:
    if LAUNCH_PROFILES_KEY in data:
        return data
    agents = data.get("agents")
    wrappers = agents.get("wrappers") if isinstance(agents, dict) else None
    profiles: List[Dict[str, Any]] = []
    seen_default = set()
    for wrapper in wrappers if isinstance(wrappers, list) else []:
        if not isinstance(wrapper, dict):
            continue
        profile = profile_from_wrapper(wrapper)
        if profile["default"] and profile["harness"] in seen_default:
            profile["default"] = False
        if profile["default"]:
            seen_default.add(profile["harness"])
        profiles.append(profile)
    block = LaunchProfilesConfig.model_validate({"revision": 0, "profiles": profiles})
    return {**data, LAUNCH_PROFILES_KEY: block.model_dump(mode="json")}
