
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional

from src.core.automations import models as m

MISFIRE_SKIP, MISFIRE_RUN_ONCE = "skip", "run_once"
MISFIRE_CHOICES = (MISFIRE_SKIP, MISFIRE_RUN_ONCE)
MISFIRE_NEW_DEFAULT = MISFIRE_RUN_ONCE
DESCRIPTION_MAX = 500
RETRY_MAX_CAP = 3
RETRY_BACKOFF_DEFAULT_S, RETRY_BACKOFF_MIN_S, RETRY_BACKOFF_MAX_S = 300, 60, 3600
MAX_RUNTIME_MIN_S, MAX_RUNTIME_MAX_S = 60, 86400
ACTOR_KINDS = ("app", "mcp", "seed")

CONTRACT_FIELDS = frozenset({"description", "project_id", "misfire", "retry_max", "retry_backoff_s", "max_runtime_s"})


def clean_description(value: Any) -> str:
    text = (value or "").strip() if isinstance(value, (str, type(None))) else None
    if text is None or len(text) > DESCRIPTION_MAX:
        raise m.AutomationInvalid("description_invalid", f"text up to {DESCRIPTION_MAX} characters")
    return text


def clean_misfire(value: Any) -> str:
    if value not in MISFIRE_CHOICES:
        raise m.AutomationInvalid("misfire_invalid", " or ".join(MISFIRE_CHOICES))
    return value


def _whole(value: Any, low: int, high: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise m.AutomationInvalid(code, f"a whole number from {low} to {high}")
    return value


def clean_retry(retry_max: Any, backoff_s: Any) -> tuple:
    return _whole(retry_max, 0, RETRY_MAX_CAP, "retry_invalid"), _whole(backoff_s, RETRY_BACKOFF_MIN_S, RETRY_BACKOFF_MAX_S, "retry_invalid")


def clean_max_runtime(value: Any) -> Optional[int]:
    return None if value is None else _whole(value, MAX_RUNTIME_MIN_S, MAX_RUNTIME_MAX_S, "max_runtime_invalid")


def clean_project_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise m.AutomationInvalid("project_invalid", "a project id")
    return value


def _project_row(project_id: int) -> Optional[Dict[str, Any]]:
    from src.core.automations import recipes  # noqa: PLC0415
    from src.core.project_writes import list_projects_ordered  # noqa: PLC0415

    with closing(recipes._open_db()) as conn:
        rows = list_projects_ordered(conn, include_archived=True)
    return next((r for r in rows if r.get("id") == project_id), None)


def project_problem(project_id: Optional[int]) -> Optional[str]:
    if project_id is None:
        return None
    try:
        row = _project_row(project_id)
    except (OSError, sqlite3.Error):
        return "project_missing"
    if row is None:
        return "project_missing"
    return "project_archived" if row.get("archived_at") else None


def project_root(project_id: int) -> Optional[str]:
    try:
        row = _project_row(project_id)
    except (OSError, sqlite3.Error):
        return None
    if row is None or row.get("archived_at"):
        return None
    return str(row.get("root") or "") or None


def actor(kind: str, **ids: Any) -> Dict[str, Any]:
    if kind not in ACTOR_KINDS:
        raise ValueError(f"unknown actor kind {kind!r}")
    return {"kind": kind, **{k: str(v) for k, v in ids.items() if v}}
