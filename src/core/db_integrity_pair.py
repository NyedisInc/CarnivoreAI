
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.db import db_path_for

VERDICT_OK = "ok"
VERDICT_FAILED = "failed"
VERDICT_CANNOT_DETERMINE = "cannot_determine"

# could not be determined
_SEVERITY: Tuple[str, ...] = (
    VERDICT_FAILED,
    VERDICT_CANNOT_DETERMINE,
    VERDICT_OK,
)

DATABASES_KEY = "databases"

ROLE_STATE = "state"


def expected_databases(state_dir: Path) -> List[Tuple[str, Path]]:
    return [(ROLE_STATE, db_path_for(state_dir))]


def part_record(role: str, path: Path, status: str, detail: Optional[str]) -> Dict[str, Any]:
    """Build one per-database entry for the artifact's ``databases`` list.

    Description: one shape for both roles, so a reader never has to
      branch on which file it is looking at.
    Inputs: role (str - ROLE_STATE), path (Path), status
      (str - one of the VERDICT_* constants), detail (str | None - the
      pragma's complaint, or why it could not run).
    Output: dict.
    Example: part_record("state", Path("/s/cloude.db"), "ok", None)
    """
    return {
        "role": role,
        "db_path": str(path),
        "status": status,
        "detail": detail,
    }


def fold_pair(
    record: Optional[Dict[str, Any]],
    expected: Sequence[Tuple[str, Path]],
) -> Dict[str, Any]:
    parts = _parts_from(record)
    by_role = {p.get("role"): p for p in parts}

    resolved: List[Dict[str, Any]] = []
    unchecked: List[str] = []
    for role, path in expected:
        part = by_role.get(role)
        if part is None:
            unchecked.append(role)
            resolved.append(part_record(
                role, path, VERDICT_CANNOT_DETERMINE,
                "no verdict for this database in the integrity artifact, so it "
                "was not checked by the run that wrote it",
            ))
        else:
            resolved.append(part)

    statuses = {_normalise(p.get("status")) for p in resolved}
    verdict = next((s for s in _SEVERITY if s in statuses), VERDICT_CANNOT_DETERMINE)

    return {
        "verdict": verdict,
        "reason": _reason(verdict, resolved, unchecked),
        "parts": resolved,
        "unchecked": unchecked,
    }


def _parts_from(record: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not record:
        return []
    listed = record.get(DATABASES_KEY)
    if isinstance(listed, list) and listed:
        return [p for p in listed if isinstance(p, dict)]
    status = record.get("status")
    if status is None:
        return []
    return [part_record(
        ROLE_STATE,
        Path(str(record.get("db_path", ""))),
        _normalise(status),
        record.get("detail"),
    )]


def _normalise(status: Optional[str]) -> str:
    if status == VERDICT_OK:
        return VERDICT_OK
    if status == VERDICT_FAILED:
        return VERDICT_FAILED
    return VERDICT_CANNOT_DETERMINE


def _reason(
    verdict: str, parts: Sequence[Dict[str, Any]], unchecked: Sequence[str],
) -> str:
    named = ", ".join(f"{p['role']}={_normalise(p.get('status'))}" for p in parts)
    if verdict == VERDICT_OK:
        return f"every database checked and sound ({named})"
    if verdict == VERDICT_FAILED:
        bad = [p["role"] for p in parts if _normalise(p.get("status")) == VERDICT_FAILED]
        return f"integrity_check failed on: {', '.join(bad)} ({named})"
    if unchecked:
        return (
            f"not every database was checked; no verdict for "
            f"{', '.join(unchecked)} ({named}). A pass that did not cover a "
            "file cannot vouch for it"
        )
    return f"the integrity of at least one database could not be determined ({named})"


def check_every_database(state_dir: Path, state_verdict: str) -> list:
    return [part_record(
        ROLE_STATE, db_path_for(state_dir),
        "ok" if state_verdict == "ok" else "failed",
        None if state_verdict == "ok" else state_verdict,
    )]
