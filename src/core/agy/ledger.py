
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.agy import accounts
from src.core.agy.state import state_folder
from src.models.provider_ledger import UsageWindow

_WINDOW_SECONDS = {"5h": 5 * 3600, "7d": 7 * 24 * 3600}


def _label(bucket_id: str) -> str:
    if bucket_id.endswith("5h"):
        return "5h"
    if bucket_id.endswith("weekly"):
        return "7d"
    return bucket_id


def _resets_at(bucket: Dict[str, Any], written_at: Optional[float]) -> Optional[datetime]:
    raw = bucket.get("reset_time")
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        if isinstance(raw, str) and raw:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    left = bucket.get("reset_in_seconds")
    if isinstance(left, (int, float)) and not isinstance(left, bool) and written_at:
        return datetime.fromtimestamp(written_at + float(left), tz=timezone.utc)
    return None


def windows_from_state(state: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> List[UsageWindow]:
    quota = (state or {}).get("quota")
    if not isinstance(quota, dict):
        return []
    written_at = (state or {}).get("written_at")
    now = now or datetime.now(timezone.utc)
    out: List[UsageWindow] = []
    for bucket_id, bucket in quota.items():
        if not isinstance(bucket, dict):
            continue
        fraction = bucket.get("remaining_fraction")
        if bucket.get("disabled"):
            used = 100.0
        elif isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
            used = min(100.0, max(0.0, 100.0 * (1.0 - float(fraction))))
        else:
            continue
        label = _label(str(bucket_id))
        resets = _resets_at(bucket, written_at if isinstance(written_at, (int, float)) else None)
        if resets is not None and resets <= now:
            used, resets = 0.0, None
        out.append(UsageWindow(kind=str(bucket_id), label=label, used_pct=round(used, 2),
                               window_seconds=_WINDOW_SECONDS.get(label), resets_at=resets))
    return out


def _id_of(email: str) -> Optional[str]:
    try:
        return accounts.account_id_for_email(email)
    except accounts.AgyAccountError:
        return None


def newest_state(state_dir: Path, account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_key = -1.0
    try:
        entries = [e for e in os.scandir(state_folder(state_dir)) if e.name.endswith(".json")]
    except OSError:
        return None
    for entry in entries:
        try:
            with open(entry.path, encoding="utf-8") as handle:
                data = json.load(handle)
            key = data.get("written_at") if isinstance(data, dict) else None
            key = float(key) if isinstance(key, (int, float)) else entry.stat().st_mtime
        except (OSError, ValueError):
            continue
        found = data.get("email") if isinstance(data, dict) else None
        if not isinstance(found, str) or not found.strip():
            continue
        if account_id is not None and _id_of(found) != account_id:
            continue
        if key > best_key:
            best, best_key = data, key
    return best


def reading_for(state_dir: Path, account_id: str, copy_exists: bool) -> Dict[str, Any]:
    state = newest_state(state_dir, account_id)
    stamp = (state or {}).get("written_at")
    return {
        "credential_state": "ok" if copy_exists else "missing",
        "windows": windows_from_state(state),
        "identity": (state or {}).get("email"),
        "plan": (state or {}).get("plan_tier"),
        "fetched_at": datetime.fromtimestamp(stamp, tz=timezone.utc) if isinstance(stamp, (int, float)) else None,
    }
