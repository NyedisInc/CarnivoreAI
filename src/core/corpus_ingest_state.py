
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.json_artifact import atomic_write_json, read_json_object

INGEST_DIRNAME = "corpus-ingest"

LATEST_FILENAME = "latest.json"

SCAN_CACHE_FILENAME = "scan-cache.json"

CODEX_SCAN_CACHE_FILENAME = "scan-cache-codex.json"

DATED_RETENTION = 30

FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_NEVER_RAN = "never_ran"
FRESHNESS_CANNOT_DETERMINE = "cannot_determine"

DEFAULT_STALE_AFTER_SECONDS = 6 * 3600


def artifact_dir(state_dir: Path) -> Path:
    return Path(state_dir) / INGEST_DIRNAME


def latest_path(state_dir: Path) -> Path:
    return artifact_dir(state_dir) / LATEST_FILENAME


def scan_cache_path(state_dir: Path, name: str = SCAN_CACHE_FILENAME) -> Path:
    return artifact_dir(state_dir) / name


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: dict) -> bool:
    return atomic_write_json(
        path, payload, log_event="corpus_ingest_artifact_write_failed",
    )


def _read_json(path: Path) -> Optional[dict]:
    return read_json_object(
        path, log_event="corpus_ingest_artifact_unreadable",
    )


def load_scan_cache(
    state_dir: Path, name: str = SCAN_CACHE_FILENAME
) -> Dict[str, Tuple[int, int, str]]:
    data = _read_json(scan_cache_path(state_dir, name))
    if not data:
        return {}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return {}
    out: Dict[str, Tuple[int, int, str]] = {}
    for source_path, value in entries.items():
        if (isinstance(value, list) and len(value) == 3
                and isinstance(value[0], int) and isinstance(value[1], int)
                and isinstance(value[2], str)):
            out[str(source_path)] = (value[0], value[1], value[2])
    return out


def load_scan_meta(
    state_dir: Path, name: str = SCAN_CACHE_FILENAME
) -> Dict[str, object]:
    data = _read_json(scan_cache_path(state_dir, name))
    meta = (data or {}).get("db")
    return meta if isinstance(meta, dict) else {}


def save_scan_cache(
    state_dir: Path, cache: Dict[str, Tuple[int, int, str]],
    db_meta: Optional[Dict[str, object]] = None,
    name: str = SCAN_CACHE_FILENAME,
) -> bool:
    payload = {
        "written_at": utc_now_iso(),
        "db": dict(db_meta or {}),
        "entries": {k: list(v) for k, v in cache.items()},
    }
    return _atomic_write_json(scan_cache_path(state_dir, name), payload)


def write_liveness(state_dir: Path, record: dict) -> bool:
    ok = _atomic_write_json(latest_path(state_dir), record)
    stamp = str(record.get("finished_at") or utc_now_iso())
    safe = stamp.replace(":", "").replace("-", "")
    _atomic_write_json(artifact_dir(state_dir) / f"run-{safe}.json", record)
    _prune_dated(state_dir)
    return ok


def _prune_dated(state_dir: Path) -> None:
    try:
        dated = sorted(artifact_dir(state_dir).glob("run-*.json"))
    except OSError:
        return
    for path in dated[:-DATED_RETENTION] if len(dated) > DATED_RETENTION else []:
        try:
            path.unlink()
        except OSError:
            pass


def read_liveness(state_dir: Path) -> Optional[dict]:
    return _read_json(latest_path(state_dir))


def _parse_stamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def classify_freshness(
    record: Optional[dict], *, now: Optional[datetime] = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> Tuple[str, Optional[float], str]:
    if record is None:
        return (
            FRESHNESS_NEVER_RAN, None,
            "no liveness artifact on disk: the ingester has not completed a "
            "run in this state directory, or the artifact is unreadable",
        )
    stamp = _parse_stamp(record.get("finished_at"))
    if stamp is None:
        return (
            FRESHNESS_CANNOT_DETERMINE, None,
            "liveness artifact carries no parseable finished_at, so its age "
            "cannot be measured",
        )
    reference = now or datetime.now(timezone.utc)
    age = (reference - stamp).total_seconds()
    if age < 0:
        return (
            FRESHNESS_CANNOT_DETERMINE, age,
            f"liveness artifact is stamped {abs(age):.0f}s in the future, so "
            "its age is not a measurement of anything",
        )
    if age <= stale_after_seconds:
        return (
            FRESHNESS_CURRENT, age,
            f"last run completed {age:.0f}s ago, within the "
            f"{stale_after_seconds}s freshness window",
        )
    return (
        FRESHNESS_STALE, age,
        f"last run completed {age:.0f}s ago, past the "
        f"{stale_after_seconds}s freshness window",
    )


def dated_records(state_dir: Path) -> List[str]:
    try:
        return sorted(p.name for p in artifact_dir(state_dir).glob("run-*.json"))
    except OSError:
        return []
