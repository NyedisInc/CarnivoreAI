
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfilesConfig
from src.core import config_writer
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.launch_profiles.wrapper_view import profiles_from_wrappers, wrappers_from_profiles
from src.core.launch_wrappers.family_defaults import ensure_family_defaults


class WrapperRefused(ValueError):
    pass


def _block_of(data: Dict[str, Any]) -> LaunchProfilesConfig:
    return LaunchProfilesConfig.model_validate(seed_launch_profiles(data)[LAUNCH_PROFILES_KEY])


def _with_wrappers(data: Dict[str, Any], block: LaunchProfilesConfig, wrappers: List[dict]) -> Dict[str, Any]:
    try:
        profiles = profiles_from_wrappers(wrappers, block.profiles)
        checked = LaunchProfilesConfig.model_validate({"revision": block.revision + 1, "profiles": profiles})
    except ValidationError as exc:
        raise WrapperRefused(str(exc.errors()[0].get("msg", "invalid"))) from None
    return {**data, LAUNCH_PROFILES_KEY: checked.model_dump(mode="json")}


def mutate(
    config_path: Path, mutation: Callable[[List[dict]], List[dict]]
) -> List[dict]:
    written: List[dict] = []

    def merge(data: dict) -> dict:
        block = _block_of(data)
        current = ensure_family_defaults(wrappers_from_profiles(block.profiles))
        updated = _with_wrappers(data, block, ensure_family_defaults(mutation(current)))
        written.clear()
        written.extend(wrappers_from_profiles(LaunchProfilesConfig.model_validate(updated[LAUNCH_PROFILES_KEY]).profiles))
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
        block = _block_of(data)
        before = wrappers_from_profiles(block.profiles)
        after = ensure_family_defaults(before)
        if after == before:
            return None
        return _with_wrappers(data, block, after)

    return config_writer.commit(config_path, seed).wrote
