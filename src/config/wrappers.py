
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfilesConfig
from src.config.launch_profiles_lenient import LoadedProfiles, kept_entries, load_profiles
from src.core import config_writer
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.launch_profiles.wrapper_view import profiles_from_wrappers, wrappers_from_profiles
from src.core.launch_wrappers.family_defaults import ensure_family_defaults


class WrapperRefused(ValueError):
    pass


def _loaded_of(data: Dict[str, Any]) -> LoadedProfiles:
    return load_profiles(seed_launch_profiles(data)[LAUNCH_PROFILES_KEY])


def _with_wrappers(
    data: Dict[str, Any], loaded: LoadedProfiles, wrappers: List[dict]
) -> Tuple[Dict[str, Any], LaunchProfilesConfig]:
    block = loaded.block
    try:
        profiles = profiles_from_wrappers(wrappers, block.profiles)
        checked = LaunchProfilesConfig.model_validate({"revision": block.revision + 1, "profiles": profiles})
    except ValidationError as exc:
        raise WrapperRefused(str(exc.errors()[0].get("msg", "invalid"))) from None
    out = checked.model_dump(mode="json")
    out["profiles"].extend(kept_entries(loaded, checked.profiles))
    return {**data, LAUNCH_PROFILES_KEY: out}, checked


def mutate(
    config_path: Path, mutation: Callable[[List[dict]], List[dict]]
) -> List[dict]:
    written: List[dict] = []

    def merge(data: dict) -> dict:
        loaded = _loaded_of(data)
        block = loaded.block
        current = ensure_family_defaults(wrappers_from_profiles(block.profiles))
        updated, checked = _with_wrappers(data, loaded, ensure_family_defaults(mutation(current)))
        written.clear()
        written.extend(wrappers_from_profiles(checked.profiles))
        return updated

    config_writer.commit(config_path, merge)
    return written


def ensure_defaults(config_path: Path) -> bool:
    def seed(data: dict) -> Optional[dict]:
        if not isinstance(data, dict):
            return None
        if LAUNCH_PROFILES_KEY not in data:
            agents_data = data.get("agents")
            if agents_data is not None and not isinstance(agents_data, dict):
                return None
            if not isinstance((agents_data or {}).get("wrappers") or [], list):
                return None
        loaded = _loaded_of(data)
        before = wrappers_from_profiles(loaded.block.profiles)
        after = ensure_family_defaults(before)
        if after == before:
            return None
        return _with_wrappers(data, loaded, after)[0]

    return config_writer.commit(config_path, seed).wrote
