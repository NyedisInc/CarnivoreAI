
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

from src.config.launch_profiles import LaunchProfile, LaunchProfilesConfig
from src.core.launch_profiles.share import executable_parts
from src.core.launch_profiles.store import normalize_defaults


def _profiles(block: Any) -> List[LaunchProfile]:
    if not isinstance(block, Mapping):
        return []
    return list(LaunchProfilesConfig.model_validate(dict(block)).profiles)


def block_digest(block: Any) -> Optional[str]:
    profiles = sorted(_profiles(block), key=lambda p: p.id)
    if not profiles:
        return None
    rows = [{**p.model_dump(mode="json"), "default": False} for p in profiles]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def review(block: Any) -> List[Dict[str, Any]]:
    return [{"id": p.id, "label": p.label, "harness": p.harness, "parts": executable_parts(p)} for p in _profiles(block)]


def merge_block(existing: Any, incoming: Any) -> Dict[str, Any]:
    local = LaunchProfilesConfig.model_validate(dict(existing) if isinstance(existing, Mapping) else {})
    by_id = {p.id: p for p in local.profiles}
    for profile in _profiles(incoming):
        old = by_id.get(profile.id)
        by_id[profile.id] = profile.model_copy(update={"default": bool(old and old.default)})
    merged = LaunchProfilesConfig(revision=local.revision, profiles=list(by_id.values()))
    normalize_defaults(merged)
    if [p.model_dump() for p in merged.profiles] != [p.model_dump() for p in local.profiles]:
        merged.revision += 1
    return merged.model_dump(mode="json")

