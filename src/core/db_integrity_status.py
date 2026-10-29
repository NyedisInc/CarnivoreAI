
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional

from src.core.corpus_ingest_state import (
    FRESHNESS_CANNOT_DETERMINE,
    FRESHNESS_NEVER_RAN,
    FRESHNESS_STALE,
    classify_freshness,
)
from src.core.db_integrity import (
    RUN_FAILED,
    RUN_OK,
    integrity_check_enabled,
    latest_path,
    read_verdict,
    resolve_interval_seconds,
    resolve_stale_after_seconds,
)

VERDICT_OK = "ok"
VERDICT_FAILED = "failed"
VERDICT_CANNOT_DETERMINE = "cannot_determine"

MAX_DETAIL_CHARS = 2000


def _classify(
    record: Optional[Dict[str, Any]], freshness: str, reason: str,
) -> Dict[str, str]:
    status = str((record or {}).get("status") or "")
    if status == RUN_FAILED:
        return {
            "verdict": VERDICT_FAILED,
            "reason": f"the last integrity check FAILED; {reason}",
        }
    if freshness == FRESHNESS_NEVER_RAN:
        return {
            "verdict": VERDICT_CANNOT_DETERMINE,
            "reason": (
                "no integrity check has ever completed in this state "
                "directory, so the database has NOT been verified - this is "
                "not a claim that it is sound"
            ),
        }
    if freshness == FRESHNESS_CANNOT_DETERMINE:
        return {"verdict": VERDICT_CANNOT_DETERMINE, "reason": reason}
    if freshness == FRESHNESS_STALE:
        return {
            "verdict": VERDICT_CANNOT_DETERMINE,
            "reason": (
                f"the cached verdict is out of date: {reason}. It says "
                f"{status or 'nothing'}, but it is too old to stand for the "
                "database as it is now"
            ),
        }
    if status == RUN_OK:
        return {"verdict": VERDICT_OK, "reason": reason}
    return {
        "verdict": VERDICT_CANNOT_DETERMINE,
        "reason": (
            f"the last check finished with status {status or 'unknown'}, "
            "which is not a verdict on the database"
        ),
    }


class VerdictReading(NamedTuple):

    verdict: str
    freshness: str
    age_seconds: Optional[float]
    reason: str


def classify_record(
    record: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    stale_after_seconds: Optional[int] = None,
) -> VerdictReading:
    window = (
        stale_after_seconds if stale_after_seconds is not None
        else resolve_stale_after_seconds()
    )
    freshness, age, why = classify_freshness(
        record, now=now, stale_after_seconds=window,
    )
    decided = _classify(record, freshness, why)
    return VerdictReading(
        verdict=decided["verdict"],
        freshness=freshness,
        age_seconds=age,
        reason=decided["reason"],
    )


_INTEGRITY_BLOCK_KEYS = (
    "verdict",
    "reason",
    "freshness",
    "age_seconds",
    "stale_after_seconds",
    "checked_at",
    "last_run_status",
    "duration_seconds",
    "detail",
    "enabled",
    "interval_seconds",
    "artifact",
)


def _base_integrity_fields() -> Dict[str, Any]:
    """Return every ``data.integrity`` key defaulted to "not known".

    Description: the single source of truth for the block's shape. Every
      builder in this module starts from a copy of this dict and only
      overrides the keys it can honestly answer, so ``integrity_block``
      (the normal, artifact-backed path) and
      ``unresolvable_integrity_block`` (the degraded path used when the
      state directory itself could not be resolved) are structurally
      incapable of publishing different key sets.
    Inputs: none.
    Output: dict - one entry per name in ``_INTEGRITY_BLOCK_KEYS``, each
      set to ``None``.
    Example: sorted(_base_integrity_fields()) == sorted(_INTEGRITY_BLOCK_KEYS)
      -> True
    """
    return {key: None for key in _INTEGRITY_BLOCK_KEYS}


def unresolvable_integrity_block(reason: str) -> Dict[str, Any]:
    """Build ``data.integrity`` for when the state directory itself failed.

    Description: this is the path taken before ``integrity_block`` could
      even be called - there is no state_dir to read an artifact from, so
      most fields genuinely are not known and stay ``None``. It publishes
      the SAME key set as :func:`integrity_block` (via
      :func:`_base_integrity_fields`) so a consumer reading
      ``.enabled``, ``.artifact``, ``.last_run_status``,
      ``.duration_seconds`` or ``.interval_seconds`` gets an honest
      ``None`` here instead of ``undefined``. ``verdict`` and
      ``freshness`` are still meaningful even without a state_dir, and
      both are ``cannot_determine`` - not having looked is not a fault,
      the same rule :func:`_classify` applies on the normal path.
    Inputs: reason (str - one sentence naming why the state directory
      could not be resolved).
    Output: dict - see this module's docstring for the full shape.
    Example: unresolvable_integrity_block("boom")["enabled"] -> None
    """
    fields = _base_integrity_fields()
    fields["verdict"] = VERDICT_CANNOT_DETERMINE
    fields["freshness"] = FRESHNESS_CANNOT_DETERMINE
    fields["reason"] = reason
    return fields


def integrity_block(
    state_dir: Path, *, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the ``data.integrity`` block for GET /api/v1/version.

    Description: a pure read of one small JSON file. Runs NO pragma, and
      that is the entire point of this module - the request path costs a
      file read, not a walk of every page in the database. Never raises:
      an unreadable artifact is a named ``cannot_determine``, because a
      status endpoint that 500s tells the user less than one that says
      "I could not read it".
    Inputs: state_dir (Path), now (datetime | None - injected by tests so
      staleness can be exercised without sleeping).
    Output: dict carrying ``verdict``, ``freshness``, ``age_seconds``,
      ``checked_at``, ``detail``, ``reason``, ``enabled``,
      ``interval_seconds``, ``stale_after_seconds`` and ``artifact``.
    Example: integrity_block(Path("/nonexistent"))["verdict"]
      -> 'cannot_determine'
    """
    interval = resolve_interval_seconds()
    stale_after = resolve_stale_after_seconds(interval)
    record = read_verdict(state_dir)
    reading = classify_record(
        record, now=now, stale_after_seconds=stale_after,
    )
    freshness = reading.freshness
    age = reading.age_seconds
    detail = (record or {}).get("detail")
    if isinstance(detail, str) and len(detail) > MAX_DETAIL_CHARS:
        detail = detail[:MAX_DETAIL_CHARS] + " ... (truncated)"
    fields = _base_integrity_fields()
    fields.update({
        "verdict": reading.verdict,
        "reason": reading.reason,
        "freshness": freshness,
        "age_seconds": None if age is None else round(age, 1),
        "stale_after_seconds": stale_after,
        "checked_at": (record or {}).get("finished_at"),
        "last_run_status": (record or {}).get("status"),
        "duration_seconds": (record or {}).get("duration_seconds"),
        "detail": detail,
        "enabled": integrity_check_enabled(),
        "interval_seconds": interval,
        "artifact": str(latest_path(state_dir)),
    })
    return fields


def cached_failure_detail(state_dir: Path) -> Optional[str]:
    record = read_verdict(state_dir)
    if not record or record.get("status") != RUN_FAILED:
        return None
    detail = record.get("detail")
    text = str(detail) if detail else "PRAGMA integrity_check reported problems"
    stamp = record.get("finished_at")
    return f"{text} (recorded {stamp or 'at an unknown time'})"
