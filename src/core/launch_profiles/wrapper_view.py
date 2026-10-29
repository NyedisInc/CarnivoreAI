
from __future__ import annotations

import shlex
from typing import Any, Dict, List, Mapping, Sequence

from src.config.launch_profiles import LaunchProfile
from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.launch_profiles.permissions import permission_flags
from src.core.launch_profiles.seed_from_wrappers import profile_from_wrapper


def structured_script(profile: LaunchProfile) -> str:
    """The wrapper script a structured profile is equivalent to (permissions, flags and a fixed model).

    Example: a claude skip_all profile -> 'command claude --dangerously-skip-permissions "$@"'
    """
    spec = AGENT_FAMILY_BY_NAME[profile.harness]
    if profile.harness == "shell":
        return spec.default_script
    words = [*permission_flags(profile.harness, profile.permissions), *profile.flags]
    if profile.model.mode == "fixed":
        words += ["--model" if profile.harness == "claude" else "-m", profile.model.value or ""]
    tail = " ".join(shlex.quote(w) for w in words)
    if profile.harness == "claude":
        return " ".join(["command claude", tail, '"$@"']) if tail else 'command claude "$@"'
    return " ".join(['codex "$@"', tail]) if tail else 'codex "$@"'


def wrapper_from_profile(profile: LaunchProfile) -> Dict[str, Any]:
    custom = profile.custom_command
    return {
        "id": profile.id,
        "family": profile.harness,
        "label": profile.label,
        "script": custom.script if custom else structured_script(profile),
        "entry": (custom.entry or None) if custom else None,
        "description": profile.description,
        "default": profile.default,
        "accepts_model": profile.model.mode == "ask",
        "icon": profile.icon,
    }


def wrappers_from_profiles(profiles: Sequence[LaunchProfile]) -> List[Dict[str, Any]]:
    return [wrapper_from_profile(p) for p in profiles]


def _carry_over(existing: LaunchProfile, wrapper: Mapping[str, Any]) -> Dict[str, Any]:
    fields = existing.model_dump(mode="json")
    fields.update(label=wrapper["label"], description=wrapper.get("description"), icon=wrapper.get("icon"),
                  default=bool(wrapper.get("default")))
    asks = bool(wrapper.get("accepts_model"))
    if asks != (existing.model.mode == "ask"):
        fields["model"] = {"mode": "ask"} if asks else {"mode": "default"}
    return fields


def profiles_from_wrappers(wrappers: Sequence[Mapping[str, Any]], existing: Sequence[LaunchProfile]) -> List[Dict[str, Any]]:
    by_id = {p.id: p for p in existing}
    out: List[Dict[str, Any]] = []
    for wrapper in wrappers:
        old = by_id.get(wrapper["id"])
        shown = wrapper_from_profile(old) if old else None
        if old and shown["script"] == wrapper["script"] and (shown["entry"] or None) == (wrapper.get("entry") or None) \
                and old.harness == (wrapper.get("family") or "claude"):
            out.append(LaunchProfile.model_validate(_carry_over(old, wrapper)).model_dump(mode="json"))
        elif old and old.custom_command is not None and old.harness == (wrapper.get("family") or "claude"):
            fields = _carry_over(old, wrapper)
            entry = (wrapper.get("entry") or "").strip() or None
            fields["custom_command"] = {"script": wrapper["script"], "entry": entry}
            fields["custom_command_ack_no_args"] = '"$@"' not in wrapper["script"] and entry is None
            out.append(LaunchProfile.model_validate(fields).model_dump(mode="json"))
        else:
            out.append(profile_from_wrapper(dict(wrapper)))
    return out
