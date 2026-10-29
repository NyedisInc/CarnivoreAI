
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog
from pydantic import ValidationError

from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile, LaunchProfilesConfig
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
    def _block(data: Mapping[str, Any]) -> LaunchProfilesConfig:
        try:
            return LaunchProfilesConfig.model_validate(data.get(LAUNCH_PROFILES_KEY) or {})
        except ValidationError:
            raise LaunchProfileError("the launch_profiles block in config.json is invalid") from None

    def read(self) -> LaunchProfilesConfig:
        return self._block(config_writer.read_config(self._path))

    def list(self) -> List[LaunchProfile]:
        return self.read().profiles

    def get(self, profile_id: str) -> LaunchProfile:
        for item in self.read().profiles:
            if item.id == profile_id:
                return item
        raise NotFound(f"no launch profile {profile_id}")

    def _write(self, change: Callable[[LaunchProfilesConfig], Optional[str]],
               expected_revision: Optional[int]) -> LaunchProfilesConfig:
        def precondition(data: Dict[str, Any]) -> Optional[str]:
            if expected_revision is not None and self._block(data).revision != expected_revision:
                return config_writer.STALE_REVISION
            return None

        def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
            block = self._block(data)
            preferred = change(block)
            normalize_defaults(block, preferred)
            block.revision += 1
            try:
                checked = LaunchProfilesConfig.model_validate(block.model_dump())
            except ValidationError as exc:
                raise LaunchProfileError(str(exc.errors()[0].get("msg", "invalid"))) from None
            return {**data, LAUNCH_PROFILES_KEY: checked.model_dump(mode="json")}

        outcome = config_writer.commit(self._path, mutate, precondition=precondition)
        if outcome.status == config_writer.STALE_REVISION:
            raise StaleRevision(f"launch_profiles revision is {self._block(outcome.data).revision}")
        if not outcome.wrote:
            raise LaunchProfileError(f"config write did not land ({outcome.status})")
        return self._block(outcome.data)

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
        def change(block: LaunchProfilesConfig) -> Optional[str]:
            if not any(p.id == profile_id for p in block.profiles):
                raise NotFound(f"no launch profile {profile_id}")
            block.profiles = [p for p in block.profiles if p.id != profile_id]
            return None

        return self._write(change, expected_revision)

    def set_default(self, profile_id: str, *, expected_revision: Optional[int] = None) -> LaunchProfilesConfig:
        def change(block: LaunchProfilesConfig) -> Optional[str]:
            if not any(p.id == profile_id for p in block.profiles):
                raise NotFound(f"no launch profile {profile_id}")
            return profile_id

        return self._write(change, expected_revision)
