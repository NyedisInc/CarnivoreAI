
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from src.config.launch_profiles import LaunchProfile
from src.core.agent_families import RESERVED_FAMILY_NAMES
from src.core.launch_profiles.flag_tones import SAFE, flag_groups
from src.core.launch_profiles.trust_parts import DEFAULT_KEPT, replaces_default, trust_parts

SHARE_FORMAT = "carnivore.launch_profile/1"

MAX_DOCUMENT_BYTES = 192 * 1024


class ShareError(ValueError):
    pass


def profile_digest(profile: LaunchProfile) -> str:
    data = profile.model_dump(mode="json")
    data["default"] = False
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def export_document(profile: LaunchProfile) -> Dict[str, Any]:
    data = profile.model_dump(mode="json")
    data["default"] = False
    return {"format": SHARE_FORMAT, "profile": data, "sha256": profile_digest(profile)}


def parse_document(raw: Any) -> LaunchProfile:
    if not isinstance(raw, dict) or set(raw) - {"format", "profile", "sha256"}:
        raise ShareError("a launch profile document is a JSON object with format, profile and sha256")
    if raw.get("format") != SHARE_FORMAT:
        raise ShareError(f"format must be {SHARE_FORMAT}")
    try:
        profile = LaunchProfile.model_validate({**(raw.get("profile") or {}), "default": False})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ShareError(f"profile.{where}: {str(first['msg']).removeprefix('Value error, ')}" if where else "invalid profile") from None
    if profile.id in RESERVED_FAMILY_NAMES:
        raise ShareError(f"{profile.id} is a harness name, not usable as a launch profile id")
    claimed = raw.get("sha256")
    if claimed is not None and claimed != profile_digest(profile):
        raise ShareError("the profile does not match the sha256 in the file; it was changed after export")
    return profile


def confirm_digest(profile: LaunchProfile, existing: Optional[LaunchProfile]) -> str:
    digest = profile_digest(profile)
    if not replaces_default(profile, existing):
        return digest
    return hashlib.sha256(f"{digest}:{DEFAULT_KEPT}".encode("utf-8")).hexdigest()


def executable_parts(profile: LaunchProfile, existing: Optional[LaunchProfile] = None) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = trust_parts(profile, existing)
    if profile.before_launch:
        parts.append({"kind": "before_launch", "text": profile.before_launch})
    if profile.custom_command:
        parts.append({"kind": "custom_command", "text": profile.custom_command.script})
        if profile.custom_command.entry:
            parts.append({"kind": "entry", "text": profile.custom_command.entry})
    for text, tone in flag_groups(profile.harness, profile.flags):
        parts.append({"kind": "flags", "text": text} if tone == SAFE else {"kind": "flags", "text": text, "tone": tone})
    if profile.agent is not None and profile.agent.resume:
        parts.append({"kind": "resume_command", "text": profile.agent.resume})
    parts.extend({"kind": "env", "text": f"{row.name}={row.value}"} for row in profile.env)
    parts.extend({"kind": "secret", "text": f"{row.name} <- {row.keychain_ref}"} for row in profile.secrets)
    return parts
