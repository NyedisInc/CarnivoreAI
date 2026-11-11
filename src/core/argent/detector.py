
from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional

from src.core.argent import overlay, row_state, settings as settings_module


def user_settings_override(environ: Optional[Mapping[str, str]] = None) -> bool:
    return overlay.settings_override("", environ)


def detect(tenant_id: str, *, feature_on: bool, environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    env = environ if environ is not None else os.environ
    switch_on = feature_on and settings_module.read().enabled
    findings: List[Dict[str, str]] = []
    for row in row_state.rows(tenant_id):
        if row["state"] != row_state.PENDING:
            continue
        if not switch_on:
            findings.append({"session_ref": row["session_ref"], "kind": "tethered_while_off", "reason": "tethered while the switch is off"})
        elif overlay.settings_override(row["working_dir"], env):
            findings.append({"session_ref": row["session_ref"], "kind": "settings_override", "reason": "settings override"})
    return {"shared_gateway_env": user_settings_override(env), "findings": findings}
