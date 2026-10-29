
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional

REMOTE_PREFIX = "remote:"
MAX_LINE_CHARS = 4000
CONTROL_LEAD = frozenset("!/#@")
SESSION_FIELDS = ("id", "session_row_id", "label", "project_id", "activity_status", "unread", "startup_gate",
                  "agent_family", "created_at", "last_activity")
NESTED_FIELDS = ("id", "created_at", "last_activity")
TOAST_PREFIX = "[plugin] "
TOAST_MAX_CHARS = 80
_URLISH = re.compile(r"(https?:|www\.|://|\b\d{1,3}(?:\.\d{1,3}){3}\b|[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,})", re.I)
_DOTS = str.maketrans({"\u3002": ".", "\uff61": ".", "\uff0e": ".", "\u2024": ".", "\ufe52": "."})
ALERT_KEY = re.compile(r"^[a-z0-9_]{1,32}$")
SEVERITIES = frozenset({"info", "warning", "error"})
INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


class Refused(Exception):

    def __init__(self, code: str, detail: str = "", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.data = data or {}


def strip_invisible(text: str) -> str:
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in INVISIBLE_CATEGORIES)


def refuse_control_line(line: object) -> str:
    if not isinstance(line, str) or not line.strip() or len(line) > MAX_LINE_CHARS:
        raise Refused("permission_denied", "bad_line", {"reason": "bad_line"})
    if any(unicodedata.category(c) in INVISIBLE_CATEGORIES for c in line):
        raise Refused("permission_denied", "control_character", {"reason": "control_character"})
    lead = strip_invisible(line).lstrip()
    if not lead or lead[0] in CONTROL_LEAD:
        raise Refused("permission_denied", "control_line", {"reason": "control_line"})
    return line


def refuse_bypass_session(launched_with: Optional[Mapping[str, Any]], agent_label: Optional[str] = None,
                          live_mode: Optional[str] = None) -> None:
    """Refuse a target launched with permissions skipped, or now in a bypass mode. Raises Refused. FAILS CLOSED (C2).

    Inputs: launched_with (the listing's ``launched_with``); agent_label (the wrapper label); live_mode (the pane's
    CURRENT permission mode text, e.g. claude's registry mode or the footer, or None when it could not be measured).
    Description: refused when there is no launch record or it carries no ``permissions`` value (an adopted pane or a
      legacy row says nothing about how it was started), when the launch text, the label or the live mode matches
      ``bypass``, ``skip`` or ``dangerous``, or when the live mode is unknown (shift+tab and ``/permissions`` can switch
      a pane into bypass after launch).
    """
    permissions = launched_with.get("permissions") if isinstance(launched_with, Mapping) else None
    if permissions in (None, "") or not isinstance(live_mode, str) or not live_mode.strip():
        raise Refused("permission_denied", "permissions_unknown", {"reason": "permissions_unknown"})
    haystack = f"{json.dumps(dict(launched_with), default=str)} {agent_label or ''} {live_mode}"
    if re.search(r"bypass|skip|dangerous", haystack, re.I):
        raise Refused("permission_denied", "bypass_session", {"reason": "bypass_session"})


def refuse_remote(ref: object) -> str:
    if not isinstance(ref, str) or not ref or len(ref) > 200:
        raise Refused("permission_denied", "bad_ref", {"reason": "bad_ref"})
    if ref.strip().lower().startswith(REMOTE_PREFIX):
        raise Refused("permission_denied", "remote_ref", {"reason": "remote_ref"})
    return ref


def _inner(row: Mapping[str, Any]) -> Mapping[str, Any]:
    inner = row.get("session")
    return inner if isinstance(inner, Mapping) else {}


def is_remote_row(row: Mapping[str, Any]) -> bool:
    ident = _inner(row).get("id", row.get("id") if "session" not in row else None)
    if not isinstance(ident, str) or not ident:
        return True
    host = row.get("host_key")
    return ident.strip().lower().startswith(REMOTE_PREFIX) or (host is not None and host != "local")


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def project_session_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    inner = _inner(row)
    out = {k: _plain(row[k]) for k in SESSION_FIELDS if k in row and k not in NESTED_FIELDS}
    out.update({k: _plain(inner[k]) for k in NESTED_FIELDS if k in inner})
    if not inner:
        out.update({k: _plain(row[k]) for k in NESTED_FIELDS if k in row})
    return out


def toast_title(title: object) -> str:
    if not isinstance(title, str) or not title.strip():
        raise Refused("invalid_params", "title is required")
    clean = strip_invisible(title).strip()
    if not clean or _URLISH.search(unicodedata.normalize("NFKC", clean).translate(_DOTS)):
        raise Refused("permission_denied", "url_in_title", {"reason": "url_in_title"})
    return (TOAST_PREFIX + clean)[:TOAST_MAX_CHARS]


def alert_key(cplug_id: str, key: object) -> str:
    if not isinstance(key, str) or not ALERT_KEY.match(key):
        raise Refused("invalid_params", "alert key must match ^[a-z0-9_]{1,32}$")
    return f"cplug.{cplug_id}.p.{key}"


def pin_tools(manifest_tools: List[Mapping[str, Any]], runtime_tools: object) -> None:
    def canon(items: Any) -> str:
        if not isinstance(items, list) or not all(isinstance(t, Mapping) for t in items):
            return "invalid"
        return json.dumps(sorted((dict(t) for t in items), key=lambda t: str(t.get("name"))), sort_keys=True, default=str)

    reported = runtime_tools.get("tools") if isinstance(runtime_tools, Mapping) else None
    if canon(reported) != canon(list(manifest_tools)):
        raise Refused("integrity", "tools/list differs from the signed manifest", {"reason": "tools_differ"})
