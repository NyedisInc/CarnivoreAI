
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import structlog

logger = structlog.get_logger()

MOVES_FILE: str = "vault-moves.json"
NOTE_SECONDS: float = 3600.0


def _read(state_dir: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads((Path(state_dir) / MOVES_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("vault_moves_unreadable", error=str(exc))
        return []
    rows = data.get("moves") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("folder"), str) and isinstance(r.get("at"), (int, float))]


def recent_folders(state_dir: Path, now: Optional[float] = None) -> List[str]:
    stamp = time.time() if now is None else now
    return [r["folder"] for r in _read(state_dir) if stamp - r["at"] <= NOTE_SECONDS]


def note_moved(state_dir: Path, folders: Iterable[str], now: Optional[float] = None) -> None:
    from src.core.json_artifact import atomic_write_json

    stamp = time.time() if now is None else now
    kept = [r for r in _read(state_dir) if stamp - r["at"] <= NOTE_SECONDS]
    kept += [{"folder": str(f).rstrip("/"), "at": stamp} for f in folders]
    atomic_write_json(Path(state_dir) / MOVES_FILE, {"moves": kept}, log_event="vault_moves_write_failed")
