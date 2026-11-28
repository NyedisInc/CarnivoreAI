
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

import structlog

logger = structlog.get_logger()

MARKER_FILE: str = "vault-offloaded.json"


@dataclass(frozen=True)
class MarkerRow:

    sessions: Tuple[str, ...]
    bytes: int
    offloaded_at: float = 0.0


@dataclass(frozen=True)
class Marker:

    rows: Mapping[str, MarkerRow]
    unreadable: bool = False


def read(state_dir: Path, *, quiet: bool = False) -> Marker:
    try:
        data = json.loads((Path(state_dir) / MARKER_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Marker({})
    except (OSError, ValueError) as exc:
        if not quiet:
            logger.error("offloaded_marker_unreadable", error_type=type(exc).__name__, error=str(exc)[:200])
        return Marker({}, unreadable=True)
    raw = data.get("conversations") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        if not quiet:
            logger.error("offloaded_marker_malformed")
        return Marker({}, unreadable=True)
    rows: Dict[str, MarkerRow] = {}
    for conversation_id, row in raw.items():
        sessions = row.get("sessions") if isinstance(row, dict) else None
        size = row.get("bytes") if isinstance(row, dict) else None
        if not isinstance(conversation_id, str) or not isinstance(sessions, list) or not isinstance(size, int):
            if not quiet:
                logger.error("offloaded_marker_malformed_row")
            return Marker({}, unreadable=True)
        when = row.get("offloaded_at", 0.0)
        rows[conversation_id] = MarkerRow(tuple(str(s) for s in sessions), size, float(when) if isinstance(when, (int, float)) else 0.0)
    return Marker(rows)


def write(state_dir: Path, rows: Iterable[Tuple[str, Iterable[str], int]], times: Optional[Mapping[str, float]] = None) -> bool:
    from src.core.json_artifact import atomic_write_json

    when = times or {}
    payload = {"conversations": {cid: {"sessions": sorted(set(sessions)), "bytes": int(size), "offloaded_at": float(when.get(cid, 0.0))} for cid, sessions, size in rows}}
    return atomic_write_json(Path(state_dir) / MARKER_FILE, payload, log_event="offloaded_marker_write_failed")
