
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.core.config_bundle import constants
from src.core.config_bundle.redact import is_secret_name


def deep_merge(base: Any, incoming: Any) -> Any:
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key, value in incoming.items():
            merged[key] = deep_merge(base[key], value) if key in base else value
        return merged
    return incoming


def carry_secrets(existing: Any, final: Any) -> Any:
    if isinstance(existing, dict) and isinstance(final, dict):
        out = dict(final)
        for key, old in existing.items():
            if key not in out:
                if isinstance(key, str) and is_secret_name(key):
                    out[key] = old
            else:
                out[key] = carry_secrets(old, out[key])
        return out
    if isinstance(existing, list) and isinstance(final, list):
        by_id = {
            item["id"]: item
            for item in existing
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        return [
            carry_secrets(by_id[item["id"]], item)
            if isinstance(item, dict) and item.get("id") in by_id
            else item
            for item in final
        ]
    return final


def flatten(value: Any, prefix: str, max_depth: int) -> Dict[str, Any]:
    if isinstance(value, dict) and value and max_depth > 0:
        out: Dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}", max_depth - 1))
        return out
    return {prefix: value}


def _preview(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if len(text) > constants.MAX_PREVIEW_CHARS:
        return text[: constants.MAX_PREVIEW_CHARS - 1] + "..."
    return text


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    changes: List[Dict[str, Any]] = []
    counts = {"added": 0, "changed": 0, "removed": 0}
    for path in sorted(set(before) | set(after)):
        if path not in before:
            kind, old, new = "added", None, _preview(after[path])
        elif path not in after:
            kind, old, new = "removed", _preview(before[path]), None
        elif before[path] != after[path]:
            kind, old, new = "changed", _preview(before[path]), _preview(after[path])
        else:
            continue
        counts[kind] += 1
        changes.append({"path": path, "kind": kind, "before": old, "after": new})
    truncated = len(changes) > constants.MAX_DIFF_ENTRIES
    return {
        "changes": changes[: constants.MAX_DIFF_ENTRIES],
        "counts": counts,
        "truncated": truncated,
    }
