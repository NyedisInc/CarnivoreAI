
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

from src.config.launch_profiles import LaunchProfile, LaunchProfilesConfig
from src.config.launch_profiles_lenient import LoadedProfiles, kept_entries, load_profiles
from src.core.launch_profiles.share import executable_parts
from src.core.launch_profiles.trust_parts import replaces_default
from src.core.launch_profiles.store import normalize_defaults


def _profiles(block: Any) -> List[LaunchProfile]:
    if not isinstance(block, Mapping):
        return []
    return list(LaunchProfilesConfig.model_validate(dict(block)).profiles)


def _local(existing: Any) -> LoadedProfiles:
    return load_profiles(existing if isinstance(existing, Mapping) else {})


def block_digest(block: Any, existing: Any = None) -> Optional[str]:
    profiles = sorted(_profiles(block), key=lambda p: p.id)
    if not profiles:
        return None
    local = {p.id: p for p in _local(existing).block.profiles}
    rows = [{**p.model_dump(mode="json"), "default": False} for p in profiles]
    kept = [p.id for p in profiles if replaces_default(p, local.get(p.id))]
    payload: Any = rows if not kept else {"profiles": rows, "replaces_default": kept}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def review(block: Any, existing: Any = None) -> List[Dict[str, Any]]:
    local = {p.id: p for p in _local(existing).block.profiles}
    return [{"id": p.id, "label": p.label, "harness": p.harness, "parts": executable_parts(p, local.get(p.id)),
             "resume_command": bool(p.agent and p.agent.resume)} for p in _profiles(block)]


def merge_block(existing: Any, incoming: Any) -> Dict[str, Any]:
    loaded = _local(existing)
    local = loaded.block
    by_id = {p.id: p for p in local.profiles}
    for profile in _profiles(incoming):
        old = by_id.get(profile.id)
        by_id[profile.id] = profile.model_copy(update={"default": bool(old and old.default)})
    merged = local.model_copy(update={"profiles": list(by_id.values())})
    normalize_defaults(merged)
    if [p.model_dump() for p in merged.profiles] != [p.model_dump() for p in local.profiles]:
        merged.revision += 1
    out = merged.model_dump(mode="json")
    out["profiles"].extend(kept_entries(loaded, merged.profiles))
    return out

