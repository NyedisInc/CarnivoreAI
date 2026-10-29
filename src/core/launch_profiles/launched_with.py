
from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional


def launched_with(raw_record: Optional[str], labels: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    if not raw_record:
        return None
    try:
        record = json.loads(raw_record)
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict) or not record.get("profile"):
        return None
    account = record.get("account") if isinstance(record.get("account"), dict) else {}
    model = record.get("model")
    profile = str(record["profile"])
    return {
        "profile": profile,
        "label": labels.get(profile) or profile,
        "harness": record.get("harness"),
        "account": account.get("id") or None,
        "model": None if model in (None, "", "default") else str(model),
        "permissions": record.get("permissions"),
    }


def launched_with_for_row(row_identity: Optional[Mapping[str, Any]], settings: Any) -> Optional[Dict[str, Any]]:
    raw = row_identity.get("launch_record") if row_identity else None
    if not raw:
        return None
    return launched_with(raw, {p.id: p.label for p in settings.get_launch_profiles()})
