
from __future__ import annotations

from typing import Any, Dict

from src.config.launch_profiles import LaunchProfile

PERMISSION_BADGES = {
    "harness_default": "default permissions",
    "ask": "asks first",
    "accept_edits": "accepts edits",
    "skip_all": "skips all permission checks",
}


def summary_row(profile: LaunchProfile) -> Dict[str, Any]:
    model = profile.model.value if profile.model.mode == "fixed" else profile.model.mode
    return {
        "id": profile.id,
        "label": profile.label,
        "harness": profile.harness,
        "account": profile.account.account_id or "follow_active",
        "endpoint": profile.endpoint.connection_id or "native",
        "model": model,
        "permissions": profile.permissions,
        "permissions_badge": PERMISSION_BADGES[profile.permissions],
        "default": profile.default,
    }
