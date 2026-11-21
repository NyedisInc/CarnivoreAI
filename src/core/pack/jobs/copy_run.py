
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

_RUNS: Dict[str, Dict[str, Any]] = {}
_ACTIVE: Dict[str, int] = {}
_OK = ("created", "present")


def start(project_uid: str) -> None:
    _ACTIVE[project_uid] = _ACTIVE.get(project_uid, 0) + 1
    prior = _RUNS.get(project_uid) if _ACTIVE[project_uid] > 1 else None
    _RUNS[project_uid] = {"running": True, "refused": dict(prior["refused"]) if prior else {}, "error": None}


def finish(project_uid: str, outcome: Mapping[str, str], error: Optional[str] = None) -> None:
    left = max(0, _ACTIVE.get(project_uid, 0) - 1)
    _ACTIVE[project_uid] = left
    refused = dict(_RUNS.get(project_uid, {}).get("refused", {}))
    for install_id, code in outcome.items():
        if code in _OK:
            refused.pop(install_id, None)
        else:
            refused[install_id] = code
    _RUNS[project_uid] = {"running": left > 0, "refused": refused, "error": error}


def get(project_uid: str) -> Dict[str, Any]:
    run = _RUNS.get(project_uid)
    return {"running": False, "refused": {}, "error": None} if run is None else {**run, "refused": dict(run["refused"])}
