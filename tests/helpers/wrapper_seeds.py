
from __future__ import annotations

from typing import List

from src.core.agent_families import AGENT_FAMILY_BY_NAME


def is_standard_seed(wrapper) -> bool:
    if not isinstance(wrapper, dict):
        return False
    family = AGENT_FAMILY_BY_NAME.get(wrapper.get("family") or "")
    return (
        family is not None
        and wrapper.get("script") == family.default_script
        and str(wrapper.get("description") or "").startswith("the standard ")
    )


def without_standard_seeds(wrappers) -> List:
    return [w for w in wrappers if not is_standard_seed(w)]


def stored_wrappers(document) -> List:
    from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfilesConfig
    from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
    from src.core.launch_profiles.wrapper_view import wrappers_from_profiles

    block = seed_launch_profiles(document)[LAUNCH_PROFILES_KEY]
    return wrappers_from_profiles(LaunchProfilesConfig.model_validate(block).profiles)


def launches(command: str, script_name: str) -> bool:
    from src.core.agent_families import AGENT_FAMILIES

    inline = {f"{f.default_wrapper_id}.zsh": f.default_script for f in AGENT_FAMILIES if f.name in ("claude", "codex", "shell")}
    return script_name in command or (script_name in inline and inline[script_name] in command)
