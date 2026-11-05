
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.config.launch_profiles import LaunchProfile, LaunchProfilesConfig

logger = structlog.get_logger()

DUPLICATE_ID = "another launch profile has the same id"


@dataclass(frozen=True)
class SetAsideProfile:

    id: str
    label: Optional[str]
    harness: Optional[str]
    reason: str
    was_default: bool
    fallback_default: Optional[str]
    raw: Any


@dataclass(frozen=True)
class LoadedProfiles:

    block: LaunchProfilesConfig
    set_aside: Tuple[SetAsideProfile, ...]


def _text(entry: Any, key: str) -> Optional[str]:
    value = entry.get(key) if isinstance(entry, Mapping) else None
    return value if isinstance(value, str) else None


def _reason(exc: ValidationError) -> str:
    return str(exc.errors()[0].get("msg", "invalid")).removeprefix("Value error, ")


def _split(entries: List[Any]) -> Tuple[List[LaunchProfile], List[Tuple[Any, str]]]:
    valid: List[LaunchProfile] = []
    rejected: List[Tuple[Any, str]] = []
    for entry in entries:
        try:
            profile = LaunchProfile.model_validate(entry)
        except ValidationError as exc:
            rejected.append((entry, _reason(exc)))
            continue
        if any(p.id == profile.id for p in valid):
            rejected.append((entry, DUPLICATE_ID))
        else:
            valid.append(profile)
    return valid, rejected


def _stand_in(valid: List[LaunchProfile], harness: Optional[str]) -> Optional[str]:
    own = [p for p in valid if p.harness == harness]
    if not own:
        return None
    current = next((p for p in own if p.default), None)
    if current is None:
        own[0].default = True
        current = own[0]
    return current.id


def load_profiles(raw: Any) -> LoadedProfiles:
    data: Dict[str, Any] = dict(raw) if isinstance(raw, Mapping) else {}
    entries = data.get("profiles")
    shell = LaunchProfilesConfig.model_validate({**data, "profiles": []})
    if not isinstance(entries, list):
        return LoadedProfiles(LaunchProfilesConfig.model_validate(data), ())
    valid, rejected = _split(entries)
    set_aside: List[SetAsideProfile] = []
    for entry, reason in rejected:
        was_default = isinstance(entry, Mapping) and entry.get("default") is True
        harness = _text(entry, "harness")
        profile_id = _text(entry, "id") or ""
        logger.warning("launch_profile_set_aside", profile_id=profile_id, reason=reason)
        set_aside.append(SetAsideProfile(
            id=profile_id, label=_text(entry, "label"), harness=harness, reason=reason, was_default=was_default,
            fallback_default=_stand_in(valid, harness) if was_default else None, raw=entry))
    block = LaunchProfilesConfig(**{**dict(shell), "profiles": valid})
    return LoadedProfiles(block, tuple(set_aside))


def kept_entries(loaded: LoadedProfiles, written: List[LaunchProfile], dropped: Optional[str] = None) -> List[Any]:
    written_ids = {p.id for p in written}
    defaulted = {p.harness for p in written if p.default}
    kept: List[Any] = []
    for aside in loaded.set_aside:
        if aside.id in written_ids or aside.id == dropped:
            continue
        entry = aside.raw
        if aside.was_default and aside.harness in defaulted:
            entry = {**entry, "default": False}
        kept.append(entry)
    return kept
