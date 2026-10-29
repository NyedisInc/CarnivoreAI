
from __future__ import annotations

import json
from typing import Dict, Mapping, Optional
from urllib.parse import urlsplit

from src.cplugs.huddle import rules
from src.cplugs.huddle.rules import TaskManagerInvalid


MAX_SUMMARY = 300

MAX_DESCRIPTION = 4000
MAX_LINK = 2000
MAX_WHERE = 500
TICK, PUSH, ANSWER, READ, NONE = "tick", "push", "answer", "read", "none"
ACTIONS = (TICK, PUSH, ANSWER, READ, NONE)
DEFAULT_REVIEW_ACTION = TICK
FIELDS = ("review_description", "review_summary", "review_link", "review_where", "review_action")
_LIMITS: Mapping[str, int] = {"review_description": MAX_DESCRIPTION, "review_summary": MAX_SUMMARY, "review_link": MAX_LINK, "review_where": MAX_WHERE}
_WEB_SCHEMES = ("http", "https")


def check_link(link: str) -> str:
    if link.startswith("/"):
        if link.startswith("//") or "\\" in link:
            raise TaskManagerInvalid("review_link must be an app path or an http(s) URL")
        return link
    parts = urlsplit(link)
    if parts.scheme.lower() not in _WEB_SCHEMES or not parts.netloc or any(c.isspace() for c in link):
        raise TaskManagerInvalid("review_link must be an app path or an http(s) URL")
    return link


def clean_field(name: str, value: object) -> Optional[str]:
    if name == "review_action":
        return check_action(value, name)
    text = rules.clean_text(value, name, _LIMITS[name], allow_blank=True)
    if name == "review_summary":
        text = " ".join(text.split())
    if not text:
        return None
    return check_link(text) if name == "review_link" else text


def check_action(value: object, field: str = "action") -> Optional[str]:
    text = rules.clean_text(value, field, 20, allow_blank=True).lower()
    if not text:
        return None
    if text not in ACTIONS:
        raise TaskManagerInvalid(f"{field} must be one of {', '.join(ACTIONS)}")
    return text


def look_parts(action: object) -> str:
    checked = check_action(action) if action is not None else None
    return json.dumps({"action": checked}) if checked else ""


def look_action(raw: object) -> Optional[str]:
    if not isinstance(raw, str) or not raw.startswith('{"action"'):
        return None
    try:
        action = json.loads(raw).get("action")
    except (ValueError, AttributeError):
        return None
    return action if action in ACTIONS else None


def clean_fields(values: Mapping[str, object]) -> Dict[str, Optional[str]]:
    return {name: clean_field(name, values[name]) for name in FIELDS if values.get(name) is not None}


def wire(row: Mapping[str, object]) -> Dict[str, Optional[str]]:
    return {name: row[name] for name in FIELDS}
