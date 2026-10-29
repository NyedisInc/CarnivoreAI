
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.config_bundle.constants import (
    ACCOUNT_DIR_FIELDS,
    AGENT_COMMAND_FIELDS,
    BROWSER_EXECUTABLE_KEY,
    WORKSPACE_EDITOR_KEY,
    WORKSPACE_ENV_KEY,
    WORKSPACE_SHELL_KEY,
)


def _wrappers(block: Any) -> Dict[str, Mapping[str, Any]]:
    rows = block.get("wrappers") if isinstance(block, Mapping) else None
    if not isinstance(rows, list):
        return {}
    return {str(row.get("id")): row for row in rows if isinstance(row, Mapping)}


def _command_of(wrapper: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: wrapper[key] for key in AGENT_COMMAND_FIELDS if key in wrapper}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def written_commands(before: Any, after: Any) -> List[Dict[str, Any]]:
    old = _wrappers(before)
    rows: List[Dict[str, Any]] = []
    for wrapper_id, wrapper in sorted(_wrappers(after).items()):
        command = _command_of(wrapper)
        if wrapper_id in old and _command_of(old[wrapper_id]) == command:
            continue
        rows.append({
            "id": wrapper_id,
            "family": wrapper.get("family"),
            "label": wrapper.get("label"),
            "parts": [{"kind": key, "text": _text(value)} for key, value in command.items()],
        })
    return rows


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def written_workspace(before: Any, after: Any) -> List[Dict[str, Any]]:
    old, new = _mapping(before), _mapping(after)
    old_env = _mapping(old.get(WORKSPACE_ENV_KEY))
    rows: List[Dict[str, Any]] = []
    for name, value in sorted(_mapping(new.get(WORKSPACE_ENV_KEY)).items()):
        if name in old_env and old_env[name] == value:
            continue
        rows.append({"id": name, "kind": "env", "label": name,
                     "parts": [{"kind": "env", "text": f"{name}={_text(value)}"}]})
    rows.extend(_scalar_row(old, new, WORKSPACE_SHELL_KEY, "shell"))
    rows.extend(_scalar_row(old, new, WORKSPACE_EDITOR_KEY, "editor"))
    return rows


def _scalar_row(old: Mapping[str, Any], new: Mapping[str, Any], key: str, kind: str) -> List[Dict[str, Any]]:
    value = new.get(key)
    if not isinstance(value, str) or not value.strip() or value == old.get(key):
        return []
    return [{"id": key, "kind": kind, "label": key, "parts": [{"kind": key, "text": value}]}]


def written_browser(before: Any, after: Any) -> List[Dict[str, Any]]:
    return _scalar_row(_mapping(before), _mapping(after), BROWSER_EXECUTABLE_KEY, "executable")


def written_template_path(before: Any, after: Any) -> List[Dict[str, Any]]:
    return _scalar_row({"template_path": before}, {"template_path": after}, "template_path", "template")


def written_account_dirs(before: Any, after: Any) -> List[Dict[str, Any]]:
    def accounts(block: Any) -> List[Mapping[str, Any]]:
        rows = _mapping(block).get("accounts")
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []

    old = {str(row.get("id")): row for row in accounts(before)}
    out: List[Dict[str, Any]] = []
    for account in accounts(after):
        account_id = str(account.get("id"))
        prior = old.get(account_id, {})
        parts = [{"kind": key, "text": f"{key}={_text(account[key])}"} for key in ACCOUNT_DIR_FIELDS
                 if key in account and (key not in prior or prior[key] != account[key])]
        if parts:
            out.append({"id": account_id, "kind": "account_dir", "label": str(account.get("name") or account_id),
                        "parts": parts})
    return out


def written_slash_commands(before: Any, after: Any) -> List[Dict[str, Any]]:
    def entries(value: Any) -> List[Tuple[str, str]]:
        if not isinstance(value, list):
            return []
        pairs: List[Tuple[str, str]] = []
        for item in value:
            if isinstance(item, str):
                pairs.append((item, ""))
            elif isinstance(item, Mapping) and isinstance(item.get("command"), str):
                pairs.append((item["command"], _text(item.get("description") or "")))
        return pairs

    known = set(entries(before))
    rows: List[Dict[str, Any]] = []
    for command, description in entries(after):
        if (command, description) in known:
            continue
        parts = [{"kind": "command", "text": command}]
        if description:
            parts.append({"kind": "description", "text": description})
        rows.append({"id": command, "kind": "slash", "label": description or command, "parts": parts})
    return rows


def digest(rows: List[Dict[str, Any]]) -> Optional[str]:
    if not rows:
        return None
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
