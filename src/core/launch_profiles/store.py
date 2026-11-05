
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog
from pydantic import ValidationError

from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile, LaunchProfilesConfig
from src.config.launch_profiles_lenient import LoadedProfiles, kept_entries, load_profiles
from src.core import config_writer

logger = structlog.get_logger()


class LaunchProfileError(Exception):
    pass


class NotFound(LaunchProfileError):
    pass


class StaleRevision(LaunchProfileError):
    pass


def normalize_defaults(block: LaunchProfilesConfig, preferred_id: Optional[str] = None) -> None:
    for harness in {p.harness for p in block.profiles}:
        own = [p for p in block.profiles if p.harness == harness]
        flagged = [p for p in own if p.default]
        keep = next((p for p in own if p.id == preferred_id), None) or (flagged or own)[0]
        for p in own:
            p.default = p is keep


class LaunchProfileStore:

    def __init__(self, config_path: Path) -> None:
        self._path = Path(config_path)

    @staticmethod
    def _loaded(data: Mapping[str, Any]) -> LoadedProfiles:
        try:
            return load_profiles(data.get(LAUNCH_PROFILES_KEY) or {})
        except ValidationError:
            raise LaunchProfileError("the launch_profiles block in config.json is invalid") from None

    @classmethod
    def _block(cls, data: Mapping[str, Any]) -> LaunchProfilesConfig:
        return cls._loaded(data).block

    def read_all(self) -> LoadedProfiles:
        return self._loaded(config_writer.read_config(self._path))

    def read(self) -> LaunchProfilesConfig:
        return self.read_all().block

    def list(self) -> List[LaunchProfile]:
        return self.read().profiles

    def get(self, profile_id: str) -> LaunchProfile:
        for item in self.read().profiles:
            if item.id == profile_id:
                return item
        raise NotFound(f"no launch profile {profile_id}")

    def _write(self, change: Callable[[LaunchProfilesConfig], Optional[str]],
               expected_revision: Optional[int], *, drop_set_aside: Optional[str] = None) -> LaunchProfilesConfig:
        def precondition(data: Dict[str, Any]) -> Optional[str]:
            if expected_revision is not None and self._block(data).revision != expected_revision:
                return config_writer.STALE_REVISION
            return None

        def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
            loaded = self._loaded(data)
            block = loaded.block
            preferred = change(block)
            normalize_defaults(block, preferred)
            block.revision += 1
            try:
                checked = LaunchProfilesConfig.model_validate(block.model_dump())
            except ValidationError as exc:
                raise LaunchProfileError(str(exc.errors()[0].get("msg", "invalid"))) from None
            out = checked.model_dump(mode="json")
            out["profiles"].extend(kept_entries(loaded, checked.profiles, drop_set_aside))
            return {**data, LAUNCH_PROFILES_KEY: out}

        outcome = config_writer.commit(self._path, mutate, precondition=precondition)
        if outcome.status == config_writer.STALE_REVISION:
            raise StaleRevision(f"launch_profiles revision is {self._block(outcome.data).revision}")
        if not outcome.wrote:
            raise LaunchProfileError(f"config write did not land ({outcome.status})")
        return self._block(outcome.data)

    def approve_resume_prefix(self, prefix: str) -> LaunchProfilesConfig:

        def change(block: LaunchProfilesConfig) -> Optional[str]:
            if prefix not in block.approved_resume_prefixes:
                block.approved_resume_prefixes.append(prefix)
            return None

        return self._write(change, None)

    def put(self, profile: LaunchProfile, *, expected_revision: Optional[int] = None) -> LaunchProfilesConfig:
        def change(block: LaunchProfilesConfig) -> Optional[str]:
            for index, item in enumerate(block.profiles):
                if item.id == profile.id:
                    block.profiles[index] = profile
                    break
            else:
                block.profiles.append(profile)
            return profile.id if profile.default else None

        return self._write(change, expected_revision)

    def delete(self, profile_id: str, *, expected_revision: Optional[int] = None) -> LaunchProfilesConfig:
        aside = {s.id for s in self.read_all().set_aside}

        def change(block: LaunchProfilesConfig) -> Optional[str]:
            if not any(p.id == profile_id for p in block.profiles) and profile_id not in aside:
                raise NotFound(f"no launch profile {profile_id}")
            block.profiles = [p for p in block.profiles if p.id != profile_id]
            return None

        return self._write(change, expected_revision, drop_set_aside=profile_id)

    def set_default(self, profile_id: str, *, expected_revision: Optional[int] = None) -> LaunchProfilesConfig:
        def change(block: LaunchProfilesConfig) -> Optional[str]:
            if not any(p.id == profile_id for p in block.profiles):
                raise NotFound(f"no launch profile {profile_id}")
            return profile_id

        return self._write(change, expected_revision)
