
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.core.automations import changes

MARKDOWN_VALUE_MAX = 160
_WIRE_FIELD = {"cron": "trigger"}


def proposed(before: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    after = json.loads(json.dumps(before))
    for key, value in patch.items():
        if key in ("automation_id", "revision", "acknowledge_unattended"):
            continue
        if key == "cron":
            after["trigger"] = {**after.get("trigger", {}), "cron": value}
        else:
            after[_WIRE_FIELD.get(key, key)] = value
    return after


def for_update(before: Dict[str, Any], patch: Dict[str, Any]) -> List[Dict[str, Any]]:
    return changes.diff(changes.snapshot(before), changes.snapshot(proposed(before, patch)))


def for_create(fields: Dict[str, Any]) -> List[Dict[str, Any]]:
    return changes.diff(None, proposed({}, fields))


def for_delete(before: Dict[str, Any]) -> List[Dict[str, Any]]:
    keep = {k: v for k, v in changes.snapshot(before).items() if k not in ("created_at", "seed_key")}
    return changes.diff(keep, None)


def _shown(value: Any) -> str:
    if value is None:
        return "(none)"
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return text if len(text) <= MARKDOWN_VALUE_MAX else text[: MARKDOWN_VALUE_MAX - 3] + "..."


def markdown(rows: Optional[List[Dict[str, Any]]]) -> str:
    if not rows:
        return ""
    lines = []
    for row in rows:
        before, after = row.get("before"), row.get("after")
        if before is None:
            lines.append(f"- {row['field']}: `{_shown(after)}`")
        elif after is None:
            lines.append(f"- {row['field']}: was `{_shown(before)}`")
        else:
            lines.append(f"- {row['field']}: `{_shown(before)}` -> `{_shown(after)}`")
    return "\n".join(lines)
