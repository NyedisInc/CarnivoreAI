
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.flag_tones import DANGER
from src.core.launch_profiles.permissions import UnsupportedPosture, permission_flags

Part = Dict[str, Any]

SKIP_ALL = "skip_all"

DEFAULT_KEPT = "kept"


def _harness(profile: LaunchProfile) -> Tuple[str, str]:
    return profile.harness, ""


def _permissions(profile: LaunchProfile) -> Tuple[str, str]:
    try:
        flags = permission_flags(profile.harness, profile.permissions)
    except UnsupportedPosture:
        flags = ()
    return profile.permissions, " ".join(flags)


def _endpoint(profile: LaunchProfile) -> Tuple[str, str]:
    return profile.endpoint.mode, profile.endpoint.connection_id or ""


def _account(profile: LaunchProfile) -> Tuple[str, str]:
    return profile.account.mode, profile.account.account_id or ""


_FIELDS: Tuple[Tuple[str, Callable[[LaunchProfile], Tuple[str, str]], Optional[str]], ...] = (
    ("harness", _harness, None),
    ("permissions", _permissions, "harness_default"),
    ("endpoint", _endpoint, "native"),
    ("account", _account, "follow_active"),
)


def trust_parts(profile: LaunchProfile, existing: Optional[LaunchProfile] = None) -> List[Part]:
    parts: List[Part] = []
    for kind, read, fresh in _FIELDS:
        value, text = read(profile)
        old = read(existing) if existing is not None else None
        changed = old is not None and old != (value, text)
        if fresh is not None and (value, text) == (fresh, "") and not changed:
            continue
        part: Part = {"kind": kind, "value": value, "text": text}
        if changed and old is not None:
            part["was"], part["was_text"] = old
        if kind == "permissions" and value == SKIP_ALL:
            part["tone"] = DANGER
        parts.append(part)
    if replaces_default(profile, existing):
        parts.append({"kind": "default", "value": DEFAULT_KEPT, "text": profile.id})
    return parts


def replaces_default(profile: LaunchProfile, existing: Optional[LaunchProfile]) -> bool:
    return existing is not None and existing.id == profile.id and existing.default
