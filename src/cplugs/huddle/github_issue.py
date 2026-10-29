
from __future__ import annotations

import re
from typing import Dict, Mapping, Optional
from urllib.parse import urlsplit

from src.cplugs.huddle.rules import TaskManagerInvalid


FIELD = "github_issue"

MAX_URL = 200

_HOST = "github.com"
_PATH = re.compile(r"^/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/issues/(?P<number>[0-9]+)/?$")


def canonical(value: str) -> str:
    if len(value) > MAX_URL:
        raise TaskManagerInvalid(f"{FIELD} is at most {MAX_URL} characters")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise TaskManagerInvalid(f"{FIELD} is not a valid URL") from exc
    match = _PATH.match(parts.path)
    if parts.scheme != "https" or parts.hostname != _HOST or port is not None or parts.username or parts.password or not match:
        raise TaskManagerInvalid(f"{FIELD} is a full https://{_HOST}/<owner>/<repo>/issues/<number> URL (an empty string clears it)")
    return f"https://{_HOST}/{match['owner']}/{match['repo']}/issues/{int(match['number'])}"


def clean_field(value: Optional[object]) -> Dict[str, Optional[str]]:
    if value is None:
        return {}
    if not isinstance(value, str):
        raise TaskManagerInvalid(f"{FIELD} is a URL (text)")
    text = value.strip()
    return {FIELD: canonical(text) if text else None}


def wire(row: Mapping[str, object]) -> Dict[str, str]:
    return {FIELD: str(row[FIELD])} if row[FIELD] else {}
